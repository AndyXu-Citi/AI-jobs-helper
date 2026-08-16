# Study Log · AI 转型 11+1 周

每天 3 行：学了啥 / 新点 / 没懂点。

格式：`YYYY-MM-DD 周X · 主题 · <3 行>`

---

## 2026-06-28 周日 · 启动日 · LLM 演化

- 学了啥：跳过阶段13/day_01 13 集纯理论视频，用 `docs/llm_cheatsheet.md` 5 分钟扫完替代
- 新点：GPT-3 的 in-context learning 就是我写 prompt 塞示例那套——之前不知道有正式名字
- 没懂点：今天没写代码，无技术卡点；唯一的"没懂"是工程通用约定（什么是脚手架），已记到 user profile

明天 (6/29) 进 LangChain day01 前 5 集 + docx 精读 3 节。

---

## 2026-06-29 周一 · LangChain day01 入门 · 总 1h

- 学了啥：LangChain 4 大核心模块（Model I/O / Chains / Retrieval / Agents），
  类比 Spring 之于 Java——把 LLM 应用开发的零散环节串成链。
- 新点：AI-jobs-helper 不是传统 LangChain Chain 项目，而是 LangGraph 主编排 + LangChain 生态模型调用 + 本地 RAG 检索 + MCP 工具暴露。
- 没懂点：项目是 vibe coding 搭起来的，所以还需要把 `src/agent/graph.py` 和 `src/agent/nodes.py` 里的 LangGraph/LangChain 代码逐行对上；明天看 6-11 集时重点补 Model I/O。

**自测 5 题成绩 4/5**：
- ✅ LangChain 是什么：能用 Spring/Django 类比说清楚
- ✅ 核心模块：Model I/O / Chains / Retrieval / Agents（注意 RAG 是 Retrieval 的典型场景）
- 🟡 项目关系：诚实承认不清楚；已补标准答案：`graph.py` 用 StateGraph 编排，`nodes.py` 用 SystemMessage/HumanMessage/ChatOpenAI，RAG 走 bge-m3 + Milvus，MCP 暴露 tools
- ✅ 调用方式：流式/非流式、同步/异步、批量调用
- ✅ 为什么不用裸 API：LangChain 统一 Prompt / Message / OutputParser / Retriever / Tool，减少重复造轮子

**今晚收尾**：已看完 `src/agent/graph.py` 和 `src/agent/nodes.py` 中提到的 LangGraph / LangChain 对应关系；也提前看完了 6/30 的阶段10/day01 第 06-11 集视频（Message 构造、多种调用方式、异步、本地模型、PromptTemplate、易错点）。明天不追新视频，转入 Model I/O docx 精读 + `experiments/w1_model_io.py` 手敲实验。

**明天任务（2026-06-30）**：
- 先口述 5 题：SystemMessage/HumanMessage、invoke/stream/batch/ainvoke、PromptTemplate、本地/云模型差异、常见错误。
- 精读 LangChain docx 的 `Model I/O` 章节，控制 30-40 分钟。
- 手敲 `experiments/w1_model_io.py`：Message、invoke、stream、batch、PromptTemplate 五段小实验。
- 写 3 行 study_log：重点记录“我今天第一次手敲了什么”。
- 不做：不提前看 Output Parser、不改 `src/agent/`、不让 AI 直接代写完整实验。

---

## 2026-06-30 周二 · LangChain day01 06-11集 + 协程补习 · 总 1h

- 学了啥：Message 构造方式（SystemMessage/HumanMessage/AIMessage）、invoke/stream/batch/ainvoke 四种调用、PromptTemplate、本地模型调用（Ollama）、协程基础
- 新点：协程的 `asyncio.gather` 并发跟 `batch` 底层多线程是两套机制；PromptTemplate 的 `partial_variables` 可以预填部分变量
- 没懂点：异步调用实测没比 batch 快多少（数据量太小，3条请求看不出差异）

**手敲实验**：`experiments/coroutine_demo.py` — 同步 vs 协程 抓5个岗位页面耗时对比（10s vs 2s）
**缺**：`w1_model_io.py` 顺延至 7/4 集中补

---

## 2026-07-01 周三 ~ 2026-07-03 周五 · day02 视频+docx 集中学习 · 总 3.5h

- 学了啥（7/1 day02_01-05集）：init_chat_model 补充、多模态提示词、JsonOutputParser、StrOutputParser、with_structured_output
- 学了啥（7/2 day02_06-08集）：Runnable 定义、LCEL `|` 管道符（__or__ 重载）、RunnableSequence、RunnableParallel
- 学了啥（7/3 休息+复习）：倍速复习 06-08 集，理解 `|` 不是位或而是 Runnable 重载
- 新点：LCEL 的 `|` 本质是 Python 魔术方法 `__or__` / `__ror__`；JsonOutputParser 用 pydantic BaseModel 定义 schema，get_format_instructions() 自动生成格式提示
- 没懂点：with_structured_output 返回 pydantic 对象 vs JsonOutputParser 返回 dict 的区别，手敲时验证

---

## 2026-07-04 周六 · day02_09-15集 + W1 手敲代码集中补 · 总 5h+

- 学了啥（day02_09-15集）：structured_output_parser、RunnableParallel 具体应用、RunnableLambda、RunnablePassthrough.assign()、with_fallbacks、RAG 概念起步、TextLoader、JSONLoader
- 新点：RunnablePassthrough.assign() 可以在不修改原始数据的情况下追加字段；with_fallbacks 实现容错链
- 没懂点：RAG 完整流程留到 W2 深入

**手敲实验完成**：
- ✅ `w1_model_io.py`：5种 Message + 4种调用方式（invoke/stream/batch/ainvoke）+ PromptTemplate + ChatPromptTemplate（85分，已优化）
- ✅ `w1_output_parser.py`：StrOutputParser + JsonOutputParser + with_structured_output + LCEL管道（92分，已优化）
- ⏳ `w1_lcel_pipeline.py`：明天学新知识前完成

**已解决疑问**：
1. KMP_DUPLICATE_LIB_OK：macOS 下多个库各自捆绑 OpenMP 运行时，设 TRUE 防冲突 abort
2. ChatOpenAI vs OpenAI：前者走 /chat/completions 接口（Message 输入输出），后者走老 /completions 接口（纯文本，已过时）
3. 异步没比同步快：batch 底层也是多线程并发，3条请求量太小看不出差异，50+ 条才有明显差距
4. load_dotenv() 查找逻辑：从 CWD 开始往上逐级找 .env，跟脚本文件位置无关
5. GLM-5.2 with_structured_output 踩坑：默认 method='json_schema' 报 400 错误，GLM 系列不支持 json_schema 格式；method='json_mode' 能返回 JSON 但结构跟 pydantic schema 对不上；**最终方案: method='function_calling'，走 function calling 路线，返回 pydantic 对象正常**。结论：不是所有模型都支持 json_schema，GLM 系列用 function_calling。

---

## 2026-07-05 周日 · w1_lcel_pipeline.py 手敲+优化 · 总 2h

- 学了啥：RunnableParallel 并行分发、RunnableLambda 两种写法（显式包装 + 装饰器）、RunnablePassthrough.assign() 追加字段、with_fallbacks 三层容错链、JsonOutputParser + 手动 JSON 提取 fallback
- 新点：
  1. ChatPromptTemplate vs PromptTemplate：前者输出多条对话消息列表（带 system/human/ai 角色），后者输出纯文本字符串；用 ChatOpenAI → ChatPromptTemplate，用老式 OpenAI Completion → PromptTemplate
  2. RunnableLambda 本质：把普通 Python 函数包成 Runnable，使其能用 | 接到链里；两种写法：RunnableLambda(func) 显式包装 / @RunnableLambda 装饰器
  3. RunnableParallel 会把同一个输入传给所有子链，不能给每个子链传不同输入
  4. RunnablePassthrough 在 RAG 里的核心用法：保留原始 question，同时 assign 一个检索到的 context（马上 day03 要用到）
  5. with_fallbacks 的正确设计：主链用 JsonOutputParser → fallback 换 StrOutputParser + 手动 JSON 提取（换条路走），而不是原路换 prompt 措辞重试
- 没懂点/踩坑：
  1. Python 字典 key 去重 bug：{"topic": "春天", "topic": "夏天"} 实际只保留"夏天"，两个模型拿到的都是同一个输入 → 修正为传一个 topic 对比两个模型输出
  2. RunnablePassthrough.assign() 对 str 输入的行为跨版本不一致，安全做法是先用 RunnableLambda 包成 dict 再 assign
  3. Pyright 类型检查报 Runnable | RunnableAssign 不支持 | 运算符，这是误报——LangChain 的 Runnable 重载了 __or__，运行时无影响
- 手敲实验：✅ `experiments/w1_lcel_pipeline.py`（88分，已优化）
  - TODO 2 基础链 ✅ 90分
  - TODO 3 RunnableParallel ✅ 90分（修复了字典 key 去重 bug）
  - TODO 4 RunnableLambda ✅ 90分
  - TODO 5 RunnablePassthrough ✅ 85分（补充了接 LLM 的真实示例）
  - TODO 6 完整流水线 ✅ 88分（fallback 从"换措辞重试"改为"换解析策略"）

**下一步**：继续看 day03 第 01-06 集（RAG 完整流程：文档加载→切分→embedding）

---
