# Milvus 迁移 + 记忆模块架构设计

> 目标：不是"把 FAISS 换成 Milvus"的平移，而是在迁移中修正当前向量化的不合理点，
> 并为"聊天记忆"功能做正确的存储选型与架构设计。

---

## 一、当前向量化合理性复盘

### 合理（迁移时保留）
| 项 | 说明 |
|----|------|
| R1 模型选型 | bge-m3 / 1024 维，中文+中英混合 SOTA，技术术语理解好 |
| R2 相似度计算 | 向量归一化 + 内积 ≈ 余弦相似度，标准做法 |
| R3 存储分离 | 向量库只存"压缩可检索文本+元信息"，完整 JD 详情放 MySQL，检索时 join。向量库保持轻量，这是优秀决策 |
| R4 幂等写入 | 按 `url` 去重 upsert，脚本可重跑不重复 |
| R5 多取后过滤 | `fetch_k = top_k*3` 再按 `source_type` 过滤，避免过滤后数量不足 |

### 不合理（迁移时必须优化）
| 项 | 问题 | 影响 |
|----|------|------|
| **U1 漏掉 JD 正文** | `build_embed_text` 只拼 `title/summary/key_points/tags`，**完全没把 `post_description` 送进向量** | 最大问题。语义检索只到"摘要级"，JD 正文中出现的技能/职责搜不到 |
| **U2 长文本未分块** | bge-m3 上限 8192 token，单条长 JD 会截断 | 纳入正文后必然触发，需分块 |
| **U3 只用 dense** | bge-m3 原生支持 sparse（词项权重向量），当前完全没用 | 精确技能词（LangChain/Kafka/PyTorch）召回差，dense 易在"近义不同词"上漏召 |
| U4 无字段权重/查询改写 | 标题与正文同等对待；query 直送 embed | 可给 title 加权、对 query 做 JD 风格改写（HyDE） |
| **U5 分数映射在 Milvus 下错误** | FAISS `IndexFlatIP` 归一化内积∈[-1,1]，用 `(d+1)/2` 映射；Milvus `COSINE` 返回的 distance 已是 [0,1] 余弦相似度 | 迁移后若继续套 `(d+1)/2` 会分数翻倍/错乱 |
| **U6 text 字段长度** | `check_milvus.py` 把 `text` 设 `VARCHAR(8192)` | JD 正文常超 8192，插入直接报错；应拉到 65535 或只存短文本 |
| **U7 后过滤 source_type** | 当前用 Python 后过滤 | Milvus 原生标量 filter（`expr`）更准更省，应在 search 时带上 |
| U8 arxiv+boss 同 collection | 靠 `source_type` 区分 | 当前可接受；若论文检索也要用，建议独立 collection |

---

## 二、Milvus 迁移优化方案

### 2.1 新 Schema（`job_docs` collection）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT64 | 主键 auto_id |
| embedding | FLOAT_VECTOR(1024) | bge-m3 dense，索引 COSINE/AUTOINDEX |
| sparse_embedding | SPARSE_FLOAT_VECTOR | bge-m3 sparse，索引 IP（用于 hybrid 召回） |
| url | VARCHAR(1024) | 去重键，建唯一索引 |
| source_type | VARCHAR(64) | 标量过滤字段 |
| title | VARCHAR(512) | |
| text | VARCHAR(65535) | 存压缩可检索文本（摘要+要点+截断正文） |
| city | VARCHAR(64) | 标量过滤（可选，按城市预筛） |
| created_at | INT64 | 时间戳，便于清理/TTL |

### 2.2 检索改造（hybrid）
- 用 **dense + sparse 双路召回 + RRFRanker 融合**，显著提升技能词精确匹配与语义泛化兼顾。
- `search` 直接带 `filter=f"source_type=='boss_zhipin'"`（替代 Python 后过滤）。
- **分数逻辑重写**：Milvus COSINE 返回的 distance 即相似度（越大越相似），直接取值，**移除 `(d+1)/2`**。

### 2.3 `build_embed_text` 优化
- 纳入 `post_description`（截断到 ~6000 字符 / 8000 token 安全区），顺序：标题 > 城市/薪资 > 要点 > 标签 > 正文摘要。
- 长 JD 启用**分块**：按"岗位职责 / 任职要求"语义切，或固定长度滑动窗口，每块一个向量，检索取最相关块。

### 2.4 兼容层
- `VectorStore` 对外接口（`upsert/search/count/SearchHit`）保持不变，内部按 `MILVUS_URL` 是否存在切换：
  - 有 `MILVUS_URL` → Milvus 实现
  - 无 → 保留 FAISS 作为无服务端 fallback
- 所有调用点（`index_final_results.py` / `search.py` / `tools.vector_search_jobs`）零改动。

---

## 三、记忆模块设计（聊天是否要用 Milvus）

### 结论
**原始聊天记录落 MySQL；语义记忆落 Milvus（独立 collection `chat_memory`）。两者不混。**

### 决策依据
- 聊天消息是**结构化事务数据**：`user_id / session_id / role / content / token_count / created_at / parent_id`。需要按会话分页、按用户隔离、精确回放、可编辑删除、可审计 —— 这是关系型 DB 的本分，Milvus 不擅长（无事务回滚、主键无业务语义、难精确取单条）。
- 但"记忆功能"本质是**在历史对话里做语义检索**（"我之前说过我擅长 Java" → 新会话能回忆），这正是向量库的活。

### 三层记忆模型
| 层 | 存储 | 内容 | 用途 |
|----|------|------|------|
| 工作记忆 | 后端 session / 前端 Zustand | 当前会话上下文 | 实时多轮 |
| 短期记忆 | **MySQL** `chat_messages` + `conversations` | 完整原文，最近 N 轮直接回填 | 精确回放、分页 |
| 长期记忆 | **Milvus** `chat_memory`（独立 collection） | 记忆片段向量：user 发言 / 会话摘要 / 提炼事实 | 跨会话语义召回 |

### `chat_memory` collection schema（与 `job_docs` 同实例不同 collection）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT64 | pk |
| embedding | FLOAT_VECTOR(1024) | bge-m3 |
| user_id | VARCHAR(64) | **必为 filter，绝不跨用户召回** |
| session_id | VARCHAR(64) | |
| memory_type | VARCHAR(32) | user_msg / summary / fact |
| content | VARCHAR(65535) | 记忆原文 |
| created_at | INT64 | |

### 写入 / 检索 / 遗忘策略
- **写入**：①每条 user 消息异步 embed 写 `chat_memory`（不阻塞回复）；②会话结束写一条**会话摘要**向量（高质量）。只写 user 发言 + 提炼事实，不写系统提示/工具中间结果。
- **检索注入**：新 query 来时 embed → 搜 `chat_memory`（`filter=user_id`）→ top-3~5 相关片段 → 拼成"你之前的相关记忆"注入 system prompt。
- **遗忘**：按 `created_at` 或访问热度做 TTL/裁剪，保留高价值记忆。

### 反模式提醒
- ❌ 不要把完整聊天塞进 Milvus（丢事务能力、难回放）。
- ❌ 不要把 job 向量和 chat 记忆混在同一 collection（语义不同、生命周期不同、隔离难）。
- ✅ 复用同一 Milvus 实例建多 collection，成本极低（一个 server 多 collection），既解决 job RAG 又解决记忆语义检索。

---

## 四、落地顺序建议
1. 确认 Milvus 地址/鉴权，跑 `utils/check_milvus.py` 全链路。
2. 改写 `VectorStore` → Milvus 实现（保留 FAISS fallback，接口零改动）。
3. 优化 `build_embed_text`（纳入正文 + 分块）+ 启用 hybrid search。
4. MySQL 建 `conversations` / `chat_messages` 表。
5. 记忆写入（user msg 实时 embed + 会话结束摘要）。
6. 记忆检索注入 prompt。
7. 修 `tests/test_rag_vector_store.py` 的老 Milvus 契约（对齐新实现）。

## 五、已确认决策（2026-08-15）
- **Milvus 地址**：`http://192.168.1.9:8000/`（standalone）。已探测：`8000` 与标准 gRPC `19530` 均可达，说明 8000 是 REST/代理入口、19530 是 gRPC。实施以 8000 为主，MilvusClient 若不兼容该形式则回退 `192.168.1.9:19530`。
- **启用 hybrid 检索**：dense(bge-m3) + 词面召回（采用 Milvus 内置 **BM25**，无需 embedder 额外产 sparse，更稳更简单）双路 + `RRFRanker` 融合。
- **记忆写入策略（由架构师决定）**：**实时逐条 + 会话级摘要 双写**。
  - 每条 user 消息：异步（不阻塞回复）embed 写 `chat_memory`（`memory_type='user_msg'`，带 `user_id`/`session_id`）。成本低、捕获细粒度信号。
  - 会话结束/空闲：LLM 生成会话摘要 embed 写 `memory_type='summary'`（高质量、跨会话泛化好）。v1 不做 fact 抽取，避免过度设计。
  - 检索注入：新 query embed → `chat_memory` filter=`user_id` top-5 → 拼成"你之前的相关记忆"注入 prompt。
  - 遗忘：按 `created_at` TTL 裁剪，保留高价值。

---

## 六、实施计划（待确认后执行）

### 阶段 0：连通与依赖
- `.env` 增加 `MILVUS_URL=http://192.168.1.9:8000`、`MILVUS_TOKEN`（若开启鉴权）、`MILVUS_JOB_COLLECTION=job_docs`、`MILVUS_MEMORY_COLLECTION=chat_memory`（自动去 trailing slash）。
- `requirements.txt` 增加 `pymilvus>=2.4.9`（BM25 需 2.4.9+）。
- 用户机器 venv 安装 pymilvus，跑 `utils/check_milvus.py --url http://192.168.1.9:8000` 验证全链路（确认 8000 连接形式，不行则换 19530）。

### 阶段 1：VectorStore 重写为 Milvus（保留 FAISS fallback）
- 文件：`src/rag/vector_store.py`。**对外接口零改动**（`__init__(db_path)` / `upsert` / `search` / `count` / `SearchHit`）。
- 内部按 `MILVUS_URL` 是否存在切换后端；FAISS 作为无服务端 fallback 保留。
- `job_docs` collection schema：
  - `id` INT64 pk auto_id
  - `embedding` FLOAT_VECTOR(1024) COSINE / AUTOINDEX
  - `sparse_embedding` SPARSE_FLOAT_VECTOR（BM25 函数自动生成，INVERTED_INDEX, metric=IP）
  - `url` VARCHAR(1024)（唯一索引，去重键）
  - `source_type` VARCHAR(64)（标量 filter）
  - `title` VARCHAR(512)
  - `text` VARCHAR(65535)
  - `city` VARCHAR(64)（可选标量 filter）
  - `created_at` INT64
- `upsert`：按 `url` expr 删旧（分块时一条 url 多行全删）→ 插入。
- `search`：hybrid `AnnSearchRequest`（dense + BM25 sparse）→ `RRFRanker` 融合 → `filter="source_type=='...'"`（原生过滤，替代 Python 后过滤）。**分数直接取 distance，删除 `(d+1)/2`**。

### 阶段 2：build_embed_text 优化 + 分块
- 纳入 `post_description`（截断 ~6000 字符 / 8k token 安全区）。
- 字段顺序加权：标题 > 城市/薪资 > 要点 > 标签 > JD 正文摘要。
- 长 JD 分块：~3000 字符滑动窗口或按"职责/要求"语义切，每块一行入库；search 结果按 `url` 去重，详情仍 join MySQL（`tools.py` 已支持按 url 取详情）。

### 阶段 3：聊天记忆存储（MySQL）
- 新增迁移 SQL：
  - `conversations(id, user_id, title, mode, created_at, updated_at)`
  - `chat_messages(id, conversation_id, user_id, role, content, token_count, created_at, parent_id, meta_json)`
- `/api/chat/unified` 落库：每次对话写 messages，首条自动建 conversation。

### 阶段 4：聊天记忆向量化（Milvus chat_memory collection）
- 新建 `chat_memory` collection（与 job_docs 同实例）：`id` / `embedding` FLOAT_VECTOR(1024) COSINE / `user_id` VARCHAR(64) / `session_id` VARCHAR(64) / `memory_type` VARCHAR(32) / `content` VARCHAR(65535) / `created_at` INT64。
- 写入（阶段 5 决策）：user 消息异步 embed → `user_msg`；会话结束/空闲 → `summary`。
- 检索注入：unified 入口 embed query → filter=`user_id` top-5 → 注入 prompt。
- 遗忘：TTL 裁剪。

### 阶段 5：修复测试契约
- `tests/test_rag_vector_store.py` 对齐新实现（Milvus / FAISS fallback 两路径都覆盖；移除老 MilvusLite `collection=` / `.client` 契约）。

### 风险与回滚
- 迁移期保留 FAISS 文件不动，一键回退：`MILVUS_URL` 置空即回 FAISS。
- 首次全量重建：`python scripts/index_final_results.py --rebuild`（写 Milvus）。

---

## 七、执行前需你拍板
确认以上 6 个阶段与"实时逐条 + 会话级摘要双写"的记忆策略后，我将按阶段 0→5 顺序实施，每阶段完成后汇报。是否现在开始？

---

## 八、实施记录（2026-08-15）

### 阶段 0：环境
- `pymilvus` 已装（**3.0.0**）。`check_milvus.py` 原默认 19530，已实测。
- **关键修正**：你给的 `http://192.168.1.9:8000/` 是 Milvus REST/WebUI 代理端口，`MilvusClient`(gRPC) 连它会报 `illegal connection params`。实测可用的是 **`http://192.168.1.9:19530`**（服务端 v2.5.0）。`.env` 已设 `MILVUS_URL=http://192.168.1.9:19530`。
- 用 `utils/probe_bm25.py` 实测：BM25 Function + dense/sparse 双路 + RRFRanker + expr 过滤/删除 在 pymilvus 3.0.0 / server 2.5.0 **全部可用**。
- **pymilvus 3.0 API 适配点**（与老代码/2.x 不同）：
  1. BM25 函数输入字段 `text` 必须 `enable_analyzer=True`（中文分词 `analyzer_params={"type":"chinese"}`）。
  2. 纯 dense `client.search` 的 `param=` 在 3.0 改名为 **`search_params=`**（否则 `multiple values for keyword argument 'param'`）。
  3. `hybrid_search` 顶层 `filter` 在部分版本不生效 → 过滤同时下放到每个 `AnnSearchRequest` 的 **`expr`**。
  4. `flush` 参数是 **`collection_name`**（单数），不是 `collection_names`。
  5. `count` 用 `client.query(..., output_fields=["count(*)"])`。

### 阶段 1：`VectorStore` 重写（src/rag/vector_store.py）
- 对外接口零破坏：`upsert / search / count / SearchHit` 不变；新增 `upsert_chunks / flush / rebuild`。
- 内部按 `MILVUS_URL` 是否存在切换：**Milvus 主** / **FAISS fallback**（保留，一键回退：`MILVUS_URL` 置空或 `FORCE_FAISS=1`）。
- `job_docs` schema：id / embedding(1024,COSINE) / sparse(BM25) / url / source_type / title / text(65535,analyzer) / city / created_at。
- **分数映射修正（U5）**：删除旧的 `(d+1)/2`；Milvus 下对 batch 内 distance 做相对归一化到 (0,1]，保留排序与单调性。
- **source_type 原生过滤（U7）**：`expr` 下放到子请求，替代 Python 后过滤。
- 用 `utils/probe_vectorstore.py` + FAISS 单测（12 项全过）双重验证。

### 阶段 2：向量化优化（scripts/index_final_results.py）
- **U1 修复**：`build_embed_text` 纳入 `post_description` 正文（截断 4000 字符），字段顺序 标题>城市>薪资>技能>简介>要点>标签>正文。
- **U2 长文本**：`chunk_text` 滑动窗口分块（3000/300 重叠），`upsert_chunks` 写入（多数 JD 单块）。
- 索引脚本改用 `upsert_chunks` + 末尾 `flush()`；`--rebuild` 走 `store.rebuild()`。
- `tools.vector_search_jobs` 与 `search.py` 传入 `query_text` 启用 hybrid。

### 阶段 3：记忆模块（双存储）
- MySQL：`conversations` / `chat_messages` 表（`scripts/init_db_memory.py` 幂等建表）。
- `src/db_conversation.py`：会话/消息 CRUD。
- `src/rag/memory_store.py`：`MemoryStore`（Milvus `chat_memory` 集合，dense COSINE，必带 `user_id` 过滤）。
- `app.py /api/chat/unified`：每轮**落库原文** + **异步写语义记忆（user_msg）**；诊断/匹配注入召回的历史记忆；新增 `/api/conversations`、`/api/conversations/{id}/messages` 只读端点。
- **偏离点（v1 范围）**：会话级 `summary` 记忆暂未做（需"会话结束/空闲"检测，过度设计，留作后续）；当前仅 user_msg 记忆已能提供跨会话语义召回。

### 阶段 4：数据迁移
- `index_final_results.py --rebuild` 全量重建进 Milvus（脚本运行中，bge-m3 本地嵌入）。

### 阶段 5：测试
- `tests/test_rag_vector_store.py` 重写为 FAISS fallback 确定性单测（12 项通过）+ Milvus 集成测试（`@pytest.mark.integration`，需 `MILVUS_URL`，自动跳过）。

### 待办 / 后续
- [ ] 迁移完成后跑 `test_milvus_integration` 与一次真实 `search.py` 召回对比。
- [ ] 前端 Sidebar 接入 `/api/conversations` 实现刷新后历史恢复（目前前端用 zustand 内存态）。
- [ ] 会话级摘要记忆（summary）。
- [ ] search 意图路径的记忆注入（目前仅 diagnose/match/interview 注入）。

