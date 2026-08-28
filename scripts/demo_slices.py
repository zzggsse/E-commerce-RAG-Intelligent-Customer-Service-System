# -*- coding: utf-8 -*-
"""生成"切片 + 检索过程"演示输出，供 README 截图。真实本地 embedding + 本地向量库。"""
import io, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import requests

URL = "http://127.0.0.1:8000"

def call(path, payload=None, method="post"):
    t = time.time()
    r = requests.request(method, URL + path, json=payload, timeout=120)
    return r.status_code, r.json(), (time.time() - t) * 1000

def main() -> int:
    from app import loader

    print("=" * 72)
    print(" A. 切片策略：售后 FAQ（按问答对边界切分，问题+答案同片）")
    print("=" * 72)
    for c in loader.parse_document("data/aftersale/售后FAQ.md", "aftersale")[:2]:
        print(">> [%s] 长度=%d" % (c["source"], len(c["content"])))
        print(c["content"][:240])
        print()

    print("=" * 72)
    print(" B. 切片策略：商品文档（按行打包，不在参数中间断开）")
    print("=" * 72)
    for c in loader.parse_document("data/goods/耳机/G10086/星野T5耳机商品详情.md", "goods")[:1]:
        print(">> [%s] 长度=%d" % (c["source"], len(c["content"])))
        print(c["content"][:280])
        print()

    print("=" * 72)
    print(" C. 检索链路：带 goods_id 元数据过滤")
    print("=" * 72)
    st, b, ms = call("/rag/chat", {"session_id": "eval_1", "goods_id": "G10086",
                                   "query": "这个耳机续航多久？"})
    print("问: 这个耳机续航多久？  goods_id=G10086  (%.0fms)" % ms)
    print("need_human=%s  top_score=%.3f" % (b.get("need_human"), b.get("top_score") or 0))
    for r in (b.get("references") or [])[:3]:
        print("  - [%s] %s  score=%.3f" % (r.get("doc_type"), r.get("source"), r.get("rerank_score") or 0))
        print("      " + ((r.get("preview") or "").replace(chr(10), " "))[:60])
    print()
    print("问: 这个耳机续航多久？  不带 goods_id（全库检索，跨商品噪声混入）")
    st, b, ms = call("/rag/chat", {"session_id": "eval_2", "query": "这个耳机续航多久？"})
    for r in (b.get("references") or [])[:3]:
        print("  - [%s] %s" % (r.get("doc_type"), r.get("source")))
        print("      " + ((r.get("preview") or "").replace(chr(10), " "))[:60])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())