"""
MySQL 数据库连接配置（从 .env 读取）。

所有需要连接数据库的模块都从这里获取连接对象，
不要各自硬编码连接参数。

用法
----
    from src.db_config import get_connection

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM final_results WHERE source_type = %s", ("boss_zhipin",))
    rows = cursor.fetchall()
    conn.close()
"""
from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)

# 默认连接参数（会被 .env 覆盖）
_DEFAULTS = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "",
    "database": "ai_collector",
}


def _load_config() -> dict:
    """从环境变量读取 MySQL 连接参数，缺失时用默认值。"""
    # 只在首次调用时加载 .env
    if "DB_HOST" not in os.environ:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

    cfg = dict(_DEFAULTS)
    cfg["host"] = os.getenv("DB_HOST", cfg["host"])
    cfg["port"] = int(os.getenv("DB_PORT", str(cfg["port"])))
    cfg["user"] = os.getenv("DB_USER", cfg["user"])
    cfg["password"] = os.getenv("DB_PASSWORD", cfg["password"])
    cfg["database"] = os.getenv("DB_NAME", cfg["database"])

    missing = [k for k in ("host", "user", "password", "database") if not cfg[k]]
    if missing:
        logger.warning(
            f"MySQL 配置缺失: {missing}。请设置环境变量或在 .env 中填写 "
            f"DB_HOST / DB_USER / DB_PASSWORD / DB_NAME"
        )
    return cfg


def get_connection(**kwargs):
    """获取一个 MySQL 连接。

    默认参数从 .env / 环境变量读取；支持直接传参覆盖（测试时有用）。

    用法
    ----
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # ...
        conn.close()
    """
    import mysql.connector

    cfg = _load_config()
    cfg.update(kwargs)
    conn = mysql.connector.connect(**cfg)
    return conn
