"""内容指纹：用于“上传新内容自动替换合并”的智能识别。
对一份文档的所有切片（按顺序）拼接后做归一化哈希；
同一份文档无论文件名如何变化，指纹一致，从而识别改名/重复上传并合并。"""
import hashlib
import re

_WS = re.compile(r"\s+")


def content_hash(contents):
    """输入有序文本列表，返回内容指纹（sha256 hex）。"""
    joined = "".join(str(c) for c in contents)
    joined = _WS.sub("", joined)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()