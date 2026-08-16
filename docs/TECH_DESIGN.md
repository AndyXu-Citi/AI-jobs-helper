# AI 求职 Agent · 技术设计文档（Tech Design）

> 用途：作为求职简历 / 面试的技术设计说明。
> 目标岗位方向：**AI 应用开发**、**AI Agent 工程**。
> 文档重点：**项目里用到的所有 AI 相关能力（skills）**，分别用在什么地方、解决什么问题。
>
> 阅读对象：技术面试官、招聘负责人，以及 2 年经验左右的 AI 应用 / Agent 方向候选人自查。

---

## 1. 项目一句话定位

一个**端到端的 AI 求职 Agent**：用自然语言描述需求（"杭州 15K+ 要 LangChain 的 AI 应用岗"），自动完成 *意图解析 → 语义检索 → 规则过滤 → 反思重试 → 生成推荐报告*，并内置 RAG 向量库、MCP 工具服务、Bad Case 自学习闭环和 Boss 直聘反爬采集。

核心价值主张：用 **LLM + RAG + Agent 编排 + 工具协议** 串起"找数据 → 理解需求 → 匹配岗位 → 复盘优化"的完整链路，是一个**能直接写进简历的 AI Agent 作品**。

---

## 2. 技术栈总览

| 层 | 技术 | 说明 |
|----|------|------|
| 大模型推理 | `langchain-openai` `ChatOpenAI`（OpenAI 兼容接口，**实测接 DeepSeek**） | 意图/反思/报告/技能提取/简历匹配，低温度 `0.2` |
| 向量化 | `BAAI/bge-m3`（1024 维，sentence-transformers） | 中英混合 SOTA，进程内加载 `HuggingFaceEmbedder` |
| 向量库 | `FAISS`（`IndexFlatIP` 内积=余弦） | 替代 Milvus Lite，规避 Windows gRPC 兼容问题 |
| Agent 编排 | `LangGraph` `StateGraph` | 有环 DAG（反思回路），同步 + SSE 流式两入口 |
| 数据采集 | `Playwright` `connect_over_cdp` | 接管真实 Chrome 绕开 Boss 风控 |
| 对外服务 | `FastAPI`（含 SSE）+ `FastMCP`（stdio） | Web UI / API 与 MCP 工具生态 |
| 存储 | `MySQL`（final_results、agent_runs） | 岗位语料 + 运行记录 |
| 前端 | 原生 HTML/CSS/JS（单页，无框架） | 暗色主题，含 master-detail 岗位库 |

---

## 3. AI 能力（Skills）清单

下面按 **6 大类** 列出项目用到的 AI 能力。每条标注：**技术 / 代码位置 / 解决的问题 / 输入输出**。

### 3.1 LLM 应用类（大模型推理）

| # | 能力 | 技术 | 位置 | 解决的问题 | 输入 / 输出 |
|---|------|------|------|-----------|------------|
| 1 | **意图解析** | ChatOpenAI（JSON 输出） | `src/agent/nodes.py::parse_intent` + `prompts.PARSE_INTENT_SYSTEM` | 把自然语言需求解析成结构化 JSON（关键词/城市/薪资/经验/学历/方向），作为下游检索与过滤的入口 | 自然语言 query → `intent` dict；失败兜底"整句当关键词" |
| 2 | **反思决策（Reflect）** | ChatOpenAI | `src/agent/nodes.py::reflect` + `route_after_reflect` | Agent 自省：岗位不够时让 LLM 提出新关键词回到检索节点，形成**反思回路**（防死循环：`MAX_RETRY_ROUNDS=3` + 必须给出新关键词才 retry） | 已过滤岗位 + 画像 + 已尝试关键词 → `decision(done/retry)` |
| 3 | **报告生成** | ChatOpenAI | `src/agent/nodes.py::summarize` + `prompts.SUMMARIZE_SYSTEM` | 把 Top N 岗位 + 画像 + 技能差距，生成 markdown 推荐报告（强推/备选/技能差距/总结） | 岗位（前 10）+ 画像 + 差距 → markdown 报告 |
| 4 | **JD 技能提取** | ChatOpenAI（批量 8 条/次） | `scripts/llm_extract_skills.py` + `src/web/app.py::_llm_extract_and_cache` | 从 JD 正文精准抽取技术关键词，统一技能口径，供热度/缺口/报表使用 | JD 列表（title+正文）→ 每 JD 一个技能数组，缓存进 MySQL |
| 5 | **简历–JD 匹配** | ChatOpenAI（招聘顾问人设） | `src/web/app.py::match_resume`（`POST /api/match`） | 给定简历 + JD，输出综合匹配度、已具备/缺失技能、提升建议、面试准备 | 简历 + JD +（自动注入的向量相似度 + 相似岗位）→ JSON（评分/技能/建议） |

> 关键设计：决策类节点（1/2/3/5）才调 LLM；**检索、过滤、技能差距计算都是确定性逻辑，不调 LLM**——既省 token 又稳。

### 3.2 RAG / 向量检索类（检索增强）

| # | 能力 | 技术 | 位置 | 解决的问题 | 输入 / 输出 |
|---|------|------|------|-----------|------------|
| 6 | **文本向量化** | `bge-m3`（`HuggingFaceEmbedder` / `OllamaEmbedder` 双实现） | `src/rag/embedder.py` | 把自然语言查询、岗位文本、简历编码为 1024 维向量，支撑语义检索与相似度 | 文本 → 向量；`embed_many` 单条失败零向量兜底 |
| 7 | **向量存储与语义检索** | `FAISS IndexFlatIP` | `src/rag/vector_store.py::VectorStore` | 存储岗位向量、执行 Top-K 语义检索（按 `source_type` 过滤），相似度归一化 0~1 | 查询向量 + top_k → `SearchHit`(url/title/score) |
| 8 | **Agent 语义检索节点** | bge-m3 向量检索 | `src/agent/nodes.py::retrieve` + `tools.vector_search_jobs` | 把意图里的关键词 + 方向/薪资/经验软线索拼成一句 query 做 embedding，召回 top 30 岗位 | `intent` → `raw_hits`（JobRecord 列表） |
| 9 | **RAG 索引构建** | HuggingFaceEmbedder + FAISS | `scripts/index_final_results.py` | 把 `final_results` 岗位拼成"标题→简介→要点→标签"文本 embed 入库，支持幂等/断点重建 | MySQL 岗位 → `data/vector.db.faiss/.pkl` |
| 10 | **MCP 语义检索工具** | bge-m3 + FAISS，经 MCP 暴露 | `src/mcp_server/ai_collector_mcp.py::query_rag` | 让外部 MCP 客户端用自然语言做语义检索（不同于关键词匹配） | 自然语言 question + top_k → JSON 命中列表 |

### 3.3 Agent 编排类

| # | 能力 | 技术 | 位置 | 解决的问题 | 输入 / 输出 |
|---|------|------|------|-----------|------------|
| 11 | **LangGraph DAG 编排（含反思回路）** | `langgraph.StateGraph` | `src/agent/graph.py::_build_graph` | 编排 `parse_intent → retrieve → filter → reflect → summarize`（reflect 可回 retrieve 成环），提供同步 `find_jobs` 与流式 `find_jobs_stream`（SSE） | query(+可选 profile) → `JobAgentResult`（报告/岗位/差距/trace/耗时） |
| 12 | **硬过滤（规则后处理）** | 确定性规则 | `src/agent/nodes.py::filter_node` + `tools.filter_jobs` | 对检索结果做薪资/城市/学历/经验/黑名单硬过滤，比 LLM 更快更稳（优先级：意图 > 画像 > 不限） | `raw_hits`+`intent`+`profile` → `filtered_jobs` + 拦截统计 |
| 13 | **技能差距计算** | 规则统计（Counter 聚合） | `src/agent/tools.py::compute_skill_gap` | 在岗位集里找"高频出现但用户未掌握"的技能，输出带热度缺口清单 | 岗位 + 画像 already_have → `[(skill, count)]` 降序（区分 have/learning/missing） |

### 3.4 工具与协议类（对外服务能力）

| # | 能力 | 技术 | 位置 | 解决的问题 | 输入 / 输出 |
|---|------|------|------|-----------|------------|
| 14 | **MCP 工具服务（3 个工具）** | `FastMCP`（stdio） | `src/mcp_server/ai_collector_mcp.py` | 把核心检索能力封装成 MCP 工具，接入任意 MCP 客户端（Claude Desktop / Cursor / Hermes） | `search_jobs`(关键词) / `query_rag`(语义) / `get_skill_gap`(缺口) |
| 15 | **Web API 服务（多智能端点）** | `FastAPI` + SSE | `src/web/app.py` | 把 Agent 包成 HTTP 接口，前端调用；含 `/api/chat`、`/api/chat/stream`、`/api/jobs`、`/api/skill-gap`、`/api/report`、`/api/match`、`/api/match/rank`、`/api/profile` | 各类 JSON 请求 → JSON/SSE 响应 |
| 16 | **用户画像驱动（Profile）** | `my_profile.yaml` 解析 | `src/agent/tools.py::load_profile` | 以简历画像（目标城市/薪资底线/学历/经验/已备技能/黑名单）作为检索默认约束与缺口基准，贯穿全部节点 | yaml → profile dict，被各节点/端点复用 |

### 3.5 数据采集的"智能化"处理

| # | 能力 | 技术 | 位置 | 解决的问题 | 输入 / 输出 |
|---|------|------|------|-----------|------------|
| 17 | **CDP 浏览器接管抓取（反爬）** | `Playwright connect_over_cdp` | `src/sources/boss_zhipin.py::BossSource` | Boss PC 站 Canvas 渲染 + 风控 code 37，用真实浏览器 + 真实 cookie 绕开；智能化点：每查询新开标签页重置 WAF 会话、code37 长冷却 + 连续失败整段冷却、导航故障 vs 真风控判定、`is_likely_noise` 启发式过滤日结/校招/保险代理噪音岗 | cities×keywords×pages → 结构化岗位列表 |
| 18 | **岗位入库与富化** | BossSource + MySQL | `scripts/ingest_boss_jobs.py`（断点续传）、`enrich_boss_details.py`（补全 JD 正文/公司/学历经验） | API 结构化数据直接落库免爬 HTML；详情补全让 embedding 召回更准 | 抓取结果 → `final_results.structured_json`（含 `_boss` 子节点） |

### 3.6 闭环 / 学习 / 可观测

| # | 能力 | 技术 | 位置 | 解决的问题 | 输入 / 输出 |
|---|------|------|------|-----------|------------|
| 19 | **Bad Case 闭环** | MySQL `agent_runs` + `BadCaseStore` + CLI | `src/agent/bad_case_store.py` + `scripts/agent_runs.py` | 每次运行落库（query/结果数/耗时/反思轮次/trace/报告），支持人工标 good/bad + root_cause + fix_commit，`replay` 同 query 重跑对比，**形成"运行→标注→复盘→改进"自学习闭环** | 运行记录 + 人工标注 → stats / replay 对比摘要（零结果自动标 bad） |
| 20 | **可观测性（Agent Trace）** | `state["trace"]` 字符串列表 | `src/agent/nodes.py::_trace` + `graph.py` | 每个节点追加运行日志，事后回放"Agent 走了哪条路、为什么"，是 Bad Case 复盘与调试基础 | 节点内追加 → 随结果返回 / SSE 实时推送 |

---

## 4. 架构与数据流

```
                  ┌───────────────── 用户 / 前端 / MCP 客户端 ─────────────────┐
                  │   POST /api/chat │ /api/chat/stream │ MCP: search_jobs/query_rag/get_skill_gap
                  └───────────────┬────────────────────────────────────────────┘
                                  │
                                  ▼
        ┌────────────────────── LangGraph DAG (src/agent/graph.py) ──────────────────────┐
        │                                                                                 │
        │  START → [parse_intent] ─LLM→ [retrieve] ─bge-m3+FAISS→ [filter] ─规则→          │
        │                         ↑  retry                │                               │
        │                         └────── [reflect] ─LLM───┘ (done) ↓                       │
        │                                   (有环：反思回路)     [summarize] ─LLM→ END        │
        │                                                                                 │
        │  全程写入 state["trace"]；结果写 agent_runs（Bad Case 闭环）                      │
        └──────────────────────────────┬──────────────────────────────────────────────────┘
                                        │ 复用
            ┌───────────────┬───────────┴────────────┬───────────────────┐
            ▼               ▼                        ▼                   ▼
      [RAG 向量检索]   [技能差距计算]            [LLM 技能提取]       [简历-JD 匹配]
      bge-m3+FAISS     compute_skill_gap        llm_extract_skills   /api/match
            │                                          │                   │
            ▼                                          ▼                   ▼
      data/vector.db(.faiss/.pkl)              MySQL final_results    MySQL + bge-m3 余弦
            ▲                                          │
            │ 数据源                                    ▼
      ┌─────┴──────────────────────────────────────────────────┐
      │  BossSource (Playwright CDP) → 抓取 m.zhipin.com JSON   │
      │  → ingest（断点续传）→ final_results → index（bge-m3）   │
      └──────────────────────────────────────────────────────────┘
```

**关键依赖关系**
- LLM 层（#1/2/3/4/5）：共用 `nodes._llm()`（OpenAI 兼容，实测 DeepSeek）。
- RAG 层（#6/7/8/10）：共用 bge-m3 + FAISS。
- 编排层（#11）：串起 `parse_intent → retrieve → filter → reflect → summarize`，并经 #19/#20 形成闭环。
- 数据层（#17/18）：为 RAG 提供结构化岗位语料；#4 提供 LLM 提取的技能标签。
- 对外（#14 MCP / #15 Web）：复用上述所有能力。

---

## 5. 与求职方向的对应（面试话术参考）

> 这一段直接对应你要找的 **AI 应用开发** 和 **AI Agent** 方向，可用于简历项目描述 / 面试自我介绍。

### 5.1 证明「AI Agent 工程」能力
- **多节点有状态 Agent**：用 LangGraph 把意图解析、检索、过滤、反思、报告编排成有环 DAG，**反思回路**是核心亮点——LLM 自主判断"岗位够不够、要不要换关键词再搜"，并带防死循环机制。
- **LLM 作为决策单元**：不是"调一次大模型"就完事，而是让 LLM 在**多个节点**承担不同决策角色（解析/反思/生成/匹配），其余环节用确定性逻辑省成本。
- **可观测与自学习闭环**：每次运行全量 trace 落库 + Bad Case 标注 + replay 对比，体现"Agent 系统要能持续优化"的工程素养。

### 5.2 证明「AI 应用开发 / RAG」能力
- **完整 RAG 链路**：bge-m3 中文 SOTA 向量化 + FAISS 落地 + Top-K 语义检索，覆盖"建库（index）→ 检索（retrieve）→ 应用（报告/匹配）"全周期。
- **混合检索策略**：关键词匹配（MCP `search_jobs`）与语义检索（`query_rag`）并存，理解"字面匹配 vs 语义匹配"的取舍。
- **LLM + 向量双路融合**：`/api/match` 用向量余弦相似度给 LLM 当参考、用相似岗位分布校准评分，体现"不盲信单路信号"的工程判断。
- **技能提取与缺口分析**：用 LLM 批量抽取 JD 技能 + 对照个人画像算缺口，是"把非结构化文本变成结构化洞察"的典型 AI 应用。

### 5.3 证明「工程落地 / 反爬实战」能力
- **Boss 反爬**：Playwright CDP 接管真实浏览器、每查询新标签页重置 WAF 会话、分级冷却与噪音过滤——这是真实生产级爬虫的难题，能体现解决复杂工程约束的能力。
- **稳定性取舍**：向量库从 Milvus Lite 换 FAISS 规避 Windows gRPC 问题、embedding 双实现（HF/Ollama）、批处理与幂等设计——体现"为部署环境做合理技术选型"。

---

## 6. 关键设计决策（面试问答备用）

| 决策 | 为什么 | 出处 |
|------|--------|------|
| 决策节点才调 LLM，检索/过滤/差距计算用确定性逻辑 | 省 token、降延迟、结果更稳定可复现 | `src/agent/nodes.py` 模块注释 |
| 向量库选 FAISS 而非 Milvus Lite | Milvus Lite 在 Windows 有 gRPC 兼容问题（AllocTimestamp/too_many_pings），FAISS 零服务器依赖 | `src/rag/vector_store.py` 文件头 |
| embedding 用 bge-m3（本地 HF 加载） | 中文 SOTA、中英混合好、进程内加载无需额外服务 | `src/rag/embedder.py` |
| 反思回路双层防死循环 | `MAX_RETRY_ROUNDS=3` + 必须给出"新"关键词才允许 retry，防 Agent 无限转圈烧 token | `reflect()` / `route_after_reflect()` |
| 每条查询新开标签页 + 分冷却 | Boss 对"同一会话连续打 API"做连接级封禁；新标签页重置会话绕开 | `src/sources/boss_zhipin.py` |
| 模型接 OpenAI 兼容接口（实测 DeepSeek） | 不绑定厂商，换 key 即可换模型；低温度 `0.2` 保证匹配结果稳定 | `src/agent/nodes.py::_llm` |

---

## 7. 快速开始（运行链路）

```bash
# 1. 采集 Boss 岗位（需先 CDP 接管已登录的 Chrome）
python scripts/ingest_boss_jobs.py --cities 杭州,苏州 --keywords "AI应用开发,大模型,LangChain,Agent"

# 2. 补全 JD 详情（提升召回质量）
python scripts/enrich_boss_details.py

# 3. 用 LLM 提取技能标签（缓存进 MySQL）
python scripts/llm_extract_skills.py

# 4. 建向量库（bge-m3 + FAISS）
python scripts/index_final_results.py --rebuild

# 5. 跑 Agent / 启动 Web
python scripts/find_jobs.py "杭州 Agent 开发" --verbose
python -m src.web.app          # http://localhost:8001

# 6. （可选）接入 MCP 生态
python src/mcp_server/ai_collector_mcp.py
```

---

*文档生成日期：2026-07-30 · 基于代码实际实现（`src/agent`、`src/rag`、`src/sources`、`src/mcp_server`、`src/web`、`scripts/`）盘点，非凭记忆。*
