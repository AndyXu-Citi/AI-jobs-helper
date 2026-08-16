"""
MySQL 数据库管理器。

管理 5 张表（原 SQLite collector.db + agent_runs.db 合并）：
  - urls_history
  - task_queue
  - raw_contents
  - final_results
  - agent_runs

连接参数从 .env / 环境变量读取，见 src/db_config.py。
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

logger = logging.getLogger(__name__)


# ====================================================================
# MySQL 建表 DDL
# ====================================================================
# 在 MySQL 中创建 ai_collector 库和全部表。
# 可在 MySQL 客户端执行，也可以调用 ensure_tables() 在代码中执行。
# ====================================================================

DDL_DATABASE = """
CREATE DATABASE IF NOT EXISTS ai_collector
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;
"""

DDL_TABLES = """
-- 1. URL 历史表
CREATE TABLE IF NOT EXISTS urls_history (
    url             VARCHAR(255) PRIMARY KEY,
    first_seen_at   DATETIME,
    last_seen_at    DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 任务队列表
CREATE TABLE IF NOT EXISTS task_queue (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    url             VARCHAR(255) UNIQUE,
    status          VARCHAR(20) DEFAULT 'PENDING',
    source_type     VARCHAR(50) DEFAULT 'bilibili',
    retry_count     INT DEFAULT 0,
    error_message   TEXT,
    last_attempt_at DATETIME,
    created_at      DATETIME,
    INDEX idx_tq_status (status),
    INDEX idx_tq_source (source_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 原始内容表
CREATE TABLE IF NOT EXISTS raw_contents (
    url             VARCHAR(255) PRIMARY KEY,
    markdown_text   LONGTEXT,
    collected_at    DATETIME,
    FOREIGN KEY (url) REFERENCES task_queue(url)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. 最终结果表
CREATE TABLE IF NOT EXISTS final_results (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    url             VARCHAR(255),
    source_type     VARCHAR(50) DEFAULT 'bilibili',
    structured_json LONGTEXT,
    processed_at    DATETIME,
    INDEX idx_fr_source (source_type),
    INDEX idx_fr_url (url),
    FOREIGN KEY (url) REFERENCES task_queue(url)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Agent 运行记录（原 agent_runs.db）
CREATE TABLE IF NOT EXISTS agent_runs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    run_at          DATETIME NOT NULL,
    query           TEXT NOT NULL,
    result_count    INT NOT NULL,
    elapsed_seconds FLOAT DEFAULT 0,
    reflect_rounds  INT DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'unreviewed',
    root_cause      TEXT,
    fix_commit      VARCHAR(40) DEFAULT '',
    fix_notes       TEXT,
    trace_json      LONGTEXT,
    final_report    LONGTEXT,
    INDEX idx_ar_status (status),
    INDEX idx_ar_run_at (run_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


# ====================================================================
# DBManager
# ====================================================================

class DBManager:
    """MySQL 数据库管理器，封装 collector 和 agent_runs 两张库的全部操作。"""

    def __init__(self):
        from src.db_config import get_connection

        self._get_connection = get_connection
        self._ensure_database()
        self._ensure_tables()

    # ------------------------------------------------------------------
    # 数据库与表初始化
    # ------------------------------------------------------------------
    def _ensure_database(self):
        """确保数据库存在（CREATE DATABASE IF NOT EXISTS）。"""
        from src.db_config import _load_config

        cfg = _load_config()
        db_name = cfg.get("database", "ai_collector")
        conn = self._get_connection(database=None)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "CREATE DATABASE IF NOT EXISTS `%s` "
                    "DEFAULT CHARACTER SET utf8mb4 "
                    "DEFAULT COLLATE utf8mb4_unicode_ci" % db_name
                )
            conn.commit()
        finally:
            conn.close()

    def _ensure_tables(self):
        """幂等创建全部表。"""
        conn = self._get_connection()
        try:
            # 逐个执行 CREATE TABLE IF NOT EXISTS
            cursor = conn.cursor()
            for statement in DDL_TABLES.split(";"):
                stmt = statement.strip()
                if stmt and stmt.upper().startswith("CREATE"):
                    cursor.execute(stmt + ";")
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 连接上下文（供外部脚本用，与 BadCaseStore 风格一致）
    # ------------------------------------------------------------------
    @contextmanager
    def conn(self) -> Iterator:
        """获取一个 MySQL 连接（with 语句自动 close）。

        用法：
            with db.conn() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(...)
        """
        c = self._get_connection()
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ------------------------------------------------------------------
    # task_queue 操作
    # ------------------------------------------------------------------
    def add_new_urls(self, urls: list[str], source_type: str = "bilibili") -> int:
        """将新发现的 URL 加入任务队列。返回新增数量。"""
        added = 0
        now = datetime.now().isoformat()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            for url in urls:
                # 历史表
                cursor.execute(
                    "INSERT IGNORE INTO urls_history (url, first_seen_at, last_seen_at) "
                    "VALUES (%s, %s, %s)",
                    (url, now, now),
                )
                # 任务队列
                cursor.execute(
                    "INSERT IGNORE INTO task_queue (url, status, source_type, created_at) "
                    "VALUES (%s, 'PENDING', %s, %s)",
                    (url, source_type, now),
                )
                if cursor.rowcount > 0:
                    added += 1
            conn.commit()
        finally:
            conn.close()
        return added

    def get_task_source_type(self, url: str) -> str | None:
        conn = self._get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT source_type FROM task_queue WHERE url = %s", (url,)
            )
            row = cursor.fetchone()
            return row["source_type"] if row else None
        finally:
            conn.close()

    def get_pending_tasks(self, limit: int = 10) -> list[str]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT url FROM task_queue WHERE status = 'PENDING' LIMIT %s",
                (limit,),
            )
            return [row["url"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def update_task_status(self, url: str, status: str):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE task_queue SET status = %s WHERE url = %s",
                (status, url),
            )
            conn.commit()
        finally:
            conn.close()

    def save_raw_content(self, url: str, text: str):
        now = datetime.now().isoformat()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "REPLACE INTO raw_contents (url, markdown_text, collected_at) "
                "VALUES (%s, %s, %s)",
                (url, text, now),
            )
            cursor.execute(
                "UPDATE task_queue SET status = 'COLLECTED' WHERE url = %s",
                (url,),
            )
            conn.commit()
        finally:
            conn.close()

    def save_final_result(self, url: str, json_data: str, source_type: str = "bilibili"):
        now = datetime.now().isoformat()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO final_results (url, source_type, structured_json, processed_at) "
                "VALUES (%s, %s, %s, %s)",
                (url, source_type, json_data, now),
            )
            cursor.execute(
                "UPDATE task_queue SET status = 'COMPLETED' WHERE url = %s",
                (url,),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 失败重试
    # ------------------------------------------------------------------
    def mark_failed(self, url: str, error_message: str | None = None):
        if error_message:
            error_message = str(error_message)[:500]
        now = datetime.now().isoformat()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE task_queue
                SET status = 'FAILED',
                    retry_count = COALESCE(retry_count, 0) + 1,
                    error_message = %s,
                    last_attempt_at = %s
                WHERE url = %s
                """,
                (error_message, now, url),
            )
            conn.commit()
        finally:
            conn.close()
        logger.warning(f"[DB] mark_failed: {url} | reason: {error_message}")

    def requeue_failed(self, max_retry: int | None = None) -> dict:
        if max_retry is None:
            max_retry = 3

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # 有 raw_contents → COLLECTED
            cursor.execute(
                """
                UPDATE task_queue
                SET status = 'COLLECTED'
                WHERE status = 'FAILED'
                  AND COALESCE(retry_count, 0) < %s
                  AND url IN (SELECT url FROM raw_contents)
                """,
                (max_retry,),
            )
            to_collected = cursor.rowcount
            # 无 raw_contents → PENDING
            cursor.execute(
                """
                UPDATE task_queue
                SET status = 'PENDING'
                WHERE status = 'FAILED'
                  AND COALESCE(retry_count, 0) < %s
                """,
                (max_retry,),
            )
            to_pending = cursor.rowcount
            # 剩余 FAILED 计数
            cursor.execute(
                "SELECT COUNT(*) AS n FROM task_queue WHERE status = 'FAILED'"
            )
            kept_failed = cursor.fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        if to_collected or to_pending:
            logger.info(
                f"[DB] requeue_failed: {to_collected} -> COLLECTED, "
                f"{to_pending} -> PENDING, {kept_failed} kept FAILED "
                f"(max_retry={max_retry})"
            )
        return {
            "to_collected": to_collected,
            "to_pending": to_pending,
            "kept_failed": kept_failed,
        }

    def get_run_summary(self) -> dict:
        conn = self._get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT status, COUNT(*) AS n FROM task_queue GROUP BY status"
            )
            by_status = {row["status"]: row["n"] for row in cursor.fetchall()}
            cursor.execute("SELECT COUNT(*) AS n FROM final_results")
            total_results = cursor.fetchone()["n"]
        finally:
            conn.close()
        return {"by_status": by_status, "total_final_results": total_results}

    # ------------------------------------------------------------------
    # Agent 运行记录（原 bad_case_store 的方法整合）
    # ------------------------------------------------------------------
    def record_agent_run(
        self,
        *,
        query: str,
        result_count: int,
        elapsed_seconds: float,
        reflect_rounds: int = 0,
        trace: list[str] | None = None,
        final_report: str = "",
        status: str = "unreviewed",
    ) -> int:
        from src.agent.bad_case_store import VALID_STATUSES

        if status not in VALID_STATUSES:
            raise ValueError(
                f"invalid status {status!r}, must be one of {sorted(VALID_STATUSES)}"
            )
        if result_count == 0 and status == "unreviewed":
            status = "bad"

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO agent_runs
                    (run_at, query, result_count, elapsed_seconds, reflect_rounds,
                     status, root_cause, trace_json, final_report)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    query,
                    int(result_count),
                    float(elapsed_seconds),
                    int(reflect_rounds),
                    status,
                    "zero_result" if result_count == 0 else "",
                    json.dumps(trace or [], ensure_ascii=False),
                    final_report,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)
        finally:
            conn.close()

    def mark_agent_run(
        self,
        run_id: int,
        *,
        status: str | None = None,
        root_cause: str | None = None,
        fix_commit: str | None = None,
        fix_notes: str | None = None,
    ) -> bool:
        from src.agent.bad_case_store import VALID_STATUSES

        if status is not None and status not in VALID_STATUSES:
            raise ValueError(
                f"invalid status {status!r}, must be one of {sorted(VALID_STATUSES)}"
            )

        sets: list[str] = []
        values: list[object] = []
        if status is not None:
            sets.append("status = %s")
            values.append(status)
        if root_cause is not None:
            sets.append("root_cause = %s")
            values.append(root_cause)
        if fix_commit is not None:
            sets.append("fix_commit = %s")
            values.append(fix_commit)
        if fix_notes is not None:
            sets.append("fix_notes = %s")
            values.append(fix_notes)
        if not sets:
            return False

        values.append(run_id)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE agent_runs SET {', '.join(sets)} WHERE id = %s",
                values,
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_agent_run(self, run_id: int) -> dict | None:
        conn = self._get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM agent_runs WHERE id = %s", (run_id,))
            return cursor.fetchone()
        finally:
            conn.close()

    def list_agent_runs(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[dict]:
        sql = "SELECT * FROM agent_runs"
        params: list[object] = []
        if status:
            sql += " WHERE status = %s"
            params.append(status)
        sql += " ORDER BY run_at DESC, id DESC LIMIT %s"
        params.append(int(limit))

        conn = self._get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            conn.close()

    def agent_run_stats(self) -> dict:
        conn = self._get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT status, COUNT(*) AS n FROM agent_runs GROUP BY status"
            )
            out = {"unreviewed": 0, "good": 0, "bad": 0}
            for row in cursor.fetchall():
                out[row["status"]] = row["n"]
            out["total"] = sum(out.values())
        finally:
            conn.close()
        return out
