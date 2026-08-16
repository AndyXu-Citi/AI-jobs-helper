"""
VectorStore 单元测试。

设计
----
- 主测试用 FAISS fallback（force_faiss=True），不依赖外部 Milvus 服务，
  每个测试一个临时目录，pytest tmp_path 自动清理。验证的是「接口契约与检索行为」。
- 另含一个 Milvus 集成测试（test_milvus_integration），仅当环境变量 MILVUS_URL
  存在时运行，用临时 collection，跑完自动清理。验证 Milvus 后端的真实链路。
"""
import os
import pytest

from dotenv import load_dotenv
load_dotenv()  # 让 MILVUS_URL 等环境变量对测试内的检查可见

from src.rag.embedder import EMBED_DIM
from src.rag.vector_store import VectorStore, SearchHit


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    """每个测试一个全新的临时 FAISS 文件（force_faiss 不依赖 Milvus）。"""
    return VectorStore(db_path=str(tmp_path / "test_vec.db"), force_faiss=True)


def _fake_vec(seed: float = 0.1) -> list[float]:
    """构造一个 1024 维的假向量。不同 seed 产生不同向量，用于测检索排序。"""
    return [seed] * EMBED_DIM


# ---------------------------------------------------------------------------
# 建表 / 空库
# ---------------------------------------------------------------------------
def test_init_empty_count(store):
    """初始化后应为空库。"""
    assert store.count() == 0


def test_search_on_empty_collection_returns_empty_list(store):
    """空库检索应返回空 list，不抛异常。"""
    hits = store.search(_fake_vec(0.5), top_k=5)
    assert hits == []


# ---------------------------------------------------------------------------
# upsert：写入 + 维度校验 + url 去重
# ---------------------------------------------------------------------------
def test_upsert_rejects_wrong_dim(store):
    """传入维度不对的 embedding 应早早抛错，避免脏数据入库。"""
    with pytest.raises(ValueError, match="embedding dim mismatch"):
        store.upsert(
            url="https://x.com/1", source_type="bilibili", title="t",
            text="t", embedding=[0.1] * 512,
        )


def test_upsert_then_search_finds_it(store):
    """写入一条后用同样向量搜应能命中自己。"""
    vec = _fake_vec(0.5)
    store.upsert(
        url="https://x.com/1", source_type="bilibili", title="测试视频",
        text="一段描述", embedding=vec,
    )
    hits = store.search(vec, top_k=5)
    assert len(hits) == 1
    assert hits[0].url == "https://x.com/1"
    assert hits[0].title == "测试视频"
    assert hits[0].source_type == "bilibili"
    assert hits[0].score > 0.99    # 同一向量 COSINE 应接近 1.0


def test_upsert_dedups_by_url(store):
    """同一 url 二次 upsert 应替换旧记录，不产生重复。"""
    store.upsert(
        url="https://x.com/1", source_type="bilibili",
        title="旧标题", text="旧文本", embedding=_fake_vec(0.1),
    )
    store.upsert  # 占位，下面真正调用
    store.upsert(
        url="https://x.com/1", source_type="bilibili",
        title="新标题", text="新文本", embedding=_fake_vec(0.1),
    )
    hits = store.search(_fake_vec(0.1), top_k=10)
    assert len(hits) == 1                  # 只剩一条
    assert hits[0].title == "新标题"        # 是新版本


def test_upsert_chunks_dedups_url(store):
    """upsert_chunks 对同一 url 多块写入，去重后只对应一条 url。"""
    store.upsert_chunks(
        url="https://x/c", source_type="bilibili", title="C",
        chunks=[("块1", _fake_vec(0.2)), ("块2", _fake_vec(0.2))],
    )
    # FAISS fallback 退化为首块；计数仍按 url 去重（这里只有一条 url）
    assert store.count() == 1


# ---------------------------------------------------------------------------
# search：排序 + top_k + 过滤
# ---------------------------------------------------------------------------
def test_search_ranks_by_similarity(store):
    """与 query 越接近的向量应排得越靠前（COSINE）。"""
    store.upsert(url="https://x/a", source_type="bilibili", title="A", text="a",
                 embedding=_fake_vec(0.5))     # 与 query 完全同向 -> 最相似
    store.upsert(url="https://x/b", source_type="bilibili", title="B", text="b",
                 embedding=_fake_vec(0.3))
    diff_vec = [1.0] * (EMBED_DIM // 2) + [-1.0] * (EMBED_DIM // 2)
    store.upsert(url="https://x/c", source_type="bilibili", title="C", text="c",
                 embedding=diff_vec)

    hits = store.search(_fake_vec(0.5), top_k=3)
    assert len(hits) == 3
    assert hits[-1].url == "https://x/c"      # C 方向不同，排最后


def test_search_respects_top_k(store):
    """top_k=2 应只返回 2 条，即使库里有更多。"""
    for i in range(5):
        store.upsert(url=f"https://x/{i}", source_type="bilibili",
                     title=f"T{i}", text=f"t{i}", embedding=_fake_vec(0.1 + i*0.01))
    hits = store.search(_fake_vec(0.15), top_k=2)
    assert len(hits) == 2


def test_search_filters_by_source_type(store):
    """指定 source_type='arxiv' 应只返回 arxiv 的数据，过滤掉 bilibili。"""
    store.upsert(url="https://b/1", source_type="bilibili",
                 title="B 站视频", text="x", embedding=_fake_vec(0.5))
    store.upsert(url="https://a/1", source_type="arxiv",
                 title="arxiv 论文", text="x", embedding=_fake_vec(0.5))
    hits = store.search(_fake_vec(0.5), top_k=10, source_type="arxiv")
    assert len(hits) == 1
    assert hits[0].source_type == "arxiv"
    assert hits[0].url == "https://a/1"


def test_search_rejects_wrong_dim(store):
    """查询向量维度不对应抛错。"""
    with pytest.raises(ValueError, match="query embedding dim mismatch"):
        store.search([0.1] * 512, top_k=5)


def test_search_returns_searchhit_dataclass(store):
    """检索结果应为 SearchHit 实例，保证下游字段访问稳定。"""
    store.upsert(url="https://x/1", source_type="bilibili",
                 title="t", text="x", embedding=_fake_vec(0.5))
    hits = store.search(_fake_vec(0.5), top_k=1)
    assert isinstance(hits[0], SearchHit)
    assert hasattr(hits[0], "score")
    assert hasattr(hits[0], "url")


def test_search_query_text_ignored_on_faiss(store):
    """FAISS 路径忽略 query_text 参数（向后兼容），不抛错。"""
    store.upsert(url="https://x/1", source_type="bilibili",
                 title="t", text="x", embedding=_fake_vec(0.5))
    hits = store.search(_fake_vec(0.5), top_k=1, query_text="任意文本")
    assert len(hits) == 1


# ---------------------------------------------------------------------------
# Milvus 集成测试（需 MILVUS_URL；否则跳过）
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_milvus_integration():
    """真实 Milvus 后端：写入 → hybrid 检索 → 过滤 → count。"""
    if not os.getenv("MILVUS_URL"):
        pytest.skip("未设置 MILVUS_URL，跳过 Milvus 集成测试")

    import time
    col = "tmp_unit_test_jobs"
    vs = VectorStore(db_path="data/vector.db", collection=col)
    vs.rebuild()
    vs.upsert(url="m_boss_1", source_type="boss_zhipin", title="Java 后端",
              text="Java Spring Boot Kafka", embedding=_fake_vec(0.5),
              city="杭州", created_at=1)
    vs.upsert(url="m_boss_2", source_type="boss_zhipin", title="Python 算法",
              text="Python PyTorch", embedding=_fake_vec(0.3),
              city="上海", created_at=2)
    vs.upsert(url="m_arx_1", source_type="arxiv", title="论文",
              text="transformer", embedding=_fake_vec(0.4),
              city="北京", created_at=3)
    vs.flush()
    assert vs.count() == 3

    # hybrid（带 query_text）
    hits = vs.search(_fake_vec(0.5), top_k=5, source_type="boss_zhipin",
                     query_text="Java Kafka")
    assert all(h.source_type == "boss_zhipin" for h in hits)
    assert hits[0].score <= 1.0 and hits[0].score > 0

    # 去重：重 upsert 同 url
    vs.upsert(url="m_boss_1", source_type="boss_zhipin", title="Java 后端 V2",
              text="Java Spring Boot Kafka 更新", embedding=_fake_vec(0.5),
              city="杭州", created_at=4)
    vs.flush()
    assert vs.count() == 3  # 删旧 + 插新，仍为 3

    vs.rebuild()  # 清理
    assert vs.count() == 0
