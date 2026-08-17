"""SSE 端到端探针：验证 unified/stream 的 step 事件 + 真流式 content。

用法: python sse_probe.py
逐路径打印事件序列与首/末 content 时间差，判断是否为真流式。
"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8002/api/chat/unified/stream"

DUMMY_RESUME = """张三 | 高级 Python 工程师
技能: Python, FastAPI, LangChain, RAG, MySQL, Redis
项目: 搭建企业知识库问答系统，使用 LangChain + 向量检索，QPS 200，准确率 92%
教育: 本科 计算机科学
经验: 5 年后端开发"""


def run(label, payload, max_chars=400):
    payload = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    t0 = time.time()
    first_content_t = None
    last_content_t = None
    n_content = 0
    step_count = 0
    intent = None
    done_ok = False
    err = None
    print(f"\n========== {label} ==========")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            for raw in r:
                line = raw.decode().strip()
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                et = ev.get("type")
                now = round(time.time() - t0, 3)
                if et == "intent":
                    intent = ev.get("intent")
                    print(f"  [{now}s] intent={intent}")
                elif et == "step":
                    step_count += 1
                    st = ev.get("status")
                    lb = ev.get("label")
                    dt = ev.get("detail", "")
                    print(f"  [{now}s] step[{st}] {lb} {dt}")
                elif et == "content":
                    n_content += 1
                    if first_content_t is None:
                        first_content_t = now
                    last_content_t = now
                elif et == "done":
                    done_ok = True
                    d = ev.get("data", {})
                    extra = ""
                    if "match_results" in d:
                        extra = f" match_results={len(d['match_results'])}"
                    if "filtered_jobs" in d:
                        extra = f" jobs={len(d.get('filtered_jobs', []))}"
                    print(f"  [{now}s] done intent={d.get('intent')}{extra}")
                elif et == "error":
                    err = ev.get("message")
                    print(f"  [{now}s] ERROR {err}")
    except Exception as e:
        err = f"REQ FAIL: {e}"
        print(f"  REQ FAIL {e}")
    span = (round(last_content_t - first_content_t, 3) if (first_content_t and last_content_t) else 0)
    print(f"  >> intent={intent} steps={step_count} content_chunks={n_content} "
          f"first_content={first_content_t}s last_content={last_content_t}s span={span}s done={done_ok} err={err}")
    verdict = "TRUE-STREAM" if (n_content > 1 and span >= 0.3) else ("SINGLE-SHOT" if n_content > 0 else "NO-CONTENT")
    print(f"  >> VERDICT: {verdict}")


if __name__ == "__main__":
    # 1. 搜索（默认助手）
    run("SEARCH", {"message": "杭州 LangChain 开发", "mode": "assistant"})
    # 2. 面试-知识点（无需简历）
    run("INTERVIEW/knowledge", {"message": "请对 RAG 知识点开始面试", "mode": "interviewer", "interview_submode": "knowledge"})
    # 3. 简历诊断（需简历）
    run("DIAGNOSE", {"message": "诊断我的简历", "mode": "assistant", "resume_text": DUMMY_RESUME})
    # 4. 简历匹配（需简历）
    run("MATCH", {"message": "和这些岗位匹配度如何", "mode": "assistant", "resume_text": DUMMY_RESUME})
