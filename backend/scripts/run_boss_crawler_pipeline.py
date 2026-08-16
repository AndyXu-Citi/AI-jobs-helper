#!/usr/bin/env python3
"""
Boss 直聘一键采集流水线：ingest -> enrich -> extract_skills -> index -> (可选) 冒烟测试

用法示例：
    python run_boss_pipeline.py
    python run_boss_pipeline.py --cities 杭州,苏州 --keywords AI应用开发,大模型 --pages 2
    python run_boss_pipeline.py --skip-enrich              # 只抓列表 + 提取技能 + 索引
    python run_boss_pipeline.py --skip-extract-skills      # 跳过 LLM 技能提取（不调 LLM）
    python run_boss_pipeline.py --force-extract            # 强制重新提取全部 JD 的技能
    python run_boss_pipeline.py --no-rebuild               # 索引时不重建向量库
    python run_boss_pipeline.py --smoke-test "杭州 AI 应用开发"  # 最后跑一条检索验证

前置要求（脚本会做预检）：
    1. backend/.env 已配置 MySQL（必用）
    2. 若运行 extract_skills 步骤（默认会），backend/.env 还需 LLM_API_KEY/LLM_API_BASE/LLM_MODEL
       （可用 DeepSeek 等 OpenAI 兼容端点；可用 --skip-extract-skills 跳过该步骤）
    3. Chrome 已用 --remote-debugging-port=9222 启动并登录 m.zhipin.com
    4. .venv 已安装依赖（脚本会自动使用 .venv 里的 Python）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Sequence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_CDP_URL = "http://127.0.0.1:9222"


def find_venv_python(start: Path) -> Path:
    """从 start 目录向上查找 .venv 里的 Python（仓库根或 backend 均可），找不到则退回当前 Python。"""
    for d in [start, *start.parents]:
        for cand in (d / ".venv" / "Scripts" / "python.exe",  # Windows
                     d / ".venv" / "bin" / "python"):          # Linux / macOS
            if cand.exists():
                return cand
    return Path(sys.executable)


def run_cmd(step_no: int, total: int, label: str, name: str,
            cmd: Sequence[str], cwd: Path, env: dict) -> float:
    """运行单条命令，失败时直接退出整个流水线。

    返回耗时（秒）。打印醒目的「开始 / 结束」横幅，使每一步的起止一目了然，
    即便子进程刷了大量进度日志也能清楚看到该步何时跑完。
    """
    bar = "═" * 70
    logger.info(bar)
    logger.info(f"▶ STEP {step_no}/{total} · {label}")
    logger.info(f"  命令: {' '.join(str(c) for c in cmd)}")
    logger.info(bar)
    start = time.time()
    result = subprocess.run(
        [str(c) for c in cmd],
        cwd=cwd,
        env=env,
        stdout=None,
        stderr=None,
    )
    elapsed = time.time() - start
    if result.returncode != 0:
        logger.error(bar)
        logger.error(f"✖ STEP {step_no}/{total} · {label} 失败（退出码 {result.returncode}，耗时 {elapsed:.1f}s）")
        logger.error(bar)
        sys.exit(result.returncode)
    logger.info(bar)
    logger.info(f"✔ STEP {step_no}/{total} · {label} 完成（耗时 {elapsed:.1f}s）")
    logger.info(bar)
    return elapsed


def check_dotenv(backend: Path) -> bool:
    env_file = backend / ".env"
    if not env_file.exists():
        logger.error(f"backend/.env 不存在: {env_file}")
        logger.error("请复制 backend/.env.example 并填写 DB_HOST/DB_USER/DB_PASSWORD/DB_NAME 等配置")
        return False
    return True


def check_cdp(cdp_url: str) -> bool:
    """检查 Chrome CDP 端口是否可达。"""
    try:
        req = urllib.request.Request(f"{cdp_url}/json/version", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            browser = data.get("Browser", "unknown")
            logger.info(f"✅ CDP 已连接: {cdp_url} ({browser})")
            return True
    except Exception as e:
        logger.error(f"❌ 无法连接 Chrome CDP: {cdp_url} | {e}")
        logger.error("请先用下面命令启动 Chrome 并登录 m.zhipin.com：")
        logger.error(
            '  & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
            '--remote-debugging-port=9222 '
            '--user-data-dir="$env:USERPROFILE\\.hermes\\chrome-debug-profile"'
        )
        return False


def check_llm(backend: Path) -> bool:
    """检查 backend/.env 是否配置了 LLM（技能提取步骤需要调用 LLM）。"""
    env_file = backend / ".env"
    if not env_file.exists():
        logger.error("❌ backend/.env 不存在，无法检查 LLM 配置")
        return False
    text = env_file.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("LLM_API_KEY") and "=" in line:
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if key:
                logger.info("✅ 检测到 LLM_API_KEY，技能提取步骤（llm_extract_skills）可用")
                return True
    logger.error("❌ backend/.env 未配置有效的 LLM_API_KEY")
    logger.error("技能提取步骤需要用 LLM 从 JD 正文提取技能关键词。请填写 LLM_API_KEY / LLM_API_BASE / LLM_MODEL")
    logger.error("（可用 DeepSeek 等 OpenAI 兼容端点；或加 --skip-extract-skills 跳过该步骤）")
    return False


def check_mysql(python: Path, backend: Path, env: dict) -> bool:
    """用 venv Python 尝试连接 MySQL，验证数据库配置。"""
    code = (
        "import sys; sys.path.insert(0, '.'); "
        "from src.db_config import get_connection; "
        "c = get_connection(); c.close(); print('MySQL OK')"
    )
    try:
        result = subprocess.run(
            [str(python), "-c", code],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
        )
    except Exception as e:
        logger.error("❌ MySQL 连接检查执行失败")
        logger.error(f"    {e}")
        logger.error("请确认 venv Python 可用，或检查 backend/.env 的 DB_HOST/DB_USER/DB_PASSWORD/DB_NAME")
        return False
    if result.returncode != 0:
        logger.error("❌ MySQL 连接失败")
        logger.error(result.stderr.strip() or result.stdout.strip())
        logger.error("请检查 backend/.env 中的 DB_HOST/DB_USER/DB_PASSWORD/DB_NAME")
        return False
    logger.info(f"✅ MySQL 连接正常: {result.stdout.strip()}")
    return True


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Boss 直聘一键采集流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
典型用法:
  python run_boss_pipeline.py --cities 杭州,苏州 --keywords AI应用开发,Agent --pages 2
  python run_boss_pipeline.py --cities 上海 --keywords 大模型,LangChain --smoke-test "上海 LangChain"
        """.strip(),
    )

    # ingest 参数
    ingest = ap.add_argument_group("ingest 参数")
    ingest.add_argument("--cities", default="上海", help="逗号分隔的城市列表（默认: 上海）")
    ingest.add_argument("--keywords", default="Agent", help="逗号分隔的关键词列表（默认: Agent）")
    ingest.add_argument("--pages", type=int, default=1, help="每个查询抓几页（默认: 1）")
    ingest.add_argument("--min-delay", type=float, default=2.0, help="请求最小随机延迟（秒，默认: 2.0）")
    ingest.add_argument("--max-delay", type=float, default=5.0, help="请求最大随机延迟（秒，默认: 5.0）")
    ingest.add_argument("--max-retries", type=int, default=3, help="单查询最大重试次数（默认: 3）")
    ingest.add_argument("--no-resume", action="store_true", help="忽略断点文件，强制全部重抓")
    ingest.add_argument("--checkpoint", default=None, help="断点文件路径（默认: backend/data/boss_checkpoint.json）")

    # enrich 参数
    enrich = ap.add_argument_group("enrich 参数")
    enrich.add_argument("--skip-enrich", action="store_true", help="跳过 JD 详情补全")
    enrich.add_argument("--enrich-limit", type=int, default=None, help="只补前 N 条（调试用）")
    enrich.add_argument("--enrich-rerun", action="store_true", help="已补过的也重抓一遍")

    # extract-skills 参数
    extract = ap.add_argument_group("extract-skills 参数（LLM 提取技能）")
    extract.add_argument("--skip-extract-skills", action="store_true", help="跳过 LLM 技能提取（不调 LLM）")
    extract.add_argument("--force-extract", action="store_true", help="重新提取全部 JD 的技能（默认只处理未提取的）")

    # index 参数
    index = ap.add_argument_group("index 参数")
    index.add_argument("--skip-index", action="store_true", help="跳过向量化索引")
    index.add_argument("--no-rebuild", action="store_true", help="索引时不重建向量库（默认会 --rebuild）")
    index.add_argument("--index-limit", type=int, default=None, help="只索引前 N 条（调试用）")

    # 流程控制
    ctl = ap.add_argument_group("流程控制")
    ctl.add_argument("--cdp-url", default=DEFAULT_CDP_URL, help="Chrome CDP 地址（默认: http://127.0.0.1:9222）")
    ctl.add_argument("--smoke-test", default=None, help="流水线结束后用 search.py 跑一条检索验证，例如 \"杭州 AI 应用开发\"")
    ctl.add_argument("--skip-preflight", action="store_true", help="跳过 CDP/MySQL/.env 预检")

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()

    scripts_dir = Path(__file__).resolve().parent           # .../backend/scripts
    backend = scripts_dir.parent                            # .../backend
    scripts = scripts_dir
    python = find_venv_python(backend)                      # 向上查找 .venv（仓库根 / backend）

    logger.info(f"backend 目录: {backend}")
    logger.info(f"使用 Python: {python}")

    env = os.environ.copy()
    env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    # ---------------- 预检 ----------------
    if not args.skip_preflight:
        ok = True
        ok = check_dotenv(backend) and ok
        ok = check_cdp(args.cdp_url) and ok
        ok = check_mysql(python, backend, env) and ok
        if not args.skip_extract_skills:
            ok = check_llm(backend) and ok
        if not ok:
            sys.exit(1)
        logger.info("=" * 70)
        logger.info("预检通过，开始执行流水线")
    else:
        logger.warning("跳过预检，按用户要求直接执行")

    pipeline_start = time.time()
    logger.info("═" * 70)
    logger.info("🚀 启动 Boss 直聘采集流水线（共 5 步：ingest → enrich → extract_skills → index → 检索验证）")
    logger.info("═" * 70)

    # ---------------- Step 1: ingest ----------------
    ingest_cmd: list[str | Path] = [
        python,
        scripts / "ingest_boss_jobs.py",
        "--cities", args.cities,
        "--keywords", args.keywords,
        "--pages", str(args.pages),
        "--min-delay", str(args.min_delay),
        "--max-delay", str(args.max_delay),
        "--max-retries", str(args.max_retries),
    ]
    if args.no_resume:
        ingest_cmd.append("--no-resume")
    if args.checkpoint:
        ingest_cmd.extend(["--checkpoint", args.checkpoint])
    run_cmd(1, 5, "抓取列表 ingest_boss_jobs", "ingest_boss_jobs", ingest_cmd, backend, env)

    # ---------------- Step 2: enrich ----------------
    if args.skip_enrich:
        logger.info("⏭ 跳过 Step 2/5 · enrich_boss_details（--skip-enrich）")
    else:
        enrich_cmd: list[str | Path] = [python, scripts / "enrich_boss_details.py"]
        if args.enrich_limit:
            enrich_cmd.extend(["--limit", str(args.enrich_limit)])
        if args.enrich_rerun:
            enrich_cmd.append("--rerun")
        run_cmd(2, 5, "补全 JD enrich_boss_details", "enrich_boss_details", enrich_cmd, backend, env)

    # ---------------- Step 3: llm_extract_skills ----------------
    if args.skip_extract_skills:
        logger.info("⏭ 跳过 Step 3/5 · llm_extract_skills（--skip-extract-skills）")
    else:
        extract_cmd: list[str | Path] = [python, scripts / "llm_extract_skills.py"]
        if args.force_extract:
            extract_cmd.append("--force")
        run_cmd(3, 5, "LLM 提取技能 llm_extract_skills", "llm_extract_skills", extract_cmd, backend, env)

    # ---------------- Step 4: index ----------------
    if args.skip_index:
        logger.info("⏭ 跳过 Step 4/5 · index_final_results（--skip-index）")
    else:
        index_cmd: list[str | Path] = [python, scripts / "index_final_results.py"]
        if not args.no_rebuild:
            index_cmd.append("--rebuild")
        if args.index_limit:
            index_cmd.extend(["--limit", str(args.index_limit)])
        run_cmd(4, 5, "向量化 index_final_results", "index_final_results", index_cmd, backend, env)

    # ---------------- Step 5: 冒烟测试 ----------------
    if args.smoke_test:
        smoke_cmd: list[str | Path] = [
            python,
            scripts / "search.py",
            args.smoke_test,
            "--source", "boss_zhipin",
            "--top-k", "3",
        ]
        run_cmd(5, 5, "检索验证 smoke_test", "smoke_test (search.py)", smoke_cmd, backend, env)
    else:
        logger.info("⏭ 跳过 Step 5/5 · 检索验证（未指定 --smoke-test）")

    total_elapsed = time.time() - pipeline_start
    logger.info(bar := "═" * 70)
    logger.info("🎉 Boss 直聘采集流水线全部完成")
    logger.info(f"   总耗时: {total_elapsed:.1f}s（{(total_elapsed / 60):.1f} 分钟）")
    logger.info("   数据已落入 MySQL final_results 与向量库，可直接用 find_jobs.py 或 Web API 查询")
    logger.info(bar)


if __name__ == "__main__":
    main()
