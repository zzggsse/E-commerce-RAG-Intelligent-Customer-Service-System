"""RAG 主链路：风控 -> 会话上下文 -> 检索重排 -> 生成 -> 转人工判定 -> 统计。"""
import logging
import re
import time
from typing import Dict, List, Optional

import settings
from app import guard, prompts, retriever, session as session_store, stats

logger = logging.getLogger(__name__)
_llm = None


def _llm_enabled() -> bool:
    """未配置 LLM API Key 时走本地演示模式。"""
    key = getattr(settings, "LLM_API_KEY", "")
    return bool(key) and key not in ("", "sk-请填写你的key", "sk-你的key")

def get_llm():
    global _llm
    if _llm is None:
        from langchain_openai import ChatOpenAI

        _llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            timeout=settings.LLM_TIMEOUT,
        )
    return _llm


_NEED_HUMAN_RE = re.compile(r"NEED_HUMAN\s*[:：]\s*(true|false)", re.I)


def _split_flag(text: str):
    """剥离模型输出末尾的 NEED_HUMAN 标记。"""
    match = _NEED_HUMAN_RE.search(text or "")
    flag = bool(match and match.group(1).lower() == "true")
    answer = _NEED_HUMAN_RE.sub("", text or "").strip()
    return answer, flag


def chat(query: str, session_id: str = "default", goods_id: Optional[str] = None) -> Dict:
    started = time.time()
    query = (query or "").strip()
    if not query:
        return _reply("请描述一下您的问题，我来帮您查询～", False, "", session_id, "", [], 0, 0, True, query)

    # 1) 敏感词拦截：直接短路，不进检索也不进大模型
    hit, word = guard.check_sensitive(query)
    if hit:
        logger.warning("敏感词拦截: %s", word)
        return _reply(
            settings.SENSITIVE_REPLY, True, f"敏感词:{word}", session_id, "", [],
            0, int((time.time() - started) * 1000), True, query,
        )

    # 2) 会话上下文：补齐 goods_id，实现追问不丢商品
    effective_goods_id = session_store.resolve_goods_id(session_id, goods_id, query)
    repeat_times = session_store.record_query(session_id, query)

    # 3) 检索 + 重排
    try:
        docs, top_score = retriever.retrieve(query, goods_id=effective_goods_id)
    except Exception as exc:  # Milvus 未就绪等异常，降级为转人工而不是抛 500
        logger.exception("检索失败")
        return _reply(
            "系统正在维护知识库，已为您转接人工客服，抱歉～", True,
            f"检索异常:{type(exc).__name__}", session_id, effective_goods_id,
            [], 0.0, int((time.time() - started) * 1000), False, query,
        )
    sources = sorted({d.get("source", "") for d in docs if d.get("source")})

    # 4) 知识库无答案：不喂大模型，直接转人工（最强的幻觉抑制手段）
    if not docs or top_score < settings.NO_ANSWER_THRESHOLD:
        answer = settings.NO_ANSWER_REPLY
        session_store.append_turn(session_id, query, answer)
        return _reply(
            answer, True, "知识库无答案", session_id, effective_goods_id, docs,
            top_score, int((time.time() - started) * 1000), kb_hit=False, query=query,
        )

    # 5) 生成

    if not _llm_enabled():
        top = docs[0]["content"] if docs else settings.NO_ANSWER_REPLY
        answer, need_human = top, False
        reasons = []
        negative, word = guard.check_negative(query)
        if negative:
            need_human = True
            reasons.append(f"负面情绪:{word}")
        if repeat_times >= settings.REPEAT_QUESTION_LIMIT:
            need_human = True
            reasons.append("重复质问")
        if top_score < settings.NO_ANSWER_THRESHOLD:
            need_human = True
            reasons.append("关联度不足")
        logger.info("演示模式(未配置LLM)，返回 top 命中原文")
        return _reply(answer, need_human, ",".join(reasons), session_id, effective_goods_id,
                      docs, top_score, int((time.time() - started) * 1000), True, query)
    context = retriever.build_context(docs)
    history = session_store.get_history_text(session_id) or "（无）"
    messages = prompts.CHAT_PROMPT.format_messages(
        goods_id=effective_goods_id or "未指定",
        history=history,
        context=context,
        query=query,
    )
    try:
        raw = get_llm().invoke(messages).content
    except Exception as exc:
        logger.exception("大模型调用失败")
        answer = "系统当前繁忙，已为您转接人工客服，抱歉～"
        return _reply(
            answer, True, f"LLM异常:{type(exc).__name__}", session_id,
            effective_goods_id, docs, top_score,
            int((time.time() - started) * 1000), True, query,
        )

    answer, need_human = _split_flag(raw)

    # 6) 兜底转人工规则（不完全依赖模型自评）
    reasons: List[str] = []
    if need_human:
        reasons.append("模型判定")
    negative, word = guard.check_negative(query)
    if negative:
        need_human = True
        reasons.append(f"负面情绪:{word}")
    if repeat_times >= settings.REPEAT_QUESTION_LIMIT:
        need_human = True
        reasons.append("重复质问")
    if settings.NO_ANSWER_REPLY[:10] in answer:
        need_human = True
        reasons.append("资料不足")

    if need_human and "人工" not in answer:
        answer = f"{answer}\n如需进一步核实，已为您转接人工客服～"

    session_store.append_turn(session_id, query, answer)
    return _reply(
        answer, need_human, ",".join(reasons), session_id, effective_goods_id,
        docs, top_score, int((time.time() - started) * 1000), True, query,
    )


def _reply(answer, need_human, reason, session_id, goods_id, docs, top_score, latency, kb_hit, query=""):
    sources = sorted({d.get("source", "") for d in docs if d.get("source")})
    stats.log_qa(
        session_id=session_id, goods_id=goods_id, query=query, answer=answer,
        need_human=need_human, human_reason=reason, kb_hit=kb_hit,
        top_score=top_score, recall_count=len(docs), latency_ms=latency,
        sources=sources,
    )
    result = {
        "answer": answer,
        "need_human": need_human,
        "human_reason": reason,
        "session_id": session_id,
        "goods_id": goods_id,
        "kb_hit": kb_hit,
        "top_score": round(top_score, 4),
        "latency_ms": latency,
        "sources": sources,
        "references": [
            {
                "source": d.get("source"),
                "doc_type": d.get("doc_type"),
                "goods_id": d.get("goods_id"),
                "rerank_score": d.get("rerank_score"),
                "preview": (d.get("content") or "")[:120],
            }
            for d in docs
        ],
    }
    logger.info(
        "QA session=%s goods=%s need_human=%s kb_hit=%s score=%.3f %dms",
        session_id, goods_id, need_human, kb_hit, top_score, latency,
    )
    return result