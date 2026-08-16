"""
向量存储：Milvus（主） + FAISS（无服务端的本地 fallback）。

为什么这样设计：
- 主路径用 Milvus（192.168.1.9:19530），支持 dense(bge-m3) + sparse(BM25 词面召回)
  双路 hybrid 检索（RRFRanker 融合），技能词精确匹配与语义泛化兼顾。
- 当环境变量 MILVUS_URL 未设置、或 Milvus 初始化失败时，自动回退到纯本地 FAISS，
  保证「一键回退」与无服务端环境（CI / 离线）仍可运行。

对外接口保持稳定（向后兼容）：
    VectorStore(db_path, collection?, force_faiss?)
    .upsert(url, source_type, title, text, embedding, city?, created_at?)
    .upsert_chunks(url, source_type, title, chunks, city?, created_at?)  # 长文本分块写入
    .search(query_embedding, top_k, source_type?, query_text?) -> list[SearchHit]
    .count() -> int
    .rebuild()  # 清空重建（--rebuild 用）

SearchHit: url / source_type / title / score(0~1, 越大越相似)
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

try:
    import faiss
except ImportError:  # pragma: no cover
    faiss = None  # type: ignore[assignment]

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):  # type: ignore
        return False

from src.rag.embedder import EMBED_DIM

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    """检索结果的最小契约（下游 tools.vector_search_jobs 只依赖这四个字段）。"""
    url: str
    source_type: str
    title: str
    score: float       # 0-1 相关性，越大越相似（已规范化）


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _escape_str(v: str) -> str:
    """Milvus expr 字符串转义：单引号翻倍。"""
    return str(v).replace("'", "\\'")


def _milvus_sdk_available() -> bool:
    try:
        import pymilvus  # noqa: F401
        return True
    except ImportError:  # pragma: no cover
        return False


class VectorStore:
    """向量存储。Milvus 优先，FAISS fallback。"""

    def __init__(self, db_path: str | None = None, collection: str | None = None,
                 force_faiss: bool = False):
        load_dotenv()
        self.db_path = str(db_path) if db_path else None
        self.collection = collection or os.getenv("MILVUS_JOB_COLLECTION", "job_docs")

        self._use_milvus = (
            (not force_faiss)
            and bool(os.getenv("MILVUS_URL"))
            and _milvus_sdk_available()
        )

        if self._use_milvus:
            try:
                self._init_milvus()
                logger.info(f"[VectorStore] 使用 Milvus 后端（collection={self.collection}）")
            except Exception as e:  # 初始化失败则回退
                logger.error(f"[VectorStore] Milvus 初始化失败，回退 FAISS: {e}")
                self._use_milvus = False

        if not self._use_milvus:
            self._init_faiss()

    # ==================================================================
    # 初始化：Milvus
    # ==================================================================
    def _init_milvus(self) -> None:
        from pymilvus import MilvusClient

        url = os.getenv("MILVUS_URL", "").rstrip("/")
        token = os.getenv("MILVUS_TOKEN", "")
        kwargs: dict = {"uri": url}
        if token:
            kwargs["token"] = token
        self._mc = MilvusClient(**kwargs)

        if not self._mc.has_collection(self.collection):
            self._create_milvus_collection()
        self._load_milvus_collection()

    def _create_milvus_collection(self) -> None:
        from pymilvus import (
            DataType, FieldSchema, CollectionSchema,
            Function, FunctionType,
        )
        schema = CollectionSchema(fields=[
            FieldSchema(name="id", dtype=DataType.INT64,
                        is_primary=True, auto_id=True),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBED_DIM),
            # BM25 函数自动从 text 字段计算 sparse（词面召回）
            FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="url", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="source_type", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
            # text 必须 enable_analyzer（BM25 输入要求），中文分词
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535,
                        enable_analyzer=True, analyzer_params={"type": "chinese"}),
            FieldSchema(name="city", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="created_at", dtype=DataType.INT64),
        ])
        bm25 = Function(
            name="bm25_fn",
            input_field_names=["text"],
            output_field_names=["sparse"],
            function_type=FunctionType.BM25,
        )
        schema.add_function(bm25)
        self._mc.create_collection(collection_name=self.collection, schema=schema)

        idx = self._mc.prepare_index_params()
        idx.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")
        # sparse 走 BM25 度量 + 倒排索引
        idx.add_index(field_name="sparse", index_type="AUTOINDEX", metric_type="BM25")
        self._mc.create_index(collection_name=self.collection, index_params=idx)
        logger.info(f"[Milvus] 已创建 collection（dense COSINE + sparse BM25）: {self.collection}")

    def _load_milvus_collection(self) -> None:
        try:
            state = self._mc.get_load_state(collection_name=self.collection)
        except Exception:
            state = None
        if state != "Loaded":
            try:
                self._mc.load_collection(self.collection)
            except Exception as e:  # 已加载时报错可忽略
                if "already loaded" not in str(e).lower():
                    raise

    # ==================================================================
    # 初始化：FAISS（fallback）
    # ==================================================================
    def _init_faiss(self) -> None:
        if faiss is None:
            raise RuntimeError("既无 Milvus 也无可用的 FAISS：请 pip install faiss-cpu 或设置 MILVUS_URL")
        if not self.db_path:
            raise RuntimeError("FAISS fallback 需要 db_path（Milvus 模式不需要）")

        base = Path(self.db_path)
        if base.suffix == ".db":
            base = base.with_suffix("")
        self.index_path = str(base) + ".faiss"
        self.meta_path = str(base) + ".pkl"
        self._index = None
        self._metadata: list[dict] = []
        self._ensure_faiss_index()
        logger.info(f"[VectorStore] 使用 FAISS fallback 后端: {self.index_path}")

    def _ensure_faiss_index(self) -> None:
        if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
            try:
                self._index = faiss.read_index(self.index_path)
                with open(self.meta_path, "rb") as f:
                    self._metadata = pickle.load(f)
                logger.info(f"[FAISS] 加载已有索引（{len(self._metadata)} 条）")
                return
            except Exception as e:
                logger.warning(f"[FAISS] 加载失败将重建: {e}")
        self._index = faiss.IndexFlatIP(EMBED_DIM)
        self._metadata = []
        logger.info(f"[FAISS] 新建空索引（dim={EMBED_DIM}）")

    # ==================================================================
    # 写入
    # ==================================================================
    def upsert(
        self, *, url: str, source_type: str, title: str, text: str,
        embedding: list[float], city: str = "", created_at: int | None = None,
    ) -> None:
        """单条写入（自动去重 url）。长文本请改用 upsert_chunks。"""
        self.upsert_chunks(
            url=url, source_type=source_type, title=title,
            chunks=[(text, embedding)], city=city, created_at=created_at,
        )

    def upsert_chunks(
        self, *, url: str, source_type: str, title: str,
        chunks: list[tuple[str, list[float]]], city: str = "",
        created_at: int | None = None,
    ) -> None:
        """按 url 去重写入一组分块向量（一条原始记录 → 多块）。"""
        if self._use_milvus:
            self._milvus_upsert(url, source_type, title, chunks, city, created_at)
        else:
            # FAISS 不支持分块：退化为第一条
            text, embedding = chunks[0]
            self._faiss_upsert(url=url, source_type=source_type, title=title,
                               text=text, embedding=embedding)

    def _milvus_upsert(self, url, source_type, title, chunks, city, created_at) -> None:
        created_at = int(created_at if created_at is not None else time.time())
        # 先删旧（同一 url 可能有多块）
        self._milvus_delete_by_url(url)
        rows = []
        for text, embedding in chunks:
            if len(embedding) != EMBED_DIM:
                raise ValueError(
                    f"embedding dim mismatch: got {len(embedding)}, want {EMBED_DIM}")
            rows.append({
                "embedding": [float(x) for x in embedding],
                "url": url,
                "source_type": source_type,
                "title": (title or "")[:512],
                "text": (text or "")[:65535],
                "city": (city or "")[:64],
                "created_at": int(created_at),
            })
        if not rows:
            return
        self._mc.insert(collection_name=self.collection, data=rows)

    def _milvus_delete_by_url(self, url: str) -> None:
        try:
            self._mc.delete(
                collection_name=self.collection,
                filter=f"url == '{_escape_str(url)}'",
            )
        except Exception as e:
            logger.warning(f"[Milvus] 删除旧记录失败（可能首次写入）: {e}")

    # ----- FAISS 写入 -----
    def _faiss_upsert(self, *, url, source_type, title, text, embedding) -> None:
        if len(embedding) != EMBED_DIM:
            raise ValueError(f"embedding dim mismatch: got {len(embedding)}, want {EMBED_DIM}")
        vec = np.array([embedding], dtype=np.float32)
        faiss.normalize_L2(vec)
        existing = [i for i, m in enumerate(self._metadata) if m.get("url") == url]
        if existing:
            for i in existing:
                self._metadata[i]["_deleted"] = True
            self._faiss_rebuild_index()
        self._index.add(vec)
        self._metadata.append({
            "url": url, "source_type": source_type,
            "title": title, "text": text,
        })
        self._faiss_save()

    def _faiss_rebuild_index(self) -> None:
        alive = [(i, m) for i, m in enumerate(self._metadata) if not m.get("_deleted")]
        if len(alive) == len(self._metadata):
            return
        n = len(alive)
        if n == 0:
            self._index = faiss.IndexFlatIP(EMBED_DIM)
            self._metadata = []
            return
        old_vecs = [self._index.reconstruct(i) for i, _ in alive]
        vecs = np.array(old_vecs, dtype=np.float32)
        self._index = faiss.IndexFlatIP(EMBED_DIM)
        self._index.add(vecs)
        self._metadata = [m for _, m in alive]

    def _faiss_save(self) -> None:
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        faiss.write_index(self._index, self.index_path)
        with open(self.meta_path, "wb") as f:
            pickle.dump(self._metadata, f)

    # ==================================================================
    # 检索
    # ==================================================================
    def search(
        self, query_embedding: list[float], top_k: int = 5,
        source_type: str | None = None, query_text: str | None = None,
    ) -> list[SearchHit]:
        """语义检索。query_text 提供时走 dense+sparse hybrid（BM25）。"""
        if self._use_milvus:
            return self._milvus_search(query_embedding, top_k, source_type, query_text)
        return self._faiss_search(query_embedding, top_k, source_type)

    def _milvus_search(self, query_embedding, top_k, source_type, query_text) -> list[SearchHit]:
        from pymilvus import AnnSearchRequest, RRFRanker

        if len(query_embedding) != EMBED_DIM:
            raise ValueError(
                f"query embedding dim mismatch: got {len(query_embedding)}, want {EMBED_DIM}")
        filter_expr = ""
        if source_type:
            filter_expr = f"source_type == '{_escape_str(source_type)}'"

        fetch_k = max(top_k * 3, top_k)
        # 过滤同时下放到每个子请求（hybrid_search 顶层 filter 在部分版本不生效）
        dense_req = AnnSearchRequest(
            data=[list(query_embedding)], anns_field="embedding",
            param={"metric_type": "COSINE"}, limit=fetch_k, expr=filter_expr)

        if query_text:
            sparse_req = AnnSearchRequest(
                data=[query_text], anns_field="sparse",
                param={"metric_type": "BM25"}, limit=fetch_k, expr=filter_expr)
            res = self._mc.hybrid_search(
                collection_name=self.collection,
                reqs=[dense_req, sparse_req],
                ranker=RRFRanker(),
                limit=top_k * 3,
                filter=filter_expr,
                output_fields=["url", "source_type", "title"],
            )
        else:
            res = self._mc.search(
                collection_name=self.collection,
                data=[list(query_embedding)], anns_field="embedding",
                search_params={"metric_type": "COSINE"}, limit=top_k * 3,
                filter=filter_expr,
                output_fields=["url", "source_type", "title"],
            )
        raw = res[0]
        # 规范化分数：相对 batch 最大值映射到 (0,1]，保留排序与单调性
        distances = [float(h.get("distance", 0.0)) for h in raw]
        max_d = max(distances) if distances else 0.0

        # 按 url 去重（分块场景），取每个 url 的最高分
        best: dict[str, SearchHit] = {}
        for h, d in zip(raw, distances):
            ent = h.get("entity", {})
            url = ent.get("url", "")
            score = (d / max_d) if max_d > 0 else 0.0
            if url not in best or score > best[url].score:
                best[url] = SearchHit(
                    url=url,
                    source_type=ent.get("source_type", ""),
                    title=ent.get("title", ""),
                    score=round(score, 4),
                )
        hits = sorted(best.values(), key=lambda x: x.score, reverse=True)[:top_k]
        return hits

    def _faiss_search(self, query_embedding, top_k, source_type) -> list[SearchHit]:
        if len(query_embedding) != EMBED_DIM:
            raise ValueError(
                f"query embedding dim mismatch: got {len(query_embedding)}, want {EMBED_DIM}")
        if self._index is None or self._index.ntotal == 0:
            return []
        q = np.array([query_embedding], dtype=np.float32)
        faiss.normalize_L2(q)
        fetch_k = min(top_k * 3, self._index.ntotal)
        distances, indices = self._index.search(q, fetch_k)
        hits: list[SearchHit] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self._metadata):
                continue
            meta = self._metadata[idx]
            if meta.get("_deleted"):
                continue
            if source_type and meta.get("source_type") != source_type:
                continue
            # 归一化内积∈[-1,1] → 余弦相似度 0~1
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

    # ==================================================================
    # 统计 / 重建
    # ==================================================================
    def count(self) -> int:
        if self._use_milvus:
            try:
                res = self._mc.query(
                    collection_name=self.collection, filter="",
                    output_fields=["count(*)"])
                return int(res[0]["count(*)"]) if res else 0
            except Exception as e:
                logger.warning(f"[Milvus] count 失败: {e}")
                return 0
        return sum(1 for m in self._metadata if not m.get("_deleted"))

    def flush(self) -> None:
        """把内存中的插入落盘，使 count/search 立即可见（批量写入后调用一次）。"""
        if self._use_milvus:
            try:
                self._mc.flush(collection_name=self.collection)
            except Exception as e:
                logger.warning(f"[Milvus] flush 失败: {e}")

    def rebuild(self) -> None:
        """清空并重建整个集合（--rebuild 用）。"""
        if self._use_milvus:
            try:
                if self._mc.has_collection(self.collection):
                    self._mc.drop_collection(self.collection)
                self._create_milvus_collection()
                self._load_milvus_collection()
                logger.info(f"[Milvus] 已重建 collection: {self.collection}")
            except Exception as e:
                logger.error(f"[Milvus] rebuild 失败: {e}")
                raise
        else:
            for p in [getattr(self, "index_path", ""), getattr(self, "meta_path", "")]:
                if p and os.path.exists(p):
                    os.remove(p)
            self._index = faiss.IndexFlatIP(EMBED_DIM)
            self._metadata = []
            logger.info("[FAISS] 已清空索引文件")


# pickle 在 fallback 分支用到，靠近使用处导入更清晰，这里统一放在模块末尾导入
import pickle  # noqa: E402
