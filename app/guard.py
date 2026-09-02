"""风控：敏感词拦截 + 负面情绪识别（转人工触发器之一）。

负面情绪用「强情绪词（单个即触发）+ 情绪句式 + 中等词组合打分」，
比纯关键字子串匹配更准。用户可在 settings.NEGATIVE_WORDS 继续附加/覆盖强触发词。
"""
import re
from typing import Optional, Tuple

import settings


def check_sensitive(query: str) -> Tuple[bool, Optional[str]]:
    """命中敏感词则拦截，不进入检索与生成。"""
    text = query or ""
    for word in settings.SENSITIVE_WORDS:
        if word in text:
            return True, word
    return False, None


# 强情绪词：单个命中即转人工
_STRONG_WORDS = [
    "投诉", "差评", "举报", "曝光", "骗子", "欺骗", "欺诈", "骗",
    "忽悠", "坑人", "黑心", "无良", "奸商", "黑店", "退一赔三",
    "报警", "工商", "12315", "气死", "气炸", "恶心",
    "太差", "太烂", "太慢", "再也不", "再也不会", "不要了", "不想要了",
    "垃圾店", "垃圾服务", "垃圾产品", "垃圾质量", "伪劣", "假货",
]
# 中等情绪词：需要组合（如 ≥2 个）才触发
_MED_WORDS = [
    "敷衍", "拖延", "迟迟", "逾期", "叠额", "推诿", "扯皮",
    "爱答不理", "失望", "愤怒", "恼火", "生气", "激动", "急死", "气人",
    "瑕疵", "破损", "是坏的", "坏了", "用不了", "质量差", "服务差",
    "态度差", "态度不好", "已读不回", "不理人", "不会处理", "糊弄",
]
# 情绪句式（正则 → 标签），命中一个即视为强触发
_PATTERNS = [
    (re.compile(r"(太|真|非常|特别|十分|这么|那么|好|巨|超|极其|简直)(差|烂|慢|气|难|烦|坑|臭|糟|乱|破)"), "强烈负面"),
    (re.compile(r"再\s*(也)?不"), "再也不"),
    (re.compile(r"(态度|服务)[^。，;]{0,5}(不好|差劲|恶劣|差)"), "态度/服务差"),
    (re.compile(r"(什么|这|那|嘛|啥)(破|鬼|烂|垃圾|狗|糟)"), "什么破X"),
    (re.compile(r"不[^。，]{0,6}(退货|退款|换货|赔偿)[!！]{1,}"), "强烈要求退换赔"),
    (re.compile(r"[!！]{2,}"), "强烈语气"),
]
_THRESHOLD = -1.5


def check_negative(query: str) -> Tuple[bool, Optional[str]]:
    """负面情绪识别（综合打分）：强词单个触发，中词组合触发。"""
    text = (query or "")
    hits: list = []
    score = 0.0
    strong = list(_STRONG_WORDS) + [w for w in settings.NEGATIVE_WORDS if w]
    for w in strong:
        if w in text:
            score -= 2.0
            hits.append(w)
    for w in _MED_WORDS:
        if w in text:
            score -= 1.0
            hits.append(w)
    for pat, label in _PATTERNS:
        if pat.search(text):
            score -= 2.0
            hits.append(label)
    if score <= _THRESHOLD and hits:
        return True, hits[0]
    return False, None
