"""
对话持久化（MySQL）：conversations / chat_messages 的 CRUD。

供 /api/chat/unified 调用，把每次对话落库，作为「短期记忆」原文。
记忆的语义检索另见 src/rag/memory_store.py（Milvus chat_memory）。
"""
from __future__ import annotations

import time
from typing import Iterable

from src.db_config import get_connection


def ensure_tables() -> None:
    """幂等建表（与 scripts/init_db_memory.py 一致）。"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                conversation_id VARCHAR(64) NOT NULL UNIQUE,
                user_id VARCHAR(64) NOT NULL DEFAULT 'default',
                title VARCHAR(255) NOT NULL DEFAULT '新对话',
                mode VARCHAR(32) NOT NULL DEFAULT 'assistant',
                created_at BIGINT NOT NULL,
                updated_at BIGINT NOT NULL,
                INDEX idx_user (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                conversation_id VARCHAR(64) NOT NULL,
                user_id VARCHAR(64) NOT NULL DEFAULT 'default',
                role VARCHAR(32) NOT NULL,
                content MEDIUMTEXT NOT NULL,
                token_count INT NOT NULL DEFAULT 0,
                created_at BIGINT NOT NULL,
                INDEX idx_conv (conversation_id),
                INDEX idx_user (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        conn.commit()
    finally:
        conn.close()


def create_conversation(conversation_id: str, user_id: str = "default",
                        title: str = "新对话", mode: str = "assistant") -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        now = int(time.time())
        cur.execute(
            """INSERT IGNORE INTO conversations
               (conversation_id, user_id, title, mode, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (conversation_id, user_id, title, mode, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def touch_conversation(conversation_id: str, title: str | None = None,
                       mode: str | None = None) -> None:
    """更新会话时间（及可选标题/模式）。"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        now = int(time.time())
        if title is not None:
            cur.execute(
                "UPDATE conversations SET updated_at=%s, title=%s WHERE conversation_id=%s",
                (now, title, conversation_id))
        else:
            cur.execute(
                "UPDATE conversations SET updated_at=%s WHERE conversation_id=%s",
                (now, conversation_id))
        conn.commit()
    finally:
        conn.close()


def save_message(conversation_id: str, role: str, content: str,
                 user_id: str = "default", token_count: int = 0) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO chat_messages
               (conversation_id, user_id, role, content, token_count, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (conversation_id, user_id, role, content, token_count, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


def list_conversations(user_id: str = "default", limit: int = 50) -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT conversation_id, title, mode, created_at, updated_at
               FROM conversations WHERE user_id=%s ORDER BY updated_at DESC LIMIT %s""",
            (user_id, limit))
        return cur.fetchall()
    finally:
        conn.close()


def get_history(conversation_id: str, limit: int = 50) -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT role, content, created_at FROM chat_messages
               WHERE conversation_id=%s ORDER BY id ASC LIMIT %s""",
            (conversation_id, limit))
        return cur.fetchall()
    finally:
        conn.close()
