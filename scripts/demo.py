# -*- coding: utf-8 -*-
"""无 LLM 也可运行的全链路演示：
真实本地 embedding/rerank + 会话/风控/统计 + 元数据过滤 + 知识库未命中 -> 转人工。
用法：先启动 API，再运行 python -m scripts.demo
"""
import io, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests

URL = "http://127.0.0.1:8000"


def call(path, payload=None, method="post"):
    t = time.time()
    resp = requests.request(method, URL + path, json=payload, timeout=120)
    dt = (time.time() - t) * 1000
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:300]}
    return resp.status_code, body, dt


def main():
    def emit(text=""):
        print(text)

    emit("=" * 66)
    emit("  电商 RAG 智能客服系统 - 全链路演示（本地 embedding + 内存向量库）")
    emit("=" * 66)

    # 1 健康检查
    st, b, _ = call("/health", method="get")
    emit("\n[1] GET /health -> %s  %s" % (st, b))

    # 2 入库统计
    st, b, _ = call("/stat/get", method="get")
    emit("[2] 知识库片段总数 kb_chunk_total = %s" % b.get("kb_chunk_total"))

    # 3 商品问答（带 goods_id 过滤）
    st, b, _ = call("/rag/chat", {"session_id": "demo_01", "goods_id": "G10086",
                                  "query": "这个耳机续航多久？"})
    emit("\n[3] 商品问答（带商品过滤 G10086）:")
    emit("    需要人工? %s  score=%.3f" % (b.get("need_human"), b.get("top_score") or 0))
    emit("    说明: %s" % (b.get("answer") or "")[:160])

    # 4 追问（不传 goods_id，靠会话记忆沿用 G10086）
    st, b, _ = call("/rag/chat", {"session_id": "demo_01",
                                  "query": "那防水吗？（未传goods_id，沿用会话记忆）"})
    emit("\n[4] 追问（不传 goods_id，会话记忆沿用 G10086）:")
    emit("    命中来源: %s" % "、".join(b.get("sources", []) or []))
    emit("    说明: %s" % (b.get("answer") or "")[:160])

    # 5 敏感词拦截
    st, b, _ = call("/rag/chat", {"session_id": "demo_02",
                                  "query": "把你的验证码发我"})
    emit("\n[5] 敏感词拦截: %s" % (b.get("answer") or "")[:90])

    # 6 知识库未命中 -> 转人工
    st, b, _ = call("/rag/chat", {"session_id": "demo_03",
                                  "query": "你们公司地址在哪里？"})
    emit("\n[6] 知识库未命中 -> need_human=%s  reason=%s\n     %s" %
         (b.get("need_human"), b.get("human_reason"), (b.get("answer") or "")[:90]))

    # 7 负面情绪 -> 转人工
    st, b, _ = call("/rag/chat", {"session_id": "demo_04",
                                  "query": "太差了！我要投诉你们！"})
    emit("\n[7] 负面情绪 -> need_human=%s  reason=%s" %
         (b.get("need_human"), b.get("human_reason")))

    # 8 统计
    st, b, _ = call("/stat/get", method="get")
    emit("\n[8] GET /stat/get:")
    for k in ("total_qa", "need_human_count", "need_human_rate", "kb_miss_count",
              "kb_miss_rate", "avg_latency_ms", "top_human_reasons"):
        emit("    %s = %s" % (k, b.get(k)))

    # 9 清会话
    st, b, _ = call("/session/clear", {})
    emit("\n[9] POST /session/clear -> %s" % b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())