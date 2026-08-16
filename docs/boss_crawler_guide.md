# Boss 直聘爬虫使用与技术文档

> 本文档说明 `AI-jobs-helper` 项目中 Boss 直聘采集爬虫的**使用方法**、**具体步骤**与**使用到的技术**。
> 爬虫负责：自动抓取 Boss 直聘真实岗位 JD → 落 MySQL → 向量化入 Milvus/FAISS，供上层 Agent 检索。

---

## 一、爬虫能做什么

| 能力 | 说明 |
|------|------|
| 抓列表 | 按 `城市 × 关键词 × 页数` 笛卡尔积批量抓取搜索结果，落 `final_results` 表 |
| 去噪 | 自动过滤日结、校招/实习、保险代理等低质岗位 |
| 补 JD 正文 | 用详情 API 补全岗位描述、公司名、学历、经验要求 |
| 向量化 | 把结构化岗位送 bge-m3 编码，写入 Milvus（dense+sparse hybrid）或 FAISS 回退 |
| 断点续传 | 海量抓取中途中断，重跑自动跳过已完成项、重试失败项 |
| LLM 技能提取 | 用 LLM 从 JD 正文提取技术关键词，写入 `_boss.skills_extracted`（enrich 之后、index 之前） |
| 一键运行 | `run_boss_pipeline.py` 串联 ingest → enrich → extract_skills → index → 可选检索验证 |

---

## 二、用到的技术

| 技术 | 用途 |
|------|------|
| **Python 3** | 整体实现（脚本为 `asyncio` 异步） |
| **Playwright (CDP)** | `connect_over_cdp` 接管用户已登录的真实 Chrome，复用其 cookie 绕过风控 |
| **MySQL (mysql.connector)** | 持久化 `final_results` / `task_queue` 等结构化数据 |
| **Milvus / FAISS** | 向量存储。配 `MILVUS_URL` 走 Milvus 双路 hybrid，否则 FAISS 本地回退 |
| **bge-m3 (sentence-transformers)** | 中文 SOTA 语义向量，输出 dense(1024) + sparse，进程内加载 |
| **RRFRanker** | Milvus hybrid 检索时融合 dense 与 sparse 两路结果 |
| **HuggingFaceEmbedder** | 封装 bge-m3 的 embedding 调用（项目默认，非 Ollama） |
| **OpenAI 兼容 LLM（DeepSeek）** | 两层都用：①**爬虫链路**的 `llm_extract_skills.py` 从 JD 正文提取技能关键词；②上层求职 Agent（意图解析/反思/报告） |
| **dotenv** | 从 `backend/.env` 读取 MySQL / LLM 配置 |

**核心反爬思路**：Boss PC 站列表用 Canvas 渲染拿不到文字，移动端 H5（m.zhipin.com）有 JSON API。爬虫用 CDP 接管真实 Chrome + 复用真人 cookie，使请求来自真实浏览器，天然绕过 `code 37` 风控，无需逆向签名。

---

## 三、前置准备

### 3.1 环境
- 已安装 `.venv` 并装好 `requirements.txt`（Playwright / mysql-connector / pymilvus / sentence-transformers 等）
- `backend/.env` 已配置 MySQL：`DB_HOST / DB_USER / DB_PASSWORD / DB_NAME`
- 若用 Milvus，需设 `MILVUS_URL`；否则自动走 FAISS

### 3.2 启动已登录的 Chrome（一次性）
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:USERPROFILE\.hermes\chrome-debug-profile"
```
在该 Chrome 里**手动打开 m.zhipin.com 并扫码登录**（cookie 持久化，后续不用重复登录）。
> 此窗口/进程需保持开着，爬虫通过 `127.0.0.1:9222` 接管它。

---

## 四、整体流程

```
准备: 启动 Chrome(CDP 9222) + 手动登录 m.zhipin.com
        │
        ▼
① ingest_boss_jobs.py   抓搜索列表 → 去噪 → 去重 → MySQL final_results
        │
        ▼
② enrich_boss_details.py  securityId+lid → 详情 API → 补全 JD/公司/学历/经验
        │
        ▼
③ llm_extract_skills.py  LLM 从 JD 正文提取技能关键词 → 写回 _boss.skills_extracted
        │
        ▼
④ index_final_results.py  build_embed_text 加权拼字段(含 skills_extracted) → bge-m3 → Milvus/FAISS
        │
        ▼
⑤ (可选) search.py / find_jobs.py  语义 + BM25 混合检索
```

---

## 五、具体步骤详解

### 步骤 ①：抓取列表 `ingest_boss_jobs.py`
- **输入**：`城市 × 关键词 × 页数` 笛卡尔积（默认 `上海 / Agent / 1 页`）
- **每个查询**：
  1. 在已登录 context 里 `new_page()` 并先 `goto m.zhipin.com` 重建同源会话
  2. 用 `page.request.fetch` 调 `GET /wapi/zpgeek/search/joblist.json`（同源 cookie 自动带）
  3. 解析出 `BossJob`（jobName / salaryDesc / skills / jobLabels / boss / encryptJobId）
- **去噪**：自动剔除日结、校招/实习、保险代理类
- **落库**：`boss_job_to_structured()` 转为 `structured_json` 契约 → 批内 URL 去重 → 写 `final_results`（`_boss` 子结构保留 `securityId / lid` 供 enrich 用）
- **断点续传**：`backend/data/boss_checkpoint.json` 记录已完成查询，重跑自动跳过

### 步骤 ②：补全 JD `enrich_boss_details.py`
- 从 `final_results` 找出缺 `post_description` 的 Boss 条目
- 取 `_boss.securityId + lid` → 调 `GET /wapi/zpgeek/job/card.json`
- 把 JD 正文、公司名、学历、经验合并回 `structured_json`（并升级 `summary / key_points / tags` 让 embedding 更准）
- ⚠️ 旧数据若没保存 `securityId/lid` 无法补全，需重跑 ingest

### 步骤 ③：LLM 技能提取 `llm_extract_skills.py`
- 从 `final_results` 找出**有 JD 正文**且还没提取过技能的 Boss 条目（靠 `_boss.skills_extracted` 标记去重，幂等）
- 每次 **8 条**一批调 LLM，从 JD 正文提取技术关键词（语言/框架/工具/平台/概念），写回 `_boss.skills_extracted`
- 价值：Boss 官方 `skills` 标签常常覆盖不全，LLM 提取的补充技能会进入下一步向量化，**提升语义召回命中率**
- ⚠️ 本步骤**需要 LLM**（`LLM_API_KEY` 等）。可用 `--force` 重提全部；不想调 LLM 时一键脚本加 `--skip-extract-skills`

### 步骤 ④：向量化 `index_final_results.py`
- `build_embed_text()` 按权重拼文本（标题 > 城市/薪资 > 技能(含 `skills_extracted`) > 简介 > 要点 > 标签 > 正文，超 4000 字截断，长 JD 滑动窗口分块）
- `HuggingFaceEmbedder(bge-m3)` 编码 → `VectorStore.upsert_chunks` 写入 Milvus 或 FAISS
- `--rebuild` 清空重建；**enrich / extract 后必须重建**，否则旧向量不含 JD 正文与提取技能、召回质量下降

### 步骤 ⑤：检索验证（可选）
- `search.py "查询语句" --source boss_zhipin`：query 同时送 dense + BM25 → Milvus hybrid + RRFRanker 融合 → 按 url 去重 → join MySQL 拿详情

---

## 六、一键运行

已封装 `run_boss_pipeline.py`（及 Windows 入口 `run_boss_pipeline.ps1`）：

```powershell
# 默认：上海 / Agent / 1 页 / 重建向量库
python run_boss_pipeline.py

# 多城市多关键词抓 2 页，最后检索验证
python run_boss_pipeline.py `
  --cities 杭州,苏州 `
  --keywords AI应用开发,大模型,LangChain,Agent `
  --pages 2 `
  --smoke-test "杭州 LangChain 岗位"

# 只抓列表 + 提取技能 + 索引，不补 JD
python run_boss_pipeline.py --skip-enrich

# 不调 LLM，跳过技能提取（适合无 LLM 配置或仅验证抓取链路）
python run_boss_pipeline.py --skip-extract-skills

# 强制重新提取全部 JD 的技能（重跑技能提取步骤）
python run_boss_pipeline.py --force-extract

# 追加式索引（不重建向量库）
python run_boss_pipeline.py --no-rebuild

# Windows PowerShell 入口（参数原样透传）
.\run_boss_pipeline.ps1 --cities 杭州 --keywords AI应用开发 --pages 2
```

**脚本内置**：
- 自动发现 `.venv/Scripts/python.exe`（从 backend 向上回溯到仓库根）
- 预检 `.env` / CDP 端口 / MySQL 连接（若运行技能提取步骤还会预检 LLM_API_KEY），不通过直接退出并给出提示
- 每步打印醒目横幅：`▶ STEP n/5 · <步骤名>` 开始、`✔ STEP n/5 · <步骤名> 完成（耗时 Xs）` 结束（双分隔线），无论子步骤刷多少进度日志都能一眼看到起止
- 结尾打印总耗时
- 任一环节失败立即停止
- 执行顺序：`ingest → enrich → llm_extract_skills → index →(可选) 冒烟测试`

> 💡 **增量抓取提速**：默认 `--rebuild` 会重建**整个**向量库（本次 150 条全文重 embed 耗时约 12 分钟）。日常小批量新增请用 `--no-rebuild`，只把新岗位 upsert 进 Milvus，快几十倍。

---

## 七、常用参数

### ingest_boss_jobs.py
| 参数 | 默认 | 说明 |
|------|------|------|
| `--cities` | `上海` | 逗号分隔城市 |
| `--keywords` | `Agent` | 逗号分隔关键词 |
| `--pages` | `1` | 每查询抓几页 |
| `--min-delay` / `--max-delay` | `2.0` / `5.0` | 请求间随机延迟（秒） |
| `--max-retries` | `3` | 单查询最大重试 |
| `--no-resume` | 关 | 忽略断点强制全抓 |

### enrich_boss_details.py
| 参数 | 默认 | 说明 |
|------|------|------|
| `--limit` | 无 | 只补前 N 条（调试） |
| `--rerun` | 关 | 已补过的也重抓 |

### index_final_results.py
| 参数 | 默认 | 说明 |
|------|------|------|
| `--rebuild` | 关 | 清空重建向量库 |
| `--limit` | 无 | 只索引前 N 条（调试） |

### llm_extract_skills.py（技能提取，enrich 之后跑）
| 参数 | 默认 | 说明 |
|------|------|------|
| `--force` | 关 | 重新提取全部 JD 的技能（默认只处理未提取的，幂等） |

---

## 八、反爬机制（能跑稳的关键）

| 机制 | 说明 |
|------|------|
| 根因 | Boss WAF 对"同一页面会话连续打 API"做连接级封禁（首个成功、后续 `Failed to fetch`） |
| 治本 | 每次查询 `new_page()` + 先 `goto m.zhipin.com` 重置会话；用 `page.request.fetch` 脱离页面 JS 上下文 |
| 退避 | 请求间随机延迟 `2~5s`；`code 37`/风控页长冷却 `20s+`；连续 5 次失败整段冷却 `60s` |
| 容错 | 重试上限内每次重试也换新标签页；`about:blank` 视为瞬时导航故障走短退避 |
| 多账号 | `BossSource(cookies=[...])` 支持注入 cookie 突破单账号频控 |

---

## 九、数据落库

| 存储 | 内容 |
|------|------|
| MySQL `final_results` | 结构化岗位（`structured_json` 含 `_boss` 富字段） |
| MySQL `task_queue` / `urls_history` | 采集流程驱动表 |
| Milvus `job_docs` | dense(1024) + sparse 双向量、url/title/city/source_type 标量 |
| FAISS `data/vector.db` | 无 Milvus 时的本地回退 |

> 检索时向量库只存"可检索文本 + 元信息"，完整 JD 详情在 MySQL，检索后按 url join，向量库保持轻量。

---

## 十、常见问题

| 现象 | 原因 / 解决 |
|------|------|
| 连不上 CDP | Chrome 未用 9222 启动或未保持运行；按 3.2 启动 |
| 首条成功后续全失败 | 同会话连续打 API 被封；脚本已用新标签页规避，仍失败调大延迟 |
| enrich 提示缺 securityId/lid | 旧数据没存配对参数，重跑 `ingest_boss_jobs.py` |
| 召回不准 | enrich 后忘了 `--rebuild` 索引 |
| MySQL 连接报错 | 检查 `backend/.env` 的 DB_* 配置 |
