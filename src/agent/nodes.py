"""
LangGraph 节点定义。每个节点是一个**纯函数**：state -> partial state update。

设计原则
--------
- 节点只做"一件事"：parse / retrieve / filter / reflect / summarize
- 决策类节点（parse_intent / reflect / summarize）调 LLM
- 检索/过滤是确定性逻辑，不调 LLM -- 省 token 也省 latency
- 所有节点都在 state["trace"] 里追加一条记录，便于后续回放/调试
"""
# ======================================================================
# 模块概览
# ----------------------------------------------------------------------
# 本文件是 v3.0 求职 Agent 的"节点实现层"。整体编排（节点之间怎么连、
# 什么时候走回路）在 graph.py 里用 LangGraph 的 StateGraph 完成；本文件
# 只负责"每个节点内部具体做什么"。
#
# 数据流（state 在节点间流动，每个节点读 state、改 state、再传下去）：
#     START
#       ↓
#   parse_intent   —— LLM：把自然语言需求解析成结构化 intent
#       ↓
#   retrieve       —— 确定性：用关键词做向量语义检索，召回原始岗位
#       ↓
#   filter         —— 确定性：按薪资/城市/学历/经验/黑名单硬过滤
#       ↓
#   reflect        —— LLM：岗位够不够？不够就换关键词回到 retrieve（反思回路）
#       ↓ (done)
#   summarize      —— LLM：把 Top N 岗位 + 技能差距生成 markdown 报告
#       ↓
#      END
#
# 关键约定：
# - 每个节点签名统一为 (state: AgentState) -> AgentState，返回的是更新后的
#   state（LangGraph 会把返回值 merge 回全局 state）。
# - 决策类节点调 LLM（需要语义理解）；检索/过滤不调 LLM（规则可描述、更快更稳）。
# - trace 是一条贯穿全程的字符串列表，每个节点都往里追加一条日志，最终随
#   JobAgentResult.trace 返回，方便排查"Agent 走了哪条路、为什么"。
# ======================================================================
from __future__ import annotations  # PEP 563：延迟注解求值，允许前向引用

import json
import logging
import os
import re
from typing import Any, TypedDict  # TypedDict：给 dict 加上"键值类型"的静态描述

# LangChain 消息抽象：SystemMessage=系统人设，HumanMessage=用户输入
from langchain_core.messages import HumanMessage, SystemMessage
# ChatOpenAI 是兼容 OpenAI 接口的聊天客户端（本工程接的是火山引擎兼容端点）
from langchain_openai import ChatOpenAI

# 各节点用到的 prompt 模板，集中在 prompts.py 里方便统一迭代
from src.agent.prompts import (
    PARSE_INTENT_SYSTEM,           # parse_intent 的系统提示词（定义输出 JSON 结构）
    PARSE_INTENT_USER_TEMPLATE,    # parse_intent 的用户提示词模板（含 {query} 占位符）
    REFLECT_SYSTEM,                # reflect 的系统提示词
    SUMMARIZE_SYSTEM,              # summarize 的系统提示词
)
# 节点用到的工具函数与数据结构（向量检索、硬过滤、画像加载等），实现在 tools.py
from src.agent.tools import (
    JobRecord,                # 岗位完整记录的数据类（向量召回 + 详情合并）
    compute_skill_gap,        # 计算用户技能与岗位要求之间的差距
    filter_jobs,              # 按薪资/城市/学历/经验/黑名单做硬过滤
    load_profile,             # 加载 my_profile.yaml 用户画像
    vector_search_jobs,       # 用 embedding 做语义检索并 join SQLite 详情
)

logger = logging.getLogger(__name__)  # 本模块专属 logger，日志带模块名前缀，便于过滤

# 最多反思重试次数（防止死循环）
# reflect 节点每进入一次 round+1，达到该上限后即使结果不理想也强制 done，
# 避免 Agent 无限换关键词转圈、白白烧 token。
MAX_RETRY_ROUNDS = 3


# ----------------------------------------------------------------------
# State：在节点间流动的全局上下文
# ----------------------------------------------------------------------
# TypedDict 让一个普通 dict 拥有静态类型检查能力：声明它"应该有哪些键、值是什么类型"。
# total=False 表示所有键都是可选的——因为不同节点只产出自己负责的那部分键，
# 初始 state 只需要 query/profile/trace，其余键随流程推进逐步填充。
class AgentState(TypedDict, total=False):
    # 输入：调用 find_jobs 时由 graph.py 注入
    query: str            # 用户的自然语言需求原文，例如"找北京以外薪资 15K+ 要 LangChain 的 AI 岗"
    profile: dict         # 用户画像（my_profile.yaml 解析结果），含目标城市/薪资/学历/技能等

    # parse_intent 节点产出
    intent: dict          # 结构化意图：{keywords, cities_include/exclude, salary_min, experience, degree, direction, ...}

    # retrieve / filter 节点产出
    raw_hits: list[JobRecord]      # retrieve 向量召回的原始岗位（未过滤）
    filtered_jobs: list[JobRecord] # filter 按硬条件筛掉后的岗位
    filter_stats: dict             # 过滤统计：各维度各淘汰了多少条，用于 trace 展示与调试

    # reflect 节点产出
    reflect_round: int             # 当前反思轮次（每进入 reflect 一次 +1）
    decision: str                  # 反思结论："done"=收工去 summarize / "retry"=回 retrieve 换关键词再搜
    tried_keywords: list[list[str]] # 已经搜过哪几组关键词（每组一个 list），用于去重防止重复搜

    # summarize 节点产出
    skill_gap: list[tuple[str, int]] # 技能差距：(技能名, 出现次数)，岗位高频要求但用户未掌握的技能
    final_report: str                # 最终 markdown 推荐报告（LLM 生成）

    # 追踪：每个节点追加的运行日志，最终随结果返回，便于调试与回放
    trace: list[str]


# ----------------------------------------------------------------------
# LLM 客户端（复用 .env 里的火山引擎 OpenAI 兼容配置）
# ----------------------------------------------------------------------
def _llm() -> ChatOpenAI:
    """
    构造一个 ChatOpenAI 客户端。

    凭据从环境变量读取（由 .env 注入），代码里不硬编码密钥。
    用函数包裹而非模块级单例，是为了每次调用都能读到最新的环境变量，
    也方便测试时 monkeypatch 替换。

    Returns:
        ChatOpenAI: 已配置好 api_key / base_url / model 的聊天客户端。
    """
    api_key = os.getenv("LLM_API_KEY")    # 火山引擎 API Key
    base_url = os.getenv("LLM_API_BASE")  # OpenAI 兼容的接口地址
    model = os.getenv("LLM_MODEL")        # 模型名，如 doubao-xxx
    if not all([api_key, base_url, model]):
        # 任一缺失就尽早失败，避免把无效配置传到深层才报错，定位困难
        raise RuntimeError(
            "Missing LLM_API_KEY / LLM_API_BASE / LLM_MODEL in .env"
        )
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.2,  # 低温度：求职匹配需要稳定、可复现的输出，不需要太多创造力
        timeout=180,      # 大模型偶发慢响应，给 3 分钟超时余量
        max_retries=2,    # SDK 自带重试，应对偶发的 429/5xx
    )


def _extract_json(text: str) -> dict:
    """从 LLM 响应里提 JSON 对象，容忍 ```json``` 包裹和多余文字。"""
    # 大模型经常不老实只返回 JSON：会套 ```json``` 代码块，或在 JSON 前后加解释。
    # 这里做两步兜底，尽量从噪声文本里把 JSON 对象捞出来。
    # 1) 先剥代码块：匹配 ```json { ... } ``` 或 ``` { ... } ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        candidate = m.group(1)
    else:
        # 2) 退而求其次，抓第一个 { ... } 片段
        #    DOTALL 让 . 能匹配换行，从而支持跨多行的 JSON。
        m = re.search(r"\{.*\}", text, re.DOTALL)
        candidate = m.group(0) if m else text
    return json.loads(candidate)


def _trace(state: AgentState, msg: str) -> None:
    """
    往 state["trace"] 追加一条日志，同时输出到 logger。

    trace 列表最终会随 JobAgentResult.trace 返回给调用方，所以这是"可观测性"的核心：
    每个节点做完事都调一次，方便事后回放"Agent 到底走了哪条路、为什么"。
    """
    state.setdefault("trace", []).append(msg)  # setdefault 兼容初始 state 没有 trace 键的情况
    logger.info(msg)


# ----------------------------------------------------------------------
# Node 1: parse_intent
# 把用户的自然语言需求解析成结构化 intent，供后续检索/过滤使用。
# 这是整条链路的"入口理解"环节，解析质量直接决定召回质量。
# ----------------------------------------------------------------------
def parse_intent(state: AgentState) -> AgentState:
    """
    解析意图节点。

    输入：state["query"]（自然语言需求）。
    输出：state["intent"]（结构化字典）+ 初始化 tried_keywords / reflect_round。
    调 LLM：是。系统提示词要求模型只返回 JSON，字段见 prompts.PARSE_INTENT_SYSTEM。
    兜底：解析失败时把整句 query 当关键词，方向标记"未明确"，保证后续不致崩溃。
    """
    query = state["query"]
    llm = _llm()
    # 组装对话：系统提示词定义"要解析成什么 JSON 结构"，用户消息填入 query
    msgs = [
        SystemMessage(content=PARSE_INTENT_SYSTEM),
        HumanMessage(content=PARSE_INTENT_USER_TEMPLATE.format(query=query)),
    ]
    resp = llm.invoke(msgs)
    # resp.content 理论上是 str，但部分模型/工具会返回 list[dict] 等结构，统一拍平成 str
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    try:
        intent = _extract_json(raw)
    except Exception as e:
        # 解析失败的兜底：把整句 query 当作关键词，方向标记"未明确"，
        # 这样后续 retrieve 至少还能用原文做一次向量检索，不至于直接崩溃。
        logger.warning(f"parse_intent 解析失败，使用兜底意图：{e}\n原始: {raw[:200]}")
        intent = {"keywords": [query], "direction": "未明确"}

    # 兜底确保 keywords 一定存在：它是 retrieve 节点的必需字段
    intent.setdefault("keywords", [query])
    state["intent"] = intent
    state["tried_keywords"] = []    # 重置"已尝试关键词"记录
    state["reflect_round"] = 0      # 重置反思轮次计数
    _trace(state, f"[parse_intent] 解析结果: {json.dumps(intent, ensure_ascii=False)}")
    return state


# ----------------------------------------------------------------------
# Node 2: retrieve（确定性，不调 LLM）
# 用 parse_intent 解析出的关键词构造一句 embedding 查询，做向量语义检索。
# 纯确定性：同样输入永远同样输出，便于复现与测试。
# ----------------------------------------------------------------------
def retrieve(state: AgentState) -> AgentState:
    """
    检索节点。

    输入：state["intent"]（关键词、方向、薪资、经验等）。
    输出：state["raw_hits"]（召回的原始岗位）+ tried_keywords 追加本轮关键词。
    调 LLM：否。只做一次 embedding + 向量库 top_k 检索。
    设计：把多个关键词拼成一句话做 embedding，比逐个搜性价比高（一次编码表达多个语义）。
    """
    intent = state["intent"]
    # 关键词缺失时退回用原始 query，保证永远有检索输入
    keywords = intent.get("keywords") or [state["query"]]
    # 把关键词拼成一句给 embedding，比逐个搜性价比高
    embed_query = " ".join(keywords)
    # 以下把意图里的方向/薪资/经验等"软线索"也拼进查询，让 embedding 更贴近用户真实诉求
    if intent.get("direction") and intent["direction"] != "未明确":
        embed_query += f" {intent['direction']}"
    if intent.get("salary_min"):
        # salary_min 是元/月（如 15000），转成 "15K+" 更贴近 JD 文本里的写法，提升召回相关性
        embed_query += f" 薪资 {intent['salary_min'] // 1000}K+"
    if intent.get("experience"):
        embed_query += f" {intent['experience']}"

    hits = vector_search_jobs(embed_query, top_k=30)  # 召回 top 30，留足余量给 filter 筛
    state["raw_hits"] = hits
    state["tried_keywords"].append(list(keywords))    # 记下本轮用了哪些关键词，供 reflect 去重
    _trace(state, f"[retrieve] embed_query={embed_query!r} → {len(hits)} 条")
    return state


# ----------------------------------------------------------------------
# Node 3: filter（确定性，不调 LLM）
# 对 retrieve 召回的原始岗位做"硬过滤"：薪资/城市/学历/经验/黑名单。
# 这些都是布尔/数值判定，规则明确，交给规则比交给 LLM 更快更稳。
# ----------------------------------------------------------------------
def filter_node(state: AgentState) -> AgentState:
    """
    过滤节点。

    输入：state["raw_hits"] + state["intent"] + state["profile"]。
    输出：state["filtered_jobs"]（通过过滤的岗位）+ state["filter_stats"]（统计）。
    调 LLM：否。
    优先级：意图（用户在 query 里明说的）> 画像（profile 默认）> 不限制。
    """
    intent = state["intent"]
    profile = state["profile"]

    # 城市：意图里明说的优先，否则用画像默认目标城市，都没有就不限
    cities_inc = intent.get("cities_include") or profile.get("target_cities") or None
    cities_exc = intent.get("cities_exclude") or None
    # 薪资：意图优先，否则用画像底线
    salary_min = intent.get("salary_min") or profile.get("salary_min") or None

    # 学历：尊重用户在 query 里明说的，否则用 profile
    degree = intent.get("degree")
    if degree and degree != "学历不限":
        degree_allow = [degree, "学历不限"]
    elif profile.get("degree"):
        # 用 profile 学历但宽松一点（你本科可以投本科/大专/学历不限）
        if profile["degree"] == "本科":
            degree_allow = ["本科", "大专", "学历不限"]
        else:
            degree_allow = [profile["degree"], "学历不限"]
    else:
        degree_allow = None

    # 经验：意图里有就用意图的，否则按 profile 年限映射
    exp = intent.get("experience")
    if exp:
        experience_allow = [exp, "经验不限"]
    elif profile.get("years_of_experience"):
        y = profile["years_of_experience"]
        if y <= 1:
            experience_allow = ["在校/应届", "经验不限", "1-3年"]
        elif y <= 3:
            experience_allow = ["1-3年", "经验不限"]
        else:
            experience_allow = ["3-5年", "1-3年", "经验不限"]
    else:
        experience_allow = None

    blacklist = profile.get("want_to_avoid") or []

    kept, stats = filter_jobs(
        state["raw_hits"],
        salary_min=salary_min,
        cities_include=cities_inc,
        cities_exclude=cities_exc,
        degree_allow=degree_allow,
        experience_allow=experience_allow,
        blacklist_keywords=blacklist,
    )
    state["filtered_jobs"] = kept
    state["filter_stats"] = stats
    _trace(
        state,
        f"[filter] {stats['input']} → {stats['kept']}（薪资 -{stats['by_salary']} / "
        f"城市 -{stats['by_city_include'] + stats['by_city_exclude']} / "
        f"学历 -{stats['by_degree']} / 经验 -{stats['by_experience']} / "
        f"黑名单 -{stats['by_blacklist']}）"
    )
    return state


# ----------------------------------------------------------------------
# Node 4: reflect（决策是否需要换关键词再搜）
# 这是整条链路的"反思回路"核心：检查 filter 后的岗位数量与质量，
# 若不够则让 LLM 提出新的关键词，回到 retrieve 再搜一轮（形成循环）。
# ----------------------------------------------------------------------
def reflect(state: AgentState) -> AgentState:
    """
    反思节点。

    输入：state["filtered_jobs"] + state["reflect_round"] + state["tried_keywords"]。
    输出：state["decision"]（"done" | "retry"）；retry 时还会改写 state["intent"]["keywords"]。
    调 LLM：仅当结果不够且未达重试上限时才调，省 token。
    防死循环：双层保护——MAX_RETRY_ROUNDS 硬上限 + 必须给出"新"关键词才算 retry。
    """
    # 先把反思轮次 +1（这一行决定了后续是否触发 MAX_RETRY_ROUNDS 上限）
    state["reflect_round"] = state.get("reflect_round", 0) + 1
    kept = state["filtered_jobs"]

    # 简单兜底：足够 ≥ 5 条或重试 ≥ 3 轮，直接 done
    # 这一步是确定性短路，避免"明明已经够好了还去调 LLM 浪费 token"
    if len(kept) >= 5 or state["reflect_round"] >= MAX_RETRY_ROUNDS:
        state["decision"] = "done"
        _trace(state, f"[reflect] decision=done（kept={len(kept)} / round={state['reflect_round']}）")
        return state

    # 否则调 LLM 决策：要不要换关键词
    intent = state["intent"]
    profile = state["profile"]
    # 把当前已通过过滤的岗位压缩成简短文本，喂给 LLM 做判断依据
    summary = "\n".join(
        f"- [{j.city}] {j.title} | {j.salary_desc} | {j.experience} {j.degree}"
        for j in kept[:10]
    ) or "（空）"

    user = (
        f"用户原始需求: {state['query']}\n"
        f"已解析意图: {json.dumps(intent, ensure_ascii=False)}\n"
        f"画像主投方向: {profile.get('primary_directions')}\n"
        f"画像保底方向: {profile.get('fallback_directions')}\n"
        f"已尝试过的关键词组: {state['tried_keywords']}\n"
        f"当前已通过过滤的岗位（{len(kept)} 条）:\n{summary}\n\n"
        f"是否需要再搜一轮？"
    )

    llm = _llm()
    msgs = [SystemMessage(content=REFLECT_SYSTEM), HumanMessage(content=user)]
    resp = llm.invoke(msgs)
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    try:
        result = _extract_json(raw)
    except Exception:
        # 解析失败时强制 done，宁可少搜一轮也不要带病重试
        logger.warning(f"reflect 解析失败，强制 done。原始: {raw[:200]}")
        result = {"decision": "done"}

    if result.get("decision") == "retry":
        next_kw_raw = result.get("next_keywords") or []
        # 强壮化：LLM 偶尔会把 next_keywords 返回成嵌套结构（[["xxx"]]）或
        # 单字符串而不是 list；统一拍平成 str 列表，不可哈希的直接跳过。
        next_kw: list[str] = []
        if isinstance(next_kw_raw, str):
            next_kw = [next_kw_raw]
        elif isinstance(next_kw_raw, list):
            for item in next_kw_raw:
                if isinstance(item, str):
                    next_kw.append(item)
                elif isinstance(item, list):
                    # 嵌套 → 拍平一层
                    next_kw.extend(s for s in item if isinstance(s, str))
                # 其它非字符串/列表的类型（dict / None）直接忽略

        # 至少要换出一个新关键词，否则强制 done 防死循环
        already_tried: set[str] = set()
        for trial in state["tried_keywords"]:
            for kw in trial:
                if isinstance(kw, str):
                    already_tried.add(kw)
        new_kw = [k for k in next_kw if k not in already_tried]
        if not new_kw:
            # LLM 想重试但没给出任何没搜过的新关键词 -> 视为无效 retry，强制收工
            state["decision"] = "done"
            _trace(state, "[reflect] LLM 想 retry 但没给出新关键词 → 强制 done")
        else:
            # 用新关键词覆盖 intent，下一轮 retrieve 会基于它重新检索
            state["intent"]["keywords"] = new_kw
            if result.get("next_cities"):
                state["intent"]["cities_include"] = result["next_cities"]
            state["decision"] = "retry"
            _trace(state, f"[reflect] retry: 新关键词={new_kw} 理由={result.get('reason', '')}")
    else:
        state["decision"] = "done"
        _trace(state, f"[reflect] decision=done 理由={result.get('reason', '')}")
    return state


def route_after_reflect(state: AgentState) -> str:
    """
    条件路由函数（供 graph.py 的 add_conditional_edges 使用）。

    根据 reflect 写入的 decision 决定下一步去哪：
    - "retry" -> 回到 "retrieve" 节点换关键词再搜（形成反思回路）；
    - 其它   -> 去 "summarize" 节点收尾出报告。
    """
    return "retrieve" if state["decision"] == "retry" else "summarize"


# ----------------------------------------------------------------------
# Node 5: summarize
# 把通过过滤的 Top N 岗位 + 用户画像 + 技能差距，交给 LLM 生成 markdown 报告。
# ----------------------------------------------------------------------
def summarize(state: AgentState) -> AgentState:
    """
    汇总节点（链路终点）。

    输入：state["filtered_jobs"] + state["profile"] + state["query"]。
    输出：state["skill_gap"]（确定性计算）+ state["final_report"]（LLM 生成）。
    调 LLM：是。先用规则算技能差距，再把"岗位+画像+差距"打包给 LLM 写报告。
    长度控制：只把相似度前 10 的岗位塞进 prompt，避免上下文过长拖慢/超 token。
    """
    jobs = state["filtered_jobs"]
    profile = state["profile"]

    # 先算技能差距（确定性，不调 LLM）
    gap = compute_skill_gap(jobs, profile)
    state["skill_gap"] = gap

    # 按 score 排序，最多给 LLM 看前 10 条（控制 prompt 长度）
    jobs_sorted = sorted(jobs, key=lambda j: j.score, reverse=True)
    show = jobs_sorted[:10]

    # 把每个岗位拍成紧凑结构，给 LLM 当输入
    jobs_payload = [
        {
            "city": j.city,
            "title": j.title,
            "brand": j.brand,
            "salary": j.salary_desc,
            "experience": j.experience,
            "degree": j.degree,
            "url": j.url,
            "score": round(j.score, 3),
            "jd_excerpt": j.short_desc,
        }
        for j in show
    ]

    user = (
        f"# 用户原始需求\n{state['query']}\n\n"
        f"# 用户画像\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
        f"# 已通过过滤的岗位（按相似度降序，共 {len(jobs)} 条，展示前 {len(show)} 条）\n"
        f"{json.dumps(jobs_payload, ensure_ascii=False, indent=2)}\n\n"
        f"# 技能差距统计（这批岗位反复出现但用户 profile 还没掌握的技能）\n"
        f"{json.dumps(gap[:10], ensure_ascii=False)}\n"
    )

    llm = _llm()
    msgs = [SystemMessage(content=SUMMARIZE_SYSTEM), HumanMessage(content=user)]
    resp = llm.invoke(msgs)
    state["final_report"] = (
        resp.content if isinstance(resp.content, str) else str(resp.content)
    )
    _trace(state, f"[summarize] 报告生成完毕，{len(state['final_report'])} 字")
    return state
