"""会话状态：磁盘持久化 + 内存维护最近 N 轮对话 + 当前 goods_id 上下文。

goods_id 粘性是电商场景关键：用户先问"这个耳机多少钱"，
再追问"怎么保修"时不会带商品号，靠会话记忆自动补齐并做元数据过滤。
"""
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

import settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()

_GOODS_ID_RE = re.compile(r"(?:商品|宝贝|货号|编号|ID|id)\s*[:：#]?\s*([A-Za-z0-9_-]{4,32})")


def _db_path() -> Path:
    return Path(getattr(settings, "SESSION_DB_PATH", str(Path(settings.LOG_DIR) / "sessions.json")))


def _load() -> "OrderedDict[str, Dict]":
    p = _db_path()
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return OrderedDict(raw)
        except Exception:
            logger.exception("会话加载失败")
    return OrderedDict()


def _persist() -> None:
    p = _db_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_sessions, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.exception("会话持久化失败")


_sessions: "OrderedDict[str, Dict]" = _load()


def _new_session() -> Dict:
    return {"history": [], "goods_id": "", "updated_at": time.time(), "recent_queries": [], "pending_reco": None, "pending_clarify": None}


def _gc() -> None:
    now = time.time()
    expired = [k for k, v in _sessions.items() if now - v["updated_at"] > settings.SESSION_TTL_SECONDS]
    for key in expired:
        _sessions.pop(key, None)
    if expired:
        _persist()


def get(session_id: str) -> Dict:
    with _lock:
        _gc()
        if session_id not in _sessions:
            _sessions[session_id] = _new_session()
            _persist()
        return _sessions[session_id]


def get_pending_reco(session_id: str) -> Optional[List]:
    """返回待用户选择的「推荐方面」选项列表；无则为 None。"""
    return get(session_id).get("pending_reco") or None


def set_pending_reco(session_id: str, options: List) -> None:
    session = get(session_id)
    with _lock:
        session["pending_reco"] = options
        session["updated_at"] = time.time()
        _persist()


def clear_pending_reco(session_id: str) -> None:
    session = get(session_id)
    with _lock:
        session["pending_reco"] = None
        session["updated_at"] = time.time()
        _persist()


def get_pending_clarify(session_id: str) -> Optional[List]:
    """返回待用户确认的「歧义对象」选项列表；无则为 None。"""
    return get(session_id).get("pending_clarify") or None


def set_pending_clarify(session_id: str, options: List) -> None:
    session = get(session_id)
    with _lock:
        session["pending_clarify"] = options
        session["updated_at"] = time.time()
        _persist()


def clear_pending_clarify(session_id: str) -> None:
    session = get(session_id)
    with _lock:
        session["pending_clarify"] = None
        session["updated_at"] = time.time()
        _persist()


def get_recent_user_queries(session_id: str, n: int = 2) -> List[str]:
    """取最近 n 条用户提问，用于历史上下文扩写。"""
    session = get(session_id)
    qs = [t.get("query", "") for t in session.get("history", []) if t.get("query")]
    return qs[-n:]


def resolve_goods_id(session_id: str, goods_id: Optional[str], query: str) -> str:
    """确定本轮生效的 goods_id：入参 > 问题里显式提到 > 会话记忆。"""
    session = get(session_id)
    if goods_id:
        with _lock:
            session["goods_id"] = str(goods_id)
            _persist()
        return str(goods_id)
    match = _GOODS_ID_RE.search(query or "")
    if match:
        with _lock:
            session["goods_id"] = match.group(1)
            _persist()
        return match.group(1)
    return session.get("goods_id", "")


def append_turn(session_id: str, query: str, answer: str) -> None:
    session = get(session_id)
    with _lock:
        session["history"].append({"query": query, "answer": answer})
        session["history"] = session["history"][-settings.SESSION_MAX_TURNS:]
        session["updated_at"] = time.time()
        _persist()


def record_query(session_id: str, query: str) -> int:
    """记录提问并返回相似重复次数（用于"反复质问 -> 转人工"判断）。"""
    session = get(session_id)
    norm = re.sub(r"\W+", "", query or "")
    with _lock:
        queries = session["recent_queries"]
        queries.append(norm)
        session["recent_queries"] = queries[-8:]
        _persist()
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


def history_messages(session_id: str) -> List[Dict]:
    """把会话历史转成前端消息列表（user/bot 交替）。"""
    session = get(session_id)
    msgs: List[Dict] = []
    for turn in session.get("history", []):
        msgs.append({"role": "user", "text": turn["query"]})
        if turn.get("answer"):
            msgs.append({"role": "bot", "text": turn["answer"]})
    return msgs


def list_sessions() -> List[Dict]:
    """返回按最后更新时间倒序的会话列表（不含整段历史）。"""
    with _lock:
        _gc()
        items = []
        for sid, s in _sessions.items():
            hist = s.get("history", [])
            items.append({
                "session_id": sid,
                "updated_at": s.get("updated_at", 0),
                "turn_count": len(hist),
                "goods_id": s.get("goods_id", ""),
                "last_query": hist[-1]["query"] if hist else "",
            })
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return items


def clear(session_id: Optional[str] = None) -> int:
    with _lock:
        if session_id:
            n = 1 if _sessions.pop(session_id, None) else 0
        else:
            n = len(_sessions)
            _sessions.clear()
        _persist()
        return n


def active_count() -> int:
    with _lock:
        _gc()
        return len(_sessions)