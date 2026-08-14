"""
一次性工具：把 /wapi/zpgeek/search/joblist.json 的【完整原始响应】落盘，
用于对比 structured_json 与原始 Boss API 响应的字段差异。

前置条件
--------
用户已用以下参数启动 Chrome，并**手动扫码登录 m.zhipin.com**，且保持该
标签页/窗口一直开着（cookie 持久化在独立 profile 里）：

    chrome.exe --remote-debugging-port=9222 \
        --user-data-dir="%USERPROFILE%\\.hermes\\chrome-debug-profile"

用法
----
    python scripts/dump_raw_joblist.py
    python scripts/dump_raw_joblist.py --city 杭州 --keyword "AI应用开发" --page 1
    python scripts/dump_raw_joblist.py --cdp-url http://127.0.0.1:9222 \
        --out data/boss_raw_sample.json

说明
----
- 本脚本只负责"抓一条完整 raw 落盘 + 打印概要"，不做任何字段投影/裁剪，
  方便你直接拿去和 SQLite 里的 structured_json 逐字段比对。
- 若 jobList 为空（未登录 / 被风控），原始响应（code/message/zpData）也会
  原样写入文件，方便排查。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 复用项目常量，避免硬编码城市 code / URL / headers
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from src.sources.boss_zhipin import (
    ZHIPIN_BASE,
    SEARCH_API_PATH,
    CITY_CODES,
    DEFAULT_CDP_URL,
)

import urllib.parse
from playwright.async_api import async_playwright


async def dump_raw(city: str, keyword: str, page_num: int,
                   cdp_url: str, out_path: Path) -> None:
    if city not in CITY_CODES:
        raise SystemExit(
            f"未知城市 {city!r}，可选: {list(CITY_CODES.keys())}"
        )
    city_code = CITY_CODES[city]
    api_url = (
        f"{ZHIPIN_BASE}{SEARCH_API_PATH}"
        f"?query={urllib.parse.quote(keyword)}"
        f"&city={city_code}&page={page_num}"
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

    # 概要：让你立刻看到 raw 的真实结构
    code = result.get("code")
    msg = result.get("message")
    zp = result.get("zpData", {})
    job_list = zp.get("jobList", []) if isinstance(zp, dict) else []
    print(f"[dump] code={code} message={msg} jobList 条数={len(job_list)}")
    if job_list:
        first = job_list[0]
        print(f"[dump] 单条 jobList 原始字段({len(first)}个):")
        print("       " + ", ".join(sorted(first.keys())))
        print(f"[dump] 完整响应已写入: {out_path}")
    else:
        print(f"[dump] ⚠️ jobList 为空，可能未登录/被风控。"
              f"原始响应已原样写入: {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="抓取并落盘 Boss joblist.json 的完整原始响应"
    )
    ap.add_argument("--city", default="杭州", help="城市名（需在 CITY_CODES 内）")
    ap.add_argument("--keyword", default="AI应用开发", help="搜索关键词")
    ap.add_argument("--page", type=int, default=1, help="页码（默认 1）")
    ap.add_argument(
        "--cdp-url", default=DEFAULT_CDP_URL,
        help="Chrome CDP 调试端口（默认 http://127.0.0.1:9222）",
    )
    ap.add_argument(
        "--out", default=str(PROJECT_ROOT / "data" / "boss_raw_sample.json"),
        help="原始响应输出路径",
    )
    args = ap.parse_args()
    asyncio.run(
        dump_raw(args.city, args.keyword, args.page, args.cdp_url, args.out)
    )


if __name__ == "__main__":
    main()
