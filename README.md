# 🤖 AI-jobs-helper — 求职 Agent v3.1

一个端到端的 **AI 求职 Agent**：自动采集 Boss 直聘真实岗位 JD，用语义向量检索匹配，用 LangGraph 编排「意图解析 → RAG 检索 → 反思决策 → 报告生成」，并通过 **React 前端**提供「求职助手 / 面试官」统一对话、岗位库浏览、技能报表三大功能。配套 **MySQL + Milvus** 双存储，支持跨会话记忆。

> 项目从 v1 采集流水线 → v2 RAG → v3 LangGraph Agent → v3.1（MCP Server + 记忆模块 + React 前端）持续演进。代码比 README 超前，本文档反映最新状态。

---

## 功能特性

- **统一对话（AI 助手模式）**：自然语言提问，自动识别「岗位搜索 / 简历匹配 / 简历诊断」意图，调用 RAG 检索 + LLM 深度分析。
- **面试官模式**：支持按 JD / 简历 / 项目 / 知识点四种维度进行「拷打式」面试，逐层深挖。
- **岗位库浏览**：从 Milvus 拉取全部岗位，支持技能多选 OR 筛选、按出现次数排序、默认展示首条 JD 详情。
- **技能报表**：统计高频技能、技能缺口与薪资分布。
- **PDF 简历上传**：前端上传 PDF，后端 pdfplumber 解析后用于匹配 / 诊断。
- **记忆模块**：MySQL 存会话原文 + Milvus 存语义向量（`user_id` 隔离，绝不跨用户），支持跨会话语义回忆。
- **混合向量检索**：bge-m3 dense 向量 + Milvus BM25 sparse 词面召回，RRFRanker 融合，召回质量显著优于纯 dense。

---

## 目录结构

```
AI-jobs-helper/
├── backend/                 # 所有后端代码（Python，导入根包为 src.*）
│   ├── src/
│   │   ├── web/app.py       # FastAPI：REST API + 统一对话 + 记忆
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
│       ├── components/      # Sidebar + ui 组件库
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

### 2. 前端

```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173 （Vite 开发服务器，代理 /api → :8001）
```

> 前端通过 Vite dev server 独立运行；`backend/src/web/static/` 仅保留占位页，`GET /` 不承载前端静态资源。生产部署可后续将 `app.py` 的 `GET /` 指向 `frontend/dist`。

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
┌─────────────┐     HTTP /api      ┌──────────────────────────┐
│  frontend   │ ─────────────────▶ │       backend (FastAPI)    │
│ (React/Vite)│ ◀────── JSON ───── │  src/web/app.py           │
└─────────────┘                    │     │                      │
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

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/` | 占位页（前端由 Vite 提供） |
| POST | `/api/chat` | 同步求职 Agent（find_jobs 完整结果） |
| POST | `/api/chat/stream` | SSE 流式输出 trace + 报告 |
| POST | `/api/chat/unified` | **统一对话入口**：自动意图识别，分发求职助手 / 面试官两模式 |
| GET  | `/api/jobs` | 查询历史岗位数据 |
| GET  | `/api/skill-gap` | 技能热度与缺口 |
| GET  | `/api/report` | 技能 / 薪资分布报表 |
| GET  | `/api/profile` | 当前求职者画像 |
| POST | `/api/match` | 简历匹配 |
| POST | `/api/match/rank` | 简历与岗位打分排序 |
| POST | `/api/interview` | 启动面试官会话 |
| POST | `/api/interview/chat` | 面试官继续对话 |
| GET  | `/api/interview/sessions` | 面试官会话列表 |
| POST | `/api/resume/upload` | 上传 PDF 简历（pdfplumber 解析） |
| GET  | `/api/conversations` | 会话历史列表（记忆模块） |
| GET  | `/api/conversations/{id}/messages` | 某会话的消息列表 |

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
| 后端 | FastAPI · Uvicorn · Pydantic · LangGraph · LangChain |
| 向量 | Milvus（hybrid dense+sparse）· bge-m3（HuggingFaceEmbedder）· FAISS（fallback） |
| 数据库 | MySQL 8.0（`final_results` / `conversations` / `chat_messages`） |
| 采集 | Playwright + CDP（Boss 直聘 Canvas 反爬绕过） |
| LLM | 任意 OpenAI 兼容端点（默认 DeepSeek） |
| MCP | FastMCP（v3.1，暴露检索 / 技能缺口工具） |

---

## 许可证

MIT
