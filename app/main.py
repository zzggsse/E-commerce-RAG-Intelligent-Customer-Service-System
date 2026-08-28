"""FastAPI 服务入口：4 个接口 —— 上传入库 / 对话 / 统计 / 清会话。"""
import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import settings
from app import ingest, rag, session as session_store, stats, vectorstore

os.makedirs(settings.LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(settings.LOG_DIR, "app.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("ecom-rag")


stats.init()  # 建统计表，导入即完成，避免首个请求报表不存在


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        vectorstore.get_collection()
        logger.info("Milvus 就绪，当前知识库片段数: %s", vectorstore.count())
    except Exception as exc:
        logger.warning("Milvus 暂不可用（稍后自动重试）: %s", exc)
    yield


app = FastAPI(
    title="电商 RAG 智能客服系统",
    version="1.0.0",
    description="商品咨询 + 售后政策问答，支持元数据过滤、会话记忆、转人工与幻觉抑制",
    lifespan=lifespan,
)


# ------------------------------------------------------------------ 模型
class ChatRequest(BaseModel):
    query: str = Field(..., description="用户问题")
    session_id: str = Field("default", description="会话 ID，同一用户保持一致")
    goods_id: Optional[str] = Field(None, description="商品编号，不传则沿用会话记忆")


class ClearRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="不传则清空全部会话")


# ------------------------------------------------------------------ 接口
@app.post("/document/upload", summary="上传商品/售后文档并入库")
async def document_upload(
    files: List[UploadFile] = File(..., description="支持 .md/.txt/.pdf，可多选"),
    doc_type: str = Form("goods", description="goods=商品资料 / aftersale=售后政策"),
    goods_id: str = Form("", description="商品编号，售后通用文档留空"),
    category: str = Form("", description="商品分类"),
):
    if doc_type not in ("goods", "aftersale"):
        raise HTTPException(400, "doc_type 只能是 goods 或 aftersale")

    results, total = [], 0
    tmpdir = tempfile.mkdtemp(prefix="ecomrag_")
    try:
        for upload in files:
            content = await upload.read()
            if len(content) > settings.UPLOAD_MAX_MB * 1024 * 1024:
                results.append({"source": upload.filename, "error": "文件超过大小限制"})
                continue
            tmp_path = os.path.join(tmpdir, os.path.basename(upload.filename))
            with open(tmp_path, "wb") as fp:
                fp.write(content)
            try:
                item = ingest.ingest_file(
                    tmp_path, doc_type, goods_id, category, upload.filename
                )
                total += item["chunk_count"]
                results.append(item)
            except Exception as exc:
                logger.exception("入库失败: %s", upload.filename)
                results.append({"source": upload.filename, "error": str(exc)})
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {"code": 0, "total_chunks": total, "detail": results}


@app.post("/document/ingest_dir", summary="批量导入 data 目录（元数据按路径自动推断）")
def document_ingest_dir(path: Optional[str] = None):
    detail = ingest.ingest_directory(path)
    return {
        "code": 0,
        "files": len(detail),
        "total_chunks": sum(d.get("chunk_count", 0) for d in detail),
        "detail": detail,
    }


@app.post("/rag/chat", summary="智能客服对话")
def rag_chat(req: ChatRequest):
    result = rag.chat(req.query, req.session_id, req.goods_id)
    return {"code": 0, **result}


@app.get("/stat/get", summary="运行统计：问答量、转人工率、知识库未命中")
def stat_get(days: int = 7):
    data = stats.summary(days)
    data["active_sessions"] = session_store.active_count()
    try:
        data["kb_chunk_total"] = vectorstore.count()
    except Exception:
        data["kb_chunk_total"] = -1
    return {"code": 0, **data}


@app.post("/session/clear", summary="清空会话记忆")
def session_clear(req: ClearRequest):
    cleared = session_store.clear(req.session_id)
    return {"code": 0, "cleared": cleared}


@app.get("/health", summary="健康检查")
def health():
    try:
        total = vectorstore.count()
        return {"code": 0, "milvus": "ok", "kb_chunk_total": total}
    except Exception as exc:
        return JSONResponse(
            status_code=503, content={"code": 1, "milvus": "down", "msg": str(exc)}
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.API_HOST, port=settings.API_PORT)
