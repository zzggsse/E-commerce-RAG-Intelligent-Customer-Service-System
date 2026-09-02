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


def build_filter_expr(goods_id=None, doc_type=None, source=None):
    """与 Milvus 版本同语义的过滤（本地用 Python 过滤实现）。"""
    parts = []
    if goods_id:
        parts.append('(goods_id == "%s" or goods_id == "")' % goods_id)
    if doc_type:
        parts.append('doc_type == "%s"' % doc_type)
    if source:
        parts.append('source == "%s"' % source)
    return " and ".join(parts) if parts else ""


def _match(chunk, goods_id, doc_type, source=None):
    if doc_type and chunk.get("doc_type") != doc_type:
        return False
    if source and chunk.get("source") != source:
        return False
    if goods_id:
        return chunk.get("goods_id") in (goods_id, "")
    return True


def search(query, top_k=None, goods_id=None, doc_type=None, source=None):
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
        if not _match(c, goods_id, doc_type, source):
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


def delete_by_source(source, goods_id="", doc_type=""):
    """按来源删除切片（本地后端），用于文件更新时先删旧再插新。返回删除条数。"""
    state = _load()
    kept = []
    removed = 0
    for c in state["chunks"]:
        if c.get("source") != source:
            kept.append(c)
            continue
        if goods_id and c.get("goods_id") != goods_id:
            kept.append(c)
            continue
        if doc_type and c.get("doc_type") != doc_type:
            kept.append(c)
            continue
        removed += 1
    if removed:
        state["chunks"] = kept
        _save()
        logger.info("本地按源删除 %d 条(source=%s)", removed, source)
    return removed


def list_sources():
    """本地后端：按来源聚合列出文档。"""
    agg = {}
    for c in _load()["chunks"]:
        key = (c.get("source", ""), c.get("doc_type", ""), c.get("goods_id", ""))
        agg[key] = agg.get(key, 0) + 1
    out = [
        {"source": k[0], "doc_type": k[1], "goods_id": k[2], "chunk_count": v}
        for k, v in agg.items()
    ]
    out.sort(key=lambda x: x["source"])
    return out


def search_content(keyword, goods_id="", doc_type="", limit=200):
    """本地后端：按关键词在内容/来源名中检索切片。"""
    kw = (keyword or "").strip().lower()
    if not kw:
        return []
    out = []
    for c in _load()["chunks"]:
        if not (kw in c.get("content", "").lower() or kw in c.get("source", "").lower()):
            continue
        if not _match(c, goods_id, doc_type, source):
            continue
        out.append({
            "source": c.get("source", ""),
            "doc_type": c.get("doc_type", ""),
            "goods_id": c.get("goods_id", ""),
            "content": c.get("content", ""),
            "chunk_index": int(c.get("chunk_index", 0)),
        })
        if len(out) >= limit:
            break
    return out


def delete_by_content_hash(doc_hash, goods_id="", doc_type=""):
    """本地后端：按内容指纹识别旧副本并删除（改名/重复自动替换合并）。"""
    from app import fingerprint
    groups = {}
    for c in _load()["chunks"]:
        if doc_type and (c.get("doc_type") or "") != doc_type:
            continue
        if goods_id and (c.get("goods_id") or "") not in (goods_id, ""):
            continue
        key = (c.get("source", ""), c.get("goods_id", ""), c.get("doc_type", ""))
        groups.setdefault(key, []).append((int(c.get("chunk_index", 0)), c.get("content", "")))
    deleted = []
    for (src, gid, dt), items in groups.items():
        items.sort(key=lambda x: x[0])
        fp = fingerprint.content_hash(c for _, c in items)
        if fp == doc_hash:
            n = delete_by_source(src, gid, dt)
            deleted.append({"source": src, "goods_id": gid, "doc_type": dt, "chunk_count": n})
    if deleted:
        logger.info("本地按内容指纹替换旧副本 %d 份(hash=%s...)", len(deleted), doc_hash[:8])
    return deleted


def product_catalog(limit_each=60000):
    """本地后端：汇总所有商品的简介（每个来源取首个片段）。"""
    groups = {}
    for c in _load()["chunks"]:
        if c.get("doc_type") != "goods" and not c.get("goods_id"):
            continue
        key = (c.get("source", ""), c.get("goods_id", ""))
        groups.setdefault(key, []).append((int(c.get("chunk_index", 0)), c.get("content", "")))
    out = []
    for (src, gid), items in groups.items():
        items.sort(key=lambda x: x[0])
        # 汇总该商品全部片段的完整文本，用于「选购/推荐」按方面打分
        full = "\n".join(str(it[1]) for it in items if it[1])
        out.append({"source": src, "goods_id": gid, "content": full[:limit_each]})
    out.sort(key=lambda x: (x["goods_id"], x["source"]))
    return out


def count():
    return len(_load()["chunks"])


def drop_collection():
    global _state
    _state = {"chunks": []}
    p = _db_path()
    if p.exists():
        os.remove(p)
