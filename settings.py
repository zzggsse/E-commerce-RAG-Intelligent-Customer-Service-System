# =============================================================
#  ecom-rag 全局配置文件  ——  普通用户只需要修改这一个文件
# =============================================================
# 说明：
#   1. 支持两种方式配置：直接改本文件的默认值，或在同目录建 .env 文件覆盖。
#   2. 只有 LLM_API_KEY 是必填项，其余都有可用默认值。
# =============================================================
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


# 加载同目录 .env（无需第三方依赖）
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


# -------------------------------------------------------------
# 1. 大模型（必填）
#    兼容任何 OpenAI 格式接口：DeepSeek / 通义 / 智谱 / OpenAI / Ollama
# -------------------------------------------------------------
LLM_API_KEY = _env("LLM_API_KEY", "sk-请填写你的key")
LLM_BASE_URL = _env("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = _env("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.1"))   # 客服场景越低越稳
LLM_MAX_TOKENS = int(_env("LLM_MAX_TOKENS", "800"))
LLM_TIMEOUT = int(_env("LLM_TIMEOUT", "60"))


# -------------------------------------------------------------
# 2. Embedding / Reranker 模型
#    首次启动会自动从 HuggingFace 或 ModelScope 下载到 ./models
#    国内网络建议保持 USE_MODELSCOPE=true
# -------------------------------------------------------------
EMBEDDING_MODEL = _env("EMBEDDING_MODEL", str((__import__("pathlib").Path(__file__).resolve().parent / "models" / "bge-large-zh-v1.5")))  # 默认用本地模型目录，也可填 HF 模型名
EMBEDDING_DIM = int(_env("EMBEDDING_DIM", "1024"))         # bge-large-zh = 1024
RERANKER_MODEL = _env("RERANKER_MODEL", "BAAI/bge-reranker-base")
# Reranker 后端：local=本地CrossEncoder(需下载模型) / dashscope=阿里云rerank API / none=跳过重排用向量分
RERANK_BACKEND = _env("RERANK_BACKEND", "none")
RERANK_API_KEY = _env("RERANK_API_KEY", "")
RERANK_API_URL = _env("RERANK_API_URL", "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank")
RERANK_DASHSCOPE_MODEL = _env("RERANK_DASHSCOPE_MODEL", "gte-rerank-v2")
MODEL_CACHE_DIR = _env("MODEL_CACHE_DIR", str(BASE_DIR / "models"))
USE_MODELSCOPE = _env("USE_MODELSCOPE", "true").lower() == "true"
EMBEDDING_DEVICE = _env("EMBEDDING_DEVICE", "cpu")         # 有显卡填 cuda
# 中文检索前缀，bge 官方推荐（提升召回，别乱改）
EMBEDDING_QUERY_INSTRUCTION = _env(
    "EMBEDDING_QUERY_INSTRUCTION", "为这个句子生成表示以用于检索相关文章："
)


# -------------------------------------------------------------
# 3. Milvus 向量库
#    docker-compose 启动时 host 用 milvus-standalone，本机直连用 127.0.0.1
# -------------------------------------------------------------
MILVUS_HOST = _env("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = int(_env("MILVUS_PORT", "19530"))
MILVUS_COLLECTION = _env("MILVUS_COLLECTION", "ecom_rag_kb")
MILVUS_INDEX_TYPE = _env("MILVUS_INDEX_TYPE", "HNSW")
MILVUS_METRIC_TYPE = _env("MILVUS_METRIC_TYPE", "COSINE")
MILVUS_INDEX_PARAMS = {"M": 16, "efConstruction": 200}
MILVUS_SEARCH_PARAMS = {"ef": 96}
# 向量库后端：milvus(默认，Docker 部署) / local(本地内存向量库，无需 Docker 与 reranker，方便演示出图)
VECTOR_BACKEND = _env("VECTOR_BACKEND", "milvus")
LOCAL_VECTOR_DB = _env("LOCAL_VECTOR_DB", str(BASE_DIR / "logs" / "local_kb.json"))


# -------------------------------------------------------------
# 4. 切片策略（按文档类型分别配置，改动会影响召回质量）
#    goods    : 商品参数密集，切小一点，避免一条参数被切散
#    aftersale: 售后 FAQ 是问答对，切大一点 + 按问答边界切分
# -------------------------------------------------------------
CHUNK_CONFIG = {
    "goods": {"chunk_size": 450, "chunk_overlap": 80},
    "aftersale": {"chunk_size": 600, "chunk_overlap": 100},
}
# 售后 FAQ 问答对起始行的识别规则（正则，命中即视为新问答对开始）
FAQ_QUESTION_PATTERNS = [
    r"^\s*#{1,6}\s*Q\d*[:：.、]?",
    r"^\s*Q\d*[:：.、]",
    r"^\s*问[:：]",
    r"^\s*\d+[.、]\s*.{0,60}[?？]\s*$",
    r"^\s*#{1,6}\s*.{0,60}[?？]\s*$",
]


# -------------------------------------------------------------
# 5. 检索与重排
# -------------------------------------------------------------
VECTOR_TOP_K = int(_env("VECTOR_TOP_K", "7"))          # 向量粗召回条数
RERANK_TOP_N = int(_env("RERANK_TOP_N", "3"))          # 重排后进 Prompt 的条数
RERANK_SCORE_THRESHOLD = float(_env("RERANK_SCORE_THRESHOLD", "0.30"))
# 重排后最高分低于此值，视为"知识库无答案"，直接转人工，不喂给大模型
NO_ANSWER_THRESHOLD = float(_env("NO_ANSWER_THRESHOLD", "0.35"))


# -------------------------------------------------------------
# 6. 会话记忆
# -------------------------------------------------------------
SESSION_MAX_TURNS = int(_env("SESSION_MAX_TURNS", "3"))        # 保留最近 N 轮
SESSION_TTL_SECONDS = int(_env("SESSION_TTL_SECONDS", "1800"))  # 会话过期时间


# -------------------------------------------------------------
# 7. 转人工与风控
# -------------------------------------------------------------
# 负面情绪词：命中即转人工
NEGATIVE_WORDS = [
    "投诉", "差评", "举报", "曝光", "骗子", "欺骗", "垃圾", "无语", "退一赔三",
    "太差", "垃圾店", "报警", "工商", "12315", "黑店", "坑人", "气死", "不想要了",
]
# 敏感词：命中直接拦截，不进入检索与生成
SENSITIVE_WORDS = [
    "身份证号", "银行卡密码", "验证码", "赌博", "私下交易", "刷单", "走私", "毒品",
]
SENSITIVE_REPLY = "抱歉，该问题涉及敏感内容，我不能处理，已为您转接人工客服。"
NEGATIVE_REPLY = "理解您的心情，这件事情我已为您转接人工客服，尽快为您处理。"
NO_ANSWER_REPLY = "该问题暂未找到对应资料，请转人工客服为您核实，感谢理解～"
# 同一会话内，用户重复问相似问题达到此次数则转人工
REPEAT_QUESTION_LIMIT = int(_env("REPEAT_QUESTION_LIMIT", "3"))


# -------------------------------------------------------------
# 8. 服务与数据目录
# -------------------------------------------------------------
API_HOST = _env("API_HOST", "0.0.0.0")
API_PORT = int(_env("API_PORT", "8001"))
DATA_DIR = _env("DATA_DIR", str(BASE_DIR / "data"))
LOG_DIR = _env("LOG_DIR", str(BASE_DIR / "logs"))
STAT_DB_PATH = _env("STAT_DB_PATH", str(BASE_DIR / "logs" / "stat.db"))
UPLOAD_MAX_MB = int(_env("UPLOAD_MAX_MB", "50"))

# -------------------------------------------------------------
# 9. 语音输入（ASR 语音识别）
#     OpenAI 兼容的 /audio/transcriptions 接口（Whisper 系列）。
#     未配置 ASR_API_KEY 时前端会自动回退到浏览器内置语音识别。
# -------------------------------------------------------------
ASR_ENABLED = _env("ASR_ENABLED", "false").lower() == "true"
ASR_BASE_URL = _env("ASR_BASE_URL", "https://api.openai.com/v1")
ASR_API_KEY = _env("ASR_API_KEY", "")
ASR_MODEL = _env("ASR_MODEL", "whisper-1")
ASR_LANGUAGE = _env("ASR_LANGUAGE", "zh")
ASR_MAX_AUDIO_MB = int(_env("ASR_MAX_AUDIO_MB", "20"))
