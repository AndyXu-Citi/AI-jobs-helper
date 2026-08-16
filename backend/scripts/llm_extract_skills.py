"""
用 LLM 从 JD 正文批量提取技能关键词，结果缓存在 MySQL _boss.skills_extracted 中。

设计：
- 只会处理还没有 skills_extracted 的 JD
- 每次 8 条批量调用 LLM，避免逐条调浪费 token
- 幂等：重复运行只处理新 JD

用法：
    python scripts/llm_extract_skills.py              # 提取全部未处理的
    python scripts/llm_extract_skills.py --force      # 重新提取全部
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db_config import get_connection
from src.agent.nodes import _llm, _extract_json
from langchain_core.messages import HumanMessage, SystemMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 8


def load_jds(force: bool = False) -> list[dict]:
    """从 MySQL 加载未提取或全部 JD。返回 [{"id": int, "title": str, "desc": str, "structured": dict}, ...]。"""
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, structured_json FROM final_results "
            "WHERE source_type = 'boss_zhipin' ORDER BY id"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    for r in rows:
        try:
            s = json.loads(r["structured_json"])
        except json.JSONDecodeError:
            continue
        b = s.get("_boss") or {}
        if not force and b.get("skills_extracted"):
            continue
        desc = (b.get("post_description") or "").strip()
        if not desc:
            continue
        out.append({
            "id": r["id"],
            "title": (s.get("title") or "").strip(),
            "desc": desc,
            "structured": s,
        })
    return out


def _parse_llm_array(raw: str) -> list | None:
    """从 LLM 响应中解析 JSON 数组，容忍 ```json``` 包裹。"""
    import re
    # 1) 剥代码块 ```json [...] ```
    m = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", raw, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # 2) 直接找第一个 [ ... ]
    m = re.search(r"(\[[\s\S]*\])", raw, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    return None


def _extract_batch(batch: list[dict]) -> list[list[str]]:
    """调一次 LLM 提取一批技能。返回每个 JD 的技能列表。"""
    prompt_lines = [
        "从以下每条 JD 中提取**技术关键词**（编程语言、框架、工具、平台、技术概念）。\n"
        "每条输出一个 JSON 字符串数组，最终输出外层 JSON 数组（数组的数组）。\n"
        "只输出 JSON，不要任何解释，不要用 ```markdown``` 包裹。\n",
    ]
    for idx, jd in enumerate(batch):
        text = f"【JD {idx + 1}】{jd['title']}\n{jd['desc'][:2000]}"
        prompt_lines.append(f"\n---\n{text}")

    prompt_lines.append(
        '\n\n请输出 JSON 格式（数组的数组），例如：\n'
        '[["Python","Django"],["Java","Spring","MySQL"]]'
    )

    llm = _llm()
    resp = llm.invoke([
        SystemMessage(content="你是一个精准的技能提取器。只从 JD 文本中提取明确提到的技术关键词，不要臆测。"),
        HumanMessage(content="\n".join(prompt_lines)),
    ])
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    parsed = _parse_llm_array(raw)
    if not isinstance(parsed, list):
        raise ValueError(f"LLM 返回的不是数组: {raw[:200]}")

    results: list[list[str]] = []
    for item in parsed:
        if not isinstance(item, list):
            results.append([])
        else:
            results.append([s.strip() for s in item if isinstance(s, str) and s.strip()])
    return results


def write_back(batch: list[dict], all_skills: list[list[str]]) -> int:
    """把提取结果写回 MySQL。返回成功条数。"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        ok = 0
        for jd, skills in zip(batch, all_skills):
            if not skills:
                continue
            jd["structured"].setdefault("_boss", {})["skills_extracted"] = skills
            cursor.execute(
                "UPDATE final_results SET structured_json = %s WHERE id = %s",
                (json.dumps(jd["structured"], ensure_ascii=False), jd["id"]),
            )
            ok += 1
        conn.commit()
    finally:
        conn.close()
    return ok


def main():
    import argparse

    ap = argparse.ArgumentParser(description="用 LLM 从 JD 正文提取技能关键词")
    ap.add_argument("--force", action="store_true", help="重新提取全部")
    args = ap.parse_args()

    jds = load_jds(force=args.force)
    if not jds:
        logger.info("没有需要提取的 JD（全部已缓存或缺少正文）")
        return

    total = len(jds)
    logger.info(f"待提取技能: {total} 条")
    ok = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch = jds[batch_start:batch_start + BATCH_SIZE]
        batch_no = batch_start // BATCH_SIZE + 1
        total_batches = (total - 1) // BATCH_SIZE + 1

        try:
            all_skills = _extract_batch(batch)
            n = write_back(batch, all_skills)
            ok += n
            logger.info(f"[batch {batch_no}/{total_batches}] +{n} OK")
        except Exception as e:
            logger.warning(f"[batch {batch_no}/{total_batches}] 失败: {e}")

    logger.info(f"完成: {ok}/{total}")


if __name__ == "__main__":
    main()
