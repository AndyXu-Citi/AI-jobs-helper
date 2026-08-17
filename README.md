# 🤖 AI-jobs-helper — 求职 Agent v3.1

一个端到端的 **AI 求职 Agent**：自动采集 Boss 直聘真实岗位 JD，用语义向量检索匹配，用 LangGraph 编排「意图解析 → RAG 检索 → 反思决策 → 报告生成」，并通过 **React 前端**提供统一的「求职助手 + 面试官」对话、岗位库浏览、技能报表三大功能。配套 **MySQL + Milvus** 双存储，支持跨会话记忆。

> 项目从 v1 采集流水线 → v2 RAG → v3 LangGraph Agent → v3.1（MCP Server + 记忆模块 + React 前端）持续演进。代码比 README 超前，本文档反映最新状态。
> 当前前端已把「求职助手」与「面试官」合并为 **单一统一对话入口**：所有对话走 `POST /api/chat/unified/stream`（SSE 真流式），UI 实时展示 Agent 思考步骤与逐 token 输出。

---

## 功能特性

- **统一求职助手（单入口，SSE 真流式）**：自然语言提问，后端自动识别「岗位搜索 / 简历匹配 / 简历诊断 / 闲聊」意图，调用 RAG 检索 + LLM 深度分析。**输出为逐 token 流式**，并实时展示 Agent 思考过程（每一步做了什么）。
- **内嵌面试官能力**：同一对话入口支持「针对我的简历面试 / 针对岗位 JD 模拟面试 / 知识点测验」三种维度，由快捷卡片触发；多轮面试通过 `session_id` 恢复上下文继续追问。
- **岗位库浏览**：从向量库拉取全部岗位，支持技能多选筛选、按出现次数排序、默认展示首条 JD 详情。
- **技能报表**：统计高频技能、技能缺口与薪资分布。
- **PDF 简历上传**：前端上传 PDF，后端 pdfplumber 解析后回填用于匹配 / 诊断 / 简历面试。
- **记忆模块**：MySQL 存会话原文 + Milvus 存语义向量（`user_id` 隔离，绝不跨用户），支持跨会话语义回忆。
- **混合向量检索**：bge-m3 dense 向量 + Milvus BM25 sparse 词面召回，RRFRanker 融合，召回质量显著优于纯 dense。

---

## 目录结构

```
AI-jobs-helper/
├── backend/                 # 所有后端代码（Python，导入根包为 src.*）
│   ├── src/
│   │   ├── web/app.py       # FastAPI：REST API + SSE 统一对话（unified/stream）+ 记忆
│   │   ├── agent/           # LangGraph 求职 Agent（graph / tools / nodes / prompts）
│   │   ├── rag/             # 向量化与检索（embedder / vector_store / memory_store）
│   │   ├── sources/         # 信息源（base.py 抽象基类 + boss_zhipin.py 实现）
│   │   ├── mcp_server/      # v3.1 MCP Server（暴露检索/技能缺口等工具）
│   │   ├── db_config.py     # MySQL 连接配置
│   │   └── db_conversation.py  # 会话 / 消息持久化
│   ├── scripts/             # Boss 采集、RAG 索引、检索、记忆初始化等脚本
│   ├── utils/               # Milvus 探路 / 探针脚本
│   ├── tests/               # pytest（离线单测：embedder / vector_store）
│   ├── data/                # 运行时产物（向量库索引、db 等，已 gitignore）
│   ├── requirements.txt     # 运行依赖
│   ├── requirements-dev.txt # 开发 / 测试依赖
│   ├── pytest.ini
│   └── .env                 # 敏感配置（从 .env.example 复制）
├── frontend/                # React 19 + Vite + TypeScript + Tailwind + Zustand
│   └── src/
│       ├── pages/           # ChatPage（统一对话）/ JobLibrary（岗位库）/ SkillReport（技能报表）
│       ├── components/      # Sidebar + ui 组件库（含 ThinkingSteps 思考步骤组件）
│       ├── stores/          # Zustand 状态（ChatStore / ConversationStore / JobStore）
│       └── api/ types/      # API 封装与类型定义
├── docs/
│   └── milvus_migration_design.md   # FAISS→Milvus 迁移与优化设计文档
└── .github/workflows/tests.yml      # CI：cd backend && pytest
```

---

## 快速开始

### 1. 后端

```bash
cd backend

# 创建虚拟环境（推荐 Python 3.11+/3.12）
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements-dev.txt

# 配置环境变量
cp .env.example .env        # 然后填入 LLM_API_KEY / DB_* / MILVUS_URL

# 初始化数据库表（首次运行自动建表；记忆表需手动跑一次）
python scripts/init_db_memory.py

# 启动 API 服务
python -m src.web.app        # 默认 http://localhost:8001 ，Swagger: /docs
```

> **端口说明**：`src/web/app.py` 的 `__main__` 把 `uvicorn.run(..., port=8001)` 写死，因此 `python -m src.web.app` 固定监听 **8001**。若要换端口，请用 uvicorn CLI：
> `python -m uvicorn src.web.app:app --host 0.0.0.0 --port 8002 --reload`
> 启动前请确认目标端口未被旧进程占用（占用的话 uvicorn 会报 `Address already in use`）。

### 2. 前端

```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173 （Vite 开发服务器，代理 /api → :8001）
```

> 前端通过 Vite dev server 独立运行；`backend/src/web/static/` 仅保留占位页，`GET /` 不承载前端静态资源。生产部署可后续将 `app.py` 的 `GET /` 指向 `frontend/dist`。
> 若 5173 被占用，Vite 会自动顺延（5174、5175…），记得同步把 `vite.config.ts` 的 proxy target 指向实际后端端口。

### 3. 采集与索引

```bash
cd backend

# ① 从 Boss 直聘采集岗位（需 CDP 接管已登录的 Chrome，详见 scripts/ingest_boss_jobs.py）
python scripts/ingest_boss_jobs.py

# ② 补全 JD 正文（enrich）
python scripts/enrich_boss_details.py

# ③ 重建向量索引进 Milvus（--rebuild 全量重建）
python scripts/index_final_results.py --rebuild
```

---

## 架构与数据流

```
┌─────────────┐   SSE /api/chat/unified/stream   ┌──────────────────────────┐
│  frontend   │ ───────────────────────────────▶ │       backend (FastAPI)    │
│ (React/Vite)│ ◀──── 逐 token content + step ── │  src/web/app.py           │
└─────────────┘                                  │     │                      │
                                                  │     ▼                      │
                                                  │  src/agent (LangGraph)    │
                                                  │     │  vector_search_jobs  │
                                                  │     ▼                      │
                                                  │  src/rag/vector_store ──▶ Milvus (hybrid)
                                                  │  src/rag/embedder (bge-m3)│
                                                  │     │                      │
                                                  │     ▼                      │
                                                  │  MySQL: final_results /   │
                                                  │  conversations / messages │
                                                  └──────────────────────────┘
```

- **采集**：`scripts/ingest_boss_jobs.py` 经 Playwright/CDP 抓取 Boss 直聘 JD → 写入 MySQL `final_results`。
- **索引**：`index_final_results.py` 用 bge-m3 将 JD 文本（含正文）向量化 → 写入 Milvus `job_docs`（dense + BM25 sparse）。
- **检索**：用户提问 → `embedder` 向量化 + 原文送 BM25 → Milvus hybrid 检索 → 返回相关岗位。
- **记忆**：每轮对话原文落 MySQL，语义向量落 Milvus `chat_memory`（按 `user_id` 过滤），新会话可跨会话回忆。

---

## API 端点

> 前端只使用 **`POST /api/chat/unified/stream`** 这唯一一个对话端点（SSE 真流式）。其余 `/api/chat`、`/api/chat/stream`、`/api/interview*`、`/api/match`、`/api/match/rank` 为早期单调用 / 搜索专用端点，功能已被 unified/stream 覆盖，保留用于脚本与向后兼容。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/` | 占位页（前端由 Vite 提供） |
| POST | `/api/chat/unified/stream` | **统一对话 SSE 流式入口**（前端唯一对话端点，含助手 / 面试全场景） |
| POST | `/api/chat/unified` | 统一对话同步版（legacy，已被 `/stream` 覆盖） |
| POST | `/api/chat` | 求职 Agent 同步（find_jobs 完整结果） |
| POST | `/api/chat/stream` | 岗位搜索 SSE 流式（legacy，仅 search） |
| GET  | `/api/jobs` | 查询历史岗位数据 |
| GET  | `/api/skill-gap` | 技能热度与缺口 |
| GET  | `/api/report` | 技能 / 薪资分布报表 |
| GET  | `/api/profile` | 当前求职者画像 |
| POST | `/api/match` | 简历匹配（legacy 单调用，已被 `/unified/stream` 覆盖） |
| POST | `/api/match/rank` | 简历与岗位打分排序（legacy） |
| POST | `/api/interview` | 启动面试官会话（legacy 单调用，已被 `/unified/stream` 覆盖） |
| POST | `/api/interview/chat` | 面试官继续对话（legacy） |
| GET  | `/api/interview/sessions` | 面试官会话列表（legacy） |
| POST | `/api/resume/upload` | 上传 PDF 简历（pdfplumber 解析） |
| GET  | `/api/conversations` | 会话历史列表（记忆模块） |
| GET  | `/api/conversations/{id}/messages` | 某会话的消息列表 |

---

## 统一对话（SSE 流式协议）

**入口**：`POST /api/chat/unified/stream`，请求体为 `UnifiedChatRequest`（JSON）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `message` | str | 用户消息（必填） |
| `mode` | str | `assistant`（求职助手）\| `interviewer`（面试官） |
| `session_id` | str | 续轮面试用；首条留空，后端生成 8 位 session 恢复上下文 |
| `resume_text` | str | 已上传 / 粘贴的简历全文 |
| `jd_text` | str | JD 面试用的岗位描述 |
| `interview_submode` | str | `resume` \| `jd` \| `project` \| `knowledge` |
| `skill_topic` | str | 知识点测验选中的领域（knowledge 子模式首条用） |

**响应**：`text/event-stream`，每条事件格式为 `data: {json}\n\n`，事件类型：

| 事件 | 字段 | 含义 |
|------|------|------|
| `intent` | `intent` | `search` \| `match` \| `diagnose` \| `interview` \| `chat`（意图判定） |
| `trace` | `content` | 仅 search 路径推送的 Agent 中间轨迹 |
| `step` | `label`, `status`(`running`/`done`), `detail?` | **Agent 思考步骤**，UI 折叠展示（如「向量检索匹配岗位」「生成诊断报告」） |
| `content` | `delta` | 逐 token 正文（真流式） |
| `done` | `data` | 终态：`reply` / `intent` / `match_results?` / `filtered_jobs?` / `session_id?` / `round?` |
| `error` | `message` | 错误提示（如未上传简历时引导上传） |

**助手模式（`mode=assistant`）**：后端 `_detect_assistant_intent` 自动识别 `search`/`match`/`diagnose`/`chat`。`match`/`diagnose` **必须有简历**（`resume_text`）；若缺失，不会误走搜索，而是推 `content` 引导用户先上传简历。`search` 走 LangGraph 手动编排（解析意图 → 检索 → 过滤 → 反思 → 报告），每步推 `step` 事件，报告逐 token 推 `content`。

**面试官模式（`mode=interviewer`）**：`interview_submode` 决定素材来源（resume/jd/project/knowledge；knowledge 用 `skill_topic`）。首条启动面试（准备素材 → 检索历史记忆 → 首轮提问，均推 `step` + `content`），续轮带 `session_id` 恢复会话继续追问。

---

## 记忆模块（双存储）

- **MySQL**（`conversations` / `chat_messages`）：结构化会话原文，按用户隔离、可分页、可审计。
- **Milvus**（`chat_memory` 集合）：会话语义向量，检索时强制 `filter=user_id`，绝不跨用户。
- 写入策略：每轮 `user` 消息实时写 MySQL + 异步写 Milvus 语义向量；诊断 / 匹配 / 面试分支注入历史记忆。

---

## 向量库：FAISS → Milvus

- 主向量库为 **Milvus**（standalone），启用 **dense(bge-m3) + sparse(BM25) 混合检索 + RRFRanker 融合**。
- 未配置 `MILVUS_URL` 时自动回退 **FAISS** 本地索引（`src/rag/vector_store.py` 内部按环境变量切换）。
- 迁移与优化细节（含向量化文本纳入 JD 正文、长 JD 分块、分数映射修正等）见 [`docs/milvus_migration_design.md`](docs/milvus_migration_design.md)。

**关键配置**（`backend/.env`）：

```ini
MILVUS_URL=http://192.168.1.9:19530     # Milvus gRPC 地址（8000 为 REST/WebUI 代理，SDK 连不上）
# 不填则回退 FAISS
```

---

## 测试与 CI

```bash
cd backend
pytest tests/ -m unit        # 离线单测：embedder / vector_store（FAISS fallback）
```

- `pytest.ini` 的 `testpaths = tests`，仅运行 `backend/tests/`。
- CI（`.github/workflows/tests.yml`）自动 `cd backend && pip install -r requirements-dev.txt && pytest`。
- `tests/test_rag_vector_store.py` 含需 `MILVUS_URL` 的集成测试（自动跳过无服务端时）。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React 19 · Vite · TypeScript · Tailwind CSS v4 · Zustand · ECharts（echarts + echarts-for-react，技能报表 Treemap 板块图） |
| 后端 | FastAPI · Uvicorn（SSE StreamingResponse）· Pydantic · LangGraph · LangChain |
| 向量 | Milvus（hybrid dense+sparse）· bge-m3（HuggingFaceEmbedder）· FAISS（fallback） |
| 数据库 | MySQL 8.0（`final_results` / `conversations` / `chat_messages`） |
| 采集 | Playwright + CDP（Boss 直聘 Canvas 反爬绕过） |
| LLM | 任意 OpenAI 兼容端点（默认 DeepSeek） |
| MCP | FastMCP（v3.1，暴露检索 / 技能缺口工具） |

---

## 许可证

MIT
