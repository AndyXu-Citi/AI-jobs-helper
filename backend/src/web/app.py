"""
v3.1 Web API -- FastAPI 后端

把 LangGraph 求职 Agent 包成 HTTP API：
  POST /api/chat          -> 同步调用 find_jobs，返回完整结果
  POST /api/chat/stream   -> SSE 流式输出 trace + 报告
  GET  /api/jobs          -> 查询历史岗位数据
  GET  /api/skill-gap     -> 查询技能热度 + 缺口
  POST /api/chat/unified  -> 统一对话入口（求职助手 / 面试官，自动意图识别）
  POST /api/resume/upload -> 上传 PDF 简历
  GET  /api/conversations -> 会话历史（记忆模块）
  GET  /                  -> 占位页（前端由 Vite 开发服务器提供）

跑法: cd backend && .venv/Scripts/python -m src.web.app
"""
import os
import logging
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import json
import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, UploadFile, File as FastAPIFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

app_logger = logging.getLogger(__name__)

load_dotenv()

from src.agent.graph import find_jobs, find_jobs_stream, JobAgentResult
from src.agent.tools import (
    JobRecord,
    load_profile,
    PROFILE_PATH,
    _parse_salary,
)
from src.agent.nodes import _llm, _extract_json
from langchain_core.messages import HumanMessage, SystemMessage
from collections import Counter
import yaml as _yaml
import threading

# 记忆模块：MySQL 会话原文持久化 + Milvus 长期语义记忆
from src.db_conversation import (
    ensure_tables, create_conversation, touch_conversation, save_message,
)
from src.rag.memory_store import MemoryStore


# ------------------------------------------------------------------
# 记忆 / 持久化 辅助（懒初始化，避免导入期连 Milvus 阻塞）
# ------------------------------------------------------------------
_MEMORY_STORE: MemoryStore | None = None
_MEMORY_INIT_LOCK = threading.Lock()
_DB_READY = False
DEFAULT_USER_ID = "default"


def _ensure_memory_ready() -> MemoryStore | None:
    """首次调用时建表 + 初始化 MemoryStore；之后复用。"""
    global _MEMORY_STORE, _DB_READY
    with _MEMORY_INIT_LOCK:
        if not _DB_READY:
            try:
                ensure_tables()
            except Exception as e:  # 表建不出来不应阻断对话
                app_logger.warning(f"记忆 MySQL 表初始化失败: {e}")
            _DB_READY = True
        if _MEMORY_STORE is None:
            try:
                _MEMORY_STORE = MemoryStore()
            except Exception as e:
                app_logger.warning(f"MemoryStore 初始化失败: {e}")
                _MEMORY_STORE = None
    return _MEMORY_STORE


def _recall_context(user_id: str, message: str, top_k: int = 3) -> str:
    """跨会话语义召回该用户历史记忆，返回格式化的上下文串（无则空）。"""
    store = _MEMORY_STORE
    if not store or not store.enabled or not message:
        return ""
    vec = store.embed(message)
    if not vec:
        return ""
    mems = store.recall(user_id, vec, top_k=top_k)
    if not mems:
        return ""
    return "\n".join(f"- {m}" for m in mems)


def _persist_and_remember(conversation_id: str, user_id: str,
                          user_msg: str, assistant_reply: str, mode: str) -> None:
    """落库原始对话 + 异步写入语义记忆（user_msg）。"""
    try:
        save_message(conversation_id, "user", user_msg, user_id=user_id)
        save_message(conversation_id, "assistant", assistant_reply, user_id=user_id)
        touch_conversation(conversation_id)
    except Exception as e:
        app_logger.warning(f"持久化对话失败: {e}")

    # 异步写语义记忆，不阻塞回复
    if _MEMORY_STORE and _MEMORY_STORE.enabled and user_msg:
        threading.Thread(
            target=_safe_add_memory, args=(user_id, conversation_id, user_msg),
            daemon=True,
        ).start()


def _safe_add_memory(user_id: str, conversation_id: str, user_msg: str) -> None:
    try:
        ok = _MEMORY_STORE.add_memory(
            user_id=user_id, session_id=conversation_id,
            memory_type="user_msg", content=user_msg)
        if ok:
            _MEMORY_STORE.flush()
    except Exception as e:
        app_logger.warning(f"记忆写入失败: {e}")

# ------------------------------------------------------------------
# Pydantic 请求/响应模型
# ------------------------------------------------------------------

class ChatRequest(BaseModel):
    query: str


class MatchRequest(BaseModel):
    resume: str = ""     # 候选人简历文本（可来自 my_profile.yaml，也可自由粘贴）
    jd_text: str = ""    # 直接粘贴的 JD 描述
    jd_url: str = ""     # 或提供岗位链接，后端自动从 final_results 取 JD


class JobItem(BaseModel):
    title: str
    brand: str
    city: str
    salary_desc: str
    salary_min: int
    salary_max: int
    experience: str
    degree: str
    score: float
    skills: list[str]
    short_desc: str
    post_description: str = ""  # JD 全文，前端可展开
    url: str


class ChatResponse(BaseModel):
    final_report: str
    filtered_jobs: list[JobItem]
    skill_gap: list[list]  # [["Python", 45], ["LangChain", 30], ...]
    intent: dict
    filter_stats: dict
    trace: list[str]
    elapsed_seconds: float


# ------------------------------------------------------------------
# FastAPI app
# ------------------------------------------------------------------

app = FastAPI(title="AI 求职 Agent", version="3.0")

_STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
async def preload_embedder():
    """服务启动时预加载 bge-m3 模型，避免第一次搜索卡顿。"""
    app_logger.info("预加载 bge-m3 embedding 模型...")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _load_embedder)
    except Exception as e:
        app_logger.warning(f"预加载模型失败，首次搜索时会自动加载: {e}")


def _load_embedder():
    """同步加载 HuggingFaceEmbedder 模型。"""
    from src.rag.embedder import HuggingFaceEmbedder
    embedder = HuggingFaceEmbedder()
    embedder.embed_one("预加载")
    app_logger.info("bge-m3 模型加载完成")


def _job_to_item(job: JobRecord) -> JobItem:
    """把 JobRecord dataclass 转成 Pydantic model。"""
    return JobItem(
        title=job.title,
        brand=job.brand,
        city=job.city,
        salary_desc=job.salary_desc,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        experience=job.experience,
        degree=job.degree,
        score=round(job.score, 3),
        skills=job.skills,
        short_desc=job.short_desc,
        post_description=job.post_description,
        url=job.url,
    )


def _result_to_response(result: JobAgentResult) -> ChatResponse:
    """把 JobAgentResult 转成 API 响应。"""
    return ChatResponse(
        final_report=result.final_report,
        filtered_jobs=[_job_to_item(j) for j in result.filtered_jobs],
        skill_gap=[[s, c] for s, c in result.skill_gap],
        intent=result.intent,
        filter_stats=result.filter_stats,
        trace=result.trace,
        elapsed_seconds=round(result.elapsed_seconds, 2),
    )


# ------------------------------------------------------------------
# 路由
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    """返回前端页面。"""
    html_path = _STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """同步调用求职 Agent，返回完整结果。"""
    try:
        result = find_jobs(req.query)
        # 记录到 agent_runs
        try:
            from src.agent.bad_case_store import BadCaseStore
            store = BadCaseStore()
            store.record_run(
                query=req.query,
                result_count=len(result.filtered_jobs),
                elapsed_seconds=result.elapsed_seconds,
                reflect_rounds=len([t for t in result.trace if "reflect" in t.lower()]),
                trace=result.trace,
                final_report=result.final_report,
            )
        except Exception:
            app_logger.warning("记录 agent_runs 失败", exc_info=True)
        return _result_to_response(result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式输出：每个节点执行完实时推送 trace，最后推送完整结果。"""
    def generate():
        try:
            for event in find_jobs_stream(req.query):
                if event["type"] == "trace":
                    lines = event["lines"]
                    # 逐条推送新 trace
                    for line in lines:
                        chunk = json.dumps({"type": "trace", "content": line}, ensure_ascii=False)
                        yield f"data: {chunk}\n\n"
                elif event["type"] == "done":
                    result = event["result"]
                    try:
                        from src.agent.bad_case_store import BadCaseStore
                        store = BadCaseStore()
                        store.record_run(
                            query=req.query,
                            result_count=len(result.filtered_jobs),
                            elapsed_seconds=result.elapsed_seconds,
                            reflect_rounds=len([t for t in result.trace if "reflect" in t.lower()]),
                            trace=result.trace,
                            final_report=result.final_report,
                        )
                    except Exception:
                        pass
                    resp = _result_to_response(result)
                    chunk = json.dumps(
                        {"type": "done", "data": resp.model_dump()},
                        ensure_ascii=False,
                    )
                    yield f"data: {chunk}\n\n"

        except Exception as e:
            chunk = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
            yield f"data: {chunk}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/jobs")
async def get_jobs(limit: int = 20, city: str = ""):
    """查询数据库里的岗位列表（不跑 Agent，直接读 MySQL）。"""
    from src.db_config import get_connection

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        if city:
            cursor.execute(
                "SELECT id, url, structured_json, processed_at FROM final_results "
                "WHERE source_type='boss_zhipin' AND structured_json LIKE %s "
                "ORDER BY processed_at DESC LIMIT %s",
                (f'%"{city}"%', limit),
            )
        else:
            cursor.execute(
                "SELECT id, url, structured_json, processed_at FROM final_results "
                "WHERE source_type='boss_zhipin' "
                "ORDER BY processed_at DESC LIMIT %s",
                (limit,),
            )
        rows = cursor.fetchall()
    finally:
        conn.close()

    jobs = []
    for row in rows:
        try:
            data = json.loads(row["structured_json"]) if isinstance(row["structured_json"], str) else row["structured_json"]
            boss = data.get("_boss") or {}
            # 合并 Boss 官方标签 + LLM 提取的技能
            skills_raw = boss.get("skills", []) or []
            extracted = boss.get("skills_extracted", []) or []
            merged = {}
            for s in skills_raw + extracted:
                if s and isinstance(s, str) and s.strip():
                    merged[s.strip()] = True
            jobs.append({
                "title": data.get("title", ""),
                "brand": boss.get("brand_name", ""),
                "city": boss.get("city", ""),
                "salary_desc": boss.get("salary_desc", ""),
                "experience": boss.get("experience_name", ""),
                "degree": boss.get("degree_name", ""),
                "skills": list(merged.keys()),
                "post_description": boss.get("post_description", ""),
                "url": row["url"],
            })
        except Exception:
            continue

    return {"total": len(jobs), "jobs": jobs}


@app.get("/api/skill-gap")
async def get_skill_gap(top_n: int = 15):
    """查询技能热度 + 缺口（与 /api/report 口径一致，基于 skills_extracted）。"""
    top_n = max(1, min(int(top_n), 30))
    structs = _load_all_structured()

    skill_counter: Counter = Counter()
    for s in structs:
        b = s.get("_boss") or {}
        for sk in (b.get("skills_extracted") or []):
            if isinstance(sk, str) and sk.strip():
                skill_counter[sk.strip()] += 1
        for sk in (b.get("skills") or []):
            if isinstance(sk, str) and sk.strip():
                skill_counter[sk.strip()] += 1

    profile = load_profile()
    have = {x.lower() for x in (profile.get("already_have") or [])}
    learning = {x.lower() for x in (profile.get("learning") or [])}

    market_top = [
        {"name": k, "count": v}
        for k, v in skill_counter.most_common(top_n)
    ]
    gap = [
        {"name": k, "count": v, "is_learning": k.lower() in learning}
        for k, v in skill_counter.most_common(top_n * 3)
        if k.lower() not in have
    ][:top_n]

    have_hits = [
        {"skill": k, "count": v}
        for k, v in skill_counter.most_common(top_n * 3)
        if k.lower() in have
    ][:top_n]
    learning_hits = [
        {"skill": k, "count": v}
        for k, v in skill_counter.most_common(top_n * 3)
        if k.lower() in learning
    ][:top_n]

    return {
        "total_jobs_analyzed": len(structs),
        "market_top_skills": market_top,
        "skill_gap": gap,
        "already_have_hits": have_hits,
        "learning_hits": learning_hits,
    }


# ------------------------------------------------------------------
# 报表 / 匹配 / 画像：横向扩展的新端点
# ------------------------------------------------------------------

def _load_all_structured() -> list[dict]:
    """读取全部 boss_zhipin 岗位的 structured_json（已解析）。"""
    from src.db_config import get_connection

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, structured_json FROM final_results WHERE source_type='boss_zhipin'"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    for r in rows:
        try:
            d = json.loads(r["structured_json"])
            d["_db_id"] = r["id"]  # 用于回写 skills_extracted
            out.append(d)
        except Exception:
            continue
    return out


_SALARY_BANDS = ["<10K", "10-15K", "15-20K", "20-30K", "30K+", "未知"]


def _salary_band(desc: str) -> str:
    """把薪资描述映射到区间档位（取上下限均值）。"""
    lo, hi = _parse_salary(desc or "")
    if lo == 0 and hi == 0:
        return "未知"
    avg = (lo + hi) / 2
    if avg < 10000:
        return "<10K"
    if avg < 15000:
        return "10-15K"
    if avg < 20000:
        return "15-20K"
    if avg < 30000:
        return "20-30K"
    return "30K+"


def _as_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v if x is not None]
    return []


# ------------------------------------------------------------------
# LLM 技能提取（从 JD 正文提取技能，结果缓存到 MySQL _boss.skills_extracted）
# ------------------------------------------------------------------

def _llm_extract_and_cache(
    structs: list[dict],
    todo: list[tuple[int, str, str]],
) -> None:
    """用 LLM 批量提取技能，结果写入 MySQL _boss.skills_extracted。

    Args:
        structs: 全部 structured_json 列表（按引用修改）
        todo: [(index_in_structs, title, post_description), ...]
    """
    BATCH_SIZE = 8
    from src.db_config import get_connection

    conn = get_connection()
    try:
        cursor = conn.cursor()
        for batch_start in range(0, len(todo), BATCH_SIZE):
            batch = todo[batch_start:batch_start + BATCH_SIZE]
            prompt_lines = [
                "从以下每条 JD 中提取**技术关键词**（编程语言、框架、工具、平台、技术概念）。",
                "每条输出一个 JSON 字符串数组，最终输出外层 JSON 数组（数组的数组）。",
                "只输出 JSON，不要任何解释。",
                "",
            ]
            for idx, (_, title, desc) in enumerate(batch):
                text = f"【JD {idx + 1}】{title}\n{(desc or '')[:800]}"
                prompt_lines.append(f"\n---\n{text}")

            prompt_lines.append(
                "\n\n请输出 JSON 格式（数组的数组），例如："
                '\n[["Python","Django"],["Java","Spring","MySQL"]]'
            )

            try:
                llm = _llm()
                resp = llm.invoke([
                    SystemMessage(content="你是一个精准的技能提取器。只从 JD 文本中提取明确提到的技术关键词，不要臆测。"),
                    HumanMessage(content="\n".join(prompt_lines)),
                ])
                raw = resp.content if isinstance(resp.content, str) else str(resp.content)
                parsed = _extract_json(raw)
                if not isinstance(parsed, list):
                    raise ValueError(f"LLM 返回的不是数组: {type(parsed)}")

                for batch_idx, item in enumerate(parsed):
                    if not isinstance(item, list):
                        continue
                    skills = [s.strip() for s in item if isinstance(s, str) and s.strip()]
                    if not skills:
                        continue
                    global_idx = batch[batch_idx][0]
                    b = structs[global_idx].setdefault("_boss", {})
                    b["skills_extracted"] = skills

                    row_id = structs[global_idx].get("_db_id")
                    if row_id:
                        cursor.execute(
                            "UPDATE final_results SET structured_json = %s WHERE id = %s",
                            (json.dumps(structs[global_idx], ensure_ascii=False), row_id),
                        )

                app_logger.info(
                    f"[LLM提取] batch {batch_start // BATCH_SIZE + 1}/"
                    f"{(len(todo) - 1) // BATCH_SIZE + 1} OK"
                )
            except Exception as e:
                app_logger.warning(f"[LLM提取] batch 失败: {e}")
        conn.commit()
    finally:
        conn.close()


@app.get("/api/report")
async def get_report(top_n: int = 30):
    """统计报表：聚合 skills_extracted（由 scripts/llm_extract_skills.py 预先提取）
    和 Boss 官方 skills 标签，附城市/薪资/经验/学历分布。
    """
    top_n = max(1, min(int(top_n), 50))
    structs = _load_all_structured()

    skill_counter: Counter = Counter()
    city_counter: Counter = Counter()
    exp_counter: Counter = Counter()
    deg_counter: Counter = Counter()
    band_counter: Counter = Counter()

    for s in structs:
        b = s.get("_boss") or {}
        # 1) LLM 提取的技能缓存（由 scripts/llm_extract_skills.py 预先写入）
        for sk in (b.get("skills_extracted") or []):
            if isinstance(sk, str) and sk.strip():
                skill_counter[sk.strip()] += 1
        # 2) Boss 官方 skills 标签
        for sk in (b.get("skills") or []):
            if isinstance(sk, str) and sk.strip():
                skill_counter[sk.strip()] += 1

        c = (b.get("city") or "").strip()
        if c:
            city_counter[c] += 1
        e = (b.get("experience_name") or "").strip()
        if e:
            exp_counter[e] += 1
        d = (b.get("degree_name") or "").strip()
        if d:
            deg_counter[d] += 1
        band_counter[_salary_band(b.get("salary_desc") or "")] += 1

    profile = load_profile()
    have = {x.lower() for x in (profile.get("already_have") or [])}
    learning = {x.lower() for x in (profile.get("learning") or [])}

    def _top(c: Counter, n: int) -> list[dict]:
        total = sum(c.values())
        return [
            {"name": k, "count": v, "pct": round(v / total * 100, 1) if total else 0}
            for k, v in c.most_common(n)
        ]

    coverage = {"have": [], "learning": [], "missing_top": []}
    for k, v in skill_counter.most_common(top_n):
        kl = k.lower()
        if kl in have:
            coverage["have"].append({"skill": k, "count": v})
        elif kl in learning:
            coverage["learning"].append({"skill": k, "count": v})
        else:
            coverage["missing_top"].append({"skill": k, "count": v})

    return {
        "total_jobs": len(structs),
        "skills": _top(skill_counter, top_n),
        "cities": _top(city_counter, top_n),
        "experience": _top(exp_counter, 12),
        "degree": _top(deg_counter, 12),
        "salary_bands": [
            {"name": b, "count": band_counter.get(b, 0)} for b in _SALARY_BANDS
        ],
        "my_coverage": coverage,
    }


@app.get("/api/profile")
async def get_profile():
    """返回 my_profile.yaml 原文与解析结果，供前端载入/编辑简历。"""
    if not PROFILE_PATH.exists():
        return {"raw": "", "profile": {}}
    text = PROFILE_PATH.read_text(encoding="utf-8")
    try:
        parsed = _yaml.safe_load(text) or {}
    except Exception:
        parsed = {}
    return {"raw": text, "profile": parsed}


@app.post("/api/match")
async def match_resume(req: MatchRequest):
    """简历 vs 单条 JD 匹配：向量相似度 + LLM 深度分析。"""
    resume = (req.resume or "").strip()
    jd_text = (req.jd_text or "").strip()
    jd_url = (req.jd_url or "").strip()

    # 给了链接就从库里取 JD 正文
    if not jd_text and jd_url:
        from src.db_config import get_connection

        conn = get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT structured_json FROM final_results WHERE url = %s LIMIT 1",
                (jd_url,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        if row:
            try:
                s = json.loads(row["structured_json"])
                b = s.get("_boss") or {}
                parts = [
                    s.get("title", ""),
                    b.get("brand_name", ""),
                    b.get("salary_desc", ""),
                ]
                if b.get("skills"):
                    parts.append("技能: " + ", ".join(b["skills"]))
                if s.get("key_points"):
                    parts.append("要点: " + " / ".join(s["key_points"]))
                if b.get("post_description"):
                    parts.append(b["post_description"])
                jd_text = "\n".join(p for p in parts if p)
            except Exception:
                pass

    if not resume:
        return JSONResponse(status_code=400, content={"error": "请填写简历内容"})
    if not jd_text:
        return JSONResponse(
            status_code=400, content={"error": "请粘贴 JD 或提供岗位链接"}
        )

    # ── 向量检索：用简历搜最相似岗位，并计算简历-JD 余弦相似度 ──
    vector_score = None
    similar_jobs_raw: list[dict] = []
    try:
        from src.agent.tools import vector_search_jobs
        from src.rag.embedder import HuggingFaceEmbedder
        import math

        similar = vector_search_jobs(resume, top_k=5)
        for j in similar:
            similar_jobs_raw.append({
                "title": j.title, "brand": j.brand, "city": j.city,
                "salary_desc": j.salary_desc, "experience": j.experience,
                "degree": j.degree, "skills": j.skills[:8],
                "score": round(j.score, 4), "url": j.url,
                "post_description": j.post_description,
            })

        # 简历向量 vs JD 向量 → 余弦相似度
        embedder = HuggingFaceEmbedder()
        rv = embedder.embed_one(resume)
        jv = embedder.embed_one(jd_text)
        dot = sum(a * b for a, b in zip(rv, jv))
        nr = math.sqrt(sum(a * a for a in rv))
        nj = math.sqrt(sum(a * a for a in jv))
        vector_score = round(dot / (nr * nj), 4) if nr and nj else None
    except Exception as e:
        app_logger.warning(f"匹配向量检索失败（降级为纯 LLM）: {e}")

    # ── 构建 LLM prompt：融入向量相似度 + 相似岗位技能分布 ──
    similar_context = ""
    if similar_jobs_raw:
        lines = [f"- {j['title']} @ {j['brand']} | {j['city']} | {j['salary_desc']} | "
                 f"技能: {', '.join(j['skills'][:6])} | 相似度 {j['score']}"
                 for j in similar_jobs_raw]
        similar_context = "\n\n【与简历最相似的岗位（向量语义检索）】\n" + "\n".join(lines)

    system = (
        "你是一位资深技术招聘顾问与求职教练。请根据【候选人简历】和【岗位JD】，"
        "客观评估匹配程度，并给出可执行的提升建议。\n"
        "要求：\n"
        "1. 只输出一个 JSON 对象，不要任何额外文字，也不要用 ```markdown``` 包裹。\n"
        "2. JSON 字段：\n"
        '   - "match_score": 整数 0-100，综合匹配度（参考向量相似度分数）\n'
        '   - "matched_skills": 字符串数组，候选人已具备且 JD 要求的技能\n'
        '   - "missing_skills": 字符串数组，JD 要求但候选人缺失或薄弱的技能\n'
        '   - "suggestions": 字符串数组，针对缺失项的具体补足建议（学什么、怎么学、优先级）\n'
        '   - "interview_tips": 字符串数组，该岗位面试准备建议\n'
        "3. 评分中肯、不讨好；缺失项要具体到技能名。\n"
        "4. 下方【与简历最相似的岗位】列表可帮你判断市场对该类简历的普遍要求。\n"
        "   如果 JD 要求与同类岗位一致，你的匹配度得分应更高。"
    )
    user_parts = [f"# 候选人简历\n{resume}", f"# 岗位 JD\n{jd_text}"]
    if vector_score is not None:
        user_parts.append(f"# 简历-JD 向量相似度（0~1，余弦）\n{vector_score}")
    if similar_context:
        user_parts.append(similar_context)
    user = "\n\n".join(user_parts)

    try:
        llm = _llm()
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        data = _extract_json(raw)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"匹配分析失败：{e}"})

    return {
        "match_score": int(data.get("match_score", 0) or 0),
        "vector_score": vector_score,
        "matched_skills": _as_str_list(data.get("matched_skills")),
        "missing_skills": _as_str_list(data.get("missing_skills")),
        "suggestions": _as_str_list(data.get("suggestions")),
        "interview_tips": _as_str_list(data.get("interview_tips")),
        "similar_jobs": similar_jobs_raw,
        "llm_raw": raw,
    }


@app.post("/api/match/rank")
async def match_rank(req: ChatRequest):
    """用简历向量检索全部岗位，按相似度排序返回 Top N。"""
    resume = (req.query or "").strip()
    if not resume:
        return JSONResponse(status_code=400, content={"error": "请填写简历内容"})

    try:
        from src.agent.tools import vector_search_jobs
        jobs = vector_search_jobs(resume, top_k=20)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"检索失败：{e}"})

    items = []
    for j in jobs:
        items.append({
            "url": j.url, "title": j.title, "brand": j.brand,
            "city": j.city, "salary_desc": j.salary_desc,
            "experience": j.experience, "degree": j.degree,
            "skills": j.skills,
            "score": round(j.score, 4),
            "post_description": j.post_description,
        })

    return {"total": len(items), "jobs": items}


# ------------------------------------------------------------------
# AI 面试：模拟技术面试官
# ------------------------------------------------------------------

import uuid
import time

# 内存会话存储（生产环境应换 Redis / 数据库）
_interview_sessions: dict[str, dict] = {}

_INTERVIEW_SYSTEM_PROMPTS = {
    "resume": """你是一位**严厉但公正的技术面试官**，专精于「简历深挖」面试。
你的任务是根据候选人简历，逐项深挖细节，判断其真实性和深度。

规则：
1. 每次只问**一个问题**，聚焦简历中某个具体经历/技能/项目。
2. 追问要具体到：做了什么、怎么做的、为什么这么做、遇到什么困难、怎么解决的、数据结果如何。
3. 如果回答模糊或泛泛而谈，继续追问细节；如果回答扎实到位，给予认可后切换下一个话题。
4. 覆盖顺序：最近项目 → 核心技能 → 既往经验 → 软技能 / 团队协作。
5. 每轮回复格式：
   - 先对上轮回答做简短点评（1-2句）
   - 然后提出下一个问题
   - 最后标注当前考察维度（如 [项目深度] / [技术原理] / [问题解决]）
6. 用中文，语气专业但不刻薄。不要一次问多个问题。
7. 如果候选人明显在编造或夸大，委婉指出矛盾点并要求澄清。""",
    "project": """你是一位**资深技术架构师兼面试官**，专精于「项目拷问」。
你的任务是对候选人描述的项目进行全方位技术拷问，评估其真实参与度和理解深度。

规则：
1. 从项目架构入手，逐步深入到具体实现细节。
2. 考察维度（按顺序）：
   - 整体架构与技术选型理由
   - 核心模块设计与实现
   - 难点攻克与性能优化
   - 工程化实践（CI/CD、测试、监控）
   - 团队协作与项目管理
3. 每次只问一个开放性问题，要求候选人用具体例子回答。
4. 如果回答浮于表面，立即追问"能举个具体的场景吗？"或"当时你具体是怎么处理的？"
5. 每轮回复格式：
   - 上轮回答评价
   - 新问题（带上下文）
   - 当前考察维度标签
6. 用中文，专业且深入。不要放过任何含糊其辞的回答。""",
    "knowledge": """你是一位**技术知识考核面试官**，专精于「知识点」问答。
你的任务是对候选人指定的技术领域进行系统性知识考核。

规则：
1. 先从基础概念开始，逐步进阶到原理、实战应用、设计权衡。
2. 问题类型交替使用：
   - 概念解释题（"请解释 XX 的原理"）
   - 场景分析题（"在 XX 场景下你会怎么选？为什么？"）
   - 排障诊断题（"XX 出了这个问题，你怎么排查？"）
   - 对比辨析题（"XX 和 YY 有什么区别？各适用什么场景？"）
3. 每次只问一题。根据回答质量决定下一题难度——答得好就加深，答得不好就降级或换角度再测。
4. 每轮回复格式：
   - 上题答案评价（指出正确/部分正确/错误之处）
   - 新题目
   - 难度标签（[基础] / [进阶] / [实战] / [架构]）
   - 知识领域标签（如 [LangChain] / [RAG] / [LLM]）
5. 用中文，严谨准确。""",
    "jd": """你是一位**目标岗位的模拟面试官**，根据 JD 要求对候选人进行针对性面试。
你的任务是严格按照岗位 JD 的要求，评估候选人的匹配度和胜任能力。

规则：
1. 先通读 JD，提取核心要求（必选技能、加分项、软技能）。
2. 按 JD 权重顺序提问：核心硬技能 → 项目经验匹配 → 业务理解 → 软技能 / 文化匹配。
3. 每个问题都要关联到 JD 的具体要求，如"该岗位要求精通 XX，请描述你在 XX 方面的经验..."。
4. 如果候选人的经历与 JD 有差距，温和地指出并询问其学习计划或补偿方案。
5. 每轮回复格式：
   - 上轮回答评价
   - 新问题（明确关联到 JD 的哪条要求）
   - 匹配度参考标签（[核心要求] / [加分项] / [通用能力]）
6. 用中文，既严格又给候选人展示机会。""",
}


class InterviewStartRequest(BaseModel):
    mode: str  # resume | project | knowledge | jd
    content: str = ""  # 简历文本 / 项目描述 / 知识点列表 / JD 文本


class InterviewChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/api/interview")
async def start_interview(req: InterviewStartRequest):
    """启动一场新的 AI 面试会话，返回 session_id 和第一个问题。"""
    mode = (req.mode or "").strip().lower()
    if mode not in _INTERVIEW_SYSTEM_PROMPTS:
        return JSONResponse(
            status_code=400,
            content={"error": f"不支持的面试模式: {mode}，可选: {list(_INTERVIEW_SYSTEM_PROMPTS.keys())}"},
        )

    content = (req.content or "").strip()
    if not content:
        return JSONResponse(status_code=400, content={"error": "请提供面试素材（简历/项目描述/知识点/JD）"})

    session_id = str(uuid.uuid4())[:8]
    mode_names = {
        "resume": "简历深挖",
        "project": "项目拷问",
        "knowledge": "知识点考核",
        "jd": "指定 JD 面试",
    }

    # 构建首条用户消息（把素材作为第一条消息发给 LLM）
    mode_labels = {
        "resume": "以下是候选人的【简历全文】",
        "project": "以下是候选人参与的【项目描述】",
        "knowledge": "以下是需要考核的【知识点范围】",
        "jd": "以下是目标岗位的【JD 描述】",
    }
    initial_user = f"{mode_labels.get(mode, '素材')}\n\n{content}"

    system = _INTERVIEW_SYSTEM_PROMPTS[mode]

    try:
        llm = _llm()
        resp = llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=initial_user + "\n\n请开始面试，提出你的第一个问题。"),
        ])
        first_reply = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"LLM 调用失败: {e}"})

    _interview_sessions[session_id] = {
        "mode": mode,
        "mode_name": mode_names.get(mode, mode),
        "system": system,
        "history": [
            {"role": "user", "content": initial_user},
            {"role": "assistant", "content": first_reply},
        ],
        "created_at": time.time(),
        "round": 1,
    }

    return {
        "session_id": session_id,
        "mode": mode,
        "mode_name": mode_names.get(mode, mode),
        "reply": first_reply,
        "round": 1,
    }


@app.post("/api/interview/chat")
async def chat_interview(req: InterviewChatRequest):
    """在已有面试会话中继续对话。"""
    sid = (req.session_id or "").strip()
    msg = (req.message or "").strip()

    if not sid or sid not in _interview_sessions:
        return JSONResponse(status_code=404, content={"error": "会话不存在或已过期"})
    if not msg:
        return JSONResponse(status_code=400, content={"error": "请输入回复内容"})

    sess = _interview_sessions[sid]
    sess["history"].append({"role": "user", "content": msg})
    sess["round"] += 1

    try:
        llm = _llm()
        messages = [SystemMessage(content=sess["system"])]
        for h in sess["history"]:
            if h["role"] == "user":
                messages.append(HumanMessage(content=h["content"]))
            else:
                # 把 assistant 历史消息也传入以保持上下文
                from langchain_core.messages import AIMessage
                messages.append(AIMessage(content=h["content"]))

        resp = llm.invoke(messages)
        reply = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"LLM 调用失败: {e}"})

    sess["history"].append({"role": "assistant", "content": reply})

    return {
        "session_id": sid,
        "reply": reply,
        "round": sess["round"],
    }


@app.get("/api/interview/sessions")
async def list_interview_sessions():
    """列出当前活跃的面试会话（调试用）。"""
    sessions = []
    for sid, sess in _interview_sessions.items():
        sessions.append({
            "session_id": sid,
            "mode_name": sess.get("mode_name", ""),
            "round": sess.get("round", 0),
            "created_at": sess.get("created_at", 0),
        })
    sessions.sort(key=lambda x: x["created_at"], reverse=True)
    return {"sessions": sessions}


# ------------------------------------------------------------------
# PDF 简历上传 + 统一对话入口
# ------------------------------------------------------------------

@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = FastAPIFile(...)):
    """上传 PDF 简历，解析为纯文本返回。"""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return JSONResponse(status_code=400, content={"error": "请上传 PDF 文件"})

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB 限制
        return JSONResponse(status_code=400, content={"error": "文件过大（>10MB）"})

    # 尝试用 pdfplumber 解析
    resume_text = ""
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
            resume_text = "\n".join(pages).strip()
    except ImportError:
        # fallback: PyPDF2
        try:
            from PyPDF2 import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content))
            pages = [p.extract_text() or "" for p in reader.pages]
            resume_text = "\n".join(pages).strip()
        except ImportError:
            return JSONResponse(
                status_code=500,
                content={"error": "服务器未安装 PDF 解析库（pdfplumber/PyPDF2）"},
            )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"PDF 解析失败: {e}"})

    if not resume_text:
        return JSONResponse(status_code=422, content={"error": "PDF 解析结果为空，可能是扫描件或图片格式"})

    return {
        "filename": file.filename,
        "size": len(content),
        "text": resume_text,
        "char_count": len(resume_text),
    }


# ── 统一对话：意图识别 + 路由分发 ──

class UnifiedChatRequest(BaseModel):
    message: str
    mode: str = "assistant"            # assistant | interviewer
    session_id: str = ""
    resume_text: str = ""              # 已上传的简历文本
    jd_text: str = ""                  # 面试用 JD
    interview_submode: str = "resume"  # jd | resume | project | knowledge

# 求职助手系统提示词（含礼貌拒绝规则）
_ASSISTANT_SYSTEM = """你是「AI 求职助手」，帮助用户搜索岗位、分析简历、匹配职位。

你的能力范围：
1. 岗位搜索：根据用户的自然语言需求（城市/技能/薪资等），从岗位库检索匹配岗位并推荐。
2. 简历匹配：当用户上传简历后，可以分析简历与岗位的匹配度。
3. 简历诊断：评估简历的优缺点，给出改进建议。
4. 数据查询：回答岗位库相关的统计问题（如某技能出现频率）。

对于超出能力范围的请求（如写代码、闲聊、非求职相关问题），请礼貌拒绝并引导用户回到求职话题。
回复请使用中文，语言简洁专业。"""

def _detect_assistant_intent(message: str, has_resume: bool) -> str:
    """轻量关键词意图检测（求职助手模式）。"""
    msg = message.lower()
    # 简历匹配
    if has_resume and any(k in msg for k in ["匹配", "适合我", "适合的", "我能胜任", "匹配度"]):
        return "match"
    # 简历诊断
    if has_resume and any(k in msg for k in ["诊断", "评价简历", "简历怎么样", "改简历", "简历问题", "优化简历"]):
        return "diagnose"
    # 默认：岗位搜索
    return "search"


@app.post("/api/chat/unified")
async def unified_chat(req: UnifiedChatRequest):
    """统一对话入口：根据模式 + 意图自动分发到对应处理链。"""
    message = (req.message or "").strip()
    if not message:
        return JSONResponse(status_code=400, content={"error": "请输入消息"})

    mode = req.mode

    # ---- 记忆 / 持久化 准备 ----
    _ensure_memory_ready()
    user_id = DEFAULT_USER_ID
    conversation_id = (req.session_id or __import__("uuid").uuid4().hex[:12])
    # 确保会话行存在（INSERT IGNORE，多轮幂等）
    try:
        create_conversation(conversation_id, user_id=user_id,
                            title=message[:30] or "新对话", mode=mode)
    except Exception:
        pass

    # ============ 面试官模式 ============
    if mode == "interviewer":
        submode = req.interview_submode or "resume"

        # 已有 session → 继续对话
        if req.session_id and req.session_id in _interview_sessions:
            try:
                llm = _llm()
                sess = _interview_sessions[req.session_id]
                sess["history"].append({"role": "user", "content": message})
                sess["round"] += 1

                messages = [SystemMessage(content=sess["system"])]
                for h in sess["history"]:
                    if h["role"] == "user":
                        messages.append(HumanMessage(content=h["content"]))
                    else:
                        from langchain_core.messages import AIMessage
                        messages.append(AIMessage(content=h["content"]))

                resp = llm.invoke(messages)
                reply = resp.content if isinstance(resp.content, str) else str(resp.content)
                sess["history"].append({"role": "assistant", "content": reply})

                _persist_and_remember(conversation_id, user_id, message, reply, mode)
                return {
                    "reply": reply,
                    "intent": "interview",
                    "session_id": req.session_id,
                    "round": sess["round"],
                }
            except Exception as e:
                return JSONResponse(status_code=500, content={"error": f"LLM 调用失败: {e}"})

        # 首条消息 → 启动面试
        content = ""
        if submode == "resume":
            content = req.resume_text or ""
        elif submode == "jd":
            content = req.jd_text or ""
        elif submode == "project":
            content = message  # 项目描述直接用用户输入
        elif submode == "knowledge":
            content = message  # 知识点直接用用户输入

        if not content and submode in ("resume", "jd"):
            field = "简历" if submode == "resume" else "JD"
            return JSONResponse(
                status_code=400,
                content={"error": f"请先上传{field}或粘贴{field}文本"},
            )

        if submode not in _INTERVIEW_SYSTEM_PROMPTS:
            return JSONResponse(status_code=400, content={"error": f"不支持的面试模式: {submode}"})

        session_id = str(uuid.uuid4())[:8]
        # 让持久化 conversation_id 与返回的 session_id 对齐，避免后续轮次历史分裂
        conversation_id = session_id
        try:
            create_conversation(conversation_id, user_id=user_id,
                                title=message[:30] or "新对话", mode=mode)
        except Exception:
            pass
        mode_labels = {
            "resume": "以下是候选人的【简历全文】",
            "project": "以下是候选人参与的【项目描述】",
            "knowledge": "以下是需要考核的【知识点范围】",
            "jd": "以下是目标岗位的【JD 描述】",
        }
        initial_user = f"{mode_labels.get(submode, '素材')}\n\n{content}"
        system = _INTERVIEW_SYSTEM_PROMPTS[submode]

        try:
            llm = _llm()
            resp = llm.invoke([
                SystemMessage(content=system),
                HumanMessage(content=initial_user + "\n\n请开始面试，提出你的第一个问题。"),
            ])
            first_reply = resp.content if isinstance(resp.content, str) else str(resp.content)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"LLM 调用失败: {e}"})

        _interview_sessions[session_id] = {
            "mode": submode,
            "mode_name": {"resume": "简历深挖", "project": "项目拷问", "knowledge": "知识点考核", "jd": "指定JD面试"}.get(submode, submode),
            "system": system,
            "history": [
                {"role": "user", "content": initial_user},
                {"role": "assistant", "content": first_reply},
            ],
            "created_at": time.time(),
            "round": 1,
        }

        _persist_and_remember(conversation_id, user_id, message, first_reply, mode)
        return {
            "reply": first_reply,
            "intent": "interview",
            "session_id": session_id,
            "round": 1,
        }

    # ============ 求职助手模式 ============
    has_resume = bool(req.resume_text and req.resume_text.strip())
    intent = _detect_assistant_intent(message, has_resume)

    # --- 简历匹配 ---
    if intent == "match" and has_resume:
        try:
            # 复用 match_rank 逻辑
            fake_req = ChatRequest(query=req.resume_text[:2000])
            # 召回历史记忆，注入匹配上下文
            recalled = _recall_context(user_id, message)
            result = await _do_match_rank(req.resume_text, message, recalled=recalled)
            _persist_and_remember(conversation_id, user_id, message, result.get("reply", ""), mode)
            return result
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"匹配失败: {e}"})

    # --- 简历诊断 ---
    if intent == "diagnose" and has_resume:
        try:
            llm = _llm()
            recalled = _recall_context(user_id, message)
            recalled_block = ""
            if recalled:
                recalled_block = f"\n\n【用户历史记忆（仅供参考，可结合判断）】\n{recalled}\n"
            diagnose_prompt = f"""请诊断以下简历，从以下维度评估并给出改进建议：
1. 整体印象（1-10分）
2. 亮点
3. 不足
4. 具体改进建议（分条列出）
{recalled_block}
简历内容：
{req.resume_text[:3000]}"""
            resp = llm.invoke([
                SystemMessage(content=_ASSISTANT_SYSTEM),
                HumanMessage(content=diagnose_prompt),
            ])
            reply = resp.content if isinstance(resp.content, str) else str(resp.content)
            _persist_and_remember(conversation_id, user_id, message, reply, mode)
            return {"reply": reply, "intent": "diagnose"}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"诊断失败: {e}"})

    # --- 岗位搜索（默认） ---
    try:
        result = find_jobs(message)
        reply_payload = {
            "reply": result.final_report,
            "intent": "search",
            "filtered_jobs": [
                {
                    "title": j.title,
                    "brand": j.brand_name,
                    "city": j.city,
                    "salary_desc": j.salary_desc,
                    "experience": j.experience_name,
                    "degree": j.degree_name,
                    "skills": j.skills or [],
                    "post_description": j.post_description or "",
                    "url": j.url,
                }
                for j in (result.filtered_jobs or [])
            ],
            "skill_gap": result.skill_gap,
        }
        _persist_and_remember(conversation_id, user_id, message, result.final_report, mode)
        return reply_payload
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"搜索失败: {e}"})


# ------------------------------------------------------------------
# 会话历史（记忆模块的 MySQL 原文存储，供前端按需加载）
# ------------------------------------------------------------------

@app.get("/api/conversations")
async def api_list_conversations(user_id: str = DEFAULT_USER_ID, limit: int = 50):
    """列出某用户的会话（按最近更新倒序）。"""
    try:
        rows = list_conversations(user_id=user_id, limit=limit)
        return {"conversations": rows}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"列出会话失败: {e}"})


@app.get("/api/conversations/{conversation_id}/messages")
async def api_get_messages(conversation_id: str, limit: int = 100):
    """获取某会话的完整消息记录（回放 / 恢复上下文用）。"""
    try:
        rows = get_history(conversation_id, limit=limit)
        return {"conversation_id": conversation_id, "messages": rows}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"读取消息失败: {e}"})


async def _do_match_rank(resume_text: str, query: str, recalled: str = ""):
    """简历匹配内部实现（复用 vector_search_jobs 检索 + LLM 深度匹配）。"""
    from src.agent.tools import vector_search_jobs

    # 用简历文本做向量检索
    try:
        jobs = vector_search_jobs(resume_text, top_k=10)
    except Exception as e:
        return {"reply": f"检索失败：{e}", "intent": "match", "match_results": []}

    if not jobs:
        return {"reply": "未找到匹配岗位，请先采集岗位数据。", "intent": "match", "match_results": []}

    # 取 Top 5 做深度匹配
    match_results = []
    llm = _llm()
    for job in jobs[:5]:
        try:
            jd_text = job.post_description or ""
            if not jd_text:
                continue

            prompt = f"""请分析以下简历与岗位的匹配度，返回 JSON：
{{"match_score": 0-100, "matched_skills": ["技能1"...], "missing_skills": ["技能1"...], "gap_analysis": "简述", "suggestions": ["建议1"...]}}
{('【候选人历史记忆，可辅助判断】\n' + recalled + '\n') if recalled else ''}
简历：
{resume_text[:1500]}

岗位：{job.title} @ {job.brand}
JD：
{jd_text[:1000]}"""
            resp = llm.invoke([HumanMessage(content=prompt)])
            data = _extract_json(resp.content if isinstance(resp.content, str) else str(resp.content))
            if isinstance(data, dict):
                match_results.append({
                    "job_title": job.title,
                    "company": job.brand,
                    "match_score": data.get("match_score", 0),
                    "matched_skills": data.get("matched_skills", []),
                    "missing_skills": data.get("missing_skills", []),
                    "gap_analysis": data.get("gap_analysis", ""),
                    "suggestions": data.get("suggestions", []),
                })
        except Exception:
            continue

    match_results.sort(key=lambda x: x.get("match_score", 0), reverse=True)

    summary = f"根据你的简历，匹配到 {len(match_results)} 个高相关岗位：\n"
    for i, m in enumerate(match_results, 1):
        summary += f"\n{i}. {m['job_title']} @ {m['company']} — 匹配度 {m['match_score']}%\n"
        if m["matched_skills"]:
            summary += f"   ✅ 匹配技能: {', '.join(m['matched_skills'][:5])}\n"
        if m["missing_skills"]:
            summary += f"   ❌ 缺失技能: {', '.join(m['missing_skills'][:5])}\n"

    return {
        "reply": summary,
        "intent": "match",
        "match_results": match_results,
    }


# ------------------------------------------------------------------
# 启动
# ------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
