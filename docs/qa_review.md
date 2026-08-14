# Q&A Review · 错题本 · 面试自测库

> **用法**：每次学完做自测题，把题目 + 我答的 + 标准答案 + 易错点都记这里。
> **面试前 1-2 周**：按主题筛选标签，5 分钟扫一遍错过的题。
> **判分**：✅ 答对  🟡 方向对/不完整  ❌ 答错

## 标签索引

- `#langchain` `#langgraph` `#rag` `#mcp` `#llm-基础` `#agent` `#prompt` `#面试常见`

---

## 2026-06-29 周一 · LangChain day01 入门

### Q1: LangChain 是什么？ `#langchain` `#面试常见`

**我答（✅）**：
> "LangChain 是一个用于开发由大语言模型驱动的开发框架，类似于 Java 有 Spring，Python 有 Django。"

**标准答案 / 完整版**：
> LangChain 是 2022 年由 Harrison Chase 发起的开源框架，用于开发由 LLM 驱动的应用程序。
> 它把 LLM 调用、Prompt、Memory、RAG、Tool 调用这些零散环节**串成链**——"Chain" 的命名就是这意思。
> 类比：**LangChain 之于 LLM，就像 Spring 之于 Java，Django 之于 Python**。

**加分点**：
- 比 ChatGPT 早 1 个月发布（2022 年 10 月，ChatGPT 是 11 月）——创始人有眼光，先机优势
- 同生态还有 LangGraph（编排）/ LangSmith（观测）/ Deep Agents

---

### Q2: 为什么有 LLM 还要 LangChain？ `#langchain` `#面试常见`

**我答（🟡）**：
> "因为 LangChain 可以更快地自定义开发。"

**为什么扣分**：方向对，但太笼统，面试官追问"具体哪里更快"就卡住。

**标准答案（3 条，记忆口诀：省事 + 通用 + 现成）**：
1. **简化开发难度**：专注业务逻辑，不用手写底层（重试、解析、错误处理）
2. **学习成本低 / 模型可移植**：换模型不用换代码——OpenAI / Claude / DeepSeek / GLM 调用方式统一
3. **现成的链式组装**：RAG / Agent / Memory 都有现成轮子，不用从 0 写

**加分点**：能讲出自己项目里的真实感受。
> "我在 ai_collector_project 里用 LangChain 切换 GLM-4 和本地 ollama 时，只改了配置，没改业务代码——这就是第 2 条的实际收益。"

---

### Q3: LangChain 架构里哪个包是入口？ `#langchain` `#包结构`

**我答（❌）**：
> "langchain-core"

**为什么错**：被名字 "core" 误导了。

**标准答案**：**`langchain`**（就这一个词，没后缀）

**完整对比**：

| 包 | 角色 | 类比 |
|---|---|---|
| **langchain** | **主入口，包含构建 LLM 应用所需的所有实现** | Django 主包（开箱即用） |
| langchain-core | 只定义**接口和抽象**，没有具体实现，给开发者写自定义组件用 | Python `abc` 模块 |
| langchain-text-splitters | 文档处理（分块） | — |
| langchain-mcp-adapters | MCP 工具适配 | — |
| langchain-tests | 集成包测试套件 | — |
| langchain-classic | 遗留实现 | — |

**为什么这是常见坑**：很多框架里 "core" 就是主入口（`spring-core` / `aspnetcore`），但 LangChain v0.1 大重构后**故意把 core 留给抽象层**，这是设计选择。

---

### Q4 (Step 1 心里画): LangChain 4 大核心模块？ `#langchain` `#面试常见`

**我答（✅）**：
> "Model I/O、Chains、RAG、Agents。"

**标准答案**：**Model I/O / Chains / Retrieval / Agents**

**翻译成人话**：
- **Model I/O** = 怎么调用大模型（输入→模型→输出）
- **Chains** = 把多个步骤"串起来"（LangChain 名字"Chain"的由来）
- **Retrieval** = RAG 用的检索能力（向量化、向量库、查找）
- **Agents** = 让 LLM 自己决定下一步干啥（Function Calling / Tool 调用）

**项目对应**（你 ai_collector_project v3.0 里）：
- Model I/O ✓ 调 chat 模型
- Retrieval ✓ bge-m3 + Milvus 做 RAG
- Agents ✓ LangGraph 反思决策
- Chains ✗ LangGraph 出来后大多场景被 graph 替代，少显式用

---

### Q5: ai_collector_project 跟 LangChain / LangGraph 有什么关系？ `#langchain` `#langgraph` `#项目复盘` `#面试常见`

**我答（🟡）**：
> "由于这个项目是通过 vibe coding 创造的，所以这个项目跟 LangChain 有什么关系我具体也不知道。"

**为什么扣分**：诚实是对的，但面试里不能停在“不知道”。至少要能把项目里的 3 个文件和 LangChain/LangGraph 的角色对上。

**标准答案 / 完整版**：
> ai_collector_project 不是传统 LangChain Chain 项目，而是 **LangGraph + LangChain 生态组件** 的项目。
> 其中 LangGraph 负责把求职 Agent 编排成状态机；LangChain 生态负责模型调用和消息格式；RAG 检索部分则是 bge-m3 + Milvus + Ollama 的本地语义检索。

**项目对应（按文件说）**：
- `src/agent/graph.py`：用 `StateGraph` 定义流程：`parse_intent → retrieve → filter → reflect → summarize`，并在 `reflect` 后用条件边决定 retry 还是 summarize。
- `src/agent/nodes.py`：用 `SystemMessage` / `HumanMessage` 组织 prompt，用 `ChatOpenAI` 调 OpenAI-compatible 模型。
- `src/agent/nodes.py:retrieve`：把关键词拼成 `embed_query`，调用 `vector_search_jobs` 做语义检索。
- `src/mcp_server/ai_collector_mcp.py`：把检索能力暴露成 MCP tools：`search_jobs` / `query_rag` / `get_skill_gap`。

**30 秒面试说法**：
> “我的项目主流程用的是 LangGraph，不是简单 LangChain Chain。LangGraph 把求职 Agent 拆成 parse_intent、retrieve、filter、reflect、summarize 五个节点，reflect 节点会根据过滤结果决定是否换关键词重搜。LangChain 生态主要用在模型调用和消息格式上，比如 `SystemMessage`、`HumanMessage`、`ChatOpenAI`。RAG 部分用 bge-m3 + Milvus 做本地语义检索，最后通过 MCP 暴露成工具。”

---

### Q6: 大模型调用这节里记住了哪些调用方式？ `#langchain` `#model-io`

**我答（✅）**：
> "流式/非流式、同步/异步、批量调用。"

**标准答案 / 完整版**：
> LangChain 的模型调用不只是 `invoke` 一种：常见维度包括同步/异步、流式/非流式、单条/批量。它们解决的是不同工程场景：普通问答用同步非流式；需要边生成边展示用流式；并发任务用异步；多条输入统一处理用批量。

**加分点**：
- 面试别只背名词，要能说场景。
- 求职 Agent 这种 CLI 报告生成，最终报告可以非流式；如果做 Web UI，流式更适合展示“正在分析”。

---

### Q7: 为什么不用裸 API，非要用 LangChain？ `#langchain` `#面试常见`

**我答（✅）**：
> "LangChain 框架提供了一套开发标准，每次开发只需要改动很少的代码就可以实现不同的功能。如果单独使用 API，每次要用一个外部工具都要重新写一遍，重新造轮子，会出现非常多冗余代码，增加工作量，导致开发没有统一标准，后期管理非常复杂。"

**标准答案 / 完整版**：
> 裸 API 适合简单的一问一答；LangChain 适合工程化 LLM 应用。它的价值主要是：统一模型调用接口、统一 Prompt/Message/OutputParser 组织方式、提供 RAG/Tool/Agent 等现成组件，并把多步骤流程标准化，减少重复造轮子。

**更利落的 30 秒面试版**：
> “如果只是问一次答一次，裸 API 就够了。但真实业务里通常还有 Prompt 模板、输出解析、检索、工具调用、重试和观测。LangChain 的价值是把这些东西标准化：换模型、换工具、加一个 RAG 步骤，不需要把整套业务代码重写。它不是为了替代 API，而是把 LLM API 变成可维护的应用工程。”

**扣字修正**：
- “溶于代码”应改成“冗余代码”。
- 回答里可以少说“非常多”，多说具体模块：Prompt / OutputParser / Retriever / Tool。

---

