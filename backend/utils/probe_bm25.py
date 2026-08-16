"""
BM25 + hybrid 检索探针：在真实 192.168.1.9:19530 (v2.5.0) 上验证
pymilvus 3.0.0 客户端能否跑通 BM25 Function + dense/sparse 双路 hybrid search。
跑完自动清理临时 collection。
"""
from __future__ import annotations
import os, sys, random, logging
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

from pymilvus import (
    MilvusClient, DataType, FieldSchema, CollectionSchema,
    Function, FunctionType, AnnSearchRequest, RRFRanker,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("probe")

DIM = 1024
COL = "tmp_bm25_probe"
URL = "http://192.168.1.9:19530"

def rand_vec(dim):
    v = [random.uniform(-1, 1) for _ in range(dim)]
    n = (sum(x*x for x in v)) ** 0.5 or 1.0
    return [x/n for x in v]

def main():
    c = MilvusClient(uri=URL)
    log.info("server: " + c.get_server_version())

    if c.has_collection(COL):
        c.drop_collection(COL)

    schema = CollectionSchema(fields=[
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=DIM),
        FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),  # BM25 输出
        FieldSchema(name="url", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="source_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535,
                     enable_analyzer=True, analyzer_params={"type": "chinese"}),
        FieldSchema(name="city", dtype=DataType.VARCHAR, max_length=64),
    ])
    # BM25 函数：输入 text -> 输出 sparse
    bm25 = Function(
        name="bm25_fn",
        input_field_names=["text"],
        output_field_names=["sparse"],
        function_type=FunctionType.BM25,
    )
    schema.add_function(bm25)

    c.create_collection(collection_name=COL, schema=schema)
    log.info("[OK] create_collection with BM25 function")

    data = [
        {"embedding": rand_vec(DIM), "url": "u1", "source_type": "boss",
         "title": "Java 后端开发", "text": "熟练掌握 Java Spring Boot Kafka 分布式", "city": "杭州"},
        {"embedding": rand_vec(DIM), "url": "u2", "source_type": "boss",
         "title": "Python 算法", "text": "Python 机器学习 PyTorch 深度学习 NLP", "city": "上海"},
        {"embedding": rand_vec(DIM), "url": "u3", "source_type": "arxiv",
         "title": "论文", "text": "transformer attention mechanism survey", "city": "北京"},
    ]
    c.insert(collection_name=COL, data=data)
    log.info(f"[OK] insert {len(data)} rows (BM25 sparse auto-generated)")

    idx = c.prepare_index_params()
    idx.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")
    idx.add_index(field_name="sparse", index_type="AUTOINDEX", metric_type="BM25")
    c.create_index(collection_name=COL, index_params=idx)
    log.info("[OK] create_index dense(COSINE)+sparse(BM25)")

    c.load_collection(COL)
    log.info("[OK] load_collection")

    req_dense = AnnSearchRequest(
        data=[rand_vec(DIM)], anns_field="embedding",
        param={"metric_type": "COSINE"}, limit=3)
    req_sparse = AnnSearchRequest(
        data=["Java Kafka 分布式"], anns_field="sparse",
        param={"metric_type": "BM25"}, limit=3)
    res = c.hybrid_search(
        collection_name=COL,
        reqs=[req_dense, req_sparse],
        ranker=RRFRanker(),
        limit=3,
        filter="source_type == 'boss'",
        output_fields=["url", "title", "text", "source_type"],
    )
    log.info("[OK] hybrid_search returned %d hits:" % len(res[0]))
    for h in res[0]:
        e = h.get("entity", {})
        log.info(f"     - {e.get('title')} | score={h.get('distance'):.4f} | text={e.get('text')}")

    # count via query
    cnt = c.query(collection_name=COL, filter="", output_fields=["count(*)"])
    log.info("[OK] query count -> %s" % cnt)

    # delete by expr
    c.delete(collection_name=COL, filter="url == 'u1'")
    log.info("[OK] delete by expr url=='u1'")

    c.drop_collection(COL)
    log.info("[OK] cleaned up temp collection")
    log.info("\n=== 结论：BM25 Function + hybrid_search 在 pymilvus 3.0.0 / server 2.5.0 下可用 ===")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"\n[FAIL] {type(e).__name__}: {e}")
        sys.exit(1)
