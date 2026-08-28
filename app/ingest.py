"""入库服务：文件/目录 -> 解析清洗切片 -> 向量化 -> Milvus。

目录批量导入约定（无需手工填元数据）：
    data/goods/<category>/<goods_id>/xxx.md   -> doc_type=goods
    data/aftersale/xxx.md                     -> doc_type=aftersale, goods_id 为空（通用）
"""
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import settings
from app import loader, stats, vectorstore

logger = logging.getLogger(__name__)


def ingest_file(
    path: str,
    doc_type: str,
    goods_id: str = "",
    category: str = "",
    source: str = "",
) -> Dict:
    chunks = loader.parse_document(path, doc_type, goods_id, category, source)
    inserted = vectorstore.insert_chunks(chunks)
    src = source or Path(path).name
    stats.log_doc(src, doc_type, goods_id, inserted)
    return {"source": src, "doc_type": doc_type, "goods_id": goods_id,
            "category": category, "chunk_count": inserted}


def ingest_directory(root: Optional[str] = None) -> List[Dict]:
    """扫描 data 目录批量入库，元数据由路径自动推断。"""
    root = root or settings.DATA_DIR
    results = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            suffix = Path(filename).suffix.lower()
            if suffix not in loader.SUPPORTED_SUFFIX:
                continue
            full = os.path.join(dirpath, filename)
            meta = _infer_meta(full, root)
            try:
                results.append(
                    ingest_file(full, meta["doc_type"], meta["goods_id"],
                                meta["category"], filename)
                )
            except Exception as exc:
                logger.exception("入库失败: %s", full)
                results.append({"source": filename, "error": str(exc)})
    return results


def _infer_meta(path: str, root: str) -> Dict:
    rel = Path(os.path.relpath(path, root)).parts
    doc_type = "aftersale" if rel and rel[0].lower().startswith("aftersale") else "goods"
    category, goods_id = "", ""
    if doc_type == "goods":
        # goods/<category>/<goods_id>/file  或  goods/<goods_id>/file
        mid = list(rel[1:-1])
        if len(mid) >= 2:
            category, goods_id = mid[0], mid[-1]
        elif len(mid) == 1:
            goods_id = mid[0]
    return {"doc_type": doc_type, "goods_id": goods_id, "category": category}
