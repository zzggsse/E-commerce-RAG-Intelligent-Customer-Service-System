"""语音识别（ASR）：把录音文件转成文本。

调用 OpenAI 兼容的 /audio/transcriptions 接口（Whisper 系列），
和系统的 LLM 一样只需填 Base URL + ApiKey，可换成任何兼容后端。
未配置 ASR_API_KEY 时返回空文本，由前端回退到浏览器内置识别。
"""
import logging

import requests

import settings

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return settings.ASR_ENABLED and bool(settings.ASR_API_KEY)


def transcribe(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """上传录音字节，返回识别文本；失败抛异常由调用方处理。"""
    url = settings.ASR_BASE_URL.rstrip("/") + "/audio/transcriptions"
    files = {"file": (filename, audio_bytes, "application/octet-stream")}
    data = {
        "model": settings.ASR_MODEL,
        "language": settings.ASR_LANGUAGE,
        "response_format": "json",
    }
    headers = {"Authorization": "Bearer " + settings.ASR_API_KEY}
    resp = requests.post(url, headers=headers, files=files, data=data, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    text = payload.get("text", "") or ""
    return text.strip() if isinstance(text, str) else ""

