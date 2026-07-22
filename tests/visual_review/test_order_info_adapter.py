# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.visual_review_poc.local_video_triage_demo import load_case_from_folder, order_info_context


class OrderInfoAdapterTest(unittest.TestCase):
    def test_customer_snapshot_becomes_minimized_order_and_fulfillment_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "617911"
            folder.mkdir()
            (folder / "content.txt").write_text("商品有伤", encoding="utf-8")
            snapshot = {
                "user": "不应进入模型",
                "user_address": "不应进入模型",
                "express_fee": 6,
                "goods_list": [{
                    "id": 245606,
                    "number": "SKU-001",
                    "name": "测试商品",
                    "des": "红色款",
                    "intro": "93x67mm",
                    "goods_num": 2,
                    "main_img": "images/products/sku-001.png",
                    "price_fen": 350,
                }, {
                    "id": 245607,
                    "number": "SKU-001",
                    "name": "测试商品",
                    "des": "红色款",
                    "intro": "93x67mm",
                    "goods_num": 1,
                    "main_img": "images/products/sku-001.png",
                }],
                "tracking_company": "测试快递",
                "tracking_number": "TRACK-001",
                "lottery_info": [{
                    "lottery_type_code": "drawcard",
                    "lottery_id": 88,
                    "name": "测试抽赏",
                    "order_goods_ids": [245606, 245607],
                    "rule1": "随机款式，端盒保配。",
                    "all_goods": [{
                        "id": 245606,
                        "number": "SKU-001",
                        "name": "测试商品",
                        "sku_name": "红色款",
                        "main_img": "images/products/sku-001.png",
                        "price_fen": 999,
                    }, {
                        "id": 999999,
                        "number": "UNORDERED-SKU",
                        "name": "未下单商品",
                        "main_img": "images/products/unordered.png",
                    }],
                }],
            }
            path = folder / "order_info_snapshot.json"
            path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

            with patch.dict("os.environ", {
                "REVIEW_PRODUCT_IMAGE_BASE_URL": "https://product.example.test/base/",
            }):
                context = order_info_context(path)
                case = load_case_from_folder(folder, supplemental_limit=10)
            serialized = json.dumps(case["structured_business_context"], ensure_ascii=False)

        self.assertEqual(context["order_items"][0]["sku"], "SKU-001")
        self.assertEqual(context["order_items"][0]["expected_quantity"], 3)
        self.assertEqual(context["order_items"][0]["product_image_ref"], "images/products/sku-001.png")
        self.assertEqual(
            context["order_items"][0]["master_image_urls"],
            ["https://product.example.test/base/images/products/sku-001.png"],
        )
        self.assertEqual(context["logistics"], {
            "carrier": "测试快递",
            "tracking_ref": "sha256:015d9db4c0d91759",
        })
        self.assertNotIn("TRACK-001", serialized)
        baseline = context["fulfillment_baseline"]
        self.assertEqual(baseline["packages"], [])
        self.assertEqual(baseline["package_mapping_status"], "not_declared_in_snapshot")
        self.assertEqual(baseline["split_shipment_status"], "not_declared_in_snapshot")
        self.assertEqual(baseline["selection_rules"][0]["rule_text"], "随机款式，端盒保配。")
        self.assertFalse(baseline["selection_rules_complete"])
        self.assertEqual(
            case["structured_business_context"]["fulfillment_baseline"]["source"],
            "customer_order_info_snapshot",
        )
        self.assertEqual(
            case["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]["expected_items"][0]["sku"],
            "SKU-001",
        )
        self.assertNotIn("不应进入模型", serialized)
        self.assertNotIn("user_address", serialized)
        self.assertNotIn("price_fen", serialized)
        self.assertNotIn("UNORDERED-SKU", serialized)
        self.assertNotIn("all_goods", serialized)


if __name__ == "__main__":
    unittest.main()
