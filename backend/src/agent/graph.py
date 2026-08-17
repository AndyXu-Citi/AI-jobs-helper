"""
LangGraph DAG 编排 + 用户入口。

DAG（带反思循环）
------------------
    START
      ↓
   parse_intent
      ↓
   retrieve ←─────────┐
      ↓                │
   filter              │ retry
      ↓                │
   reflect ──── retry ─┘
      ↓ done
   summarize
      ↓
     END
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agent.nodes import (
    AgentState,
    filter_node,
    parse_intent,
    reflect,
    retrieve,
    route_after_reflect,
    summarize,
    summarize_stream,
)
from src.agent.tools import JobRecord, load_profile


@dataclass
class JobAgentResult:
    """find_jobs 的返回值，封装报告 + 详细数据 + 追踪日志。"""

    final_report: str            # markdown 形式的推荐报告
    filtered_jobs: list[JobRecord]
    skill_gap: list[tuple[str, int]]
    intent: dict
    filter_stats: dict
    trace: list[str]
    elapsed_seconds: float


def _build_graph():
    """构建 + 编译 LangGraph DAG。"""
    g = StateGraph(AgentState)
    g.add_node("parse_intent", parse_intent)
    g.add_node("retrieve", retrieve)
    g.add_node("filter", filter_node)
    g.add_node("reflect", reflect)
    g.add_node("summarize", summarize)

    g.add_edge(START, "parse_intent")
    g.add_edge("parse_intent", "retrieve")
    g.add_edge("retrieve", "filter")
    g.add_edge("filter", "reflect")
    g.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {
            "retrieve": "retrieve",  # 反思要求 retry → 回到 retrieve
            "summarize": "summarize",
        },
    )
    g.add_edge("summarize", END)
    return g.compile()


# 编译一次，多次调用复用
_GRAPH = None


def _get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph()
    return _GRAPH


def find_jobs(query: str, profile: dict | None = None) -> JobAgentResult:
    """
    端到端跑求职 Agent（同步，一次性返回结果）。
    """
    if profile is None:
        profile = load_profile()

    initial: AgentState = {
        "query": query,
        "profile": profile,
        "trace": [],
    }

    t0 = time.time()
    graph = _get_graph()
    final_state = graph.invoke(initial)
    elapsed = time.time() - t0

    return JobAgentResult(
        final_report=final_state.get("final_report", ""),
        filtered_jobs=final_state.get("filtered_jobs", []),
        skill_gap=final_state.get("skill_gap", []),
        intent=final_state.get("intent", {}),
        filter_stats=final_state.get("filter_stats", {}),
        trace=final_state.get("trace", []),
        elapsed_seconds=elapsed,
    )


def find_jobs_stream(query: str, profile: dict | None = None):
    """
    逐步执行求职 Agent，并以结构化事件实时推送「思考步骤」与「流式报告」。

    事件格式（供 SSE 前端消费）：
        {"type": "step",    "label": "...", "status": "running"|"done", "detail": "..."}   # Agent 每步做了什么
        {"type": "content", "delta": "..."}                                                 # 报告 token（真流式）
        {"type": "done",    "result": <JobAgentResult>}                                      # 最终结果
        {"type": "error",   "message": "..."}

    注意：手动编排节点（不再用 graph.stream），以便精确控制每一步的 UI 展示，
    并让 summarize 走流式版本（token-by-token 推送，而非整段生成后再逐字切）。
    """
    if profile is None:
        profile = load_profile()

    state: dict = {
        "query": query,
        "profile": profile,
        "trace": [],
        "tried_keywords": [],
        "reflect_round": 0,
    }

    t0 = time.time()

    # ---- Step 1: 解析意图（调 LLM）----
    yield {"type": "step", "label": "解析求职意图", "status": "running"}
    parse_intent(state)
    intent = state.get("intent", {})
    kw = intent.get("keywords") or []
    detail_parts = []
    if kw:
        detail_parts.append("关键词：" + "、".join(kw))
    if intent.get("cities_include"):
        detail_parts.append("城市：" + "、".join(intent["cities_include"]))
    if intent.get("salary_min"):
        detail_parts.append(f"薪资≥{intent['salary_min'] // 1000}K")
    if intent.get("experience"):
        detail_parts.append("经验：" + intent["experience"])
    if intent.get("degree"):
        detail_parts.append("学历：" + intent["degree"])
    yield {
        "type": "step",
        "label": "解析求职意图",
        "status": "done",
        "detail": "｜".join(detail_parts) if detail_parts else "已解析",
    }

    # ---- Step 2: 检索 → 过滤 → 反思（可循环 retry）----
    while True:
        yield {"type": "step", "label": "语义检索岗位", "status": "running"}
        retrieve(state)
        yield {
            "type": "step",
            "label": "语义检索岗位",
            "status": "done",
            "detail": f"向量召回 {len(state.get('raw_hits', []))} 条相关岗位",
        }

        yield {"type": "step", "label": "按硬条件过滤", "status": "running"}
        filter_node(state)
        stats = state.get("filter_stats", {})
        yield {
            "type": "step",
            "label": "按硬条件过滤",
            "status": "done",
            "detail": f"保留 {stats.get('kept', 0)} 条（共 {stats.get('input', 0)} 条候选，"
            f"薪资 -{stats.get('by_salary', 0)} / 城市 -{stats.get('by_city_include', 0) + stats.get('by_city_exclude', 0)} "
            f"/ 学历 -{stats.get('by_degree', 0)} / 经验 -{stats.get('by_experience', 0)}）",
        }

        yield {"type": "step", "label": "反思：岗位是否充足", "status": "running"}
        reflect(state)
        if state.get("decision") == "retry":
            yield {
                "type": "step",
                "label": "反思：岗位是否充足",
                "status": "done",
                "detail": "不足，换关键词再搜一轮",
            }
            continue
        yield {
            "type": "step",
            "label": "反思：岗位是否充足",
            "status": "done",
            "detail": "充足，进入报告生成",
        }
        break

    # ---- Step 3: 流式生成报告（真 token-by-token）----
    yield {"type": "step", "label": "生成推荐报告", "status": "running"}
    for delta in summarize_stream(state):
        yield {"type": "content", "delta": delta}
    yield {"type": "step", "label": "生成推荐报告", "status": "done"}

    elapsed = time.time() - t0

    yield {
        "type": "done",
        "result": JobAgentResult(
            final_report=state.get("final_report", ""),
            filtered_jobs=state.get("filtered_jobs", []),
            skill_gap=state.get("skill_gap", []),
            intent=state.get("intent", {}),
            filter_stats=state.get("filter_stats", {}),
            trace=state.get("trace", []),
            elapsed_seconds=elapsed,
        ),
    }
