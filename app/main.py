"""FastAPI 服务入口：4 个接口 —— 上传入库 / 对话 / 统计 / 清会话。"""
import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import settings
from app import asr, brand, goods, ingest, rag, session as session_store, stats, vectorstore

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
    files: List[UploadFile] = File(..., description="支持 .md/.markdown/.txt/.pdf/.docx/.csv/.tsv，可多选"),
    doc_type: str = Form("goods", description="文档类型，可自由填写（goods=商品资料 / aftersale=售后 / 物流 / 发票 / 会员等）"),
    goods_id: str = Form("", description="商品编号，通用文档留空"),
    category: str = Form("", description="商品分类"),
    replace: bool = Form(True, description="同文件名重新上传时先删旧切片（替换更新）"),
):

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
                    tmp_path, doc_type, goods_id, category, upload.filename,
                    replace=replace,
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
def document_ingest_dir(path: Optional[str] = None, replace: bool = Form(False)):
    detail = ingest.ingest_directory(path, replace=replace)
    return {
        "code": 0,
        "files": len(detail),
        "total_chunks": sum(d.get("chunk_count", 0) for d in detail),
        "detail": detail,
    }


@app.get("/config/brand", summary="获取客服标题品牌名")
def get_brand():
    return {"code": 0, "brand": brand.get_brand()}


@app.post("/config/brand", summary="手动设置客服标题品牌名")
def set_brand(brand_name: str = Form("", description="品牌名，空则恢复为未设置(留空待自动识别)")):
    return {"code": 0, "brand": brand.set_brand(brand_name)}


@app.get("/document/sources", summary="列出知识库中的所有文档（按来源聚合）")
def document_sources():
    try:
        docs = vectorstore.list_sources()
    except Exception as exc:
        raise HTTPException(500, f"获取文档列表失败: {exc}")
    return {"code": 0, "documents": docs, "total": len(docs)}


@app.post("/document/search", summary="按关键词检索知识库内容（定位要删的内容）")
def document_search(
    keyword: str = Form(..., description="关键词，匹配文档内容或文件名"),
    goods_id: str = Form("", description="可选：限定商品"),
    doc_type: str = Form("", description="可选：goods=商品 / aftersale=售后"),
):
    try:
        hits = vectorstore.search_content(keyword, goods_id, doc_type, limit=500)
    except Exception as exc:
        raise HTTPException(500, f"检索失败: {exc}")
    return {"code": 0, "keyword": keyword, "hit_count": len(hits), "hits": hits}


@app.post("/document/delete", summary="删除某个来源文档的切片（按文件名匹配，用于活动/规则下线）")
def document_delete(
    source: str = Form(..., description="文件名（source），例如 双11规则.docx"),
    goods_id: str = Form("", description="仅删除该商品下的切片，留空为全部"),
    doc_type: str = Form("", description="仅删除该类型下的切片，留空为全部"),
):
    if not source:
        raise HTTPException(400, "source 不能为空")
    removed = vectorstore.delete_by_source(source, goods_id, doc_type)
    goods.invalidate()  # 删除后刷新提问自动识别缓存
    logger.info("删除来源 [%s] 切片 %d 条", source, removed)
    return {
        "code": 0,
        "source": source,
        "deleted": removed,
        "detail": f"已删除 {removed} 条切片" if removed else f"未找到来源 {source} 的切片",
    }






@app.post("/asr", summary="语音识别：上传录音，返回识别文本")
async def asr_transcribe(file: UploadFile = File(..., description="录音文件 webm/wav/mp3等")):
    content = await file.read()
    if len(content) > settings.ASR_MAX_AUDIO_MB * 1024 * 1024:
        raise HTTPException(400, "录音文件超过大小限制")
    if not asr.enabled():
        return {"code": 1, "text": "", "msg": "未配置 ASR_API_KEY（请在 .env 填写并设 ASR_ENABLED=true）"}
    try:
        text = asr.transcribe(content, file.filename or "audio.webm")
        if not text:
            return {"code": 1, "text": "", "msg": "未识别到有效语音"}
        return {"code": 0, "text": text}
    except Exception as exc:
        logger.exception("ASR 识别失败")
        return {"code": 1, "text": "", "msg": "语音识别失败: {}".format(exc)}

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
@app.post("/stat/clear", summary="清空统计记录")
def stat_clear():
    cleared = stats.clear()
    return {"code": 0, "cleared": cleared}


@app.post("/session/clear", summary="清空会话记忆")
def session_clear(req: ClearRequest):
    cleared = session_store.clear(req.session_id)
    return {"code": 0, "cleared": cleared}
@app.get("/session/list", summary="会话列表（按更新时间倒序）")
def session_list():
    return {"code": 0, "sessions": session_store.list_sessions()}


@app.get("/session/detail", summary="会话历史消息")
def session_detail(session_id: str):
    msgs = session_store.history_messages(session_id)
    return {"code": 0, "session_id": session_id, "messages": msgs}


@app.get("/", summary="接口入口信息", response_class=HTMLResponse)
def root():
    _links = [
        ("接口文档 (Swagger UI)", "/docs"),
        ("健康检查", "/health"),
        ("发起对话 (POST /rag/chat)", "/rag/chat"),
        ("上传知识库文档 (POST /document/upload)", "/document/upload"),
        ("运行统计", "/stat/get"),
    ]
    _cards = "".join(
        f'<a class="card" href="{u}"><span class="method">接口</span><span class="path">{u}</span><span class="desc">{d}</span></a>'
        for d, u in _links
    )
    return HTMLResponse(f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ecom-rag-cs 服务入口</title>
<style>
  body{{margin:0;font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;background:#f4f6fb;color:#1f2937;display:flex;align-items:center;justify-content:center;min-height:100vh}}
  .wrap{{max-width:520px;width:90%;background:#fff;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.08);padding:36px 32px}}
  h1{{font-size:22px;margin:0 0 4px}}
  .sub{{color:#6b7280;font-size:13px;margin-bottom:20px}}
  .ports{{display:flex;gap:8px;margin-bottom:22px}}
  .badge{{background:#eef2ff;color:#4338ca;border-radius:20px;padding:4px 12px;font-size:12px}}
  .card{{display:flex;flex-direction:column;gap:2px;text-decoration:none;border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;margin-bottom:10px;transition:border-color .15s,box-shadow .15s}}
  .card:hover{{border-color:#6366f1;box-shadow:0 4px 12px rgba(99,102,241,.12)}}
  .card .path{{font-weight:600;color:#111827;font-size:14px}}
  .card .desc{{color:#6b7280;font-size:12px}}
  .foot{{margin-top:18px;font-size:11px;color:#9ca3af;text-align:center}}
</style>
</head>
<body>
<div class="wrap">
  <h1>ecom-rag-cs 服务入口</h1>
  <div class="sub">电商 RAG 智能客服后端服务已启动</div>
  <div class="ports"><span class="badge">后端端口 {settings.API_PORT}</span></div>
  {''.join(_cards)}
  <div class="foot">前端控制台：<a href="http://localhost:5174/">http://localhost:5174/</a></div>
</div>
</body>
</html>"""
    )


@app.get("/health", summary="健康检查")
def health():
    try:
        total = vectorstore.count()
        return {"code": 0, "milvus": "ok", "kb_chunk_total": total, "asr_enabled": asr.enabled()}
    except Exception as exc:
        return JSONResponse(
            status_code=503, content={"code": 1, "milvus": "down", "msg": str(exc)}
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.API_HOST, port=settings.API_PORT)
