<!-- 说明：方括号【】内为需要你自行替换的占位内容（手机/邮箱/学校/公司名等）。其余均为本项目真实能力，可直接投递。 -->

# Andy
**AI 应用开发工程师（测试转型）**

- 手机：【1xx-xxxx-xxxx】 ｜ 邮箱：【andyl@example.com】 ｜ 城市：上海（可调配至杭州/苏州/青岛等）
- GitHub：github.com/nakajimamiyuki/ai_collector_project ｜ 技术博客：CSDN（AI 工程系列 5 篇）
- 期望薪资：18–22K ｜ 到岗时间：【可面议】

---

## 求职意向

AI 应用开发工程师 / AI Agent 工程师 / LLM 应用工程师 / RAG 工程师

---

## 个人简介

2 年软件测试与质量评测经验（军工/航天级 CNAS+CMA 评测体系），具备扎实的测试用例设计、缺陷管理与**评测闭环**能力；近半年自学并独立从 0 到 1 构建端到端 AI 求职 Agent 项目，完整覆盖 **Agent 编排（LangGraph）、RAG 检索（bge-m3 + Milvus）、反爬数据采集（Playwright + CDP）、MCP 协议开发**与工程化测试，已开源并配套 5 篇技术博客。对"问题归因 + 回归验证"的工程方法论有天然手感，能直接迁移到 AI 应用的评测与 Bad Case 治理。

---

## 教育背景

- **本科 · 计算机相关专业** — 【学校名称】（【入学年份】–【毕业年份】）

---

## 核心技能

- **语言**：Python（主力，asyncio 异步编程）、SQL
- **Agent / LLM**：LangGraph（5 节点 DAG + conditional_edge 反思循环）、LangChain、Prompt 工程、Function Calling / Tool Use
- **RAG**：bge-m3 embedding、HuggingFace Transformers、Milvus Lite / Milvus 向量库、语义检索召回
- **协议 / 集成**：MCP（FastMCP，stdio 传输）、REST API 封装为智能体工具
- **数据采集**：Playwright、Chrome DevTools Protocol（CDP）接管真实浏览器、反爬绕过（cookie 持久化、同源 fetch、节流退避）
- **后端 / 存储**：FastAPI、SQLite、MySQL
- **工程化**：pytest（81 单测全绿）、GitHub Actions CI、Git、失败自动重试 / 限流 / 指数退避
- **质量**：测试用例设计、Bug 跟踪、评测体系与 Bad Case 闭环、对话链路质量监控

---

## 项目经历

### AI Collector — 端到端 AI 求职 Agent（v3.0）+ MCP Server（v3.1）｜ 独立作者 ｜ 2026.06

**项目描述**
一个从「采集 + LLM 清洗」一路演进到「LangGraph 求职 Agent + MCP 生态原生」的端到端项目。用真实 Chrome（CDP 接管）绕过 Boss 直聘 Canvas 反爬，从 5 城市采集 192+ 条 AI 岗位真实 JD；用 Milvus + bge-m3 做语义检索；用 LangGraph 5 节点 DAG 完成「意图解析 → RAG 检索 → 反思决策 → 报告生成」；并通过自研 MCP Server 把能力暴露给任意 MCP 客户端；每次运行自动落 Bad Case 库，形成"跑 → 复盘 → 修 → replay"闭环。**用自己造的 Agent 跑通了完整求职链路，并据 192 条市场数据反推出学习路线。**

**项目亮点**
1. **真 Agent 编排**：LangGraph 5 节点 DAG（parse_intent → retrieve → filter → reflect → summarize）。reflect 节点用 conditional_edge 实现"0 结果自主换近义词重搜"，最多 3 轮；自然语言意图解析覆盖薪资（"15K+"）、城市（"北京以外"）、年限（"1-3 年"）、黑名单等硬条件，硬过滤 + 向量软排序结合。
2. **反爬数据采集**：独立 Chrome profile + 9222 调试端口，Playwright 经 CDP 接管真实浏览器，同源 fetch 自动带 cookie，绕过 Boss 直聘 Canvas 反爬与 code37 风控；节流（随机 0.6–1.4s）+ 指数退避（1.5^attempt）把临时风控的重试救活率拉到 100%；启发式去噪过滤实习/校招/销售包装岗。
3. **RAG 语义检索**：本地 bge-m3（1024 维中英混合 SOTA）+ Milvus Lite 单文件向量库，4 query benchmark 召回 A+（最高 0.901 余弦相似度），支持跨城市 / 跨源 / 跨语言命中；整段 embed 的 YAGNI 取舍清晰。
4. **自研 MCP Server**：基于 FastMCP 暴露 3 个 Tool —— `search_jobs`（字面检索）/ `query_rag`（语义检索）/ `get_skill_gap`（市场技能热度 vs 个人画像缺口），stdio 传输，Claude Desktop / Cursor / Hermes Agent 等任意 MCP 客户端零配置调用。
5. **Bad Case 闭环**：每次 Agent 运行落 `agent_runs.db`，零结果自动标 bad；支持 `mark root_cause` + `replay` 批量回归验证，复用军工评测"问题归因 + 回归"习惯——这是 AI 应用质量保障的直接体现。
6. **工程化素养**：插件式多源架构（`BaseSource` 抽象，加新数据源只写一个子类）；81 个 pytest 单测全离线 mock、GitHub Actions CI 每次 push 自动跑；失败自动重试 + 限流 + 退避；graph 编译缓存降低延迟。
7. **知识沉淀**：配套 5 篇 CSDN 技术博客（v1.0→v3.1 完整工程演进：采集 Agent → 插件化重构 → RAG → LangGraph Agent → MCP），开源仓库 README 30 秒可读。

**技术栈**
`Python` · `LangGraph` · `LangChain` · `bge-m3` · `HuggingFace Transformers` · `Milvus Lite` · `Playwright` · `Chrome DevTools Protocol` · `MCP / FastMCP` · `FastAPI` · `SQLite / MySQL` · `pytest` · `GitHub Actions`

---

## 工作 / 评测经历

**【公司名称】 · 软件测试 / 质量评测工程师 ｜ 【2024.xx – 2026.xx】**
- 负责军工 / 航天级产品的测试与 CNAS+CMA 评测，设计测试用例、跟踪缺陷、建立可复现的评测闭环
- 沉淀"问题归因 + 回归验证"方法论，后直接迁移到 AI 项目的 Bad Case 治理与对话链路质量监控
- 【可补充：自动化测试 / 接口测试 / 性能测试等相关产出】

---

## 其他

- **开源**：github.com/nakajimamiyuki/ai_collector_project（端到端 AI 求职 Agent，81 单测 + CI）
- **技术输出**：CSDN 5 篇 AI 工程系列博客（累计覆盖采集 Agent、插件化架构、RAG 实战、LangGraph Agent、MCP 接入）
- **方法论**：用自己造的 Agent 完成求职，并据市场数据反推学习路线（MCP / LangGraph / Agent 为市场最缺技能）
