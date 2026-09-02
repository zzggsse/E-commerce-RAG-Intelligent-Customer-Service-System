"""微弱语义增强 + 歧义澄清工具。

优先用「历史上下文扩写」让追问继承前文主语；若扩写后检索仍同时命中多个互不
相同的主体（不同商品 / 不同来源文档），则让用户从数字选项里确认是哪一个。
"""
import re
from typing import Dict, List, Optional

from app import session as session_store

logger = __import__("logging").getLogger(__name__)

# 触发「历史扩写」的碎片化词（追问常以这些词开头或包含它们）
_FRAGMENT_WORDS = (
    "它", "这", "那", "其", "该", "怎么", "如何",
    "多少", "多久", "几", "支持", "能", "可以",
    "是不是", "有没有", "吗", "呢", "款", "个问",
)
# 歧义阈值
TIE_MARGIN = 0.10      # 最高分与第二名分差小于该值即视为“并列”
MIN_BEST = 0.35         # 最高分需达到该值以上才值得让用户确认（太低说明本来就答不准）
MAX_OPTIONS = 4        # 最多给几个选项


def _looks_fragment(query: str) -> bool:
    """判断当前问题是否像“追问/碎片”，此时需要用上文主语来补全。"""
    q = (query or "").strip()
    if not q:
        return False
    if len(q) >= 8:
        return False
    if q.isdigit():
        return True
    # 去掉末尾语气词后仍有足够主语（如「苹果手机降价吗」）则视为完整问题，不扩写
    core = q.rstrip("吗呢呕吧啊的?？。，,")
    if len(core) >= 6:
        return False
    for w in _FRAGMENT_WORDS:
        if w in q:
            return True
    return len(q) <= 4


def expand_query(query: str, session_id: str) -> str:
    """优先功能：用最近会话里用户的问题来扩写当前追问，给检索补足上下文。"""
    q = (query or "").strip()
    if not q:
        return q
    recent = session_store.get_recent_user_queries(session_id, 2)
    if not recent:
        return q
    prior = (recent[-1] or "").strip()
    if not _looks_fragment(q) or not prior:
        return q
    expanded = f"{prior}。{q}"
    logger.info("展开检索: %r -> %r", q, expanded)
    return expanded


def _entity_key(d: Dict) -> str:
    gid = (d.get("goods_id") or "").strip()
    if gid:
        return "g:" + gid
    return "s:" + (d.get("source") or "").strip()


def _entity_label(d: Dict) -> str:
    src = (d.get("source") or "").strip()
    label = re.sub(r"(\.md|\.txt|\.pdf|\.docx|\.csv)$", "", src) or src
    label = re.sub(r"(商品资料|商品详情|商品).?ɑ*$", "", label) or label
    return label


def _score(d: Dict) -> float:
    v = d.get("rerank_score")
    if v is None:
        v = d.get("vector_score", 0.0)
    try:
        return float(v) or 0.0
    except (TypeError, ValueError):
        return 0.0


def detect_ambiguity(docs: List[Dict]) -> List[Dict]:
    """若 top 候选确实同时命中多个不同主体（且得分接近），返回可选项；否则返回空列表。"""
    groups: Dict[str, Dict] = {}
    for d in docs or []:
        key = _entity_key(d)
        sc = _score(d)
        g = groups.get(key)
        if g is None:
            groups[key] = {
                "key": key,
                "label": _entity_label(d),
                "goods_id": (d.get("goods_id") or "").strip(),
                "source": (d.get("source") or "").strip(),
                "best": sc,
            }
        elif sc > g["best"]:
            g["best"] = sc
    if len(groups) < 2:
        return []
    items = sorted(groups.values(), key=lambda g: -g["best"])
    top = items[0]
    if top["best"] < MIN_BEST:
        return []
    others = [g for g in items[1:] if top["best"] - g["best"] < TIE_MARGIN]
    if not others:
        return []
    opts = ([top] + others)[:MAX_OPTIONS]
    # 主要用于商品级峺义（如苹果 vs 苹果手机）：至少两个不同商品才询问，避免对通用资料过度询问
    goods = {o["goods_id"] for o in opts if o["goods_id"]}
    if len(goods) < 2:
        return []
    return opts


def parse_choice(query: str, options: List[Dict]) -> Optional[Dict]:
    """把用户回复解析成某个候选；不是候选则返回 None。"""
    q = (query or "").strip()
    if not q:
        return None
    if q.isdigit():
        i = int(q) - 1
        return options[i] if 0 <= i < len(options) else None
    for o in options:
        for field in (o.get("label"), o.get("goods_id"), o.get("source")):
            if field and str(field) in q:
                return o
    return None
