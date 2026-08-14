# AI Collector — 技术栈与架构梳理

> 项目定位：端到端 AI 求职 Agent（自研作品型学习项目）。
> 整理口径：**以实际代码为准**（README 部分内容已过时，见文末对照表）。
> 整理时间：2026-08-11

---

## 一、前端技术

| 技术点 | 说明 |
|---|---|
| 原生 HTML / CSS / JS | 无前端框架，单文件 `src/web/static/index.html`，内联 `<style>` + `<script>` |
| Tab 多视图架构 | 求职 Agent / 岗位库 / 技能报表 / 简历匹配 / AI 面试 共 5 个 Tab 切换 |
| Fetch API | 所有后端调用走原生 `fetch`（拼接 `API_BASE + '/api/xxx'`） |
| SSE 流式渲染 | 消费 `/api/chat/stream`，逐条追加 trace + 最终报告（打字机效果） |
| 标签云 + 多选筛选 | 技能统计在前端用 `Object.keys` + `Counter` 聚合，支持按技能过滤岗位 |
| 聊天气泡 UI | AI / 用户双色气泡 + 加载动画 + 维度标签（正则提取 `[xxx]`） |
| 会话管理 | AI 面试用前端内存数组管理会话列表（非持久化，刷新即清空） |
| 响应式布局 | `@media` 移动端适配，左右分栏在窄屏下自动转为上下堆叠 |

---

## 二、后端技术

| 技术点 | 说明 |
|---|---|
| FastAPI | Web API 框架，由 `uvicorn[standard]` 启动（默认端口 8000） |
| 9 个 REST / SSE 端点 | `/api/chat`（同步）、`/api/chat/stream`（SSE）、`/api/jobs`、`/api/report`、`/api/match`、`/api/match/rank`、`/api/profile`、`/api/interview`、`/api/interview/chat` |
| Pydantic | `ChatRequest` / `MatchRequest` / `InterviewStartRequest` 等请求模型做入参校验 |
| MySQL | `mysql-connector-python` 驱动；`final_results`（岗位库）、`agent_runs`（Bad Case）两库隔离 |
| JSON_TABLE 解析 | 用 MySQL 8.0 `JSON_TABLE` 把 `structured_json` 内的技能数组展平统计 |
| python-dotenv | `.env` 注入 `LLM_API_KEY` / `LLM_API_BASE` / `DB_HOST` 等配置 |
| StaticFiles | FastAPI 直接托管 `src/web/static/` 前端静态目录 |

---

## 三、AI / 智能技术（核心亮点）

### 1. Agent 编排 — LangGraph
- **5 节点 DAG**：`parse_intent`（LLM 意图解析）→ `retrieve`（RAG 检索）→ `filter`（硬过滤）→ `reflect`（LLM 反思）→ `summarize`（LLM 报告）
- **反思循环**：`conditional_edge` 实现「0 结果时 LLM 自主换近义词重搜」，最多 3 轮
- 3 个 LLM 节点 + 2 个纯函数节点；意图解析识别「15K+」「北京以外」「1-3 年」等条件

### 2. LLM 调用层 — LangChain 生态
- `langchain` / `langchain-openai` / `langchain-community`
- **OpenAI 兼容客户端** `ChatOpenAI`，**实际接入 DeepSeek**（`deepseek-chat`，由 `.env` 的 `LLM_API_BASE` + `LLM_API_KEY` 注入，不绑定厂商）
- 单次查询 2~4 次小调用，成本 < 1 分

### 3. RAG 检索
- **Embedding**：`HuggingFaceEmbedder`（BAAI/bge-m3，1024 维，进程内加载，无需 Ollama）
- **向量库**：`faiss-cpu`（本地 FAISS 索引，规避 Milvus 在 Windows 的兼容性问题）
- 检索：余弦相似度 + 硬过滤（薪资 / 城市 / 学历 / 经验 / 黑名单）+ 软排序

### 4. MCP Server（v3.1）
- `mcp==1.26.0`，用 **FastMCP** 暴露 **3 个 Tool**：`search_jobs`（字面）、`query_rag`（语义）、`get_skill_gap`（技能缺口）
- **stdio 传输**，可被 Claude Desktop / Cursor / Hermes 等调用

### 5. Bad Case 闭环（v3.1）
- 每次运行自动落 `agent_runs.db`，零结果自动标 bad
- `replay` 命令批量重跑，验证修复是否生效（回归测试）

### 6. 数据采集 / 反爬
- **Playwright + playwright-stealth** 浏览器自动化
- **CDP 接管真实 Chrome**（`--remote-debugging-port=9222`）+ 手动扫码登录，绕过 Boss 直聘 Canvas 反爬 + code37 风控
- 多源插件架构 `BaseSource`：Bilibili / arXiv（Atom XML）/ Boss 直聘

### 7. 工程化
- **81 个 pytest 单测**（全离线 mock，不依赖外部网络）+ **GitHub Actions CI**
- 失败重试 + 指数退避 + 节流

---

## 四、技术栈一句话版（可直接写简历）

> 自研**端到端 AI 求职 Agent**：基于 **LangGraph** 5 节点 DAG + 反思循环编排；**FastAPI** 提供 9 个 REST/SSE 接口；**RAG** 用本地 **bge-m3 (HuggingFace)** + **FAISS** 语义检索；**MCP Server (FastMCP)** 暴露 3 个工具接入 Claude/Cursor；**Playwright CDP** 接管真实 Chrome 绕过 Boss 反爬采集 240+ 岗位；后端 **MySQL** 存储，前端原生 HTML/JS 实现 5 大功能页；**DeepSeek** 驱动全部 LLM 决策节点；81 单测 + GitHub Actions CI 保障质量。

---

## 五、⚠️ README 已过时 — 投递务必按实际代码写

| 维度 | README 写的 | **实际代码（按这个写）** |
|---|---|---|
| 数据库 | SQLite | **MySQL** |
| Embedding | Ollama bge-m3 | **HuggingFace bge-m3（本地）** |
| 向量库 | Milvus Lite | **FAISS（faiss-cpu）** |
| LLM | 火山引擎 kimi-k2.6 | **DeepSeek（deepseek-chat）** |
| 岗位数 | 192 条 | **240+ 条 Boss（含 3 篇 arXiv）** |
| 前端 | 未记载 | **原生 HTML/JS 5 Tab + SSE 流式** |

---

## 六、技术架构图

见同目录：`技术架构图_ai_collector.svg`（分层架构：Browser → Frontend → FastAPI → AI 智能层 → 数据采集 → 存储）
