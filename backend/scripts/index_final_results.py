"""
批量索引脚本：从 SQLite final_results → embed → 写入 Milvus Lite。

用法：
    python scripts/index_final_results.py                 # 索引全部
    python scripts/index_final_results.py --limit 10      # 只索引前 10 条
    python scripts/index_final_results.py --rebuild       # 重建（删旧 db 后全量索引）

设计：
- 幂等：同一 url 二次跑会覆盖（VectorStore.upsert 内部按 url 去重）
- 容错：单条 embed 失败只打日志、跳过，不中断整批
- 进度可见：每条打印 [N/M] url，方便看到 embedding 推理节奏
"""
from __future__ import annotations

import os

# macOS OpenMP 双库冲突 escape hatch（必须在 import numpy/faiss/milvus 前设置）
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# 让脚本能 import src.* —— 兼容直接 python scripts/xxx.py 跑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.embedder import HuggingFaceEmbedder
from src.rag.vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


VECTOR_DB_PATH = PROJECT_ROOT / "data" / "vector.db"


# 送 embedding 的文本上限：bge-m3 约 8192 token，正文截断到这里避免模型侧截断
MAX_BODY_CHARS = 4000
# 单块字符上限与块间重叠（长 JD 分块，重叠保留语义连续）
CHUNK_SIZE = 3000
CHUNK_OVERLAP = 300


def build_embed_text(structured: dict) -> str:
    """
    把 structured_json 拼成送 embed 的文本。

    优化点（相对旧版）：
    - U1 修复：纳入 JD 正文 post_description（旧版完全没进向量，只到摘要级）
    - 字段加权：标题 > 城市/薪资 > 技能 > 简介 > 要点 > 标签 > 正文
    - 每段换行分隔，让模型看到字段边界

    Boss 记录结构：top-level 有 title/summary/key_points/tags，
    _boss 下有 city/salary_desc/skills/detail_labels/post_description。
    """
    boss = structured.get("_boss", {}) or {}
    parts: list[str] = []

    title = structured.get("title") or ""
    if title:
        parts.append(f"标题：{title}")

    city = boss.get("city") or ""
    if city:
        parts.append(f"城市：{city}")

    salary = boss.get("salary_desc") or ""
    if salary:
        parts.append(f"薪资：{salary}")

    # 技能：Boss 官方标签 + 详情标签（与 /api/report / 技能差距统计口径一致）
    skills = list(boss.get("skills") or []) + list(boss.get("detail_labels") or [])
    skills = [s for s in skills if s]
    if skills:
        parts.append("技能：" + "、".join(skills))

    summary = structured.get("summary") or ""
    if summary:
        parts.append(f"简介：{summary}")

    key_points = structured.get("key_points") or []
    if isinstance(key_points, list) and key_points:
        parts.append("要点：" + "；".join(str(kp) for kp in key_points))

    tags = structured.get("tags") or []
    if isinstance(tags, list) and tags:
        parts.append("标签：" + "、".join(str(t) for t in tags))

    body = boss.get("post_description") or ""
    if body:
        body = body.strip()
        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS]
        parts.append("正文：" + body)

    return "\n".join(parts).strip()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """长文本滑动窗口分块；未超上限则整段返回（单块）。"""
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(1, size - overlap)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + size])
        if start + size >= len(text):
            break
        start += step
    return chunks



def load_final_results(limit: int | None) -> list[tuple[str, str, dict]]:
    """从 MySQL 加载所有 final_results，返回 [(url, source_type, parsed_json), ...]。"""
    from src.db_config import get_connection

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        sql = "SELECT url, source_type, structured_json FROM final_results ORDER BY id"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cursor.execute(sql)
        rows = cursor.fetchall()
    finally:
        conn.close()

    out = []
    for row in rows:
        try:
            parsed = json.loads(row["structured_json"]) if row["structured_json"] else {}
        except json.JSONDecodeError as e:
            logger.warning(f"[parse] {row['url']}: structured_json 解析失败，跳过 ({e})")
            continue
        out.append((row["url"], row["source_type"] or "bilibili", parsed))
    return out


def main():
    ap = argparse.ArgumentParser(description="批量索引 final_results 到向量库")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 条（调试用）")
    ap.add_argument("--rebuild", action="store_true",
                    help="重建：删旧 vector.db 后全量索引")
    args = ap.parse_args()

    # FAISS 索引文件路径（.faiss + .pkl）；Milvus 模式下这些文件不存在，删除无害
    faiss_path = VECTOR_DB_PATH.with_suffix(".faiss")
    pkl_path = VECTOR_DB_PATH.with_suffix(".pkl")

    VECTOR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    embedder = HuggingFaceEmbedder()
    store = VectorStore(db_path=str(VECTOR_DB_PATH))

    if args.rebuild:
        # 清空重建（Milvus: drop+recreate collection；FAISS: 删文件）
        store.rebuild()
        logger.info("[rebuild] 已清空向量库")

    logger.info("[load] 从 MySQL 读 final_results...")
    records = load_final_results(args.limit)
    total = len(records)
    logger.info(f"[load] 共 {total} 条待索引")

    if total == 0:
        logger.warning("没有数据可索引，退出")
        return

    ok, skipped, failed, chunked = 0, 0, 0, 0
    for i, (url, source_type, structured) in enumerate(records, 1):
        text = build_embed_text(structured)
        if not text:
            logger.warning(f"[{i}/{total}] 跳过（拼接文本为空）: {url}")
            skipped += 1
            continue

        # 长文本分块（多数 JD 不超上限，单块）
        chunks = chunk_text(text)
        try:
            vecs = [embedder.embed_one(c) for c in chunks]
        except Exception as e:
            logger.error(f"[{i}/{total}] embed 失败: {url} | {e}")
            failed += 1
            continue

        city = (structured.get("_boss", {}) or {}).get("city", "") or ""
        try:
            store.upsert_chunks(
                url=url,
                source_type=source_type,
                title=structured.get("title") or "(无标题)",
                chunks=list(zip(chunks, vecs)),
                city=city,
                created_at=int(time.time()),
            )
            ok += 1
            if len(chunks) > 1:
                chunked += 1
                logger.info(f"[{i}/{total}] [OK] {source_type} | "
                            f"{(structured.get('title') or url)[:50]} | {len(chunks)} 块")
            else:
                logger.info(f"[{i}/{total}] [OK] {source_type} | "
                            f"{(structured.get('title') or url)[:60]}")
        except Exception as e:
            logger.error(f"[{i}/{total}] upsert 失败: {url} | {e}")
            failed += 1

    # 批量写入后 flush，使 count/search 立即可见
    store.flush()

    logger.info("=" * 60)
    logger.info(f"索引完成：成功 {ok} / 跳过 {skipped} / 失败 {failed} / 分块 {chunked} / 总计 {total}")
    logger.info(f"向量库：{store.collection}（{'Milvus' if store._use_milvus else 'FAISS'}）")


if __name__ == "__main__":
    main()
