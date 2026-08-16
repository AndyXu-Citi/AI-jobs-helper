# AI 助手记忆模块设计

> 目标：让求职助手 Agent 具备"跨会话记住用户"的能力——既能回看完整对话历史，
> 又能跨会话语义召回相关背景、自动沉淀用户画像、压缩超长对话，并对面试官会话做持久化。
>
> 设计参考：MemGPT / Zep / Generative Agents 的分层记忆思想，落地为适合本项目的四层 + 面试官持久化。

---

## 一、整体架构

| 层 | 名称 | 存储介质 | 作用 | 状态 |
|----|------|----------|------|------|
| **L1** | 会话原文 | MySQL `conversations` + `chat_messages` | 单会话完整上下文，按 `session_id` 持久化 | ✅ 已有，本轮补全面试官 |
| **L2** | 语义记忆 | Milvus `chat_memory` collection | 跨会话语义召回（用户发言 + 助手回复），带 MMR/时间衰减/相关性阈值 | ✅ 本轮增强（C） |
| **L3** | 用户画像 | 独立 md（`long_term_memory.md`） | 对话中 LLM 自动提炼的技能/学习状态/偏好禁忌，增量沉淀 | ✅ 本轮新增（B） |
| **L4** | 会话摘要 | Milvus `chat_memory`（`memory_type='summary'`） | 超长对话压缩为要点摘要，防 context 爆炸 | ✅ 本轮新增（D） |
| 面试官 | 面试上下文 | MySQL（同 L1）+ Milvus（同 L2） | 面试会话落库、重启可恢复、跨面试共享技术水位 | ✅ 本轮新增 |

关系：**L1 是原始真相源；L2/L4 是 L1 的向量化派生；L3 是跨会话的用户级画像，由 L1 提炼且独立于核心画像 `my_profile.yaml`。**

```
┌─────────────────────────────────────────────────────────────┐
│                    一次对话（任意模式）                       │
└───────────────┬───────────────────────────┬─────────────────┘
                │ 落库 + 向量化             │ 提炼
                ▼                           ▼
        ┌───────────────┐          ┌────────────────────┐
        │  L1 MySQL 原文 │          │  L3 long_term_     │
        │  conversations │          │  memory.md (画像)  │
        │  chat_messages │          └────────────────────┘
        └───────┬───────┘
                │ 异步 embed
                ▼
        ┌───────────────────────────────┐
        │  L2 Milvus chat_memory         │
        │   ├─ user_msg (用户发言)       │
        │   ├─ assistant_reply (回复)    │  ── 召回 ──┐
        │   └─ summary (L4 压缩摘要)     │            │
        └───────────────────────────────┘            │
                ▲                                     ▼
                │                          ┌────────────────────┐
                └──── 下次对话注入 prompt  │ system prompt 拼接 │
                                          │ recalled + 画像     │
                                          └────────────────────┘
```

---

## 二、L1 会话原文（MySQL）

**存储**：`db_conversation.py`
- `conversations`（会话元信息：`conversation_id` / `user_id` / `mode` / `title` / `created_at`）
- `chat_messages`（逐条：`conversation_id` / `role` / `content` / `created_at`）

**关键函数**：
- `save_message(conv_id, role, content, user_id)` — 落一条消息
- `get_history(conv_id, limit)` — 读会话历史（D 压缩、C 多轮 query、面试恢复都用）
- `get_conversation(conv_id)` — 读会话元信息（含 `mode`，用于还原面试官 submode）
- `count_messages(conv_id)`、`list_interviews()` — 面试列表/计数

**面试模式的 `mode` 约定**：存为 `interview:<submode>`（如 `interview:resume`），便于 `_interview_submode_from_conv` 还原面试官子类型。

---

## 三、L2 语义记忆（Milvus `chat_memory`）

### 3.1 Schema（`memory_store.py`）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT64 | 主键 auto_id |
| embedding | FLOAT_VECTOR(1024) | bge-m3 dense，索引 AUTOINDEX / COSINE |
| user_id | VARCHAR(64) | **强制过滤，绝不跨用户召回** |
| session_id | VARCHAR(64) | 来源会话 |
| memory_type | VARCHAR(32) | `user_msg` / `assistant_reply` / `summary` |
| content | VARCHAR(65535) | 记忆文本 |
| created_at | INT64 | 写入时间戳，用于时间衰减 |

> 同一 Milvus 实例，独立 collection `chat_memory`，与岗位库 `job_docs` 完全隔离。

### 3.2 写入（`add_memory` + `_safe_add_memory`）

- 进程内懒加载 `bge-m3` 单例（`_get_embedder`），避免每次重载权重。
- **本轮补全（A）**：每轮对话**同时**写 `user_msg`（用户发言）与 `assistant_reply`（助手回复），使跨会话召回能看到"用户说了什么 + 当时怎么答"，而非半截上下文。
- 异步线程写入（`daemon=True`），**不阻塞回复**。

### 3.3 召回升级（C，`_recall_context`）

旧实现：固定 `top_k=3`、单句 query、无过滤。新版四招齐上：

| 能力 | 实现 | 参数 |
|------|------|------|
| **多轮 query** | 传 `conversation_id` 时用 `get_history` 取最近 **3 条 user 消息**拼接作为检索文本 | 消除单句语义漂移 |
| **MMR 去冗余** | 召回 10 条候选 → 本地 re-embed → `_mmr_select`（λ=0.7）挑 top_k 个多样性片段 | `_mmr_select(store, vec, cands, top_k=5, λ=0.7)` |
| **时间衰减** | `eff = score / (1 + 已过去天数/30)` | 约 30 天衰减一半，越久权重越低 |
| **相关性阈值** | 余弦相似度 `< 0.4` 直接丢弃 | `REL_THRESHOLD = 0.4` |

`recall()` 返回结构化结果（`content / score / created_at / memory_type`），供筛选与排序使用。`summary` 类型在结果中**优先前置**（前 2 条），作为长期背景。

---

## 四、L3 长期画像（独立 md）

### 4.1 设计决策

> **不修改 `my_profile.yaml`**——用户手写的权威核心画像保持纯净；
> 聊天自动沉淀的增量画像落到独立的 `src/agent/long_term_memory.md`。

分工：
- `my_profile.yaml`：用户手写的权威核心画像（"我的技能覆盖"统计仍用它）
- `long_term_memory.md`：LLM 从对话中提炼的增量画像，两者在对话时**合并注入** system prompt，互不污染

优势：md 天然可读、可 Git 跟踪、可手动审阅，省去 `ruamel.yaml` 保注释的复杂度。

### 4.2 md 结构（`long_term_memory.py`）

```markdown
# 用户长期记忆（自动沉淀，由对话学习，请勿手改）

## 已掌握技能 (have)
- Python
## 学习中 (learning)
- LangGraph
## 偏好 / 禁忌 (avoid)
- 不想做外包
```

### 4.3 提炼与写入

- `extract_profile_delta(user_msg, assistant_reply)`：每轮对话后用轻量 LLM 调用，从"用户发言 + 助手回复"抽 `{add_to_have, add_to_learning, add_to_avoid}`，只取**用户明确说出的信号，不猜测不编造**。
- `update_longterm_md(delta)`：**仅追加去重**（大小写不敏感），**绝不删除已有项**。
- `upsert_longterm_async(...)`：异步执行，由 `_persist_and_remember` 在每轮对话后触发，**不阻塞回复**。

### 4.4 读取与注入

- `load_longterm_md()` 返回全文；在 unified 入口读取，并在**面试官 / 简历诊断 / 简历匹配**三个分支注入 system prompt（岗位搜索不注入，价值低）。
- 与 `load_profile()` 的 yaml 内容拼接，共同构成"已知用户"上下文。

---

## 五、L4 会话摘要压缩（D）

**问题**：单会话消息过多时，把整段历史塞进 prompt 会撑爆 context 窗口。

**方案**（`_maybe_summarize_session` + `_summarize_session`）：
- 每轮对话后异步检测：单会话消息 `≥ 20` 条 **且** 距上次压缩 `≥ 10` 条时触发。
- 用 `_llm()` 把早期对话（`hist[last : total-10]`）压成要点摘要，写入 Milvus `memory_type='summary'`。
- `_SUMMARY_PROGRESS` 记录已压缩条数，避免重复/频繁压缩（进程内字典，重启清零无碍，Milvus 中的 summary 仍在）。
- 召回时 summary 优先前置（见 3.3），作为长期背景注入。

---

## 六、面试官会话持久化

**问题**：原 `_interview_sessions` 是进程内存 dict，重启即丢；独立 `/api/interview` 端点不落库、不写 L2。

**方案**：
- `_recover_interview_session(session_id, submode_hint)`：优先命中内存热缓存；未命中则 `get_history` + `get_conversation` 从 MySQL 重建 history 与 system prompt，**重启不丢**。
- `_persist_interview_turn(conv_id, user_msg, assist_reply, user_id)`：落 MySQL + 异步写 L2（user/assistant 都存，跨面试共享技术水位）。
- 独立 `/api/interview` 端点接入 L2 recall 与异步写入；unified 面试官分支续轮改用恢复逻辑，首条 `mode` 编码为 `interview:<submode>`。
- `/api/interview/sessions` 改读 MySQL（`list_interviews()`），重启后仍可见。

`conversations.mode` 约定：`interview:resume` / `interview:project` / `interview:knowledge` / `interview:jd`，由 `_interview_submode_from_conv` 还原子类型。

---

## 七、一次完整对话的生命周期

以 unified 入口的一轮对话为例（`_persist_and_remember` 串联）：

1. **召回（读）**：`_recall_context(user_id, message, conversation_id)` → 从 L2 取相关历史 + L4 摘要；读取 L3 `long_term_memory.md`；合并注入 system prompt。
2. **应答**：`_llm()` 基于完整上下文生成回复。
3. **持久化（写）**，异步并行：
   - L1：MySQL 落 `user` + `assistant` 消息
   - L2：异步 embed 写 `user_msg` + `assistant_reply`
   - L3：异步提炼用户画像写 `long_term_memory.md`
   - L4：异步检测并按需压缩早期对话为 `summary`

> 所有写操作异步（`daemon` 线程），**主回复链路零阻塞**。

---

## 八、配置与开关

| 环境变量 / 条件 | 作用 |
|------------------|------|
| `MILVUS_URL` | 未配置 → 整个 L2/L4 记忆功能**自动禁用**（仅告警），L1 MySQL 原文持久化仍生效 |
| `MILVUS_MEMORY_COLLECTION` | L2 collection 名，默认 `chat_memory` |
| `PRELOAD_EMBEDDER=false` | 开发时跳过启动预加载 bge-m3，首次调用时懒加载（秒启） |

**启用确认**：启动后端日志出现 `[MemoryStore] 启用 Milvus 记忆库（collection=chat_memory）` 即表示记忆全功能生效。

---

## 九、降级与边界

- **无 Milvus**：L2/L4 不工作，L1/L3 仍正常（L3 是纯本地 md，不依赖 Milvus）。
- **L3 提炼失败**：`extract_profile_delta` 异常时静默跳过，不中断对话。
- **L4 摘要失败**：`_summarize_session` 返回空串则本次不压缩，下轮重试。
- **跨用户隔离**：所有 L2 召回强制 `user_id` 过滤，防串号。
- **进程重启**：L1/L3 在磁盘，L2 在 Milvus，均持久；仅 `_SUMMARY_PROGRESS`（压缩进度游标）与 `_interview_sessions`（热缓存）为进程内，重启清零，但可从 MySQL 恢复，无数据丢失。

---

## 十、文件清单

| 文件 | 职责 |
|------|------|
| `backend/src/rag/memory_store.py` | L2 `MemoryStore`：Milvus `chat_memory` 读写、结构化 `recall` |
| `backend/src/agent/long_term_memory.py` | L3 模块：md 读/写/LLM 提炼画像 |
| `backend/src/db_conversation.py` | L1 + 面试官持久化：`save_message` / `get_history` / `get_conversation` / `list_interviews` |
| `backend/src/web/app.py` | 编排层：`_recall_context` / `_mmr_select` / `_cosine` / `_maybe_summarize_session` / `_persist_and_remember` / `_safe_upsert_longterm` / `_recover_interview_session` / `_persist_interview_turn` |
| `backend/src/agent/long_term_memory.md` | L3 运行时自动生成/更新的用户画像（**非手改**） |

---

## 十一、验证要点

- `py_compile` 后端相关文件通过。
- 数据库层冒烟（`db_conversation`）：`create_conversation` + `save_message` + `get_history` + `get_conversation` + `list_interviews` 全部正确，面试会话重启后可由 MySQL 恢复。
- 端到端：启动后端跑一轮对话 → 检查 Milvus `chat_memory` 写入 user/assistant，跑多轮后 `long_term_memory.md` 出现增量画像，长会话触发 `summary`。
- ⚠️ 跑数据库脚本务必先 `cd backend`（否则 `load_dotenv()` 按 cwd 找 `.env` 失败，回退到 `root@localhost` 无密码导致 1045）。
