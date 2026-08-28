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


def build_filter_expr(goods_id: Optional[str], doc_type: Optional[str] = None) -> str:
    """构造元数据过滤表达式 —— 解决跨商品信息混淆的核心。"""
    if _local():
        from app import local_store
        return local_store.build_filter_expr(goods_id, doc_type)
    parts = []
    if goods_id:
        safe = str(goods_id).replace('"', "")
        parts.append(f'(goods_id == "{safe}" or goods_id == "")')
    if doc_type:
        parts.append(f'doc_type == "{doc_type}"')
    return " and ".join(parts)


def search(
    query: str,
    top_k: Optional[int] = None,
    goods_id: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> List[Dict]:
    if _local():
        from app import local_store
        return local_store.search(query, top_k, goods_id, doc_type)
    from app import models
    col = get_collection()
    top_k = top_k or settings.VECTOR_TOP_K
    expr = build_filter_expr(goods_id, doc_type)
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


def count() -> int:
    if _local():
        from app import local_store
        return local_store.count()
    col = get_collection()
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