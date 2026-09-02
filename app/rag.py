"""RAG 主链路：风控 -> 会话上下文 -> 检索重排 -> 生成 -> 转人工判定 -> 统计。"""
import logging
import re
import time
from typing import Dict, List, Optional

import settings
from app import (goods as goods_detect, guard, disambiguate, prompts, retriever, session as session_store, stats, vectorstore)

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



_RECOMMEND_RE = re.compile(r"(?:推荐|哪款|哪一款|哪几款|买哪(?:款|个)|怎么选|选购|对比|适合我|适合买|性价比|有.{1,6}推荐)", re.IGNORECASE)

# 推荐时让用户先选择「更看重哪个方面」的多轮引导选项
ASPECT_OPTIONS = [
    {"key": "jz", "label": "降噪",        "kw": ["降噪", "主动降噪", "enc", "隔音"]},
    {"key": "xh", "label": "续航",        "kw": ["续航", "电量", "电池", "小时"]},
    {"key": "jg", "label": "价格",        "kw": ["价格", "价位", "预算", "元"]},
    {"key": "yq", "label": "音质",        "kw": ["音质", "低音", "高音", "解析", "声音"]},
    {"key": "yx", "label": "游戏 / 低延迟", "kw": ["游戏", "延迟", "电竞", "低延迟"]},
    {"key": "fsh", "label": "防水 / 运动", "kw": ["防水", "ipx", "运动", "汗"]},
]


def _offer_reco_menu(session_id: str, query: str, started: float):
    """第一步：给出「更看重哪个方面」的选项，并记录为待选择状态。"""
    session_store.set_pending_reco(session_id, ASPECT_OPTIONS)
    lines = "\n".join(f"{i}. {o['label']}" for i, o in enumerate(ASPECT_OPTIONS, 1))
    text = ("好的，为了给您推荐更合适的产品，请先告诉我您更看重哪个方面？\n"
            + lines + "\n回复序号或名称（如「2」或「续航」）即可。")
    latency = int((time.time() - started) * 1000)
    return _reply(text, False, "", session_id, "", [], 0.0, latency, True, query, kind="reco")


def _parse_aspect_choice(query: str, pending: list):
    """把用户的回复解析成某个方面选项；不是选项则返回 None。"""
    q = (query or "").strip()
    if q.isdigit():
        idx = int(q) - 1
        return pending[idx] if 0 <= idx < len(pending) else None
    ql = q.lower()
    for o in pending:
        if o["label"] in q:
            return o
    for o in pending:
        if any(k.lower() in ql for k in o["kw"]):
            return o
    return None


def _hits_in(content_lower: str, opt: dict):
    return [k for k in opt["kw"] if k in content_lower]


def _handle_reco_choice(session_id: str, query: str, pending: list, started: float):
    """第二步：根据用户选中的方面，从商品里推荐对应款。"""
    opt = _parse_aspect_choice(query, pending)
    if opt is None:
        return None  # 不是选项内容，交给正常回答，保留待选择状态
    session_store.clear_pending_reco(session_id)
    catalog = vectorstore.product_catalog()
    latency = int((time.time() - started) * 1000)
    scored = []
    for d in catalog:
        text = (d.get("source", "") + "\n" + d.get("content", "")).lower()
        s = sum(text.count(k.lower()) for k in opt["kw"])
        scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    good = [d for s, d in scored if s > 0]
    if good:
        head = f"您更看重「{opt['label']}」，为您推荐：\n"
        for d in good[:2]:
            cl = (d.get("content", "") or "").lower() + (d.get("source", "") or "").lower()
            hits = _hits_in(cl, opt)
            reason = "、".join(hits[:4]) or opt["label"]
            head += f"- [{d.get('goods_id') or '通用'}] {d.get('source')}（{reason}）\n"
        head += "您可以再告诉我预算或具体用途，我帮您进一步对比。"
        return _reply(head, False, "", session_id, "", good, 0.0, latency, True, query, kind="reco")
    text = f"很抱歉，目前商品资料里还没有特别能体现「{opt['label']}」的产品信息。\n店内在售商品：\n"
    text += "\n".join(f"- [{d.get('goods_id') or '通用'}] {d.get('source')}" for d in catalog)
    text += "\n如需进一步核实，可为您转接人工客服～"
    return _reply(text, True, "无对应推荐", session_id, "", catalog, 0.0, latency, True, query, kind="reco")


def _run_recommend_flow(query: str, session_id: str, started: float):
    """多轮选购引导：先问「更看重哪个方面」，再按选项推荐。返回回复或 None（交给正常流程）。"""
    pending = session_store.get_pending_reco(session_id)
    if pending:
        return _handle_reco_choice(session_id, query, pending, started)
    if not _RECOMMEND_RE.search(query or ""):
        return None
    if goods_detect.detect(query):
        return None  # 已指名具体商品，走正常检索推荐
    if not vectorstore.product_catalog():
        return None
    return _offer_reco_menu(session_id, query, started)



def _clarify_reply(session_id: str, query: str, options: list, started: float):
    """尚未确宩：给出可选对象，让用户输数字确认。"""
    lines = "\n".join(f"{i}. {o['label']}" for i, o in enumerate(options, 1))
    text = ("根据上文，我判断您想了解的可能是：\n"
            + lines + "\n如果不是，请输入对应数字（如「1」），或用更完整的话描述一下。")
    latency = int((time.time() - started) * 1000)
    return _reply(text, False, "", session_id, "", [], 0.0, latency, True, query, kind="clarify")


def _run_clarify_flow(session_id: str, query: str, started: float):
    """处理已挂起的峺义确认；无挂起则返回 None。
    确认成功返回 {"kind":"resolve", "goods_id":.., "source":..} 给调用方继续检索；
    非合法输入返回 {"kind":"reply", "reply":..} 重发菜单。"""
    pending = session_store.get_pending_clarify(session_id)
    if not pending:
        return None
    opt = disambiguate.parse_choice(query, pending)
    if opt is None:
        return {"kind": "reply", "reply": _clarify_reply(session_id, query, pending, started)}
    session_store.clear_pending_clarify(session_id)
    return {"kind": "resolve", "goods_id": opt.get("goods_id") or "", "source": opt.get("source") or ""}


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

    # 1.1) 负面情绪识别：提前检测，抱怨/情绪激动直接转人工，不等知识库查询
    neg_hit, neg_word = guard.check_negative(query)
    if neg_hit:
        logger.warning("负面情绪：%s", neg_word)
        return _reply(
            settings.NEGATIVE_REPLY, True, f"负面情绪:{neg_word}", session_id, "", [],
            0, int((time.time() - started) * 1000), True, query,
        )

    # 峺义澄清：处理上一轮已挂起的「您指的是哪个」确认
    resolve_gid, resolve_src = "", ""
    clar = _run_clarify_flow(session_id, query, started)
    if clar is not None:
        if clar.get("kind") == "reply":
            return clar["reply"]
        resolve_gid = clar.get("goods_id") or ""
        resolve_src = clar.get("source") or ""

    # 选购/推荐多轮引导：先问「更看重哪个方面」，再按选择推荐
    reco = _run_recommend_flow(query, session_id, started)
    if reco:
        return reco

    # 2) 提问自动识别商品：用户问题里自带商品名（如「xx耳机售后期有几天」）
    if not goods_id:
        goods_id = goods_detect.detect(query) or None
    if resolve_gid:
        goods_id = resolve_gid
    # 3) 会话上下文：补齐 goods_id，实现追问不丢商品
    effective_goods_id = session_store.resolve_goods_id(session_id, goods_id, query)
    repeat_times = session_store.record_query(session_id, query)

    # 3) 检索 + 重排（优先：历史上下文扩写，让追问继承前文主语）
    search_query = query if (resolve_gid or resolve_src) else disambiguate.expand_query(query, session_id)
    try:
        docs, top_score = retriever.retrieve(search_query, goods_id=effective_goods_id, source=resolve_src or None)
    except Exception as exc:  # Milvus 未就绪等异常，降级为转人工而不是抛 500
        logger.exception("检索失败")
        return _reply(
            "系统正在维护知识库，已为您转接人工客服，抱歉～", True,
            f"检索异常:{type(exc).__name__}", session_id, effective_goods_id,
            [], 0.0, int((time.time() - started) * 1000), False, query,
        )
    # 峺义澄清：扩写后仍同时命中多个不同主体，且未本次确认 -> 让用户选是哪一个
    if docs and not resolve_gid and not resolve_src:
        clarify_options = disambiguate.detect_ambiguity(docs)
        if clarify_options:
            session_store.set_pending_clarify(session_id, clarify_options)
            return _clarify_reply(session_id, query, clarify_options, started)
    sources = sorted({d.get("source", "") for d in docs if d.get("source")})

    # 4) 知识库无答案：不喂大模型，直接转人工（最强的幻觉抑制手段）
    if not docs or top_score < settings.NO_ANSWER_THRESHOLD:
        answer = settings.NO_ANSWER_REPLY
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

    return _reply(
        answer, need_human, ",".join(reasons), session_id, effective_goods_id,
        docs, top_score, int((time.time() - started) * 1000), True, query,
    )


def _reply(answer, need_human, reason, session_id, goods_id, docs, top_score, latency, kb_hit, query="", kind=""):
    if query and query.strip():
        session_store.append_turn(session_id, query, answer)
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
        "kind": kind,
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
