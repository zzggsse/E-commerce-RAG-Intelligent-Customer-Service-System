"""风控：敏感词拦截 + 负面情绪识别（转人工触发器之一）。"""
from typing import Optional, Tuple

import settings


def check_sensitive(query: str) -> Tuple[bool, Optional[str]]:
    """命中敏感词则拦截，不进入检索与生成。"""
    text = query or ""
    for word in settings.SENSITIVE_WORDS:
        if word in text:
            return True, word
    return False, None


def check_negative(query: str) -> Tuple[bool, Optional[str]]:
    text = query or ""
    for word in settings.NEGATIVE_WORDS:
        if word in text:
            return True, word
    return False, None
