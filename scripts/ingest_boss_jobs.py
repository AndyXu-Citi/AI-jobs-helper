"""
P3：把 BossSource 抓到的岗位入库到 final_results。

为什么不走完整流水线（监控 → 采集 → 清洗）？
- Boss 搜索 API 本身就返回结构化数据（jobName/salaryDesc/skills/jobLabels/boss）
- 不需要再爬一遍 HTML，也不需要 LLM 清洗
- 把数据按 v2.1 的 structured_json 契约 shim 一下，直接落库

落库后：
- scripts/index_final_results.py  → 索引到向量库（零修改）
- scripts/search.py               → 自然语言查询（零修改）

用法：
    python scripts/ingest_boss_jobs.py
    python scripts/ingest_boss_jobs.py --cities 杭州,苏州 --keywords AI应用开发
    python scripts/ingest_boss_jobs.py --pages 2     # 每个查询抓 2 页

断点续传（海量抓取必备）：
    python scripts/ingest_boss_jobs.py                # 首次跑，进度存 data/boss_checkpoint.json
    python scripts/ingest_boss_jobs.py                # 中断后重跑，自动跳过已完成项
    python scripts/ingest_boss_jobs.py --no-resume   # 强制全部重抓

反爬节奏（默认 2~5s 随机延迟 + code37 长冷却，已够稳；封得狠就调大）：
    python scripts/ingest_boss_jobs.py --min-delay 5 --max-delay 10 --max-retries 5
"""
from __future__ import annotations

import os

# macOS OpenMP 双库冲突 escape hatch（必须在 import numpy/faiss/milvus 前设置）
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db_manager import DBManager
from src.sources.boss_zhipin import BossSource, BossJob

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


DEFAULT_CITIES = ["上海"]
DEFAULT_KEYWORDS = ["Agent"]

# 断点续传文件：记录已成功抓取的 (城市|关键词|页码)，重跑自动跳过
CHECKPOINT_PATH = PROJECT_ROOT / "data" / "boss_checkpoint.json"


def boss_job_to_structured(job: BossJob) -> dict:
    """
    把 BossJob 转成 v2.1 structured_json 契约的 dict。

    映射规则（让索引脚本 build_embed_text 拼出来的语义最强）：
      title       = jobName                 ← 标题最重要
      summary     = 自然语言一句话总结      ← 让 embedding 抓到薪资+城市+经验
      key_points  = jobLabels（经验/学历）  ← 已经是结构化要点
      tags        = skills + 关键词 + 城市  ← 检索时用得上
    """
    summary_parts = [
        f"{job.city}地区",
        f"职位「{job.job_name}」",
        f"薪资 {job.salary_desc}",
    ]
    if job.job_labels:
        summary_parts.append("要求：" + " / ".join(job.job_labels))
    if job.boss_title:
        summary_parts.append(f"发布人：{job.boss_name}（{job.boss_title}）")

    tags: list[str] = list(job.skills)
    if job.keyword and job.keyword not in tags:
        tags.append(job.keyword)
    if job.city and job.city not in tags:
        tags.append(job.city)

    return {
        "title": job.job_name,
        "summary": "，".join(summary_parts) + "。",
        "key_points": list(job.job_labels),
        "tags": tags,
        # Boss 专属富字段（不影响 v2.1 build_embed_text，下游 Agent 可用）
        "_boss": {
            "salary_desc": job.salary_desc,
            "city": job.city,
            "keyword": job.keyword,
            "skills": list(job.skills),
            "boss_name": job.boss_name,
            "boss_title": job.boss_title,
            "boss_cert": job.boss_cert,
            "encrypt_job_id": job.encrypt_job_id,
            # 详情 API 所需配对参数（P4' enrich 时使用）
            "security_id": job.raw.get("securityId", ""),
            "lid": job.raw.get("lid", ""),
        },
    }


async def ingest(
    cities: list[str],
    keywords: list[str],
    pages_per_query: int,
    min_delay: float = 2.0,
    max_delay: float = 5.0,
    max_retries: int = 3,
    checkpoint_path=None,
    resume: bool = True,
) -> tuple[int, int, int]:
    """返回 (抓到, 新入库, 已存在跳过)。

    支持断点续传：已成功的 (城市|关键词|页码) 写入 checkpoint 文件，重跑时
    自动跳过，Ctrl-C 不丢数据——适合"海量"分多次跑。
    """
    if checkpoint_path is None:
        checkpoint_path = CHECKPOINT_PATH
    checkpoint_path = Path(checkpoint_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    # 断点续传：已完成的查询集合
    done_set: set[str] = set()
    if resume and checkpoint_path.exists():
        try:
            done_set = set(json.loads(checkpoint_path.read_text(encoding="utf-8")))
            logger.info(f"断点续传：已加载 {len(done_set)} 个已完成查询，将自动跳过")
        except Exception as e:
            logger.warning(f"读取断点文件失败，将从头开始: {e}")
            done_set = set()

    def _key(c, k, p):
        return f"{c}|{k}|{p}"

    def _skip(c, k, p):
        return _key(c, k, p) in done_set

    def _on_done(c, k, p, jobs):
        # 只有成功的查询才会回调 → 失败的会在重跑时自动重试
        done_set.add(_key(c, k, p))
        try:
            checkpoint_path.write_text(
                json.dumps(sorted(done_set), ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"写入断点文件失败: {e}")

    db = DBManager()

    src = BossSource(
        cities=cities,
        keywords=keywords,
        pages_per_query=pages_per_query,
        filter_noise=True,
        min_delay=min_delay,
        max_delay=max_delay,
        max_retries=max_retries,
    )

    total = len(cities) * len(keywords) * pages_per_query
    logger.info(
        f"开始抓取 {len(cities)} 城市 × {len(keywords)} 关键词 × {pages_per_query} 页 "
        f"（共 {total} 个查询，断点续传将跳过 {len(done_set)} 个已完成）..."
    )
    jobs = await src.fetch_jobs_structured(
        progress_callback=_on_done,
        skip_predicate=_skip if resume else None,
    )
    logger.info(f"BossSource 共返回 {len(jobs)} 条去噪岗位")

    # 同一 url 在本批中可能重复（同一岗位被多个关键词同时召回）—— 先去重
    seen, unique_jobs = set(), []
    for j in jobs:
        if j.url in seen:
            continue
        seen.add(j.url)
        unique_jobs.append(j)
    logger.info(f"批内去重后 {len(unique_jobs)} 条唯一 URL")

    # 1) URL 入 task_queue（v2.1 流水线惯例：先有 task，再有 final_result）
    urls = [j.url for j in unique_jobs]
    added_to_queue = db.add_new_urls(urls, source_type="boss_zhipin")
    logger.info(f"task_queue 新增 {added_to_queue} 条（{len(urls) - added_to_queue} 条已存在）")

    # 2) 直接写 final_results（跳过 collector + processor，因为 Boss API 已结构化）
    saved = 0
    skipped_already_in_results = 0

    # 查一遍 final_results 已有的 url，避免重复写入
    from src.db_config import get_connection

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT url FROM final_results WHERE source_type = 'boss_zhipin'"
        )
        existing = {row["url"] for row in cursor.fetchall()}
    finally:
        conn.close()

    for job in unique_jobs:
        if job.url in existing:
            skipped_already_in_results += 1
            continue
        structured = boss_job_to_structured(job)
        db.save_final_result(
            url=job.url,
            json_data=json.dumps(structured, ensure_ascii=False),
            source_type="boss_zhipin",
        )
        saved += 1

    return len(unique_jobs), saved, skipped_already_in_results


def main():
    ap = argparse.ArgumentParser(description="抓 Boss 岗位 → final_results")
    ap.add_argument(
        "--cities",
        default=",".join(DEFAULT_CITIES),
        help=f"逗号分隔；默认 {DEFAULT_CITIES}",
    )
    ap.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help=f"逗号分隔；默认 {DEFAULT_KEYWORDS}",
    )
    ap.add_argument("--pages", type=int, default=1, help="每个查询抓几页（默认 1）")
    ap.add_argument(
        "--min-delay", type=float, default=2.0,
        help="每次查询间的随机延迟下限（秒，默认 2.0）",
    )
    ap.add_argument(
        "--max-delay", type=float, default=5.0,
        help="每次查询间的随机延迟上限（秒，默认 5.0）",
    )
    ap.add_argument(
        "--max-retries", type=int, default=3,
        help="单查询最大重试次数（默认 3）",
    )
    ap.add_argument(
        "--no-resume", action="store_true",
        help="忽略断点文件，强制全部重抓",
    )
    ap.add_argument(
        "--checkpoint", default=None,
        help="断点文件路径（默认 data/boss_checkpoint.json）",
    )
    args = ap.parse_args()

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    fetched, saved, skipped = asyncio.run(ingest(
        cities, keywords, args.pages,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        max_retries=args.max_retries,
        checkpoint_path=args.checkpoint,
        resume=not args.no_resume,
    ))

    print()
    print("=" * 70)
    print(f"[完成] 抓取去噪 {fetched} 条 / 新入库 {saved} 条 / 已存在跳过 {skipped} 条")
    print("=" * 70)
    print()
    print("下一步：")
    print("  python scripts/index_final_results.py   # 把新岗位喂给 bge-m3 + Milvus")
    print('  python scripts/search.py "薪资 20K+ 要 LangChain 的 AI 应用岗"')


if __name__ == "__main__":
    main()
