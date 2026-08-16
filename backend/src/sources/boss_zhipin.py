"""
BossSource —— Boss 直聘招聘源 (v3.0)

设计思路
--------
Boss 直聘 PC 站列表用 Canvas 渲染，常规爬虫拿不到岗位文字；但**移动端 H5
站 m.zhipin.com 提供了 JSON API**（/wapi/zpgeek/search/joblist.json），
直接返回结构化岗位列表（jobName / salaryDesc / skills / jobLabels / 发布人）。

为了优雅、长期可持续地绕过 Boss 风控（code 37 "您的环境存在异常"），
我们采用 **CDP 接管真实 Chrome** 方案：

1. 用户用 ~/.hermes/chrome-debug-profile 这个独立 profile 启动 Chrome：
       --remote-debugging-port=9222
       --user-data-dir="$HOME/.hermes/chrome-debug-profile"
2. 用户在那个 Chrome 里手动扫码登 Boss（一次性，cookie 持久保存）
3. BossSource 通过 Playwright 的 connect_over_cdp 接管这个浏览器
4. 在已登录的 m.zhipin.com 页面里直接 fetch API（同源、cookie 自动带）

这样：
- 完全绕开 code 37 风控（请求来自真实浏览器、真实用户 cookie）
- cookie 失效时浏览器会自然提示，用户重新扫码即可
- 不需要逆向 __zp_stoken__ 签名

实战经验（v3.0 → v3.1 反爬加固）
------------------------------
- **每个查询必须在已登录上下文里新开标签页**（`context.new_page()` + 先
  `goto m.zhipin.com`）：Boss 会对"同一页面会话连续打 API"做连接级封禁
  （表现为首个请求成功、后续 Failed to fetch）。新标签页重置会话即绕开。
- 请求间随机延迟 + code 37 触发长冷却（默认 20s）+ 连续 N 次失败整段冷却
  （默认 60s），避免硬刚把账号/连接打进长期封禁。
- 单次失败大多是临时的，重试即可恢复；但重试也要用新标签页。
- 日志打印 page_num（数字），不打印 page 对象，否则刷一串 <Page url=...>。

与 BaseSource 契约
------------------
fetch_new_urls() 返回岗位详情页 URL 列表，符合既有 Monitor 调度模式。
另外暴露 fetch_jobs_structured()，直接返回完整结构化岗位（v3.0 Agent 用）。
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import List

from .base import BaseSource

logger = logging.getLogger(__name__)

# Boss 直聘城市编码（与 m.zhipin.com 的 city 参数一致）
CITY_CODES = {
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "苏州": "101190400",
    "郑州": "101180100",
    "济南": "101120100",
    "青岛": "101120200",
    "南京": "101190100",
    "成都": "101270100",
    "武汉": "101200100",
    "西安": "101110100",
}

# Boss 搜索 API（移动端 H5）
SEARCH_API_PATH = "/wapi/zpgeek/search/joblist.json"

# Boss 岗位详情卡片 API（移动端 H5）—— 用搜索返回的 securityId + lid 调用
DETAIL_API_PATH = "/wapi/zpgeek/job/card.json"

# Boss H5 站点基准地址：page.request.fetch 不接受相对路径，必须拼成绝对 URL
ZHIPIN_BASE = "https://m.zhipin.com"

# CDP 端点（用户启动 Chrome 时指定的 --remote-debugging-port）
DEFAULT_CDP_URL = "http://127.0.0.1:9222"


@dataclass
class BossJobDetail:
    """Boss 岗位详情（来自 /wapi/zpgeek/job/card.json）。"""

    encrypt_job_id: str
    job_name: str
    post_description: str       # JD 正文
    city_name: str
    experience_name: str        # "1-3 年" / "经验不限" 等
    degree_name: str            # "本科" / "大专" 等
    job_labels: List[str] = field(default_factory=list)
    salary_desc: str = ""
    brand_name: str = ""        # 公司名（搜索 API 里没有）
    address: str = ""
    boss_name: str = ""
    boss_title: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class BossJob:
    """Boss 一条岗位的结构化表示。"""

    job_name: str
    salary_desc: str
    city: str
    keyword: str
    encrypt_job_id: str
    skills: List[str] = field(default_factory=list)
    job_labels: List[str] = field(default_factory=list)
    boss_name: str = ""
    boss_title: str = ""
    boss_cert: int = 0  # 3 = 已认证企业 boss
    raw: dict = field(default_factory=dict)

    @property
    def url(self) -> str:
        """构造 PC 站详情页 URL（统一对外暴露的"内容 URL"）。"""
        return f"https://www.zhipin.com/job_detail/{self.encrypt_job_id}.html"

    @property
    def is_likely_noise(self) -> bool:
        """快速垃圾岗启发式：日结/项目外包/校招实习等。"""
        s = self.salary_desc
        if "元/天" in s or "元/小时" in s:
            return True
        labels = "".join(self.job_labels)
        if "校招" in self.job_name or "校招" in labels:
            return True
        if "实习" in self.job_name and "转正" not in self.job_name:
            return True
        # 发布人头衔包含明显非技术的关键词（"收展员" = 保险代理人 等）
        if self.boss_title and any(
            x in self.boss_title for x in ["收展", "保险", "代理", "招聘专员"]
        ):
            # 注意：HR / 招聘专员也算正常发布岗位的人，这里只把"收展/保险/代理"列噪音
            if any(x in self.boss_title for x in ["收展", "保险", "代理"]):
                return True
        return False


class BossSource(BaseSource):
    """
    Boss 直聘招聘源，通过 CDP 接管真实 Chrome 抓取 m.zhipin.com 搜索 API。

    用法
    ----
    >>> src = BossSource(
    ...     cities=["杭州", "苏州", "济南", "青岛", "郑州"],
    ...     keywords=["AI应用开发", "大模型", "LangChain", "Agent"],
    ... )
    >>> urls = await src.fetch_new_urls()           # 走 BaseSource 契约
    >>> jobs = await src.fetch_jobs_structured()    # v3.0 Agent 用
    """

    source_type: str = "boss_zhipin"

    def __init__(
        self,
        cities: List[str],
        keywords: List[str],
        pages_per_query: int = 1,
        cdp_url: str = DEFAULT_CDP_URL,
        filter_noise: bool = True,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        max_retries: int = 3,
        settle_delay: tuple = (0.3, 0.9),
        code37_cooldown: float = 20.0,
        max_consecutive_failures: int = 5,
        consecutive_cooldown: float = 60.0,
        cookies: list = None,
    ):
        if not cities:
            raise ValueError("BossSource: cities 不能为空")
        if not keywords:
            raise ValueError("BossSource: keywords 不能为空")

        unknown_cities = [c for c in cities if c not in CITY_CODES]
        if unknown_cities:
            raise ValueError(
                f"BossSource: 未知城市 {unknown_cities}；"
                f"已支持: {list(CITY_CODES.keys())}"
            )

        self.cities = cities
        self.keywords = keywords
        self.pages_per_query = pages_per_query
        self.cdp_url = cdp_url
        self.filter_noise = filter_noise
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.settle_delay = settle_delay
        self.code37_cooldown = code37_cooldown
        self.max_consecutive_failures = max_consecutive_failures
        self.consecutive_cooldown = consecutive_cooldown
        self.cookies = cookies or []

        # 连续失败计数：达到阈值就整段长冷却，避免硬刚 WAF 把账号/连接打进长期封禁
        self.consecutive_failures = 0

        # 抓取后缓存一份完整结构化数据，BaseSource 契约只返回 URL，
        # 但 v3.0 Agent / scripts 可以直接读这个属性拿到富数据。
        self._last_jobs: List[BossJob] = []

    @property
    def last_jobs(self) -> List[BossJob]:
        return list(self._last_jobs)

    # ------------------------------------------------------------------
    # BaseSource 契约
    # ------------------------------------------------------------------
    async def fetch_new_urls(self) -> List[str]:
        jobs = await self.fetch_jobs_structured()
        # 去重保序
        seen, urls = set(), []
        for j in jobs:
            if j.url in seen:
                continue
            seen.add(j.url)
            urls.append(j.url)
        return urls

    # ------------------------------------------------------------------
    # v3.0 富接口：结构化岗位
    # ------------------------------------------------------------------
    async def fetch_jobs_structured(
        self, progress_callback=None, skip_predicate=None
    ) -> List[BossJob]:
        """
        抓取 cities × keywords 笛卡尔积下所有岗位。

        返回去噪后的 BossJob 列表（如果 filter_noise=True）。

        progress_callback(city, keyword, page_num, jobs): 可选，每完成一个
            成功的查询就回调一次。ingest 脚本用它做断点续传——只有成功的查询
            才会被回调，失败的不会，因此重跑时会自动重试失败项。
        skip_predicate(city, keyword, page_num) -> bool: 可选，返回 True 表示该
            查询已完成、直接跳过（断点续传用）。
        """
        from playwright.async_api import async_playwright

        all_jobs: List[BossJob] = []

        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(self.cdp_url)
            except Exception as e:
                logger.error(
                    f"BossSource: 无法连接 CDP 端口 {self.cdp_url}。"
                    f"请确认 Chrome 已用 --remote-debugging-port=9222 启动。错误: {e}"
                )
                return []

            # 关键修复：拿到"已登录的浏览器上下文"，后续每个查询都在该上下文里
            # 开一个全新标签页（cookie 自动继承），从根本上绕开"同一会话连续打
            # API 被 WAF 连接级封禁"的问题。
            context = await self._get_or_create_context(browser)

            total_queries = (
                len(self.cities) * len(self.keywords) * self.pages_per_query
            )
            done = 0
            for city in self.cities:
                for keyword in self.keywords:
                    for page_num in range(1, self.pages_per_query + 1):
                        done += 1

                        # 断点续传：已完成的直接跳过
                        if skip_predicate is not None and skip_predicate(
                            city, keyword, page_num
                        ):
                            logger.info(
                                f"[跳过 已完成] {done}/{total_queries} "
                                f"{city}/{keyword}/p{page_num}"
                            )
                            continue

                        logger.info(
                            f"[进度 {done}/{total_queries}] {city}/{keyword}/p{page_num}"
                        )
                        jobs, status = await self._fetch_with_retry(
                            context,
                            city=city,
                            keyword=keyword,
                            page_num=page_num,
                        )
                        if status == "ok":
                            all_jobs.extend(jobs)
                            self.consecutive_failures = 0
                            if progress_callback is not None:
                                try:
                                    progress_callback(city, keyword, page_num, jobs)
                                except Exception:
                                    pass
                        else:
                            self.consecutive_failures += 1
                            if (
                                self.consecutive_failures
                                >= self.max_consecutive_failures
                            ):
                                logger.warning(
                                    f"BossSource: 连续 {self.consecutive_failures} 次失败 → "
                                    f"冷却 {self.consecutive_cooldown}s 让 WAF 放松后再继续"
                                )
                                await asyncio.sleep(self.consecutive_cooldown)
                                self.consecutive_failures = 0

                        # 节流：每次请求间随机延迟，缓解 code 37（跳过项不再额外等待）
                        if status == "ok" and done < total_queries:
                            await asyncio.sleep(
                                random.uniform(self.min_delay, self.max_delay)
                            )

            # 断开 CDP（不关用户的 Chrome 窗口）
            try:
                await browser.close()
            except Exception:
                pass

        # 去噪
        if self.filter_noise:
            kept = [j for j in all_jobs if not j.is_likely_noise]
            noisy = len(all_jobs) - len(kept)
            logger.info(
                f"BossSource: 抓到 {len(all_jobs)} 条，过滤噪音 {noisy} 条，保留 {len(kept)} 条"
            )
        else:
            kept = all_jobs

        self._last_jobs = kept
        return kept

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    async def _get_or_create_zhipin_page(browser):
        """找一个 zhipin.com 已打开的页面，没有就新建。（保留兼容）"""
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "zhipin.com" in pg.url:
                    return pg
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        pg = await ctx.new_page()
        await pg.goto("https://m.zhipin.com", wait_until="domcontentloaded")
        return pg

    async def _get_or_create_context(self, browser):
        """
        拿到 BossSource 要用的浏览器上下文。

        - 优先复用 CDP 连接的"默认上下文"（即用户扫码登录的那个 profile，
          cookie 全在里面）；
        - 若构造函数传入了 cookies，则补注入（支持多账号轮换）；
        - 后续每个查询都在该上下文里 new_page()，自动继承登录态。
        """
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        if self.cookies:
            try:
                await ctx.add_cookies(self.cookies)
                logger.info(f"BossSource: 已注入 {len(self.cookies)} 条 cookie")
            except Exception as e:
                logger.warning(f"BossSource: 注入 cookies 失败: {e}")
        return ctx

    async def _fetch_with_retry(
        self,
        context,
        *,
        city: str,
        keyword: str,
        page_num: int,
    ) -> tuple[List[BossJob], str]:
        """带重试 + 退避的查询封装。code 37 视为可重试。

        返回 (jobs, status)：成功时 status='ok' 且 jobs 为列表；
        失败时 status 为最后的状态（fetch_error/code_37/...）且 jobs=[]。
        """
        last_status = "unknown"
        for attempt in range(self.max_retries + 1):
            jobs, status = await self._fetch_one_query(
                context, city=city, keyword=keyword, page_num=page_num
            )
            if status == "ok":
                return jobs, "ok"
            last_status = status
            if attempt < self.max_retries:
                # code 37 / 风控类失败：用更长的冷却，避免硬刚把账号打进长期封禁
                if status == "code_37":
                    backoff = self.code37_cooldown + random.uniform(0, 3)
                else:
                    backoff = (2 ** attempt) + random.uniform(1.0, 3.0)
                logger.info(
                    f"BossSource: {city}/{keyword}/p{page_num} {status} → "
                    f"{backoff:.1f}s 后重试 ({attempt + 1}/{self.max_retries})"
                )
                await asyncio.sleep(backoff)
        logger.warning(
            f"BossSource: {city}/{keyword}/p{page_num} 重试 {self.max_retries} 次后仍失败 ({last_status})"
        )
        return [], last_status

    @staticmethod
    async def _ensure_zhipin_session(page, settle_delay) -> str:
        """
        判断 page 当前落地状态，返回三种判定：
          - "ok"        已落在 m.zhipin.com 同源会话（正常）
          - "nav_glitch" 停在 about:blank，导航未落地（非真风控）。已重 goto 一次仍
                        未落地 → 调用方应按**瞬时故障**立即重试（短退避，不进 20s 冷却）
          - "risk"      跳到非 zhipin 域的验证码/风控页 → 调用方按 code_37 走长冷却
        """
        if "zhipin.com" in page.url:
            return "ok"
        if page.url == "about:blank":
            try:
                await page.goto(
                    "https://m.zhipin.com",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await asyncio.sleep(random.uniform(*settle_delay))
            except Exception:
                pass
            return "ok" if "zhipin.com" in page.url else "nav_glitch"
        return "risk"

    async def _fetch_one_query(
        self,
        context,
        *,
        city: str,
        keyword: str,
        page_num: int = 1,
    ) -> tuple[List[BossJob], str]:
        """
        单次查询：1 个城市 + 1 个关键词 + 1 页。

        关键修复：每次查询都在已登录上下文里**新开一个标签页**，先 goto 回
        m.zhipin.com 重建同源会话，再发 fetch。这样每个查询都相当于"真人新开
        一个标签页去搜"，绕开 WAF 对"同一会话连续打 API"的连接级封禁
        （表现为首个请求成功、后续 Failed to fetch）。

        返回 (jobs, status)；status 取值：
          - "ok"        正常拿到数据（即使空列表）
          - "code_37"   触发 Boss 风控 / 被重定向到验证码，可重试
          - "code_other"  其他业务错误
          - "fetch_error" 网络 / JS 异常
        """
        import urllib.parse

        city_code = CITY_CODES[city]
        api_url = (
            f"{ZHIPIN_BASE}{SEARCH_API_PATH}?query={urllib.parse.quote(keyword)}"
            f"&city={city_code}&page={page_num}"
        )

        page = None
        try:
            page = await context.new_page()
            # 新标签页先访问 m.zhipin.com：重置 WAF 会话/连接（治本动作）
            await page.goto(
                "https://m.zhipin.com",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            # 等 SPA 完成客户端二次跳转/初始化，确保 WAF 会话 token 已就位
            try:
                await page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(random.uniform(*self.settle_delay))

            # 判定落地状态：about:blank 视为瞬时导航故障（短退避重试，不进 20s 冷却），
            # 真跳到非 zhipin 风控页才判 code_37 走长冷却
            verdict = await self._ensure_zhipin_session(page, self.settle_delay)
            if verdict == "risk":
                logger.warning(
                    f"BossSource: {city}/{keyword}/p{page_num} 被重定向到 "
                    f"{page.url}（疑似风控/验证码）→ code_37"
                )
                return [], "code_37"
            if verdict == "nav_glitch":
                logger.warning(
                    f"BossSource: {city}/{keyword}/p{page_num} 导航未落地"
                    f"（{page.url}）→ 按瞬时故障重试"
                )
                return [], "fetch_error"

            # 关键修复：用 page.request.fetch 代替 page.evaluate(fetch)。
            # page.request 走浏览器上下文的 cookie，但完全**脱离页面 JS 执行上下文**，
            # 因此不受 SPA 客户端跳转「销毁执行上下文」的影响——之前报
            # "Execution context was destroyed" 正是 page.evaluate 在导航后被杀所致。
            try:
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
                result = await response.json()
            except Exception as e_json:
                logger.warning(
                    f"BossSource: {city}/{keyword}/p{page_num} 响应解析失败"
                    f"（疑似风控页/非 JSON）: {e_json}"
                )
                return [], "code_37"
        except Exception as e:
            logger.error(
                f"BossSource: {city}/{keyword}/p{page_num} fetch 失败: {e}"
            )
            return [], "fetch_error"
        finally:
            if page is not None:
                try:
                    # 不关闭标签页，只导航到空白页重置状态。
                    # 关掉 context 中最后一个标签页会导致 Chrome 自动关闭整个
                    # context（含登录态），后续查询无法再建新标签页。
                    await page.goto("about:blank", timeout=5000)
                except Exception:
                    pass

        code = result.get("code")
        if code != 0:
            msg = result.get("message")
            logger.warning(
                f"BossSource: {city}/{keyword}/p{page_num} 业务码非 0: "
                f"code={code} message={msg}"
            )
            return [], "code_37" if code == 37 else "code_other"

        job_list = result.get("zpData", {}).get("jobList", []) or []
        jobs: List[BossJob] = []
        for raw in job_list:
            try:
                jobs.append(
                    BossJob(
                        job_name=raw.get("jobName", "").strip(),
                        salary_desc=raw.get("salaryDesc", "").strip(),
                        city=city,
                        keyword=keyword,
                        encrypt_job_id=raw.get("encryptJobId", ""),
                        skills=list(raw.get("skills", []) or []),
                        job_labels=list(raw.get("jobLabels", []) or []),
                        boss_name=raw.get("bossName", ""),
                        boss_title=raw.get("bossTitle", ""),
                        boss_cert=int(raw.get("bossCert", 0) or 0),
                        raw=raw,
                    )
                )
            except Exception as e:
                logger.warning(f"BossSource: 跳过一条解析失败的岗位: {e}")

        logger.info(
            f"BossSource: {city}/{keyword}/p{page_num} → {len(jobs)} 条"
        )
        return jobs, "ok"

    # ------------------------------------------------------------------
    # 详情 API（P4'：富数据补全）
    # ------------------------------------------------------------------
    async def fetch_job_details(
        self,
        security_id_lid_pairs: List[tuple],
    ) -> List[BossJobDetail]:
        """
        批量抓岗位详情。

        Args:
            security_id_lid_pairs: [(security_id, lid), ...] 序列。
                security_id 和 lid 都来自搜索 API 返回的 jobList[*]，
                调详情接口必须配对，否则会被风控。

        返回去重后的 BossJobDetail 列表（按抓取顺序）。失败的条目跳过。
        """
        from playwright.async_api import async_playwright

        details: List[BossJobDetail] = []

        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(self.cdp_url)
            except Exception as e:
                logger.error(
                    f"BossSource: 无法连接 CDP 端口 {self.cdp_url}。错误: {e}"
                )
                return []

            context = await self._get_or_create_context(browser)
            total = len(security_id_lid_pairs)

            for i, (security_id, lid) in enumerate(security_id_lid_pairs, 1):
                detail = await self._fetch_one_detail_with_retry(
                    context, security_id=security_id, lid=lid, idx=i,
                    total=total,
                )
                if detail is not None:
                    details.append(detail)
                if i < total:
                    await asyncio.sleep(random.uniform(self.min_delay, self.max_delay))

            try:
                await browser.close()
            except Exception:
                pass

        return details

    async def _fetch_one_detail_with_retry(
        self,
        context,
        *,
        security_id: str,
        lid: str,
        idx: int,
        total: int,
    ) -> "BossJobDetail | None":
        last_status = "unknown"
        for attempt in range(self.max_retries + 1):
            detail, status = await self._fetch_one_detail(
                context, security_id=security_id, lid=lid, idx=idx, total=total
            )
            if status == "ok":
                return detail
            last_status = status
            if attempt < self.max_retries:
                if status == "code_37":
                    backoff = self.code37_cooldown + random.uniform(0, 3)
                else:
                    backoff = (2 ** attempt) + random.uniform(1.0, 3.0)
                logger.info(
                    f"BossSource detail [{idx}/{total}] {status} → "
                    f"{backoff:.1f}s 后重试 ({attempt + 1}/{self.max_retries})"
                )
                await asyncio.sleep(backoff)
        logger.warning(
            f"BossSource detail [{idx}/{total}] 重试 {self.max_retries} 次后仍失败 ({last_status})"
        )
        return None

    async def _fetch_one_detail(
        self,
        context,
        *,
        security_id: str,
        lid: str,
        idx: int,
        total: int,
    ) -> tuple["BossJobDetail | None", str]:
        """调一次详情 API。每条约新开标签页，避免连接级封禁。返回 (BossJobDetail, status)。"""
        import urllib.parse

        api_url = (
            f"{ZHIPIN_BASE}{DETAIL_API_PATH}?securityId={urllib.parse.quote(security_id)}"
            f"&lid={urllib.parse.quote(lid)}"
        )

        page = None
        try:
            page = await context.new_page()
            await page.goto(
                "https://m.zhipin.com",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            # 等 SPA 客户端二次跳转落定，避免执行上下文被销毁
            try:
                await page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(random.uniform(*self.settle_delay))
            # 同 _fetch_one_query：about:blank 视为瞬时导航故障（短退避），真风控页才 code_37
            verdict = await self._ensure_zhipin_session(page, self.settle_delay)
            if verdict == "risk":
                logger.warning(
                    f"BossSource detail [{idx}/{total}] 被重定向到 {page.url}（风控）→ code_37"
                )
                return None, "code_37"
            if verdict == "nav_glitch":
                logger.warning(
                    f"BossSource detail [{idx}/{total}] 导航未落地（{page.url}）→ 按瞬时故障重试"
                )
                return None, "fetch_error"

            # 改用 page.request.fetch，脱离页面 JS 上下文，免疫导航销毁上下文
            try:
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
                result = await response.json()
            except Exception as e_json:
                logger.warning(
                    f"BossSource detail [{idx}/{total}] 响应解析失败"
                    f"（疑似风控页/非 JSON）: {e_json}"
                )
                return None, "code_37"
        except Exception as e:
            logger.error(f"BossSource detail [{idx}/{total}] fetch 失败: {e}")
            return None, "fetch_error"
        finally:
            if page is not None:
                try:
                    # 同 _fetch_one_query：不关标签页，避免 context 被 Chrome 自动关闭
                    await page.goto("about:blank", timeout=5000)
                except Exception:
                    pass

        code = result.get("code")
        if code != 0:
            msg = result.get("message")
            logger.warning(
                f"BossSource detail [{idx}/{total}] 业务码非 0: "
                f"code={code} message={msg}"
            )
            return None, "code_37" if code == 37 else "code_other"

        card = result.get("zpData", {}).get("jobCard", {}) or {}
        if not card:
            logger.warning(f"BossSource detail [{idx}/{total}] jobCard 为空")
            return None, "empty"

        detail = BossJobDetail(
            encrypt_job_id=card.get("encryptJobId", ""),
            job_name=(card.get("jobName") or "").strip(),
            post_description=(card.get("postDescription") or "").strip(),
            city_name=card.get("cityName", ""),
            experience_name=card.get("experienceName", ""),
            degree_name=card.get("degreeName", ""),
            job_labels=list(card.get("jobLabels", []) or []),
            salary_desc=card.get("salaryDesc", ""),
            brand_name=card.get("brandName", ""),
            address=card.get("address", ""),
            boss_name=card.get("bossName", ""),
            boss_title=card.get("bossTitle", ""),
            raw=card,
        )

        # 紧凑日志：JD 长度 + 公司，让批量跑时能看到进度
        jd_len = len(detail.post_description)
        brand = (detail.brand_name or "?")[:14]
        logger.info(
            f"BossSource detail [{idx}/{total}] ✅ {brand} | "
            f"{detail.job_name[:25]} | JD {jd_len} 字"
        )
        return detail, "ok"
