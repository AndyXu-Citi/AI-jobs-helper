"""
记忆模块 —— 长期语义记忆存储（Milvus chat_memory collection）。

设计（见 docs/milvus_migration_design.md 第三节）：
- 原始聊天落 MySQL（conversations / chat_messages），语义记忆落 Milvus。
- 同一 Milvus 实例，独立 collection `chat_memory`，与 job_docs 不混。
- 每条 user 消息异步 embed 写入 memory_type='user_msg'；可选会话摘要 'summary'。
- 检索必须带 user_id 过滤，绝不跨用户召回。

若未配置 MILVUS_URL，则 memory 功能自动禁用（不报错，仅告警）。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Iterable

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):  # type: ignore
        return False

from src.rag.embedder import EMBED_DIM

logger = logging.getLogger(__name__)

_EMBEDDER = None
_EMBEDDER_LOCK = threading.Lock()


def _get_embedder():
    """进程内懒加载 bge-m3（避免每次调用都重载权重）。"""
    global _EMBEDDER
    if _EMBEDDER is None:
        with _EMBEDDER_LOCK:
            if _EMBEDDER is None:
                from src.rag.embedder import HuggingFaceEmbedder
                _EMBEDDER = HuggingFaceEmbedder()
    return _EMBEDDER


class MemoryStore:
    """长期语义记忆（Milvus chat_memory）。"""

    def __init__(self, collection: str | None = None, force_faiss: bool = False):
        load_dotenv()
        self.collection = collection or os.getenv("MILVUS_MEMORY_COLLECTION", "chat_memory")
        self.enabled = (
            (not force_faiss) and bool(os.getenv("MILVUS_URL"))
            and self._milvus_available()
        )
        if self.enabled:
            try:
                self._init_milvus()
                logger.info(f"[MemoryStore] 启用 Milvus 记忆库（collection={self.collection}）")
            except Exception as e:
                logger.error(f"[MemoryStore] Milvus 初始化失败，记忆功能禁用: {e}")
                self.enabled = False
        else:
            logger.warning("[MemoryStore] 未配置 MILVUS_URL，记忆功能禁用（仅 MySQL 原文持久化仍生效）")

    @staticmethod
    def _milvus_available() -> bool:
        try:
            import pymilvus  # noqa: F401
            return True
        except ImportError:  # pragma: no cover
            return False

    def _init_milvus(self) -> None:
        from pymilvus import MilvusClient, DataType, FieldSchema, CollectionSchema

        url = os.getenv("MILVUS_URL", "").rstrip("/")
        token = os.getenv("MILVUS_TOKEN", "")
        kwargs: dict = {"uri": url}
        if token:
            kwargs["token"] = token
        self._mc = MilvusClient(**kwargs)

        if not self._mc.has_collection(self.collection):
            schema = CollectionSchema(fields=[
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBED_DIM),
                FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="session_id", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="memory_type", dtype=DataType.VARCHAR, max_length=32),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="created_at", dtype=DataType.INT64),
            ])
            self._mc.create_collection(collection_name=self.collection, schema=schema)
            idx = self._mc.prepare_index_params()
            idx.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")
            self._mc.create_index(collection_name=self.collection, index_params=idx)
            logger.info(f"[MemoryStore] 已创建 chat_memory collection（dense COSINE）")

        # 加载
        try:
            state = self._mc.get_load_state(collection_name=self.collection)
        except Exception:
            state = None
        if state != "Loaded":
            try:
                self._mc.load_collection(self.collection)
            except Exception as e:
                if "already loaded" not in str(e).lower():
                    raise

    # ------------------------------------------------------------------
    def add_memory(
        self, *, user_id: str, session_id: str, memory_type: str, content: str,
        embedding: list[float] | None = None, created_at: int | None = None,
    ) -> bool:
        """写入一条记忆。返回是否成功。"""
        if not self.enabled:
            return False
        if not content or not content.strip():
            return False
        try:
            if embedding is None:
                embedding = _get_embedder().embed_one(content)
            if len(embedding) != EMBED_DIM:
                logger.warning("[MemoryStore] embedding 维度异常，跳过")
                return False
            self._mc.insert(collection_name=self.collection, data=[{
                "embedding": [float(x) for x in embedding],
                "user_id": (user_id or "default")[:64],
                "session_id": (session_id or "")[:64],
                "memory_type": (memory_type or "user_msg")[:32],
                "content": content[:65535],
                "created_at": int(created_at if created_at is not None else time.time()),
            }])
            return True
        except Exception as e:
            logger.warning(f"[MemoryStore] add_memory 失败: {e}")
            return False

    def recall(
        self, user_id: str, query_embedding: list[float], top_k: int = 10,
    ) -> list[dict]:
        """跨会话语义召回该用户的历史记忆片段。

        返回 list[dict]，每项含 content / score(余弦相似度) / created_at / memory_type。
        score 用于相关性阈值与时间衰减；memory_type 用于区分 summary / 普通对话。
        """
        if not self.enabled:
            return []
        if len(query_embedding) != EMBED_DIM:
            logger.warning("[MemoryStore] query 维度异常")
            return []
        try:
            res = self._mc.search(
                collection_name=self.collection,
                data=[list(query_embedding)], anns_field="embedding",
                search_params={"metric_type": "COSINE"}, limit=top_k,
                filter=f"user_id == '{_esc(user_id)}'",
                output_fields=["content", "memory_type", "created_at"],
            )
            out = []
            for h in res[0]:
                ent = h.get("entity", {})
                c = ent.get("content", "")
                if not c:
                    continue
                out.append({
                    "content": c,
                    "score": float(h.get("distance", 0) or 0),
                    "created_at": int(ent.get("created_at", 0) or 0),
                    "memory_type": ent.get("memory_type", "") or "",
                })
            return out
        except Exception as e:
            logger.warning(f"[MemoryStore] recall 失败: {e}")
            return []

    def flush(self) -> None:
        if self.enabled:
            try:
                self._mc.flush(collection_name=self.collection)
            except Exception as e:
                logger.warning(f"[MemoryStore] flush 失败: {e}")

    def embed(self, text: str) -> list[float] | None:
        """把文本转向量（复用进程内 bge-m3 单例）。失败返回 None。"""
        if not self.enabled:
            return None
        try:
            return _get_embedder().embed_one(text)
        except Exception as e:
            logger.warning(f"[MemoryStore] embed 失败: {e}")
            return None


def _esc(v: str) -> str:
    return str(v).replace("'", "\\'")
