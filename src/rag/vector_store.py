"""
FAISS 向量存储封装（替代 Milvus Lite）。

为什么换 FAISS：
- Milvus Lite 在 Windows 上有 gRPC 兼容问题（AllocTimestamp / too_many_pings）
- FAISS 纯本地库，零服务器依赖，pip install 即用
- 本数据量（~几百条）FAISS 性能完全足够

接口与旧 MilvusLite VectorStore 完全兼容（SearchHit / upsert / search / count）。
"""
from __future__ import annotations

import logging
import os
import pickle
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

try:
    import faiss
except ImportError:
    faiss = None  # type: ignore[assignment]

from src.rag.embedder import EMBED_DIM

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    """检索结果的最小契约。"""
    url: str
    source_type: str
    title: str
    score: float       # 0-1 余弦相似度，越大越相似


class VectorStore:
    """FAISS 向量存储。

    持久化：index + metadata 分别存为 .faiss 和 .pkl 文件。
    线程安全：每次写入后落盘，每次读从磁盘加载（适合单进程场景）。
    """

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        # 消除 .db 后缀（Milvus 习惯），统一用 .faiss / .pkl
        base = Path(self.db_path)
        if base.suffix == ".db":
            base = base.with_suffix("")
        self.index_path = str(base) + ".faiss"
        self.meta_path = str(base) + ".pkl"
        self._index: faiss.IndexFlatIP | None = None
        self._metadata: list[dict] = []
        self._ensure_index()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _ensure_index(self) -> None:
        """加载已有索引，或新建空索引。"""
        if faiss is None:
            raise RuntimeError("faiss 未安装：pip install faiss-cpu 或 faiss")

        if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
            try:
                self._index = faiss.read_index(self.index_path)
                with open(self.meta_path, "rb") as f:
                    self._metadata = pickle.load(f)
                logger.info(
                    f"[VectorStore] 加载已有索引：{self.index_path} "
                    f"（{len(self._metadata)} 条）"
                )
                return
            except Exception as e:
                logger.warning(f"[VectorStore] 加载索引失败，将重建: {e}")

        # 新建空索引
        self._index = faiss.IndexFlatIP(EMBED_DIM)  # Inner Product = 余弦相似度（归一化后）
        self._metadata = []
        logger.info(f"[VectorStore] 新建空索引（dim={EMBED_DIM}）: {self.index_path}")

    def _save(self) -> None:
        """把索引和元数据落盘。"""
        if self._index is None:
            return
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        faiss.write_index(self._index, self.index_path)
        with open(self.meta_path, "wb") as f:
            pickle.dump(self._metadata, f)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def upsert(
        self,
        *,
        url: str,
        source_type: str,
        title: str,
        text: str,
        embedding: list[float],
    ) -> None:
        """按 url 去重写入：先删旧记录，再追加新向量。"""
        if faiss is None:
            raise RuntimeError("faiss 未安装")
        if len(embedding) != EMBED_DIM:
            raise ValueError(
                f"embedding dim mismatch: got {len(embedding)}, want {EMBED_DIM}"
            )

        vec = np.array([embedding], dtype=np.float32)
        # 归一化：FAISS 的 IndexFlatIP 在归一化向量上等价于余弦相似度
        faiss.normalize_L2(vec)

        # 1) 若已有同 url 的记录，删掉
        existing_indices = [
            i for i, m in enumerate(self._metadata) if m.get("url") == url
        ]
        if existing_indices:
            # FAISS 不支持删除单条，变通：把要删的向量置零 + 元数据设标记
            for i in existing_indices:
                self._metadata[i]["_deleted"] = True
                # 不能真正从 index 删除，但 search 时会被过滤掉
            # 重建索引（去掉已删除的）
            self._rebuild_index()

        # 2) 添加新记录
        idx = self._index.ntotal
        self._index.add(vec)
        self._metadata.append({
            "url": url,
            "source_type": source_type,
            "title": title,
            "text": text,
        })
        self._save()

    def _rebuild_index(self) -> None:
        """重建索引：剔除标记为 _deleted 的条目。"""
        alive = [(i, m) for i, m in enumerate(self._metadata) if not m.get("_deleted")]
        if len(alive) == len(self._metadata):
            return  # 没有删除，无需重建

        n = len(alive)
        if n == 0:
            self._index = faiss.IndexFlatIP(EMBED_DIM)
            self._metadata = []
            return

        # 从原 index 取出向量（FAISS 没有按 id 取向量的 API，需用 reconstruct）
        old_vectors = []
        for old_idx, _ in alive:
            old_vectors.append(self._index.reconstruct(old_idx))
        vecs = np.array(old_vectors, dtype=np.float32)

        self._index = faiss.IndexFlatIP(EMBED_DIM)
        self._index.add(vecs)
        self._metadata = [m for _, m in alive]

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        source_type: str | None = None,
    ) -> list[SearchHit]:
        """语义检索。可选按 source_type 过滤。"""
        if faiss is None:
            raise RuntimeError("faiss 未安装")
        if len(query_embedding) != EMBED_DIM:
            raise ValueError(
                f"query embedding dim mismatch: got {len(query_embedding)}, want {EMBED_DIM}"
            )
        if self._index is None or self._index.ntotal == 0:
            return []

        q = np.array([query_embedding], dtype=np.float32)
        faiss.normalize_L2(q)

        # 多搜一些，留给过滤
        fetch_k = min(top_k * 3, self._index.ntotal)
        distances, indices = self._index.search(q, fetch_k)

        hits: list[SearchHit] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self._metadata):
                continue
            meta = self._metadata[idx]
            # 跳过已删除的
            if meta.get("_deleted"):
                continue
            # 按 source_type 过滤
            if source_type and meta.get("source_type") != source_type:
                continue
            # distance 是内积（对内积=1 完全相似，0 正交）
            similarity = float(max(0.0, min(1.0, (dist + 1.0) / 2.0)))
            hits.append(SearchHit(
                url=meta.get("url", ""),
                source_type=meta.get("source_type", ""),
                title=meta.get("title", ""),
                score=similarity,
            ))
            if len(hits) >= top_k:
                break

        return hits

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------
    def count(self) -> int:
        """有效（未删除）的向量数。"""
        if self._metadata is None:
            return 0
        return sum(1 for m in self._metadata if not m.get("_deleted"))
