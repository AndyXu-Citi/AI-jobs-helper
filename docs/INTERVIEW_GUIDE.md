# 🎯 AI Collector Project 面试指南

> 本文档帮助你全面理解项目技术栈，并预演面试官可能提出的问题。
> 建议配合代码一起阅读，理解每个技术选型背后的"为什么"。

---

## 📋 目录

1. [项目架构全景](#一项目架构全景)
2. [逐层技术详解](#二逐层技术详解)
3. [技术栈清单](#三技术栈清单)
4. [面试高频问题 Q&A](#四面试高频问题-qa)
5. [深度追问预演](#五深度追问预演)
   - 5.1 [架构设计类](#51-架构设计类)
   - 5.2 [技术细节类](#52-技术细节类)
   - 5.3 [项目经验类](#53-项目经验类)
   - 5.4 [刁钻追问](#54-刁钻追问面试官可能出的难题)
6. [项目亮点话术](#六项目亮点话术)

---

## 一、项目架构全景

### 1.1 五层分层设计

```
┌─────────────────────────────────────────────────────────────┐
│  ① 服务暴露层 (FastAPI Web API + MCP Server)                 │
│     - HTTP API: /api/chat, /api/jobs, /api/report, /api/match│
│     - MCP Server: search_jobs / query_rag / get_skill_gap   │
│     - SSE 流式输出                                            │
├─────────────────────────────────────────────────────────────┤
│  ② Agent 编排层 (LangGraph 5节点DAG)                         │
│     - parse_intent → retrieve → filter → reflect → summarize│
│     - 反思回路：0结果时自主换关键词重搜（最多3轮）              │
├─────────────────────────────────────────────────────────────┤
│  ③ RAG 检索层 (bge-m3 Embedding + FAISS 向量库)              │
│     - 1024维中英混合语义向量                                   │
│     - 余弦相似度检索 Top-K                                    │
├─────────────────────────────────────────────────────────────┤
│  ④ 数据存储层 (MySQL 状态机 + JSON 结构化存储)                │
│     - 5张表: urls_history / task_queue / raw_contents         │
│               / final_results / agent_runs                   │
│     - 状态机: PENDING → PROCESSING → COLLECTED → COMPLETED   │
├─────────────────────────────────────────────────────────────┤
│  ⑤ 数据采集层 (Playwright CDP 接管 Chrome + 多源插件)         │
│     - Boss直聘: CDP绕反爬 + 搜索API + 详情API                 │
│     - B站: API + Playwright fallback                         │
│     - arXiv: Atom XML API                                    │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 数据流

```
用户自然语言需求
      ↓
  parse_intent (LLM) → 结构化意图 JSON
      ↓
  retrieve (纯函数) → FAISS 语义检索 Top-30
      ↓
  filter (纯函数) → 薪资/城市/学历/经验/黑名单 硬过滤
      ↓
  reflect (LLM) → 够了→summarize / 不够→换关键词→retrieve
      ↓
  summarize (LLM) → Markdown 推荐报告 + 技能差距分析
      ↓
  返回 JobAgentResult (报告 + 岗位列表 + trace + 耗时)
```

---

## 二、逐层技术详解

### 2.1 数据采集层 — 反爬与浏览器自动化

#### 核心技术

| 技术 | 版本 | 用途 |
|------|------|------|
| **Playwright** | ≥1.40.0 | 浏览器自动化框架 |
| **CDP** | - | Chrome DevTools Protocol，远程调试协议 |
| **playwright-stealth** | ≥2.0.0 | 隐藏自动化指纹 |
| **requests** | ≥2.31.0 | HTTP 请求（arXiv 数据源） |
| **beautifulsoup4** | ≥4.12.0 | HTML 解析 |
| **markdownify** | ≥0.11.6 | HTML 转 Markdown |

#### Boss 直聘反爬方案详解

**问题**：Boss 直聘 PC 站用 Canvas 渲染列表，常规爬虫拿不到文字；移动端 H5 站有 JSON API，但有 code 37 风控（"您的环境存在异常"）。

**解决方案 — CDP 接管真实 Chrome**：

```python
# 1. 用户用独立 profile 启动 Chrome（一次性）
chrome --remote-debugging-port=9222 \
       --user-data-dir="$HOME/.hermes/chrome-debug-profile"

# 2. 用户在那个 Chrome 里扫码登录 Boss（cookie 持久保存）

# 3. Playwright 通过 CDP 接管这个浏览器
browser = await playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")

# 4. 在已登录的页面里 fetch API（同源，cookie 自动带）
response = await page.request.fetch(api_url)
```

**为什么这样做？**
- 请求来自真实浏览器、真实用户 cookie → 完全绕开 code 37
- cookie 失效时浏览器自然提示，用户重新扫码即可
- 不需要逆向 `__zp_stoken__` 签名

**反爬加固策略**：
1. **每个查询新开标签页**：绕开 WAF 对"同一会话连续打 API"的连接级封禁
2. **随机延迟 2-5s**：模拟真人操作节奏
3. **code 37 触发 20s 冷却**：不硬刚 WAF
4. **连续失败 5 次触发 60s 长冷却**：避免账号被封
5. **指数退避重试**：`backoff = 2^attempt + random(1,3)`

#### 多源插件架构

```python
class BaseSource(ABC):
    """信息源抽象基类"""
    source_type: str = "base"

    @abstractmethod
    async def fetch_new_urls(self) -> List[str]:
        """发现该源当前可见的内容 URL"""
        raise NotImplementedError

class BossSource(BaseSource):
    source_type = "boss_zhipin"
    # ...

class ArxivSource(BaseSource):
    source_type = "arxiv"
    # ...
```

**设计优势**：新增数据源只需写一个子类，对 Monitor / DBManager / Pipeline 零侵入。

---

### 2.2 数据存储层 — 关系型数据库 + 状态机

#### 核心技术

| 技术 | 版本 | 用途 |
|------|------|------|
| **MySQL** | - | 主数据库 |
| **mysql-connector-python** | ≥9.0.0 | Python MySQL 驱动 |

#### 数据库设计（5 张表）

**task_queue — 任务队列**
```sql
CREATE TABLE task_queue (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    url             VARCHAR(255) UNIQUE,
    status          VARCHAR(20) DEFAULT 'PENDING',
    source_type     VARCHAR(50) DEFAULT 'bilibili',
    retry_count     INT DEFAULT 0,
    error_message   TEXT,
    last_attempt_at DATETIME,
    created_at      DATETIME
);
```

**状态机流转**：
```
PENDING → PROCESSING → COLLECTED → COMPLETED
                ↓                       ↑
              FAILED ──── 重试 ─────────┘
```

**final_results — 结构化结果**
```sql
CREATE TABLE final_results (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    url             VARCHAR(255),
    source_type     VARCHAR(50),
    structured_json LONGTEXT,  -- LLM 清洗后的 JSON
    processed_at    DATETIME
);
```

**agent_runs — Bad Case 闭环**
```sql
CREATE TABLE agent_runs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    run_at          DATETIME,
    query           TEXT,
    result_count    INT,
    elapsed_seconds FLOAT,
    reflect_rounds  INT,
    status          VARCHAR(20) DEFAULT 'unreviewed',
    root_cause      TEXT,
    fix_commit      VARCHAR(40),
    fix_notes       TEXT,
    trace_json      LONGTEXT,
    final_report    LONGTEXT
);
```

#### 失败重试机制

```python
def requeue_failed(self, max_retry: int = 3) -> dict:
    # 有 raw_contents → COLLECTED（已采集，只差 LLM 处理）
    # 无 raw_contents → PENDING（需要重新采集）
    # retry_count >= max_retry → 保持 FAILED（不再重试）
```

---

### 2.3 RAG 检索层 — 向量语义搜索

#### 核心技术

| 技术 | 版本 | 用途 |
|------|------|------|
| **bge-m3 (BAAI)** | - | 1024 维中英混合 embedding SOTA 模型 |
| **sentence-transformers** | ≥2.3.0 | HuggingFace 模型加载框架 |
| **FAISS** | ≥1.7.4 | Facebook 向量检索库 |
| **numpy** | ≥1.24.0 | 数值计算 |

#### Embedding 封装

```python
class HuggingFaceEmbedder:
    """基于本地 HuggingFace bge-m3 的 Embedding 封装"""

    _model = None  # 进程内单例，避免重复加载

    def embed_one(self, text: str) -> list[float]:
        # sentence-transformers 加载 BAAI/bge-m3
        vec = self._get_model().encode(text)
        return vec.tolist()  # 1024 维向量

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        # 批量 embedding，一条挂掉不影响其他条
        # 失败时用零向量占位 + 日志报警
```

**为什么用 bge-m3？**
- 1024 维，中文 SOTA embedding 之一（BAAI 智源出品）
- 支持中英混合，对 AI/技术领域的术语理解好
- 本地运行，零网络依赖

#### FAISS 向量存储

```python
class VectorStore:
    def __init__(self, db_path: str):
        # IndexFlatIP: 内积索引
        # 归一化后 = 余弦相似度
        self._index = faiss.IndexFlatIP(EMBED_DIM)

    def upsert(self, *, url, source_type, title, text, embedding):
        vec = np.array([embedding], dtype=np.float32)
        faiss.normalize_L2(vec)  # L2 归一化
        self._index.add(vec)

    def search(self, query_embedding, top_k=5, source_type=None):
        q = np.array([query_embedding], dtype=np.float32)
        faiss.normalize_L2(q)
        distances, indices = self._index.search(q, fetch_k)
        # distances 是内积，转换为 0-1 相似度
        similarity = (dist + 1.0) / 2.0
```

**FAISS vs Milvus 选型**：
- Milvus Lite 在 Windows 上有 gRPC 兼容问题
- FAISS 纯本地库，pip install 即用
- 几百条数据量 FAISS 性能完全足够

**余弦相似度实现**：
```
归一化后的内积 = cos(θ) = (A·B) / (|A|·|B|)
FAISS IndexFlatIP + L2 归一化 = 余弦相似度
```

---

### 2.4 Agent 编排层 — LangGraph 状态图

#### 核心技术

| 技术 | 版本 | 用途 |
|------|------|------|
| **LangGraph** | ≥1.0.0 | Agent DAG 编排框架 |
| **LangChain** | ≥1.0.0 | LLM 应用框架 |
| **langchain-openai** | ≥1.0.0 | OpenAI 兼容客户端 |
| **PyYAML** | ≥6.0 | 配置文件加载 |

#### LangGraph DAG 定义

```python
def _build_graph():
    g = StateGraph(AgentState)

    # 添加 5 个节点
    g.add_node("parse_intent", parse_intent)
    g.add_node("retrieve", retrieve)
    g.add_node("filter", filter_node)
    g.add_node("reflect", reflect)
    g.add_node("summarize", summarize)

    # 定义边
    g.add_edge(START, "parse_intent")
    g.add_edge("parse_intent", "retrieve")
    g.add_edge("retrieve", "filter")
    g.add_edge("filter", "reflect")

    # 条件路由：reflect 后根据 decision 决定去哪
    g.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {
            "retrieve": "retrieve",   # retry → 回到 retrieve
            "summarize": "summarize", # done → 去 summarize
        },
    )
    g.add_edge("summarize", END)

    return g.compile()
```

#### State 定义（TypedDict）

```python
class AgentState(TypedDict, total=False):
    # 输入
    query: str            # 用户自然语言需求
    profile: dict         # 用户画像 (my_profile.yaml)

    # parse_intent 产出
    intent: dict          # 结构化意图

    # retrieve/filter 产出
    raw_hits: list[JobRecord]      # 向量召回的原始岗位
    filtered_jobs: list[JobRecord] # 过滤后的岗位
    filter_stats: dict             # 过滤统计

    # reflect 产出
    reflect_round: int             # 当前反思轮次
    decision: str                  # "done" | "retry"
    tried_keywords: list[list[str]] # 已尝试的关键词组

    # summarize 产出
    skill_gap: list[tuple[str, int]] # 技能差距
    final_report: str                # Markdown 报告

    # 追踪
    trace: list[str]  # 每个节点追加的运行日志
```

#### 5 个节点详解

**Node 1: parse_intent (LLM)**
```python
def parse_intent(state: AgentState) -> AgentState:
    """自然语言 → 结构化意图 JSON"""
    llm = _llm()
    msgs = [
        SystemMessage(content=PARSE_INTENT_SYSTEM),
        HumanMessage(content=PARSE_INTENT_USER_TEMPLATE.format(query=query)),
    ]
    resp = llm.invoke(msgs)
    intent = _extract_json(resp.content)
    # 输出: {keywords, cities_include, cities_exclude, salary_min, experience, degree, direction}
```

**Node 2: retrieve (纯函数)**
```python
def retrieve(state: AgentState) -> AgentState:
    """用意图构造 embedding 查询，FAISS 检索 Top-30"""
    keywords = intent.get("keywords") or [state["query"]]
    embed_query = " ".join(keywords)

    # 拼入软线索
    if intent.get("direction"):
        embed_query += f" {intent['direction']}"
    if intent.get("salary_min"):
        embed_query += f" 薪资 {intent['salary_min'] // 1000}K+"

    hits = vector_search_jobs(embed_query, top_k=30)
    state["raw_hits"] = hits
```

**Node 3: filter (纯函数)**
```python
def filter_node(state: AgentState) -> AgentState:
    """硬过滤: 薪资/城市/学历/经验/黑名单"""
    kept, stats = filter_jobs(
        state["raw_hits"],
        salary_min=salary_min,
        cities_include=cities_inc,
        cities_exclude=cities_exc,
        degree_allow=degree_allow,
        experience_allow=experience_allow,
        blacklist_keywords=blacklist,
    )
```

**Node 4: reflect (LLM + 反思回路)**
```python
def reflect(state: AgentState) -> AgentState:
    """决策: 信息够不够？要不要换关键词重搜？"""
    state["reflect_round"] = state.get("reflect_round", 0) + 1

    # 确定性短路：足够 ≥ 5 条或重试 ≥ 3 轮，直接 done
    if len(kept) >= 5 or state["reflect_round"] >= MAX_RETRY_ROUNDS:
        state["decision"] = "done"
        return state

    # 调 LLM 决策
    result = _extract_json(resp.content)
    if result.get("decision") == "retry":
        # 必须给出新关键词，否则强制 done（防死循环）
        new_kw = [k for k in next_kw if k not in already_tried]
        if not new_kw:
            state["decision"] = "done"
        else:
            state["intent"]["keywords"] = new_kw
            state["decision"] = "retry"
```

**Node 5: summarize (LLM)**
```python
def summarize(state: AgentState) -> AgentState:
    """生成 Markdown 推荐报告 + 技能差距分析"""
    # 先算技能差距（确定性，不调 LLM）
    gap = compute_skill_gap(jobs, profile)

    # 把 Top-10 岗位 + 画像 + 差距打包给 LLM
    llm = _llm()
    resp = llm.invoke([SystemMessage(...), HumanMessage(user)])
    state["final_report"] = resp.content
```

#### 设计决策

**为什么 retrieve/filter 不调 LLM？**
- 规则明确的逻辑交给确定性函数
- 省 token 也省 latency
- 同样输入永远同样输出，便于测试和复现

**反思循环怎么防死循环？**
- 双层保护：
  1. `MAX_RETRY_ROUNDS=3` 硬上限
  2. 必须给出"新"关键词才算 retry
- 如果 LLM 想重试但没给出新关键词 → 强制 done

---

### 2.5 服务暴露层 — Web API + MCP 协议

#### 核心技术

| 技术 | 版本 | 用途 |
|------|------|------|
| **FastAPI** | ≥0.110.0 | 高性能异步 Web 框架 |
| **uvicorn** | ≥0.30.0 | ASGI 服务器 |
| **Pydantic** | - | 数据校验 + 序列化 |
| **MCP** | 1.26.0 | Model Context Protocol |
| **FastMCP** | - | MCP Server 快速实现 |

#### FastAPI 端点设计

```python
app = FastAPI(title="AI 求职 Agent", version="3.0")

@app.post("/api/chat")           # 同步调用 Agent
@app.post("/api/chat/stream")    # SSE 流式输出 trace
@app.get("/api/jobs")            # 查询历史岗位
@app.get("/api/skill-gap")       # 技能热度 + 缺口
@app.get("/api/report")          # 统计报表
@app.get("/api/profile")         # 用户画像
@app.post("/api/match")          # 简历 vs JD 匹配
@app.post("/api/match/rank")     # 简历向量检索排序
```

#### SSE 流式输出

```python
@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    def generate():
        for event in find_jobs_stream(req.query):
            if event["type"] == "trace":
                for line in event["lines"]:
                    chunk = json.dumps({"type": "trace", "content": line})
                    yield f"data: {chunk}\n\n"
            elif event["type"] == "done":
                resp = _result_to_response(event["result"])
                chunk = json.dumps({"type": "done", "data": resp.model_dump()})
                yield f"data: {chunk}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

#### MCP Server（3 个 Tool）

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ai-collector")

@mcp.tool()
def search_jobs(keyword: str, city: str = "", top_k: int = 5) -> str:
    """字面包含匹配搜索岗位"""

@mcp.tool()
def query_rag(question: str, top_k: int = 5) -> str:
    """bge-m3 语义检索岗位"""

@mcp.tool()
def get_skill_gap(top_n: int = 10) -> str:
    """市场技能热度 + 个人画像缺口对照"""

if __name__ == "__main__":
    mcp.run(transport="stdio")  # stdio 传输
```

**MCP 工作原理**：
1. Claude Desktop / Cursor 启动 MCP Server 子进程
2. 通过 stdio（标准输入输出）发送 JSON-RPC 请求
3. Server 执行工具函数，返回结果
4. 客户端展示结果给用户

---

### 2.6 工程化实践

| 实践 | 实现方式 | 代码位置 |
|------|----------|----------|
| **单元测试** | 81 个 pytest，全离线 mock | `tests/` |
| **CI/CD** | GitHub Actions，每次 push 自动跑 | `.github/workflows/` |
| **插件式架构** | BaseSource 抽象基类 | `src/sources/base.py` |
| **Bad Case 闭环** | agent_runs 表 + replay 命令 | `src/agent/bad_case_store.py` |
| **日志追踪** | state["trace"] 贯穿全程 | `src/agent/nodes.py` |
| **配置管理** | .env + python-dotenv | `.env.example` |
| **失败重试** | 状态机 + requeue_failed | `src/db_manager.py` |
| **反爬节流** | 随机延迟 + 指数退避 + 冷却 | `src/sources/boss_zhipin.py` |

---

## 三、技术栈清单

### 3.1 简历/面试速查版

```
语言: Python 3.11

AI/LLM:
  - LangGraph (Agent 编排)
  - LangChain + langchain-openai (LLM 调用)
  - bge-m3 / sentence-transformers (Embedding)
  - FAISS (向量检索)
  - OpenAI API 兼容 (火山引擎方舟)

Web:
  - FastAPI + uvicorn (Web API)
  - SSE (流式输出)
  - Pydantic (数据校验)
  - MCP (AI 工具协议)

爬虫/自动化:
  - Playwright (浏览器自动化)
  - CDP (Chrome DevTools Protocol)
  - requests (HTTP 请求)
  - BeautifulSoup4 (HTML 解析)

数据库:
  - MySQL (关系型存储)
  - FAISS (向量存储)

工程化:
  - pytest (单元测试, 81个)
  - GitHub Actions (CI/CD)
  - dotenv (配置管理)
  - logging (日志体系)
```

### 3.2 依赖清单 (requirements.txt)

```txt
# Web 与 HTML 处理
requests>=2.31.0
beautifulsoup4>=4.12.0
markdownify>=0.11.6

# Web API
fastapi>=0.110.0
uvicorn[standard]>=0.30.0

# 浏览器自动化
playwright>=1.40.0
playwright-stealth>=2.0.0

# LLM 调用
openai>=1.30.0

# 工具
python-dotenv>=1.0.0
pandas>=2.0.0

# RAG: 向量检索
faiss-cpu>=1.7.4
numpy>=1.24.0

# RAG: Embedding
sentence-transformers>=2.3.0

# MCP Server
mcp==1.26.0

# MySQL
mysql-connector-python>=9.0.0

# Agent 编排
langgraph>=1.0.0
langchain>=1.0.0
langchain-openai>=1.0.0
langchain-community>=0.4.0
pyyaml>=6.0
```

---

## 四、面试高频问题 Q&A

### Q1: 为什么用 LangGraph 而不是直接写 if-else？

**标准回答**：
> "LangGraph 提供了可视化的 DAG 编排，支持条件路由和循环（反思回路），比手写 if-else 更易维护和调试。它内置了 state 管理，节点间数据流动清晰。而且 LangGraph 是 LangChain 团队出品，和 LangChain 生态无缝集成。"

**追问：LangGraph 和 LangChain Chain 有什么区别？**
> "Chain 是线性的 A→B→C，LangGraph 是图结构，支持条件分支（if/else）和循环（while）。我们的反思回路就是循环的典型场景：reflect 节点根据结果决定是回到 retrieve 还是去 summarize。"

---

### Q2: 反思循环怎么防死循环？

**标准回答**：
> "双层保护机制：
> 1. **硬上限**：MAX_RETRY_ROUNDS=3，达到后强制 done
> 2. **新关键词检查**：LLM 想重试时，必须给出'新'关键词才算 retry。如果给出的关键词都搜过了，强制 done
> 
> 这样既给了 Agent 自主探索的空间，又保证了确定性终止。"

**追问：为什么选 3 轮而不是 5 轮？**
> "实测发现 3 轮已经能覆盖大部分场景：第一轮用原始关键词，第二轮换近义词，第三轮扩大城市范围。超过 3 轮往往是查询本身有问题（比如'郑州 25K+ LangGraph'太稀有），继续搜也找不到。"

---

### Q3: FAISS 怎么实现余弦相似度？

**标准回答**：
> "用 IndexFlatIP（内积索引）+ 先对向量做 L2 归一化。数学上，归一化后的内积等于余弦相似度：
> 
> cos(θ) = (A·B) / (|A|·|B|)
> 
> 当 |A|=|B|=1 时，cos(θ) = A·B
> 
> 所以 FAISS 返回的 distance 就是余弦相似度，再做 (dist+1)/2 映射到 0-1 区间。"

**追问：为什么不直接用 IndexFlatL2（欧氏距离）？**
> "欧氏距离受向量模长影响，两个方向相同但模长不同的向量，欧氏距离可能很大。余弦相似度只看方向，更适合文本语义匹配——两段文字主题相同但长度不同，余弦相似度应该很高。"

---

### Q4: CDP 接管 Chrome 和 Selenium 有什么区别？

**标准回答**：
> "CDP 是 Chrome 原生调试协议，Playwright 通过 `connect_over_cdp` 连接用户已登录的真实 Chrome，复用登录态和浏览器指纹。Selenium 是自己启动浏览器，容易被检测为自动化。
> 
> 具体来说：
> - CDP 连接的是用户正在用的 Chrome，cookie、localStorage、浏览器指纹都是真实的
> - Selenium 启动的是一个新的浏览器实例，需要自己管理 cookie，指纹也容易被识别
> - Boss 直聘的 code 37 风控就是检测自动化特征，CDP 方案完全绕过"

**追问：为什么不直接用 requests 带 cookie 请求？**
> "Boss 直聘的 API 需要特定的请求头（Referer、X-Requested-With）和会话 token，这些 token 是 JavaScript 动态生成的。用 requests 模拟这些太脆弱，前端一改就挂。用真实浏览器发请求，这些都自动处理。"

---

### Q5: MCP 是什么？为什么用它？

**标准回答**：
> "MCP 是 Anthropic 推出的 Model Context Protocol（模型上下文协议），让 AI 客户端（Claude Desktop / Cursor / Hermes）能直接调用本地工具。
> 
> 我把项目的检索能力封装成 3 个 MCP Tool：
> 1. `search_jobs` — 字面关键词匹配
> 2. `query_rag` — bge-m3 语义检索
> 3. `get_skill_gap` — 技能缺口分析
> 
> 任何支持 MCP 的客户端都能调用，不需要额外写 API 对接。传输方式是 stdio（标准输入输出），客户端启动 Server 子进程，通过 stdin/stdout 发送 JSON-RPC 请求。"

**追问：MCP 和 REST API 有什么区别？**
> "REST API 是通用的 HTTP 接口，需要客户端自己实现 HTTP 调用逻辑。MCP 是专门为 AI 工具设计的协议，客户端只需要声明工具的 JSON Schema，就能自动调用。而且 MCP 支持本地 stdio 传输，不需要暴露端口，更安全。"

---

### Q6: 为什么用 FAISS 不用 Milvus / Pinecone / Weaviate？

**标准回答**：
> "选型考虑了三点：
> 1. **部署复杂度**：FAISS 是纯本地库，pip install 即用，零服务器依赖。Milvus 需要 Docker，Pinecone 是云服务
> 2. **数据量**：我们只有几百条岗位数据，FAISS 的暴力搜索（IndexFlatIP）性能完全够用
> 3. **平台兼容**：Milvus Lite 在 Windows 上有 gRPC 兼容问题，FAISS 跨平台无问题
> 
> 如果数据量到百万级，会考虑迁移到 Milvus Cluster 或 Qdrant。"

---

### Q7: 插件式架构怎么设计的？

**标准回答**：
> "用 ABC（抽象基类）定义统一接口：
> 
> ```python
> class BaseSource(ABC):
>     source_type: str = "base"
>     
>     @abstractmethod
>     async def fetch_new_urls(self) -> List[str]:
>         raise NotImplementedError
> ```
> 
> 每个数据源实现一个子类（BossSource、ArxivSource、BilibiliSource），设置自己的 source_type，实现 fetch_new_urls()。
> 
> Monitor 调度器只调 BaseSource 的接口，不关心具体实现。新增数据源 = 写一个子类，对 Monitor / DBManager / Pipeline 零侵入。
> 
> v2.0 重构时，我用三段式：Phase 1 抽象 → Phase 2 接源 → Phase 3 字段化，保证每步都可验证。"

---

### Q8: Bad Case 闭环是什么？

**标准回答**：
> "每次跑 Agent 都会自动落一条记录到 agent_runs 表，包含 query、结果数、耗时、trace、报告。零结果自动标 bad。
> 
> 人工 review 时可以：
> 1. 打 root_cause（filter_too_strict / rag_miss / prompt_off）
> 2. 关联 fix_commit（修了哪个 commit）
> 3. 写 fix_notes（修了什么）
> 
> 修完之后用 `replay` 命令把所有 bad case 重跑一遍，验证是否真的修好了。
> 
> 这形成了'跑 → 复盘 → 修 → replay'闭环，Agent 越用越准。"

---

### Q9: 怎么保证 LLM 输出是合法 JSON？

**标准回答**：
> "三层兜底：
> 
> 1. **Prompt 约束**：在 system prompt 里明确要求'只返回 JSON 对象，不要代码块和解释'
> 2. **正则提取**：`_extract_json()` 先尝试匹配 ```json...``` 代码块，再退而求其次抓第一个 `{...}` 片段
> 3. **失败兜底**：解析失败时，parse_intent 用整句 query 当关键词（保证后续不崩），reflect 强制 done（宁可少搜一轮也不要带病重试）
> 
> 实测这套方案能处理 99% 的 LLM 输出格式问题。"

---

### Q10: 项目有哪些可以改进的地方？

**标准回答**：
> "三个方向：
> 
> 1. **性能优化**：summarize 节点调 LLM 较慢（~30s），可以换成更小的模型，或者缓存相似查询的结果
> 2. **更多数据源**：目前只有 Boss 直聘，可以接入拉勾、智联、猎聘，增加数据覆盖面
> 3. **智能路由**：parse_intent 用本地小模型（Qwen 7B），summarize 才用云上大模型，降低成本
> 
> 这些都在 ROADMAP 里有规划。"

---

## 五、深度追问预演

### 5.1 架构设计类

**Q: 如果要支持百万级岗位数据，架构怎么改？**
> 1. FAISS 换成 Milvus Cluster 或 Qdrant（支持分布式向量检索）
> 2. MySQL 读写分离（主库写，从库读）
> 3. 加 Redis 缓存热门查询结果
> 4. Agent 状态持久化到 Redis（支持断点续跑）

**Q: 如果要支持多用户并发，怎么改？**
> 1. FastAPI 本身就是异步的，天然支持并发
> 2. 每个用户独立的 AgentState（已支持）
> 3. 向量检索加连接池
> 4. LLM 调用加队列（避免触发限流）

**Q: 如果 LLM API 挂了，系统怎么降级？**
> 1. parse_intent 降级：把整句 query 当关键词（已有兜底）
> 2. reflect 降级：直接 done，不反思
> 3. summarize 降级：返回原始岗位列表（无报告）
> 4. 重试机制：LLM 调用有 max_retries=2

---

### 5.2 技术细节类

**Q: Playwright 的 page.evaluate 和 page.request.fetch 有什么区别？**
> "page.evaluate 是在页面 JS 上下文里执行代码，如果页面导航了，执行上下文会被销毁，报 'Execution context was destroyed'。
> 
> page.request.fetch 是 Playwright 的 HTTP 客户端，走浏览器的 cookie 但脱离页面 JS 上下文，不受导航影响。我们用它来调 API，更稳定。"

**Q: FAISS 的 IndexFlatIP 和 IndexIVFFlat 有什么区别？**
> "IndexFlatIP 是暴力搜索（精确），适合小数据量（<10万）。IndexIVFFlat 是倒排索引（近似），先聚类再搜索，适合大数据量（百万级）。
> 
> 我们几百条数据用 IndexFlatIP 就够了，精确搜索且延迟 <1ms。"

**Q: LangGraph 的 state 是怎么在节点间传递的？**
> "LangGraph 维护一个全局 state dict。每个节点函数接收 state，返回一个 partial update（只返回你修改的字段）。LangGraph 会自动 merge 回全局 state。
> 
> 比如 parse_intent 返回 `{"intent": {...}}`，LangGraph 会把它 merge 到全局 state 里，下一个节点就能读到 `state["intent"]`。"

---

### 5.3 项目经验类

**Q: 遇到的最大挑战是什么？怎么解决的？**
> "Boss 直聘的反爬。一开始用 requests 带 cookie 请求，被 code 37 封了。后来换成 Playwright 无头浏览器，还是被封。
> 
> 最后发现关键点：Boss 检测的是'自动化特征'，不是请求内容。解决方案是 CDP 接管用户已登录的真实 Chrome，请求来自真实浏览器、真实 cookie，完全绕过检测。
> 
> 还有个细节：每个查询要新开标签页，否则 WAF 会封'同一会话连续打 API'。"

**Q: 项目有什么遗憾或教训？**
> "一个教训：ingest 阶段漏存了 securityId 和 lid 字段，导致下游 enrich 脚本拿不到配对信息。修完之后清库重跑。
> 
> 教训是：**下游需要的字段都要在上游存好**，不要假设'以后可能用不到'。"

**Q: 这个项目你学到了什么？**
> 1. **Agent 设计**：不是所有逻辑都要交给 LLM，规则明确的部分用确定性函数更快更稳
> 2. **反爬对抗**：技术对抗是动态的，要理解对方的检测逻辑，而不是硬刚
> 3. **工程化**：测试、日志、配置管理这些'无聊'的东西，决定了项目能不能长期维护

---

### 5.4 刁钻追问（面试官可能出的难题）

**Q1: 你的 Agent 和 ReAct 模式有什么区别？**

> "ReAct 是经典的 Thought→Action→Observation 循环，每一步都由 LLM 决定下一步做什么。我们的项目是**固定 DAG + 条件回路**：
> 
> - **ReAct**：LLM 决定 → 调工具 → 观察结果 → LLM 再决定...（完全由 LLM 驱动）
> - **我们的方案**：5 个节点固定编排，只有 reflect 节点有条件路由（retry/done）
> 
> 优势是**更可控、更可预测**。retrieve/filter 是纯函数，同样输入同样输出，方便测试。ReAct 每次执行路径可能不同，调试更难。
> 
> 劣势是灵活性不如 ReAct——如果用户需求超出了预设的 5 个节点能力范围，我们的 Agent 无法自主扩展。"

---

**Q2: 如果用户查询很模糊（比如"给我找个工作"），Agent 怎么办？**

> "三层兜底机制：
> 
> 1. **parse_intent 兜底**：LLM 解析失败时，把整句 query 当关键词，direction 标记为'未明确'
> ```python
> except Exception:
>     intent = {"keywords": [query], "direction": "未明确"}
> ```
> 
> 2. **retrieve 兜底**：keywords 为空时退回用原始 query
> ```python
> keywords = intent.get("keywords") or [state["query"]]
> ```
> 
> 3. **reflect 探索**：第一轮结果不好时，LLM 会自主换近义词（比如"AI开发"→"大模型应用"→"Agent工程师"）
> 
> 实测：输入"给我找个工作"，parse_intent 会解析出空关键词，retrieve 用原句检索，reflect 发现结果太泛后换更具体的关键词，最终也能返回有意义的结果。"

---

**Q3: 向量检索的召回率怎么保证？**

> "四个策略：
> 
> 1. **多关键词拼接 embedding**：把 [LangChain, Agent, RAG] 拼成一句 "LangChain Agent RAG" 做 embedding，比逐个搜性价比高
> 2. **软线索也拼入查询**：意图里的方向、薪资、经验都拼进 embed_query
> ```python
> embed_query = " ".join(keywords)
> if intent.get("direction"):
>     embed_query += f" {intent['direction']}"
> if intent.get("salary_min"):
>     embed_query += f" 薪资 {intent['salary_min'] // 1000}K+"
> ```
> 3. **Top-30 留足余量**：retrieve 召回 30 条，filter 再筛，避免漏掉好岗位
> 4. **反思回路补救**：第一轮召回不够时，换关键词再搜一轮
> 
> 实测 4 个 benchmark query 召回质量全部 A+，最高 0.901 相似度。"

---

**Q4: filter 为什么不用 LLM？**

> "三个原因：
> 
> 1. **规则明确**：薪资 ≥ 15K、城市 ∈ [杭州,苏州]、学历 ∈ [本科,大专]——这些都是布尔/数值判定，用 if-else 比 LLM 更快更准
> 2. **省 token 省 latency**：filter 不调 LLM，省了一次 API 调用（~2-5s），也省了 token 费用
> 3. **结果可复现**：同样输入永远同样输出，方便测试和调试
> 
> 如果用 LLM 做 filter，可能出现'LLM 觉得 14K 也差不多算 15K+'这种不稳定行为。
> 
> 设计原则：**决策类节点（parse/reflect/summarize）调 LLM，检索/过滤类节点用确定性函数**。"

---

**Q5: 如果 Boss 直聘改了 API 怎么办？**

> "四层防护：
> 
> 1. **常量集中管理**：API 路径、城市编码都在文件顶部常量里，改一处即可
> ```python
> SEARCH_API_PATH = "/wapi/zpgeek/search/joblist.json"
> DETAIL_API_PATH = "/wapi/zpgeek/job/card.json"
> CITY_CODES = {"杭州": "101210100", ...}
> ```
> 
> 2. **搜索 API 和详情 API 分离**：搜索返回列表，详情返回正文。改一个不影响另一个
> 
> 3. **字段解析有兜底**：所有字段取值都有 `.get("key", "")` 或 `or ""` 兜底，字段缺失不会崩
> 
> 4. **日志监控**：API 返回非 0 code 时会 warning 日志，可以及时发现变化
> 
> 如果 API 大改（比如路径变了），改 `SEARCH_API_PATH` 一个常量就行。如果字段结构大改，需要改 `_fetch_one_query` 的解析逻辑。"

---

**Q6: 为什么用火山引擎不用 OpenAI？**

> "三个原因：
> 
> 1. **国内访问稳定**：OpenAI 需要翻墙，火山引擎在国内直连，延迟更低
> 2. **性价比高**：火山引擎 Coding Plan 走套餐而非按量付费，适合学习项目
> 3. **OpenAI 兼容协议**：火山引擎提供 OpenAI 兼容的 API，换模型零改代码
> ```python
> ChatOpenAI(
>     api_key=api_key,
>     base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
>     model="kimi-k2.6",
> )
> ```
> 
> 如果要换成 OpenAI 的 GPT-4，只改 `.env` 里的三个配置就行，代码不用动。"

---

**Q7: 测试怎么保证不依赖外部服务？**

> "全部 mock，三个层面：
> 
> 1. **DB 用临时库**：pytest 的 `tmp_path` fixture 创建临时目录，每个测试一个独立的 DB
> ```python
> @pytest.fixture
> def temp_db(tmp_path):
>     db_path = str(tmp_path / "test_collector.db")
>     return DBManager(db_path=db_path)
> ```
> 
> 2. **网络用 monkeypatch**：mock 掉 requests.post、playwright 等外部调用
> 
> 3. **LLM 用固定返回值**：mock 掉 ChatOpenAI.invoke，返回预设的 JSON
> 
> 这样测试可以在完全离线的环境跑，0.5 秒跑完 81 个测试。CI 环境也不需要配置任何外部服务。"

---

**Q8: agent_runs 表为什么和 collector.db 分开？后来又合并了？**

> "最初设计是分开的：
> - `collector.db`：v1/v2 pipeline 的状态机（task_queue / raw_contents / final_results）
> - `agent_runs.db`：v3.0 Agent 的调试数据（query / trace / report）
> 
> 分开的理由是**职责隔离**：pipeline 的状态机不应该被 Agent 调试数据污染。
> 
> 后来合并到同一个 MySQL 库的理由是**运维简化**：只需要维护一个数据库连接，备份/恢复更简单。
> 
> 合并时用的是**幂等建表**：
> ```sql
> CREATE TABLE IF NOT EXISTS agent_runs (...)
> ```
> 
> 老代码调 `BadCaseStore()`，新代码调 `DBManager().record_agent_run()`，接口兼容。"

---

**Q9: reflect 节点的 prompt 怎么设计的？**

> "给 LLM 看四类信息：
> 
> 1. **用户原始需求**：让它理解用户到底想要什么
> 2. **已解析意图 + 已尝试关键词**：避免重复搜同样的词
> 3. **当前岗位列表**：让它判断质量够不够
> 4. **画像主投/保底方向**：指导它换什么方向的关键词
> 
> ```python
> user = (
>     f"用户原始需求: {state['query']}\n"
>     f"已解析意图: {json.dumps(intent)}\n"
>     f"画像主投方向: {profile.get('primary_directions')}\n"
>     f"画像保底方向: {profile.get('fallback_directions')}\n"
>     f"已尝试过的关键词组: {state['tried_keywords']}\n"
>     f"当前已通过过滤的岗位（{len(kept)} 条）:\n{summary}\n"
> )
> ```
> 
> System prompt 定义了输出格式：JSON 含 decision / reason / next_keywords / next_cities。
> 
> 关键设计：**只在结果不够时才调 LLM**，足够 ≥ 5 条直接 done，省 token。"

---

**Q10: 这个项目你一个人做的？团队合作怎么分工？**

> "学习项目，独立完成。但设计时考虑了**可扩展性**，体现了工程思维：
> 
> 1. **插件式架构**：新增数据源只需写一个子类，不影响其他模块
> 2. **配置外置**：.env 存敏感信息，my_profile.yaml 存画像，不硬编码
> 3. **测试覆盖**：81 个 pytest，每个模块独立测试，重构有信心
> 4. **文档完善**：README + 5 篇博客 + ROADMAP + JD_MAPPING，不是'能跑就行'
> 
> 如果是团队协作，这种架构可以这样分工：
> - A 负责数据采集层（新增数据源）
> - B 负责 RAG 层（优化 embedding/检索）
> - C 负责 Agent 层（优化 prompt/反思策略）
> - D 负责 Web 层（前端/API）
> 
> 各层通过接口解耦，互不干扰。"

---

## 六、项目亮点话术

### 简历版（一行）

> 自研基于 LangGraph + FAISS + Playwright + bge-m3 的求职 Agent，通过 CDP 接管真实浏览器绕过 Boss 直聘反爬，从 5 城市采集 192+ AI 岗位真实 JD，端到端实现意图解析 → RAG 检索 → 反思决策 → 报告生成。用自己造的 Agent 找到了现在这份工作。

### 面试版（2 分钟）

> "这是一个端到端的 AI 求职 Agent。简单说就是：你告诉它想找什么工作，它自己去采集岗位、语义匹配、反思优化、生成报告。
> 
> 技术上分五层：
> 1. **采集层**：用 Playwright CDP 接管真实 Chrome 绕过 Boss 直聘反爬，从 5 个城市采集了 192 条 AI 岗位
> 2. **存储层**：MySQL 状态机管理任务生命周期，失败自动重试
> 3. **检索层**：bge-m3 做 embedding（1024 维），FAISS 做向量检索，支持自然语言查询
> 4. **Agent 层**：LangGraph 5 节点 DAG，核心是反思回路——结果不够时自主换关键词重搜
> 5. **服务层**：FastAPI Web API + MCP Server，Claude Desktop 可以直接调用
> 
> 亮点是反爬方案和反思循环。反爬用 CDP 接管真实浏览器，完全绕过风控。反思循环让 Agent 能自主探索，而不是一次搜不到就放弃。"

### 数据驱动版（强调成果）

> "用这个 Agent 跑了真实数据：
> - 192 条 Boss 直聘 AI 岗位，覆盖 5 个城市
> - 4 个 benchmark query 召回质量全部 A+（最高 0.901 相似度）
> - 端到端 ~3.5 分钟（从自然语言到报告）
> - 反思循环实测：第一轮 0 结果，第二轮换关键词命中 6 条
> - 81 个 pytest 单测全绿，GitHub Actions CI 自动跑
> 
> 而且我真的用这个 Agent 找到了工作——查了一下市场数据，MCP 在 192 条 JD 里出现 14 次（稀缺度高），LangGraph 16 次，Agent 106 次（市场最缺）。这就是我接下来的学习路线。"

---

## 附录：关键代码位置速查

| 功能 | 文件 | 行号 |
|------|------|------|
| LangGraph DAG 定义 | `src/agent/graph.py` | 53-75 |
| 5 个节点实现 | `src/agent/nodes.py` | 173-480 |
| State 定义 | `src/agent/nodes.py` | 83-106 |
| Prompt 模板 | `src/agent/prompts.py` | 全文 |
| 向量检索工具 | `src/agent/tools.py` | 68-112 |
| 硬过滤逻辑 | `src/agent/tools.py` | 143-204 |
| 技能差距计算 | `src/agent/tools.py` | 210-238 |
| FAISS 向量存储 | `src/rag/vector_store.py` | 全文 |
| Embedding 封装 | `src/rag/embedder.py` | 全文 |
| Boss 反爬 | `src/sources/boss_zhipin.py` | 全文 |
| 插件基类 | `src/sources/base.py` | 全文 |
| MySQL 状态机 | `src/db_manager.py` | 全文 |
| FastAPI Web | `src/web/app.py` | 全文 |
| MCP Server | `src/mcp_server/ai_collector_mcp.py` | 全文 |
| Bad Case 闭环 | `src/agent/bad_case_store.py` | 全文 |

---

**最后更新**: 2026-08-03
**版本**: v3.1
