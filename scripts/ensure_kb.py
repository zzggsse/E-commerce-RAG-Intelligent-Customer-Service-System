"""确保空知识库集合已创建，不导入任何内置数据。
start.bat 首次启动时调用；默认不内置测试知识库。
"""
import logging
import sys

sys.path.insert(0, ".")

from app import stats, vectorstore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    stats.init()
    vectorstore.get_collection()
    print("知识库集合已就绪，当前片段数:", vectorstore.count())
    print("默认不内置测试数据。您可以选择：")
    print("  1) 运行  generate_test_data.bat  一键生成并导入测试内容")
    print("  2) 在知识库管理页直接上传自己的文档")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
