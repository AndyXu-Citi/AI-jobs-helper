# 项目重构计划：backend / frontend 顶层分离 + 死代码清理 + README 重生成

> 状态：Proposed（待用户确认后执行）
> 日期：2026-08-16

## 一、当前设计复盘（问题诊断）

### 1.1 目录现状（痛点）
```
AI-jobs-helper/                # 项目根
├── src/                             # 所有 Python（backend 逻辑）
│   ├── web/
│   │   ├── app.py                   # FastAPI（API + 旧 static 托管）
│   │   ├── frontend/                # ← React 前端被埋在 src/web 里
│   │   └── static/                  # ← 旧单体 HTML（已被 React 取代，死）
│   ├── agent/ rag/ sources/ mcp_server/ ...
│   ├── collector.py monitor.py db_manager.py processor.py  # v1 遗留
├── main.py ai_collector_cron.py run_batch.py   # v1 编排入口（遗留）
├── test_*.py (×8, 顶层)             # 孤儿测试，pytest 根本不跑（testpaths=tests）
├── experiments/                     # 学习/草稿代码
├── 技术架构图*.svg 技术栈*.md 简历_Andy*.md RETROSPECTIVE.md run.sh  # 顶层杂物
├── scripts/ utils/ tests/ docs/ data/ .github/
```

**核心问题**
- 前端 `src/web/frontend/` 没有独立成顶层目录，与后端 `app.py` 耦合在同一 `src/` 包里。
- 存在两套平行世界：v1 采集流水线（`main.py`+`collector/monitor/processor`+`bilibili/arxiv` 源）与 v3 求职 Agent（`src/agent`+`src/rag`+`src/web/app.py`+`scripts/ingest_*`）。v1 已停用但代码未清。
- 8 个顶层 `test_*.py` 因 `pytest.ini` 的 `testpaths=tests` 而**从未被 CI 执行**，属于孤儿。
- `src/web/static/` 是迁移到 React 前的旧页面，已死。
- `README.md` 停留在 v3.0/3.1（写的是 Milvus Lite、81 测试、MCP 3 工具），与现在的「React 前端 + Milvus 服务端 + 记忆模块 + 统一对话」严重不符。

### 1.2 依赖关系结论（活 / 死）
- **活**（当前系统真正用到）：`src/agent/*`、`src/rag/*`、`src/web/app.py`、`src/db_config.py`、`src/db_conversation.py`、`src/sources/boss_zhipin.py`、`src/sources/base.py`、`src/mcp_server/*`、`src/sources/arxiv.py`（仅被 v1 main 用，见决策）、`scripts/*`（Boss 采集/RAG/记忆流水线）。
- **死**（仅被 v1 引用，无任何活代码 import）：`src/collector.py`、`src/monitor.py`、`src/processor.py`、`src/sources/bilibili.py`（已坏）、`main.py`、`ai_collector_cron.py`、`run_batch.py`、顶层 8 个 `test_*.py`、`experiments/`、`src/web/static/*`、`run.sh`、`scripts/record_demo.sh`。

## 二、目标布局（backend / frontend 顶层分离）

> 关键决策：**保留 `src/` 包名**（内部 `from src.xxx` 导入零改动），把它整体挪到 `backend/` 下，
> 运行时从 `backend/` 目录启动。这样迁移成本最低、导入路径不破。

```
AI-jobs-helper/
├── backend/                         # 所有后端（原 src/ 整体内移，导入不变）
│   ├── src/
│   │   ├── web/app.py               # FastAPI（GET / 改为托管 ../frontend/dist）
│   │   ├── agent/ rag/ sources/ mcp_server/ db_config.py db_conversation.py
│   │   └── (删除 collector/monitor/processor)
│   ├── scripts/                     # Boss 采集 / RAG 索引 / 记忆初始化
│   ├── utils/                       # Milvus 探路脚本（保留，便于运维）
│   ├── tests/                       # pytest（删除依赖死模块的用例）
│   ├── data/                        # 运行时产物（已 gitignore）
│   ├── requirements.txt requirements-dev.txt pytest.ini .env .env.example
│   └── (删除 main.py / cron / run_batch / experiments)
├── frontend/                        # 原 src/web/frontend 整体上移
│   ├── src/ package.json vite.config.ts tsconfig*.json
│   └── (删除 dist/，后续 npm run build 重建)
├── docs/                            # 设计文档（保留 milvus_migration_design.md）
├── .github/workflows/tests.yml      # 改为 cd backend && pytest
├── .gitignore README.md
└── (删除顶层杂物：技术架构图.svg / 技术栈.md / 简历.md / RETROSPECTIVE.md / run.sh / 顶层 test_*.py)
```

### 启动方式变化
| 场景 | 旧 | 新 |
|------|----|----|
| 后端 API | `python -m src.web.app`（根目录） | `cd backend && python -m src.web.app` |
| 前端 dev | `cd src/web/frontend && npm run dev` | `cd frontend && npm run dev` |
| 索引重建 | `python scripts/index_final_results.py --rebuild` | `cd backend && python scripts/index_final_results.py --rebuild` |
| 测试 | `pytest`（根目录） | `cd backend && pytest` |

## 三、清理清单（按风险分层）

### A. 安全删除（无活引用，纯死代码）
- `src/collector.py`、`src/monitor.py`、`src/processor.py`
- `src/sources/bilibili.py`（反爬已坏，仅 v1 用）
- `main.py`、`ai_collector_cron.py`、`run_batch.py`
- 顶层 8 个 `test_*.py`（孤儿，不进 CI）
- `tests/test_processor.py`、`tests/test_collector_dispatch.py`（依赖已删的 v1 模块）
- `experiments/`（学习草稿）
- `src/web/static/*`（旧单体页，被 React 取代）
- `src/web/frontend/dist/`（残次构建，重建）
- `run.sh`、`scripts/record_demo.sh`（bash，Windows 不可用）
- 顶层杂物：`RETROSPECTIVE.md`、`技术架构图_ai_collector.svg`、`技术栈_ai_collector.md`、`run.sh`

### B. 需你拍板（有取舍）
- **B1. `src/sources/arxiv.py` 去留**：删除则失去 arxiv 论文采集能力（目前仅 main.py 驱动）；保留则作为可选信息源留着（base.py 已留）。
- **B2. 个人简历文件 `简历_Andy_AI应用开发工程师.md`**：是否从仓库移除（属个人资料，非项目文档）。
- **B3. 前端生产托管是否一并做**：把 `app.py` 的 `GET /` 指向 `frontend/dist` 并删除旧 `static/`；还是只做目录整理、前端仍走 Vite dev server（5173）。

### C. 保留
- `src/agent/*`、`src/rag/*`、`src/web/app.py`、`src/db_config.py`、`src/db_conversation.py`
- `src/sources/base.py`、`src/sources/boss_zhipin.py`
- `src/mcp_server/*`
- `scripts/*`（ingest/enrich/index/search/find_jobs/init_db_memory/agent_runs/dump_raw*/scout/llm_extract_skills）
- `utils/check_milvus.py`、`probe_*.py`
- `tests/` 其余用例、`docs/`、`data/`（gitignore）、`.github/`

## 四、README 重生成方案
基于最新代码重写 `README.md`，覆盖：
1. 项目定位（v3.1 求职 Agent + React 前端 + Milvus 服务端 + 记忆模块）
2. 新目录结构（backend / frontend）
3. 快速开始（backend 启动 + frontend dev + 索引重建）
4. 架构图（采集→RAG→Agent→前端 数据流）
5. API 端点表（含 `/api/chat/unified`、`/api/resume/upload`、`/api/conversations`）
6. Milvus 迁移说明（指向 docs/milvus_migration_design.md）
7. 测试与 CI

## 五、执行顺序（确认后）
1. 先 Git 提交当前状态（安全基线）
2. 删除 A 类死代码
3. 按 B 决策处理arxiv/简历/前端托管
4. 移动 `src/→backend/src`、`frontend→顶层`、`scripts/utils/tests/data/requirements/.env` 入 `backend/`
5. 更新 `app.py` 静态路径、`pytest.ini` 无需改（testpaths 相对）、`.github/workflows/tests.yml` 加 `cd backend`
6. `cd backend && pytest` 验证测试不破
7. 重建 `frontend/dist`（若选 B3 生产托管）
8. 重写 README
9. 再 Git 提交
