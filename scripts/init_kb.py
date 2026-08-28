"""初始化知识库：建集合 + 导入 data 目录全部文档。

用法： python -m scripts.init_kb
"""
import logging
import sys

sys.path.insert(0, ".")

from app import ingest, stats, vectorstore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    stats.init()
    vectorstore.get_collection()
    detail = ingest.ingest_directory()
    ok = [d for d in detail if "error" not in d]
    bad = [d for d in detail if "error" in d]
    print(f"\n导入完成：文件 {len(ok)} 个，切片 {sum(d['chunk_count'] for d in ok)} 条")
    for item in ok:
        print(f"  + {item['source']:<40} type={item['doc_type']:<9} "
              f"goods={item['goods_id'] or '通用':<10} chunks={item['chunk_count']}")
    for item in bad:
        print(f"  ! {item['source']} 失败: {item['error']}")
    print(f"知识库当前片段总数: {vectorstore.count()}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
