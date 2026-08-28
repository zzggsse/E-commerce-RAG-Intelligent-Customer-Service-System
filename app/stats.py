"""观测统计：SQLite 落库，支撑总问答量 / 转人工率 / 知识库未命中次数。"""
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

import settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS qa_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    session_id TEXT,
    goods_id TEXT,
    query TEXT,
    answer TEXT,
    need_human INTEGER DEFAULT 0,
    human_reason TEXT,
    kb_hit INTEGER DEFAULT 1,
    top_score REAL DEFAULT 0,
    recall_count INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    sources TEXT
);
CREATE INDEX IF NOT EXISTS idx_qa_ts ON qa_log(ts);
CREATE TABLE IF NOT EXISTS doc_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    source TEXT,
    doc_type TEXT,
    goods_id TEXT,
    chunk_count INTEGER
);
"""


def _conn():
    os.makedirs(os.path.dirname(settings.STAT_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(settings.STAT_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _lock, _conn() as conn:
        conn.executescript(_SCHEMA)


def log_qa(
    session_id: str,
    goods_id: str,
    query: str,
    answer: str,
    need_human: bool,
    human_reason: str = "",
    kb_hit: bool = True,
    top_score: float = 0.0,
    recall_count: int = 0,
    latency_ms: int = 0,
    sources: Optional[List[str]] = None,
) -> None:
    try:
        with _lock, _conn() as conn:
            conn.execute(
                "INSERT INTO qa_log (ts, session_id, goods_id, query, answer, need_human,"
                " human_reason, kb_hit, top_score, recall_count, latency_ms, sources)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    int(time.time()), session_id, goods_id, query, answer,
                    int(need_human), human_reason, int(kb_hit), float(top_score),
                    recall_count, latency_ms,
                    json.dumps(sources or [], ensure_ascii=False),
                ),
            )
    except Exception as exc:  # 统计失败绝不影响主链路
        logger.warning("写入统计失败: %s", exc)


def log_doc(source: str, doc_type: str, goods_id: str, chunk_count: int) -> None:
    try:
        with _lock, _conn() as conn:
            conn.execute(
                "INSERT INTO doc_log (ts, source, doc_type, goods_id, chunk_count) VALUES (?,?,?,?,?)",
                (int(time.time()), source, doc_type, goods_id, chunk_count),
            )
    except Exception as exc:
        logger.warning("写入文档统计失败: %s", exc)


def summary(days: int = 7) -> Dict:
    since = int(time.time()) - days * 86400
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) total, SUM(need_human) human, SUM(1-kb_hit) miss,"
            " AVG(latency_ms) latency, AVG(top_score) score FROM qa_log WHERE ts >= ?",
            (since,),
        ).fetchone()
        total = row["total"] or 0
        human = row["human"] or 0
        miss = row["miss"] or 0
        top_reasons = conn.execute(
            "SELECT human_reason reason, COUNT(*) cnt FROM qa_log"
            " WHERE ts >= ? AND need_human = 1 AND human_reason != ''"
            " GROUP BY human_reason ORDER BY cnt DESC LIMIT 5",
            (since,),
        ).fetchall()
        miss_queries = conn.execute(
            "SELECT query, ts FROM qa_log WHERE ts >= ? AND kb_hit = 0"
            " ORDER BY ts DESC LIMIT 10",
            (since,),
        ).fetchall()
        doc_row = conn.execute(
            "SELECT COUNT(*) files, SUM(chunk_count) chunks FROM doc_log"
        ).fetchone()

    def rate(a, b):
        return round(a / b * 100, 2) if b else 0.0

    return {
        "window_days": days,
        "total_qa": total,
        "need_human_count": human,
        "need_human_rate": rate(human, total),
        "kb_miss_count": miss,
        "kb_miss_rate": rate(miss, total),
        "avg_latency_ms": int(row["latency"] or 0),
        "avg_top_score": round(row["score"] or 0, 4),
        "doc_files": doc_row["files"] or 0,
        "doc_chunks": doc_row["chunks"] or 0,
        "top_human_reasons": [dict(r) for r in top_reasons],
        "recent_kb_miss_queries": [r["query"] for r in miss_queries],
    }
