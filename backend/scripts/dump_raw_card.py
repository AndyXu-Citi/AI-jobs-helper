"""
一次性工具：把 /wapi/zpgeek/job/card.json（岗位详情卡片接口，enrich 用的那个）
的【完整原始响应】落盘，用于对比 structured_json._boss 与原始 Boss 详情 API
的字段差异。

前置条件
--------
用户已用以下参数启动 Chrome，并**手动扫码登录 m.zhipin.com**，且保持该
标签页/窗口一直开着（cookie 持久化在独立 profile 里）：

    chrome.exe --remote-debugging-port=9222 \
        --user-data-dir="%USERPROFILE%\\.hermes\\chrome-debug-profile"

用法
----
    # 默认：自动从 SQLite 取第一条含 security_id/lid 的 Boss 岗位来 dump
    python scripts/dump_raw_card.py

    # 显式指定配对参数
    python scripts/dump_raw_card.py --security-id "xxxxx" --lid "5lS9..."

    # 指定输出路径 / CDP 端口
    python scripts/dump_raw_card.py --out data/boss_card_sample.json \
        --cdp-url http://127.0.0.1:9222

说明
----
- card 接口靠 securityId + lid 配对，二者来自搜索 API 返回的 jobList[*]，
  已存入 final_results.structured_json._boss.security_id / .lid。
- 本脚本只负责"抓一条完整 raw 落盘 + 打印概要"，不做任何字段投影/裁剪。
- 若 jobCard 为空（未登录 / securityId+lid 失效 / 被风控），原始响应也会
  原样写入文件，方便排查。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 复用项目常量，避免硬编码 URL / CDP 端口
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from src.sources.boss_zhipin import (
    ZHIPIN_BASE,
    DETAIL_API_PATH,
    DEFAULT_CDP_URL,
)

import urllib.parse
from playwright.async_api import async_playwright

def pick_pair_from_db(only_url: str | None = None):
    """从 MySQL 取一条有效的 (url, security_id, lid)。

    - 若 only_url 给定，只在该 url 的记录里找；
    - 否则返回第一条含非空 security_id + lid 的 Boss 岗位。
    """
    from src.db_config import get_connection

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        if only_url:
            cursor.execute(
                "SELECT url, structured_json FROM final_results "
                "WHERE source_type='boss_zhipin' AND url=%s",
                (only_url,),
            )
        else:
            cursor.execute(
                "SELECT url, structured_json FROM final_results "
                "WHERE source_type='boss_zhipin'"
            )
        rows = cursor.fetchall()
    finally:
        conn.close()

    for row in rows:
        try:
            s = json.loads(row["structured_json"])
        except Exception:
            continue
        boss = s.get("_boss", {})
        sid = (boss.get("security_id") or "").strip()
        lid = (boss.get("lid") or "").strip()
        if sid and lid:
            return row["url"], sid, lid
    return None, None, None


async def dump_card(security_id: str, lid: str,
                    cdp_url: str, out_path: Path) -> None:
    api_url = (
        f"{ZHIPIN_BASE}{DETAIL_API_PATH}"
        f"?securityId={urllib.parse.quote(security_id)}"
        f"&lid={urllib.parse.quote(lid)}"
    )
    print(f"[dump] GET {api_url}")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            raise SystemExit(
                f"无法连接 CDP 端口 {cdp_url}：{e}\n"
                f"请确认已用 --remote-debugging-port=9222 启动 Chrome "
                f"并手动扫码登录 m.zhipin.com。"
            )

        # 复用已登录的默认上下文（cookie 都在里面）
        context = (
            browser.contexts[0]
            if browser.contexts
            else await browser.new_context()
        )
        page = await context.new_page()
        await page.goto(
            "https://m.zhipin.com",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        try:
            await page.wait_for_load_state("load", timeout=10000)
        except Exception:
            pass

        response = await page.request.fetch(
            api_url,
            method="GET",
            timeout=30000,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://m.zhipin.com/",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        print(f"[dump] HTTP {response.status}")
        result = await response.json()

    # 关键：原样落盘完整原始响应，不做任何投影/裁剪
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 概要：让你立刻看到 raw 的真实结构与字段差异
    code = result.get("code")
    msg = result.get("message")
    card = result.get("zpData", {}).get("jobCard", {}) or {}
    print(f"[dump] code={code} message={msg} jobCard 字段数={len(card)}")
    if card:
        print("       字段: " + ", ".join(sorted(card.keys())))
        pd = card.get("postDescription", "")
        print(f"[dump] postDescription 字数={len(pd)}")
        print(f"[dump] 完整响应已写入: {out_path}")
    else:
        print(f"[dump] ⚠️ jobCard 为空，可能未登录 / securityId+lid 失效 / 被风控。"
              f"原始响应已原样写入: {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="抓取并落盘 Boss job/card.json 的完整原始响应"
    )
    ap.add_argument("--security-id", default=None, help="详情接口 securityId（不填则自动从库取）")
    ap.add_argument("--lid", default=None, help="详情接口 lid（不填则自动从库取）")
    ap.add_argument(
        "--url", default=None,
        help="指定从某条 final_results 记录取 security_id/lid（需在库中存在）",
    )
    ap.add_argument(
        "--cdp-url", default=DEFAULT_CDP_URL,
        help="Chrome CDP 调试端口（默认 http://127.0.0.1:9222）",
    )
    ap.add_argument(
        "--out", default=str(PROJECT_ROOT / "data" / "boss_card_sample.json"),
        help="原始响应输出路径",
    )
    args = ap.parse_args()

    # 决定 security_id / lid 来源
    if args.security_id and args.lid:
        url, sid, lid = "(cli)", args.security_id, args.lid
    else:
        url, sid, lid = pick_pair_from_db(only_url=args.url)

    if not sid or not lid:
        raise SystemExit(
            "未能从 SQLite 取到有效的 security_id/lid 配对。"
            "请先用 scripts/ingest_boss_jobs.py 采集过岗位（它们会写入 _boss.security_id/lid），"
            "或用 --security-id / --lid 显式指定。"
        )
    print(f"[dump] 使用配对 url={url}  security_id={sid[:24]}... lid={lid}")
    asyncio.run(dump_card(sid, lid, args.cdp_url, args.out))


if __name__ == "__main__":
    main()
