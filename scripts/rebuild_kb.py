"""重建知识库：删除集合后全量重导（切片策略调整后使用）。

用法： python -m scripts.rebuild_kb
"""
import logging
import sys

sys.path.insert(0, ".")

from app import vectorstore  # noqa: E402
from scripts import init_kb  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

if __name__ == "__main__":
    print("正在删除旧集合...")
    vectorstore.drop_collection()
    raise SystemExit(init_kb.main())
