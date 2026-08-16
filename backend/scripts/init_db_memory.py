"""
初始化记忆模块所需的 MySQL 表：conversations / chat_messages。
幂等：表已存在则跳过。

用法：
    .venv/Scripts/python.exe scripts/init_db_memory.py
"""
from __future__ import annotations
import os, sys
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.db_config import get_connection


SQL_CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS conversations (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id VARCHAR(64)  NOT NULL UNIQUE,
    user_id         VARCHAR(64)  NOT NULL DEFAULT 'default',
    title           VARCHAR(255) NOT NULL DEFAULT '新对话',
    mode            VARCHAR(32)  NOT NULL DEFAULT 'assistant',
    created_at      BIGINT       NOT NULL,
    updated_at      BIGINT       NOT NULL,
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

SQL_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id VARCHAR(64)  NOT NULL,
    user_id         VARCHAR(64)  NOT NULL DEFAULT 'default',
    role            VARCHAR(32)  NOT NULL,           -- user / assistant / system
    content         MEDIUMTEXT    NOT NULL,
    token_count     INT           NOT NULL DEFAULT 0,
    created_at      BIGINT        NOT NULL,
    INDEX idx_conv (conversation_id),
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def main():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(SQL_CONVERSATIONS)
        cur.execute(SQL_MESSAGES)
        conn.commit()
        print("[OK] 已确保 conversations / chat_messages 表存在")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
