"""商品自动识别：用户提问时从文字里识别出商品名，映射到 goods_id 做检索过滤。
例如「星野T5耳机售后期有几天」-> 命中商品「星野T5耳机」-> goods_id=G10086。"""
import logging
import re
from typing import Dict, List

from app import vectorstore

logger = logging.getLogger(__name__)

# 来源文件名结尾常见后缀，去掉后可得到更“口语”的商品名
_SUFFIXES = ["商品详情", "产品详情", "产品介绍", "商品介绍", "介绍", "说明书", "参数", "信息", "说明", "描述", "资料", "详情"]
_EXT_RE = re.compile(r"(?i)\.(md|markdown|txt|pdf|docx|csv|tsv)$")

_catalog: Dict[str, List[str]] | None = None  # goods_id -> [候选商品名]


def _derive_names(raw: str) -> List[str]:
    root = _EXT_RE.sub("", raw or "").strip()
    cands = [root]
    if root.endswith("商品"):
        pass
    for suf in _SUFFIXES:
        if root.endswith(suf):
            cands.append(root[: -len(suf)].strip())
            break
    # 去掉首尾空白后，再收一个最短形态（如 "星野T5耳机" 同时保留整名）
    return list(dict.fromkeys(n for n in cands if len(n) >= 2))


def _load() -> Dict[str, List[str]]:
    global _catalog
    if _catalog is None:
        cat: Dict[str, List[str]] = {}
        try:
            for s in vectorstore.list_sources():
                if s.get("doc_type") != "goods":
                    continue
                gid = (s.get("goods_id") or "").strip() or (s.get("source") or "")
                src = s.get("source") or ""
                names = _derive_names(src)
                if gid not in cat:
                    cat[gid] = names
                else:
                    cat[gid] = list(dict.fromkeys(cat[gid] + names))
        except Exception as exc:
            logger.warning("加载商品目录失败: %s", exc)
            return {}
        _catalog = cat
    return _catalog


def invalidate() -> None:
    """文档新增/删除/更新后刷新商品目录缓存。"""
    global _catalog
    _catalog = None


def _lcs(a: str, b: str) -> str:
    """最长公共子串，用于「问题里提到的商品名」与「已知商品名」的模糊匹配（可去掉品牌前缀）。"""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return ""
    best = ""
    dp = [0] * (m + 1)
    for i in range(1, n + 1):
        prev = 0
        for j in range(1, m + 1):
            cur = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev + 1
                if dp[j] > len(best):
                    best = a[i - dp[j]:i]
            else:
                dp[j] = 0
            prev = cur
    return best


def detect(query: str) -> str:
    """从提问中识别商品，返回 goods_id；识别不到返回空串（走全店通用/会话记忆）。"""
    q = (query or "").strip()
    if not q or not _load():
        return ""
    best_gid, best_score = "", 0
    for gid, names in _load().items():
        for n in names:
            if n in q:
                score = len(n)
            else:
                score = len(_lcs(n, q))
            # 只认足够具体的商品片段（避免把「耳机」「手机」这种通用词误判成某款商品）
            if score >= 4 and score > best_score:
                best_score, best_gid = score, gid
    return best_gid