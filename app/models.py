"""模型加载：Embedding 与 Reranker 懒加载单例。

直接持有 SentenceTransformer 单例（比 langchain 的 HuggingFaceEmbeddings
包装层更稳，避免其每次 encode 前重新探测/加载模型导致的卡顿）。

三档 Reranker：
  local      -> 本地 CrossEncoder
  dashscope  -> 阿里 DashScope rerank API
  none       -> 跳过重排，直接用向量相似度
"""
import logging
import os
import threading
from pathlib import Path

import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_st_model = None
_reranker = None


def _prepare_env(cache_dir: str) -> None:
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", cache_dir)
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", cache_dir)
    os.environ.setdefault("TRANSFORMERS_CACHE", cache_dir)


def _resolve_model_path(name: str) -> str:
    local = Path(name)
    if local.exists() and local.is_dir():
        return str(local)
    if local.is_absolute() or local.exists():
        return str(local)
    candidate = Path(settings.MODEL_CACHE_DIR) / name.split("/")[-1]
    if candidate.exists() and candidate.is_dir():
        return str(candidate)
    return name  # 否则按 HF 模型名处理


def _get_st_model():
    global _st_model
    if _st_model is not None:
        return _st_model
    with _lock:
        if _st_model is None:
            from sentence_transformers import SentenceTransformer

            _prepare_env(settings.MODEL_CACHE_DIR)
            path = _resolve_model_path(settings.EMBEDDING_MODEL)
            logger.info("加载 Embedding 模型: %s", path)
            _st_model = SentenceTransformer(path, device=settings.EMBEDDING_DEVICE)
    return _st_model


def embed_query(text: str):
    """查询向量化：bge 官方要求 query 加检索指令前缀。"""
    model = _get_st_model()
    return model.encode(
        [settings.EMBEDDING_QUERY_INSTRUCTION + text],
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0].tolist()


def embed_documents(texts):
    model = _get_st_model()
    return model.encode(
        list(texts), normalize_embeddings=True, show_progress_bar=False
    ).tolist()


def get_reranker():
    global _reranker
    if _reranker is not None:
        return _reranker
    with _lock:
        if _reranker is None:
            from sentence_transformers import CrossEncoder

            _prepare_env(settings.MODEL_CACHE_DIR)
            path = _resolve_model_path(settings.RERANKER_MODEL)
            logger.info("加载 Reranker 模型: %s", path)
            _reranker = CrossEncoder(
                path, device=settings.EMBEDDING_DEVICE,
                cache_folder=settings.MODEL_CACHE_DIR,
            )
    return _reranker


def rerank(query: str, docs):
    """对候选片段重排，返回 [(doc, score)]，score 归一化到 0~1。"""
    if not docs:
        return []

    backend = getattr(settings, "RERANK_BACKEND", "local").lower()
    if backend == "dashscope":
        return _rerank_dashscope(query, docs)
    if backend == "none":
        return sorted(
            ((d, max(0.0, float(d.get("vector_score", 0.0)))) for d in docs),
            key=lambda x: x[1], reverse=True,
        )

    import math
    model = get_reranker()
    pairs = [(query, d["content"]) for d in docs]
    raw_scores = model.predict(pairs)
    scored = []
    for doc, raw in zip(docs, raw_scores):
        score = 1 / (1 + math.exp(-float(raw)))
        scored.append((doc, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _rerank_dashscope(query: str, docs):
    import json
    import urllib.request

    payload = json.dumps(
        {
            "model": getattr(settings, "RERANK_DASHSCOPE_MODEL", "gte-rerank-v2"),
            "input": {"query": query, "documents": [d["content"] for d in docs]},
            "parameters": {"top_n": len(docs), "return_documents": False},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        settings.RERANK_API_URL, data=payload,
        headers={"Authorization": f"Bearer {settings.RERANK_API_KEY}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=settings.LLM_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    scored = [
        (docs[item["index"]], float(item["relevance_score"]))
        for item in data["output"]["results"]
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored