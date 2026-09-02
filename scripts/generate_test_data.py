"""一键生成测试知识库内容并导入 Milvus。
用法：
    python -m scripts.generate_test_data
    或双击仓库根目录的 generate_test_data.bat

流程：
    1. 清空当前向量库集合（删除旧切片，含内置示例）
    2. 清空 data/goods 与 data/aftersale 下的旧内容，写入新生成的测试文件
    3. 按目录路径自动识别元数据并批量导入
"""
import logging
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import settings  # noqa: E402
from app import ingest, stats, vectorstore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
DATA = Path(settings.DATA_DIR)

# (data 下的相对路径, markdown 内容)
TEST_DOCS = [
    ("goods/手机/G20077/星野Note12商品详情.md", """# 星野 Note12 手机 商品详情

商品名称：星野 Note12，5G 智能手机
颜色：曜石黑 / 星辉银 / 流沙金
存储：8GB+128GB / 8GB+256GB / 12GB+256GB
屏幕：6.7 英寸 AMOLED，120Hz 高刷
电池：5500mAh，支持 67W 有线快充
摄像头：后置 5000 万主摄 + 200 万微距
系统：基于 Android 14 的星野 OS
净重：198 克
保修：整机 12 个月，屏幕 6 个月
价格：官方建议零售价 1999 元起

## 常见咨询
问：星野 Note12 支持无线充电吗？
答：不支持，仅支持 67W 有线快充。
问：手机运存是多大？
答：可选 8GB 或 12GB。
问：支持哪些网络？
答：支持移动、联通、电信 5G 全网通。"""),
    ("goods/耳机/G10086/星野T5耳机商品详情.md", """# 星野 T5 无线耳机 商品详情

商品名称：星野 T5 真无线蓝牙耳机
颜色：云雾白 / 曜石黑
续航：单次聆听约 7 小时，配合充电仓总续航约 30 小时
蓝牙：蓝牙 5.3，支持双设备连接
防水：支持 IPX5 生活防水
降噪：主动降噪 ANC，支持通透模式
重量：单耳约 4.2 克
充电：Type-C 快充，充电 10 分钟可听 2 小时
保修：主机 12 个月保修
价格：官方建议零售价 399 元

## 常见咨询
问：这款耳机支持防水吗？
答：支持 IPX5 生活防水，可应对运动出汗和轻微溅水。
问：耳机续航多久？
答：单次约 7 小时，配合充电仓总续航约 30 小时。
问：支持双设备同时连接吗？
答：支持蓝牙 5.3 双设备连接。"""),
    ("aftersale/物流与运费说明.md", """# 物流与运费说明

默认发货时效：现货商品下单后 48 小时内发出，预售商品以商品页标注时间为准。
快递承运：默认顺丰 / 中通，部分偏远地区转为邮政 EMS。
运费规则：满 99 元包邮；未满 99 元收取运费 8 元；偏远地区运费按实际产生金额收取。
发货提醒：付款后系统会自动推送物流单号，可在订单中心查询。

问：多久能发货？
答：现货商品 48 小时内发货。
问：满多少包邮？
答：单笔订单满 99 元包邮。
问：偏远地区运费怎么算？
答：偏远地区运费按实际产生金额收取。"""),
    ("aftersale/售后FAQ.md", """# 售后常见问题 FAQ

问：发票怎么开？
答：可在订单详情中申请电子发票，支持个人或企业抬头。
问：可以改收货地址吗？
答：商品未发货前可在订单中心自行修改；已发货则需联系客服处理。
问：多久可以收到退款？
答：退款审核通过后，一般 1-3 个工作日到账，具体以支付渠道为准。
问：客服人工几点在线？
答：人工客服在线时间为每天 9:00-22:00。"""),
    ("aftersale/退换货规则.md", """# 退换货规则

七天无理由退货：自签收之日起 7 天内，商品完好、不影响二次销售，支持无理由退货。
退货运费：无理由退货运费由买家承担；质量问题退货运费由商家承担。
换货：在 15 天质量保障期内，出现非人为损坏的性能故障，支持更换同型号新机。
退款路径：货款原路退回，1-3 个工作日到账。
注意事项：定制、生鲜、特殊标注商品不支持七天无理由退换。"""),
    ("aftersale/常见投诉处理.md", """# 常见投诉处理指引

投诉一：商品破损 / 少件
处理：核实物流与开箱视频，确认后补发或退款，并对用户致歉。

投诉二：发货超时
处理：核对订单与发货时间，若属超时，按规则补偿优惠券或运费。

投诉三：商品质量问题（无法开机 / 无法连接）
处理：引导用户进入质量检测流程，凭证齐全可申请换新或退款。

投诉四：退款迟迟未到账
处理：分渠道核实支付平台处理状态，向用户说明预计到账时间并跟进。"""),
]


def write_docs(base: Path) -> None:
    for rel, content in TEST_DOCS:
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.strip() + "\n", encoding="utf-8")
        print("  生成 " + str(target.relative_to(base)))


def main() -> int:
    stats.init()
    print("1) 清空向量库（删除旧切片与内置示例）...")
    vectorstore.drop_collection()
    vectorstore.get_collection()

    for sub in ("goods", "aftersale"):
        target = DATA / sub
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    print("2) 已清空旧示例内容，写入新的测试数据：")
    write_docs(DATA)

    print("3) 向量化并导入 Milvus（首次会加载本地 Embedding 模型，请耐心等待）...")
    detail = ingest.ingest_directory()
    ok = [d for d in detail if "error" not in d]
    bad = [d for d in detail if "error" in d]
    print("\n导入完成：文件 %d 个，切片 %d 条" % (len(ok), sum(d["chunk_count"] for d in ok)))
    for item in ok:
        gid = item["goods_id"] or "通用"
        print("  + %-34s type=%s goods=%s chunks=%d" % (item["source"], item["doc_type"], gid, item["chunk_count"]))
    for item in bad:
        print("  ! %s 失败: %s" % (item["source"], item["error"]))
    print("知识库当前切片总数: %d" % vectorstore.count())
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print("\n[错误] 生成/导入失败: %s" % exc)
        print("提示：请确认 Milvus 已启动（运行 start.bat 或 docker compose up -d etcd minio milvus）后重试。")
        raise SystemExit(1)