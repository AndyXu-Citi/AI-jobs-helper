import json
import sys
import urllib.request

url = "http://127.0.0.1:8001/api/chat/unified/stream"
body = json.dumps({
    "message": "请针对 Python 知识点开始面试",
    "mode": "interviewer",
    "interview_submode": "knowledge",
    "skill_topic": "Python"
}, ensure_ascii=False).encode()

req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        print(f"STATUS {resp.status}")
        for line in resp:
            line = line.decode().strip()
            print(f"RAW | {line[:200]}")
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    continue
                try:
                    obj = json.loads(data)
                    t = obj.get("type")
                    if t == "step":
                        print(f"STEP  {obj['status']:7} | {obj['label']} | {obj.get('detail', '')}")
                    elif t == "content":
                        d = obj.get("delta", "")
                        print(f"CONTENT | {repr(d)}")
                    elif t == "done":
                        print(f"DONE | reply_len={len(obj.get('data', {}).get('reply', ''))}")
                    elif t == "error":
                        print(f"ERROR | {obj.get('message')}")
                    else:
                        print(f"OTHER | {obj}")
                except Exception as e:
                    print(f"PARSE_ERR | {data} | {e}")
except Exception as e:
    print(f"REQUEST_ERR | {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
