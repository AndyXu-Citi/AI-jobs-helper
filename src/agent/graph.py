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
    逐步执行求职 Agent，每完成一个节点 yield trace 更新，最后 yield 完整结果。

    用法：
        for event in find_jobs_stream(query):
            if event["type"] == "trace":
                push_to_frontend(event["lines"])
            elif event["type"] == "done":
                push_result(event["result"])
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

    last_len = 0
    for event in graph.stream(initial):
        for _node_name, state_update in event.items():
            trace: list[str] = state_update.get("trace") or []
            new_lines = trace[last_len:]
            if new_lines:
                yield {"type": "trace", "lines": new_lines}
                last_len = len(trace)

    final_state = graph.invoke(initial)
    elapsed = time.time() - t0

    yield {
        "type": "done",
        "result": JobAgentResult(
            final_report=final_state.get("final_report", ""),
            filtered_jobs=final_state.get("filtered_jobs", []),
            skill_gap=final_state.get("skill_gap", []),
            intent=final_state.get("intent", {}),
            filter_stats=final_state.get("filter_stats", {}),
            trace=final_state.get("trace", []),
            elapsed_seconds=elapsed,
        ),
    }
