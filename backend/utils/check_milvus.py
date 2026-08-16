#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Milvus 连通性自检工具
=====================

用途
----
1. 确认能否连上你的 Milvus 服务（默认 http://192.168.1.9:19530）。
2. 为「把 FAISS 换成 Milvus」探路：建一张临时 collection，schema 完全对齐
   现有 src/rag/vector_store.py 的字段（1024 维 bge-m3 向量 / COSINE / url+source_type+title+text），
   做 插入 → 建索引 → 检索 → 删除 全链路验证，跑完自动清理，不留残留。

用法
----
    # 用环境变量指定地址（可选，默认见下）
    set MILVUS_URL=http://192.168.1.9:19530
    # 若 Milvus 开启了鉴权，再设 token
    set MILVUS_TOKEN=root:Milvus

    # 用项目 venv 运行
    .venv/Scripts/python.exe utils/check_milvus.py
    # 只测连通性、跳过建表往返（更快）
    .venv/Scripts/python.exe utils/check_milvus.py --quick

退出码：0 = 正常，1 = 异常。
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys

try:
    from pymilvus import (
        DataType,
        FieldSchema,
        CollectionSchema,
        MilvusClient,
        MilvusException,
    )
except ImportError:  # pragma: no cover
    sys.exit("❌ 未安装 pymilvus：请先 `pip install pymilvus` 后重试")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("check_milvus")

# 对齐现有 FAISS VectorStore：bge-m3 输出 1024 维；FAISS 用归一化内积≈余弦，
# 这里直接上 COSINE 索引，行为一致。
EMBED_DIM = 1024
TEST_COLLECTION = "tmp_connectivity_check"
DEFAULT_URL = "http://192.168.1.9:19530"


def _banner(title: str) -> None:
    log.info("\n" + "=" * 60)
    log.info(title)
    log.info("=" * 60)


def _rand_unit_vec(dim: int) -> list[float]:
    """生成随机单位向量（模拟一段 embedding）。"""
    v = [random.uniform(-1.0, 1.0) for _ in range(dim)]
    norm = (sum(x * x for x in v)) ** 0.5 or 1.0
    return [x / norm for x in v]


def build_client(url: str, token: str) -> MilvusClient:
    kwargs: dict = {"uri": url}
    if token:
        kwargs["token"] = token
    return MilvusClient(**kwargs)


def connectivity_only(client: MilvusClient) -> int:
    """只验证连通性。"""
    _banner("2. 连通性验证")
    try:
        ver = client.get_server_version()
        log.info(f"  ✓ 连接成功，服务端版本: {ver}")
        return 0
    except MilvusException as e:
        log.error(f"  ✗ 连接失败: {e}")
        return 1
    except Exception as e:  # 非 Milvus 异常（如网络不可达）
        log.error(f"  ✗ 连接异常: {e}")
        return 1


def roundtrip(client: MilvusClient) -> int:
    """建表 → 插入 → 建索引 → 检索 → 删除 全链路。"""
    _banner("3. 全链路往返测试（建表→插入→索引→检索→删除）")
    try:
        # 防残留：若上次异常没清掉，先删
        if client.has_collection(TEST_COLLECTION):
            client.drop_collection(TEST_COLLECTION)
            log.info("  · 清理已存在的测试 collection")

        schema = CollectionSchema(
            fields=[
                FieldSchema(name="id", dtype=DataType.INT64,
                            is_primary=True, auto_id=True),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR,
                            dim=EMBED_DIM),
                FieldSchema(name="url", dtype=DataType.VARCHAR, max_length=1024),
                FieldSchema(name="source_type", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
            ],
        )
        client.create_collection(collection_name=TEST_COLLECTION, schema=schema)
        log.info(f"  ✓ 创建临时 collection（dim={EMBED_DIM}）")

        data = [
            {"embedding": _rand_unit_vec(EMBED_DIM), "url": "http://a/1",
             "source_type": "boss", "title": "岗位A", "text": "..."},
            {"embedding": _rand_unit_vec(EMBED_DIM), "url": "http://a/2",
             "source_type": "arxiv", "title": "论文B", "text": "..."},
            {"embedding": _rand_unit_vec(EMBED_DIM), "url": "http://a/3",
             "source_type": "boss", "title": "岗位C", "text": "..."},
        ]
        client.insert(collection_name=TEST_COLLECTION, data=data)
        log.info(f"  ✓ 插入 {len(data)} 条向量")

        # AUTOINDEX 是最省心的选择，standalone / 集群都支持；度量用 COSINE
        idx = client.prepare_index_params()
        idx.add_index(field_name="embedding",
                      index_type="AUTOINDEX",
                      metric_type="COSINE")
        client.create_index(collection_name=TEST_COLLECTION, index_params=idx)
        log.info("  ✓ 创建向量索引（AUTOINDEX / COSINE）")

        client.load_collection(TEST_COLLECTION)
        log.info("  ✓ 加载 collection 到内存（检索前必做）")

        res = client.search(
            collection_name=TEST_COLLECTION,
            data=[_rand_unit_vec(EMBED_DIM)],
            limit=2,
            output_fields=["url", "source_type", "title"],
        )
        hits = res[0]
        log.info(f"  ✓ 检索返回 {len(hits)} 条：")
        for h in hits:
            ent = h.get("entity", {})
            log.info(f"     - {ent.get('title')}  score(distance)={h.get('distance'):.4f}")

        client.drop_collection(TEST_COLLECTION)
        log.info("  ✓ 已删除临时 collection（无残留）")
        return 0
    except MilvusException as e:
        log.error(f"  ✗ 往返测试失败: {e}")
        return 1
    except Exception as e:
        log.error(f"  ✗ 往返测试异常: {e}")
        return 1
    finally:
        # 无论如何都尝试清理，避免留垃圾
        try:
            if client.has_collection(TEST_COLLECTION):
                client.drop_collection(TEST_COLLECTION)
                log.info("  · 兜底清理：已删除测试 collection")
        except Exception:
            pass


def list_existing(client: MilvusClient) -> None:
    _banner("4. 服务端已有 collection")
    try:
        cols = client.list_collections()
        if cols:
            for c in cols:
                log.info(f"  - {c}")
        else:
            log.info("  （空）")
    except Exception as e:
        log.warning(f"  ⚠ 列出 collection 失败: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Milvus 连通性自检")
    ap.add_argument("--url", default=os.getenv("MILVUS_URL", DEFAULT_URL),
                    help=f"Milvus 地址，默认 {DEFAULT_URL}（也可用环境变量 MILVUS_URL）")
    ap.add_argument("--token", default=os.getenv("MILVUS_TOKEN", ""),
                    help="鉴权 token（开启鉴权时填，如 root:Milvus）")
    ap.add_argument("--quick", action="store_true",
                    help="只测连通性，跳过建表往返")
    args = ap.parse_args()

    _banner("1. 连接参数")
    log.info(f"  MILVUS_URL  = {args.url}")
    log.info(f"  MILVUS_TOKEN= {'<已设置>' if args.token else '<空>'}")

    try:
        client = build_client(args.url, args.token)
        log.info("  ✓ MilvusClient 创建成功（注意：真正建连发生在首次请求时）")
    except Exception as e:
        log.error(f"  ✗ 客户端创建失败: {e}")
        return 1

    # 连通性是必测项
    rc = connectivity_only(client)
    if rc != 0:
        _banner("❌ 结论")
        log.info("  连不上 Milvus。常见原因：")
        log.info("    · 地址/端口写错（standalone gRPC 默认 19530）")
        log.info("    · 服务端没起来 / 防火墙挡了 19530")
        log.info("    · 本机与此沙箱不在同一网络（192.168.x.x 是局域网地址）")
        return rc

    if args.quick:
        _banner("✅ 结论")
        log.info("  连通性正常。去掉 --quick 可跑一次建表往返，确认读写能力。")
        return 0

    rc = roundtrip(client)
    # roundtrip 内部已清理；非零直接返回错误
    if rc != 0:
        _banner("❌ 结论")
        log.info("  连通正常，但写入/检索链路有问题，见上方错误。")
        return rc

    # 列出已有 collection（顺带验证，不计入成败）
    list_existing(client)

    _banner("✅ 结论")
    log.info("  Milvus 连接正常，具备 建表/插入/索引/检索/删除 全链路能力。")
    log.info("  后续可参考此 schema 把 src/rag/vector_store.py 的 FAISS 实现替换为 Milvus。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("\n已中断")
        sys.exit(130)
