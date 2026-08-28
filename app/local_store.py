"""本地内存向量库后端（可直接用整数分，无需真向量，用于无 Milvus 时可运行）。

接口与 vectorstore.py（Milvus）保持一致：insert_chunks / search / count / build_filter_expr，
由 app/vectorstore.py 按 settings.VECTOR_BACKEND 分发。数据落盘 JSON，重启不丢。
存储路径：settings.LOCAL_VECTOR_DB（默认 logs/local_kb.json）
"""
# -*- coding: utf-8 -*-
import json
import logging
import os
import uuid
from pathlib import Path

import settings
from app import models

logger = logging.getLogger(__name__)

_state = None  # {chunks: [ {content,...,vec:[...]} ]}


def _db_path() -> Path:
    return Path(getattr(settings, "LOCAL_VECTOR_DB", str(Path(settings.LOG_DIR) / "local_kb.json")))


def _load():
    global _state
    if _state is None:
        p = _db_path()
        if p.exists():
            try:
                _state = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                _state = {"chunks": []}
        else:
            _state = {"chunks": []}
    return _state


def get_collection():
    """兼容 vectorstore 公共接口（本地后端无实际集合）。"""
    _load()
    return None

def _save():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_state, ensure_ascii=False), encoding="utf-8")


def build_filter_expr(goods_id=None, doc_type=None):
    """与 Milvus 版本同语义的过滤（本地用 Python 过滤实现）。"""
    parts = []
    if goods_id:
        parts.append('(goods_id == "%s" or goods_id == "")' % goods_id)
    if doc_type:
        parts.append('doc_type == "%s"' % doc_type)
    return " and ".join(parts) if parts else ""


def _match(chunk, goods_id, doc_type):
    if doc_type and chunk.get("doc_type") != doc_type:
        return False
    if goods_id:
        return chunk.get("goods_id") in (goods_id, "")
    return True


def search(query, top_k=None, goods_id=None, doc_type=None):
    from app.retriever import preprocess
    top_k = top_k or settings.VECTOR_TOP_K
    qvec = models.embed_query(preprocess(query))
    import math

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    def norm(v):
        return math.sqrt(dot(v, v)) or 1.0

    scored = []
    for c in _load()["chunks"]:
        if not _match(c, goods_id, doc_type):
            continue
        sim = dot(qvec, c["vec"]) / (norm(qvec) * norm(c["vec"]))
        scored.append((c, max(0.0, min(1.0, sim))))
    scored.sort(key=lambda x: x[1], reverse=True)
    out = []
    for c, sim in scored[:top_k]:
        out.append({
            "content": c["content"],
            "doc_type": c.get("doc_type", ""),
            "goods_id": c.get("goods_id", ""),
            "category": c.get("category", ""),
            "source": c.get("source", ""),
            "chunk_index": c.get("chunk_index", 0),
            "vector_score": sim,
        })
    logger.info("本地向量召回 %d 条 (top_k=%s)", len(out), top_k)
    return out


def insert_chunks(chunks):
    if not chunks:
        return 0
    state = _load()
    vectors = models.embed_documents([c["content"] for c in chunks])
    for c, v in zip(chunks, vectors):
        state["chunks"].append({
            "pk": uuid.uuid4().hex,
            "content": c["content"],
            "doc_type": c.get("doc_type", ""),
            "goods_id": c.get("goods_id", ""),
            "category": c.get("category", ""),
            "source": c.get("source", ""),
            "chunk_index": int(c.get("chunk_index", 0)),
            "vec": v,
        })
    _save()
    logger.info("本地写入 %d 个切片", len(chunks))
    return len(chunks)


def count():
    return len(_load()["chunks"])


def drop_collection():
    global _state
    _state = {"chunks": []}
    p = _db_path()
    if p.exists():
        os.remove(p)