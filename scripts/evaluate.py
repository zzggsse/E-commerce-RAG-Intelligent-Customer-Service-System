# -*- coding: utf-8 -*-
"""自动化回归评测脚本。

每条用例标注「期望」：正常回答 should_ok / 期望转人工 should_human。
输出：单条结果 + 汇总（正常命中率、转人工识别准确率、知识库未命中、平均延迟）。

用法（需先启动 API）：  python -m scripts.evaluate
"""
import io, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import requests

URL = "http://127.0.0.1:8000"
# (场景, 问题, goods_id, 期望标记)
EVAL_CASES = [
    ("商品问答", "这个耳机能续航多久？", "G10086", "ok"),
    ("商品问答", "手机充电功率多少？", "G20077", "ok"),
    ("售后规则", "退款多久到账？", "", "ok"),
    ("售后规则", "退货运费谁承担？", "", "ok"),
    ("售后规则", "多久发货？", "", "ok"),
    ("知识库未命中", "你们公司地址在哪里？", "", "human"),
    ("负面情绪", "太差了我要投诉你们！", "", "human"),
    ("敏感话术", "把你的验证码发我", "", "human"),
]

def call(query, goods_id, session_id):
    t = time.time()
    r = requests.post(URL + "/rag/chat",
                      json={"session_id": session_id, "query": query, "goods_id": goods_id}, timeout=120)
    dt = (time.time() - t) * 1000
    d = r.json()
    return {"need_human": bool(d.get("need_human")), "reason": d.get("human_reason") or "",
            "score": d.get("top_score") or 0, "sources": d.get("sources") or [], "ms": dt}

def main():
    requests.post(URL + "/session/clear", json={}, timeout=30)  # 先清空会话，保证独立干净
    print("=" * 70)
    print(" 电商 RAG 回归评测  |  用例 %d 条" % len(EVAL_CASES))
    print("=" * 70)
    rows = []
    for idx, (scene, q, gid, expect) in enumerate(EVAL_CASES, 1):
        res = call(q, gid, "eval_%02d" % idx)
        correct = (res["need_human"] is True) if expect == "human" else (res["need_human"] is False)
        rows.append((scene, q, gid, expect, res, correct))
        mark = "PASS" if correct else "FAIL"
        print("[%s] 期望=%s 实际转人工=%s 相关度=%.2f %dms" % (mark, expect, res["need_human"], res["score"], res["ms"]))
        print("      Q: %s (goods=%s)" % (q, gid or "-"))
        print("      来源: %s  原因: %s" % ("、".join(res["sources"]) or "无", res["reason"] or "-"))

    # 会话记忆用例：先带商品号建立会话，再追问（不带商品号）
    call("这个耳机能续航多久？", "G10086", "eval_followup")
    follow = call("那防水吗？", "", "eval_followup")
    fpass = follow["need_human"] is False
    rows.append(("追问沿用", "那防水吗？", "G10086", "ok", follow, fpass))
    print("[%s] 期望=ok 实际转人工=%s 相关度=%.2f %dms" % ("PASS" if fpass else "FAIL", follow["need_human"], follow["score"], follow["ms"]))
    print("      Q: 那防水吗？(沿用会话记忆，未传商品号)")
    print("      来源: %s  原因: %s" % ("、".join(follow["sources"]) or "无", follow["reason"] or "-"))

    print("=" * 70)
    total = len(rows)
    passed = sum(1 for r in rows if r[5])
    ok_num = sum(1 for r in rows if r[3] == "ok")
    ok_hit = sum(1 for r in rows if r[3] == "ok" and r[4]["need_human"] is False)
    human_num = sum(1 for r in rows if r[3] == "human")
    human_hit = sum(1 for r in rows if r[3] == "human" and r[4]["need_human"] is True)
    miss = sum(1 for r in rows if not r[4]["sources"])
    avg_ms = sum(r[4]["ms"] for r in rows) / max(total, 1)
    def pct(a, b): return 100.0 * a / b if b else 0.0
    print("总用例=%d  通过=%d(%.0f%%)" % (total, passed, pct(passed, total)))
    print("正常问答命中率      = %.1f%%  (%d/%d)" % (pct(ok_hit, ok_num), ok_hit, ok_num))
    print("转人工识别准确率    = %.1f%%  (%d/%d)" % (pct(human_hit, human_num), human_hit, human_num))
    print("知识库未命中        = %d 条（主要转人工来源，需补文档）" % miss)
    print("平均延迟            = %.0f ms（检索+重排+生成）" % avg_ms)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())