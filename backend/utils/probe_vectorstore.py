"""VectorStore(Milvus) 端到端探针：验证新版 VectorStore 在真实服务端的读写/检索。"""
import os, sys
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

# 让脚本能 import src.*（与 scripts/ 下脚本一致）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.rag.vector_store import VectorStore, SearchHit

COL = "tmp_vs_probe"
DIM = 1024

# 用假向量即可（只验证链路与字段契约），维度必须 1024
def v(seed):
    return [seed] * DIM

def main():
    # 用临时 collection
    store = VectorStore(db_path="data/vector.db", collection=COL)
    print("[init] backend:", "milvus" if store._use_milvus else "faiss")

    # 清空重建
    store.rebuild()
    print("[rebuild] ok, count =", store.count())

    # 写入：boss + arxiv 混合
    store.upsert(url="u_boss_1", source_type="boss_zhipin", title="Java 后端开发",
                 text="Java Spring Boot Kafka 分布式微服务", embedding=v(0.5),
                 city="杭州", created_at=1)
    store.upsert(url="u_boss_2", source_type="boss_zhipin", title="Python 算法",
                 text="Python PyTorch 深度学习 NLP 大模型", embedding=v(0.3),
                 city="上海", created_at=2)
    store.upsert(url="u_arx_1", source_type="arxiv", title="论文",
                 text="transformer attention survey", embedding=v(0.4),
                 city="北京", created_at=3)
    store.flush()  # insert 异步，flush 后 count 才准确
    print("[upsert] ok, count =", store.count(), "(应为 3)")
    assert store.count() == 3, "flush 后 count 应等于 3"

    # 去重测试：重复 upsert 同 url，count 不应增加
    store.upsert(url="u_boss_1", source_type="boss_zhipin", title="Java 后端开发 V2",
                 text="Java Spring Boot Kafka 分布式微服务 更新版", embedding=v(0.5),
                 city="杭州", created_at=4)
    print("[dedup] count after re-upsert same url =", store.count(), "(应为 3)")

    # hybrid 检索（带 query_text）
    hits = store.search(v(0.5), top_k=5, source_type="boss_zhipin",
                        query_text="Java Kafka 分布式")
    print(f"\n[hybrid] 命中 {len(hits)} 条：")
    for h in hits:
        assert isinstance(h, SearchHit)
        print(f"   - {h.title} | score={h.score} | url={h.url} | type={h.source_type}")

    # dense-only 检索（不带 query_text，向后兼容）
    hits2 = store.search(v(0.5), top_k=5, source_type="boss_zhipin")
    print(f"\n[dense-only] 命中 {len(hits2)} 条（无 query_text 应退化为纯 dense）：")
    for h in hits2:
        print(f"   - {h.title} | score={h.score}")

    # 过滤验证：arxiv 不应出现在 boss 结果里
    assert all(h.source_type == "boss_zhipin" for h in hits), "source_type 过滤失效!"
    print("\n[OK] source_type 过滤正确")

    # 清理
    store.rebuild()
    print("[cleanup] 已清空临时 collection, count =", store.count())

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[FAIL] {type(e).__name__}: {e}")
        sys.exit(1)
