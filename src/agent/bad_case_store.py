"""v3.0 求职 Agent 的运行记录 + Bad Case 闭环存储（MySQL 版）。

用法与旧 SQLite 版完全兼容，只是底层换成了 MySQL。
建表由 db_manager.DDL_TABLES 负责，本模块只做读写。
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

logger = logging.getLogger(__name__)

VALID_STATUSES = {"unreviewed", "good", "bad"}


@dataclass
class AgentRun:
    """一次 Agent 跑的完整记录。"""

    id: int | None
    run_at: str
    query: str
    result_count: int
    elapsed_seconds: float
    reflect_rounds: int
    status: str
    root_cause: str = ""
    fix_commit: str = ""
    fix_notes: str = ""
    trace_json: str = ""
    final_report: str = ""


class BadCaseStore:
    """对 agent_runs 表的薄封装。

    使用 MySQL 作为后端，连接参数从 .env 读取。
    方法签名与旧 SQLite 版完全兼容。
    """

    def __init__(self):
        # 表由 DBManager._ensure_tables 创建，这里不重复建
        pass

    @contextmanager
    def _conn(self) -> Iterator:
        from src.db_config import get_connection

        conn = get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _row_to_run(self, row: dict[str, Any]) -> AgentRun:
        return AgentRun(
            id=row["id"],
            run_at=row["run_at"],
            query=row["query"],
            result_count=row["result_count"],
            elapsed_seconds=row["elapsed_seconds"] or 0.0,
            reflect_rounds=row["reflect_rounds"] or 0,
            status=row["status"],
            root_cause=row["root_cause"] or "",
            fix_commit=row["fix_commit"] or "",
            fix_notes=row["fix_notes"] or "",
            trace_json=row["trace_json"] or "",
            final_report=row["final_report"] or "",
        )

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def record_run(
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
        if status not in VALID_STATUSES:
            raise ValueError(
                f"invalid status {status!r}, must be one of {sorted(VALID_STATUSES)}"
            )
        if result_count == 0 and status == "unreviewed":
            status = "bad"

        with self._conn() as conn:
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
            return int(cursor.lastrowid or 0)

    def mark(
        self,
        run_id: int,
        *,
        status: str | None = None,
        root_cause: str | None = None,
        fix_commit: str | None = None,
        fix_notes: str | None = None,
    ) -> bool:
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
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE agent_runs SET {', '.join(sets)} WHERE id = %s",
                values,
            )
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def get(self, run_id: int) -> AgentRun | None:
        with self._conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM agent_runs WHERE id = %s", (run_id,))
            row = cursor.fetchone()
        return self._row_to_run(row) if row else None

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        sql = "SELECT * FROM agent_runs"
        params: list[object] = []
        if status:
            sql += " WHERE status = %s"
            params.append(status)
        sql += " ORDER BY run_at DESC, id DESC LIMIT %s"
        params.append(int(limit))

        with self._conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        return [self._row_to_run(r) for r in rows]

    def stats(self) -> dict[str, int]:
        with self._conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT status, COUNT(*) AS n FROM agent_runs GROUP BY status"
            )
            out = {"unreviewed": 0, "good": 0, "bad": 0}
            for row in cursor.fetchall():
                out[row["status"]] = row["n"]
            out["total"] = sum(out.values())
        return out
