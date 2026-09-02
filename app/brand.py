"""客服标题品牌名：从上传内容自动识别 + 可手动持久化（logs/brand.json）。"""
import json
import logging
import re
from pathlib import Path

import settings

logger = logging.getLogger(__name__)

# 常见写法：品牌:XXX / 品牌：XXX / brand:XXX / 品牌名称
_PAT = re.compile(r"(?:品牌(?:名称)?|brand)\s*[:：=]\s*([\w\u4e00-\u9fa5][\w \u4e00-\u9fa5\-]{0,15})", re.IGNORECASE)

_cache = None  # None=未加载


def _path() -> Path:
    return Path(getattr(settings, "BRAND_CONFIG_PATH", str(Path(settings.LOG_DIR) / "brand.json")))


def _load() -> str:
    global _cache
    if _cache is None:
        val = ""
        p = _path()
        if p.exists():
            try:
                val = (json.loads(p.read_text(encoding="utf-8")) or {}).get("brand", "")
            except Exception:
                val = ""
        env = getattr(settings, "BRAND_NAME", "") or ""
        if env:
            val = env
        _cache = val or ""
    return _cache or ""


def get_brand() -> str:
    """返回当前品牌名（空 = 尚未识别）。"""
    return _load()


def set_brand(name: str) -> str:
    """手动设置品牌名并持久化。"""
    global _cache
    name = (name or "").strip()
    _cache = name
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"brand": name}, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("品牌保存失败: %s", exc)
    logger.info("品牌已设置为: %s", name or "(空)")
    return name


def detect_and_set(texts) -> str:
    """从上传内容的文本里自动识别品牌名并设置（仅当当前尚未设置品牌时生效）。"""
    if _load():
        return get_brand()
    for t in texts or []:
        m = _PAT.search(str(t))
        if m:
            return set_brand(m.group(1).strip())
    return get_brand()