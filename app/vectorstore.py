"""向量库：Milvus 后端实现 + 本地后端的统一分发。

设 settings.VECTOR_BACKEND="local"（或 "demo"）时切换到内存向量库，
接口完全一致，便于没有 Milvus / 不想下载模型时的演示与出图。
"""
import logging
import time
import uuid
from typing import Dict, List, Optional

import settings

logger = logging.getLogger(__name__)

_collection = None

FIELD_MAX_LEN = {
    "content": 4000,
    "doc_type": 32,
    "goods_id": 64,
    "category": 64,
    "source": 256,
}


def _local() -> bool:
    return getattr(settings, "VECTOR_BACKEND", "milvus").lower() in ("local", "demo")


def connect() -> None:
    if _local():
        return
    from pymilvus import connections

    if connections.has_connection("default"):
        return
    connections.connect(
        alias="default", host=settings.MILVUS_HOST, port=str(settings.MILVUS_PORT)
    )
    logger.info("已连接 Milvus %s:%s", settings.MILVUS_HOST, settings.MILVUS_PORT)


def get_collection():
    if _local():
        from app import local_store
        return local_store.get_collection()
    global _collection
    if _collection is not None:
        return _collection
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility

    connect()
    name = settings.MILVUS_COLLECTION
    if not utility.has_collection(name):
        fields = [
            FieldSchema("pk", DataType.VARCHAR, is_primary=True, max_length=64),
            FieldSchema("content", DataType.VARCHAR, max_length=FIELD_MAX_LEN["content"]),
            FieldSchema("doc_type", DataType.VARCHAR, max_length=FIELD_MAX_LEN["doc_type"]),
            FieldSchema("goods_id", DataType.VARCHAR, max_length=FIELD_MAX_LEN["goods_id"]),
            FieldSchema("category", DataType.VARCHAR, max_length=FIELD_MAX_LEN["category"]),
            FieldSchema("source", DataType.VARCHAR, max_length=FIELD_MAX_LEN["source"]),
            FieldSchema("chunk_index", DataType.INT64),
            FieldSchema("created_at", DataType.INT64),
            FieldSchema("vector", DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM),
        ]
        schema = CollectionSchema(fields, description="电商 RAG 知识库")
        col = Collection(name, schema)
        col.create_index(
            "vector",
            {
                "index_type": settings.MILVUS_INDEX_TYPE,
                "metric_type": settings.MILVUS_METRIC_TYPE,
                "params": settings.MILVUS_INDEX_PARAMS,
            },
        )
        logger.info("已创建集合 %s", name)
    else:
        col = Collection(name)
    col.load()
    _collection = col
    return _collection


def insert_chunks(chunks: List[Dict]) -> int:
    if _local():
        from app import local_store
        return local_store.insert_chunks(chunks)
    if not chunks:
        return 0
    from app import models
    col = get_collection()
    vectors = models.embed_documents([c["content"] for c in chunks])
    now = int(time.time())
    rows = []
    for chunk, vector in zip(chunks, vectors):
        rows.append(
            {
                "pk": uuid.uuid4().hex,
                "content": chunk["content"][: FIELD_MAX_LEN["content"]],
                "doc_type": chunk["doc_type"][: FIELD_MAX_LEN["doc_type"]],
                "goods_id": str(chunk.get("goods_id", ""))[: FIELD_MAX_LEN["goods_id"]],
                "category": str(chunk.get("category", ""))[: FIELD_MAX_LEN["category"]],
                "source": str(chunk.get("source", ""))[: FIELD_MAX_LEN["source"]],
                "chunk_index": int(chunk.get("chunk_index", 0)),
                "created_at": now,
                "vector": vector,
            }
        )
    col.insert(rows)
    col.flush()
    logger.info("写入 %d 个切片", len(rows))
    return len(rows)


def build_filter_expr(goods_id: Optional[str], doc_type: Optional[str] = None, source: Optional[str] = None) -> str:
    """构造元数据过滤表达式 —— 解决跨商品信息混淆的核心。"""
    if _local():
        from app import local_store
        return local_store.build_filter_expr(goods_id, doc_type, source)
    parts = []
    if goods_id:
        safe = str(goods_id).replace('"', "")
        parts.append(f'(goods_id == "{safe}" or goods_id == "")')
    if doc_type:
        parts.append(f'doc_type == "{doc_type}"')
    if source:
        safe_src = str(source).replace('"', "")
        parts.append(f'source == "{safe_src}"')
    return " and ".join(parts)


def search(
    query: str,
    top_k: Optional[int] = None,
    goods_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict]:
    if _local():
        from app import local_store
        return local_store.search(query, top_k, goods_id, doc_type, source)
    from app import models
    col = get_collection()
    top_k = top_k or settings.VECTOR_TOP_K
    expr = build_filter_expr(goods_id, doc_type, source)
    vector = models.embed_query(query)
    results = col.search(
        data=[vector],
        anns_field="vector",
        param={
            "metric_type": settings.MILVUS_METRIC_TYPE,
            "params": settings.MILVUS_SEARCH_PARAMS,
        },
        limit=top_k,
        expr=expr or None,
        output_fields=["content", "doc_type", "goods_id", "category", "source", "chunk_index"],
    )
    docs = []
    for hit in (results[0] if results else []):
        entity = hit.entity
        docs.append(
            {
                "content": entity.get("content"),
                "doc_type": entity.get("doc_type"),
                "goods_id": entity.get("goods_id"),
                "category": entity.get("category"),
                "source": entity.get("source"),
                "chunk_index": entity.get("chunk_index"),
                "vector_score": float(hit.score),
            }
        )
    logger.info("向量召回 %d 条 (expr=%s)", len(docs), expr or "无")
    return docs


def delete_by_source(source: str, goods_id: str = "", doc_type: str = "") -> int:
    """按来源删除切片：用于文件更新时先删旧的再插入新的。"""
    if _local():
        from app import local_store
        return local_store.delete_by_source(source, goods_id, doc_type)
    col = get_collection()
    parts = ['source == "%s"' % source.replace('"', '\\"')]
    if goods_id:
        parts.append('goods_id == "%s"' % goods_id.replace('"', '\\"'))
    if doc_type:
        parts.append('doc_type == "%s"' % doc_type.replace('"', '\\"'))
    expr = " and ".join(parts)
    try:
        res = col.delete(expr)
        return res.delete_count if hasattr(res, "delete_count") else len(res or [])
    except Exception as exc:
        logger.warning("按源删除失败: %s", exc)
        return 0

def list_sources() -> List[Dict]:
    """按来源聚合列出知识库中的文档：source / doc_type / goods_id / 切片数。"""
    if _local():
        from app import local_store
        return local_store.list_sources()
    col = get_collection()
    rows = col.query(expr="", output_fields=["source", "doc_type", "goods_id"], limit=16384)
    agg = {}
    for r in rows:
        key = (r.get("source", "") or "", r.get("doc_type", "") or "", r.get("goods_id", "") or "")
        agg[key] = agg.get(key, 0) + 1
    out = [
        {"source": k[0], "doc_type": k[1], "goods_id": k[2], "chunk_count": v}
        for k, v in agg.items()
    ]
    out.sort(key=lambda x: x["source"])
    return out


def search_content(
    keyword: str,
    goods_id: str = "",
    doc_type: str = "",
    limit: int = 200,
) -> List[Dict]:
    """按关键词在内容/来源名中检索切片，用于知识库管理页快速定位要删的内容。"""
    if _local():
        from app import local_store
        return local_store.search_content(keyword, goods_id, doc_type, limit)
    kw = (keyword or "").strip()
    if not kw:
        return []
    col = get_collection()
    expr = '(content like "%%%s%%" or source like "%%%s%%")' % (kw.replace('"', '\\"'), kw.replace('"', '\\"'))
    if goods_id:
        expr += ' and (goods_id == "%s" or goods_id == "")' % goods_id.replace('"', '\\"')
    if doc_type:
        expr += ' and doc_type == "%s"' % doc_type.replace('"', '\\"')
    try:
        rows = col.query(
            expr=expr,
            output_fields=["source", "doc_type", "goods_id", "content", "chunk_index"],
            limit=limit,
        )
    except Exception as exc:
        logger.warning("内容检索失败: %s", exc)
        return []
    out = []
    for r in rows:
        out.append({
            "source": r.get("source", ""),
            "doc_type": r.get("doc_type", ""),
            "goods_id": r.get("goods_id", ""),
            "content": r.get("content", ""),
            "chunk_index": int(r.get("chunk_index", 0)),
        })
    return out


def delete_by_content_hash(
    doc_hash: str,
    goods_id: str = "",
    doc_type: str = "",
) -> List[Dict]:
    """按内容指纹识别旧副本并删除（解决改名/重复上传的自动替换合并）。
    对每个来源（同一 source+goods_id+doc_type）按 chunk_index 拼接出指纹，
    指纹与目标一致则整个来源删除。返回被删除的来源列表。"""
    if _local():
        from app import local_store
        return local_store.delete_by_content_hash(doc_hash, goods_id, doc_type)
    from app import fingerprint
    col = get_collection()
    rows = col.query(
        expr="", output_fields=["source", "doc_type", "goods_id", "content", "chunk_index"],
        limit=16384,
    )
    groups = {}
    for r in rows:
        if doc_type and (r.get("doc_type") or "") != doc_type:
            continue
        if goods_id and (r.get("goods_id") or "") not in (goods_id, ""):
            continue
        key = (r.get("source") or "", r.get("goods_id") or "", r.get("doc_type") or "")
        groups.setdefault(key, []).append((int(r.get("chunk_index", 0)), r.get("content", "")))
    deleted = []
    for (src, gid, dt), items in groups.items():
        items.sort(key=lambda x: x[0])
        fp = fingerprint.content_hash(c for _, c in items)
        if fp == doc_hash:
            n = delete_by_source(src, gid, dt)
            deleted.append({"source": src, "goods_id": gid, "doc_type": dt, "chunk_count": n})
    if deleted:
        logger.info("按内容指纹替换旧副本 %d 份(hash=%s...)", len(deleted), doc_hash[:8])
    return deleted


def product_catalog(limit_each: int = 60000) -> List[Dict]:
    """汇总所有商品的简介（每个来源取首个片段），用于「选购/推荐」类问题兜底。"""
    if _local():
        from app import local_store
        return local_store.product_catalog(limit_each)
    col = get_collection()
    rows = col.query(
        expr='(doc_type == "goods" or goods_id != "")',
        output_fields=["source", "goods_id", "content", "chunk_index"],
        limit=16384,
    )
    groups = {}
    for r in rows:
        key = (r.get("source") or "", r.get("goods_id") or "")
        groups.setdefault(key, []).append((int(r.get("chunk_index", 0)), r.get("content", "")))
    out = []
    for (src, gid), items in groups.items():
        items.sort(key=lambda x: x[0])
        # 汇总该商品全部片段的完整文本，用于「选购/推荐」按方面打分
        full = "\n".join(str(it[1]) for it in items if it[1])
        out.append({"source": src, "goods_id": gid, "content": full[:limit_each]})
    out.sort(key=lambda x: (x["goods_id"], x["source"]))
    return out


def count() -> int:
    if _local():
        from app import local_store
        return local_store.count()
    col = get_collection()
    try:
        # num_entities 在删除后会滞后（残留 tombstone），改为统计实际行数
        rows = col.query(expr="", output_fields=["pk"], limit=16384)
        return len(rows)
    except Exception:
        return col.num_entities


def drop_collection() -> None:
    if _local():
        from app import local_store
        return local_store.drop_collection()
    from pymilvus import utility

    global _collection
    connect()
    if utility.has_collection(settings.MILVUS_COLLECTION):
        utility.drop_collection(settings.MILVUS_COLLECTION)
    _collection = None
