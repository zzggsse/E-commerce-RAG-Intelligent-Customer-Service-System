"""检索模块：预处理 -> 元数据过滤向量召回 -> Reranker 重排 -> top-N。"""
import logging
import re
from typing import Dict, List, Optional, Tuple

import settings
from app import models, vectorstore

logger = logging.getLogger(__name__)


def preprocess(query: str) -> str:
    """轻量预处理：去多余符号、压缩空白，不做分词避免破坏语义。"""
    text = re.sub(r"[!!?？。，,、~～…\.]{2,}", " ", query)
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"[【】\[\]（）()《》\"'`*#]+", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def retrieve(
    query: str, goods_id: Optional[str] = None, source: Optional[str] = None
) -> Tuple[List[Dict], float]:
    """返回 (top-N 上下文片段, 最高重排分)。"""
    clean_query = preprocess(query)
    candidates = vectorstore.search(
        clean_query, top_k=settings.VECTOR_TOP_K, goods_id=goods_id, source=source
    )
    if not candidates:
        return [], 0.0

    scored = models.rerank(clean_query, candidates)
    best = scored[0][1] if scored else 0.0
    picked = []
    for doc, score in scored[: settings.RERANK_TOP_N]:
        if score < settings.RERANK_SCORE_THRESHOLD:
            continue  # 低相关片段直接丢掉，减少幻觉素材
        doc = dict(doc)
        doc["rerank_score"] = round(score, 4)
        picked.append(doc)
    logger.info("重排后保留 %d 条，最高分 %.4f", len(picked), best)
    return picked, best


def build_context(docs: List[Dict]) -> str:
    """拼接上下文，带来源编号，方便大模型引用、也便于排查。"""
    blocks = []
    for i, doc in enumerate(docs, 1):
        tag = "商品资料" if doc.get("doc_type") == "goods" else "售后政策"
        gid = doc.get("goods_id") or "通用"
        blocks.append(
            f"[资料{i}] 类型={tag} 商品={gid} 来源={doc.get('source')}\n{doc['content']}"
        )
    return "\n\n".join(blocks)
