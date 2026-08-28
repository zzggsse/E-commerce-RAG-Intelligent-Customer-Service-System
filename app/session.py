"""会话状态：内存维护最近 N 轮对话 + 当前 goods_id 上下文。

goods_id 粘性是电商场景关键：用户先问"这个耳机多少钱"，
再追问"怎么保修"时不会带商品号，靠会话记忆自动补齐并做元数据过滤。
"""
import re
import threading
import time
from collections import OrderedDict
from typing import Dict, List, Optional

import settings

_lock = threading.Lock()
_sessions: "OrderedDict[str, Dict]" = OrderedDict()

_GOODS_ID_RE = re.compile(r"(?:商品|宝贝|货号|编号|ID|id)\s*[:：#]?\s*([A-Za-z0-9_-]{4,32})")


def _new_session() -> Dict:
    return {"history": [], "goods_id": "", "updated_at": time.time(), "recent_queries": []}


def _gc() -> None:
    now = time.time()
    expired = [k for k, v in _sessions.items() if now - v["updated_at"] > settings.SESSION_TTL_SECONDS]
    for key in expired:
        _sessions.pop(key, None)


def get(session_id: str) -> Dict:
    with _lock:
        _gc()
        if session_id not in _sessions:
            _sessions[session_id] = _new_session()
        return _sessions[session_id]


def resolve_goods_id(session_id: str, goods_id: Optional[str], query: str) -> str:
    """确定本轮生效的 goods_id：入参 > 问题里显式提到 > 会话记忆。"""
    session = get(session_id)
    if goods_id:
        with _lock:
            session["goods_id"] = str(goods_id)
        return str(goods_id)
    match = _GOODS_ID_RE.search(query or "")
    if match:
        with _lock:
            session["goods_id"] = match.group(1)
        return match.group(1)
    return session.get("goods_id", "")


def append_turn(session_id: str, query: str, answer: str) -> None:
    session = get(session_id)
    with _lock:
        session["history"].append({"query": query, "answer": answer})
        session["history"] = session["history"][-settings.SESSION_MAX_TURNS:]
        session["updated_at"] = time.time()


def record_query(session_id: str, query: str) -> int:
    """记录提问并返回相似重复次数（用于"反复质问 -> 转人工"判断）。"""
    session = get(session_id)
    norm = re.sub(r"\W+", "", query or "")
    with _lock:
        queries = session["recent_queries"]
        queries.append(norm)
        session["recent_queries"] = queries[-8:]
        return sum(1 for q in session["recent_queries"] if _similar(q, norm))


def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    return len(short) >= 4 and short in long


def get_history_text(session_id: str) -> str:
    session = get(session_id)
    lines: List[str] = []
    for turn in session.get("history", []):
        lines.append(f"用户：{turn['query']}\n客服：{turn['answer']}")
    return "\n".join(lines)


def clear(session_id: Optional[str] = None) -> int:
    with _lock:
        if session_id:
            return 1 if _sessions.pop(session_id, None) else 0
        n = len(_sessions)
        _sessions.clear()
        return n


def active_count() -> int:
    with _lock:
        _gc()
        return len(_sessions)
