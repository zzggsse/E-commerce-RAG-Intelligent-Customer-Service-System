"""切片效果自检（不需要 Milvus / 不需要模型，纯本地验证切分逻辑）。

用法： python -m scripts.check_chunks data/aftersale/退换货规则.md aftersale
"""
import io
import sys

sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import loader  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    path, doc_type = sys.argv[1], sys.argv[2]
    chunks = loader.parse_document(path, doc_type)
    print(f"文件 {path} 切出 {len(chunks)} 片\n")
    for chunk in chunks:
        text = chunk["content"]
        print(f"--- 第 {chunk['chunk_index']+1} 片  长度={len(text)} ---")
        print(text)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
