# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.sync_customer_order_info import plan_sync


def snapshot(path: Path, sku: str = "SKU-1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "user": "[hidden]",
        "user_address": "[hidden]",
        "goods_list": [{
            "id": 1,
            "number": sku,
            "name": "测试商品",
            "goods_num": 1,
            "main_img": "images/sku.png",
        }],
    }, ensure_ascii=False), encoding="utf-8")


class OrderInfoSyncTest(unittest.TestCase):
    def test_ticket_scenario_and_label_must_uniquely_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "help_ticket_order_info"
            snapshot(source_root / "售后样本" / "04_发错货_负样本" / "123" / "order_info_snapshot.json")
            (root / "02_发错货" / "02_负样本__人工拒绝或审核不通过" / "123").mkdir(parents=True)
            (root / "04_开箱视频" / "01_合格" / "123").mkdir(parents=True)

            report = plan_sync(root, source_root)

        self.assertEqual(report["status_counts"], {"ready": 1})
        self.assertIn("02_发错货", report["rows"][0]["target"])

    def test_existing_different_snapshot_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "help_ticket_order_info"
            snapshot(source_root / "售后样本" / "03_漏发货_负样本" / "456" / "order_info_snapshot.json", "SKU-A")
            target = root / "03_漏发货" / "02_负样本__人工拒绝或审核不通过" / "456"
            snapshot(target / "order_info_snapshot.json", "SKU-B")

            report = plan_sync(root, source_root)

        self.assertEqual(report["status_counts"], {"target_conflict": 1})

    def test_same_scenario_but_opposite_label_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "help_ticket_order_info"
            snapshot(source_root / "售后样本" / "04_发错货_负样本" / "789" / "order_info_snapshot.json")
            (root / "02_发错货" / "01_正样本__人工认可或审核通过" / "789").mkdir(parents=True)

            report = plan_sync(root, source_root)

        self.assertEqual(report["status_counts"], {"scenario_or_label_mismatch": 1})
        self.assertEqual(report["rows"][0]["target"], "")

    def test_multiple_sources_cannot_target_the_same_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "help_ticket_order_info"
            snapshot(source_root / "来源A" / "发错货_负样本" / "888" / "order_info_snapshot.json", "SKU-A")
            snapshot(source_root / "来源B" / "发错货_负样本" / "888" / "order_info_snapshot.json", "SKU-B")
            (root / "02_发错货" / "02_负样本__人工拒绝或审核不通过" / "888").mkdir(parents=True)

            report = plan_sync(root, source_root)

        self.assertEqual(report["status_counts"], {"ambiguous_source_target": 2})

    def test_evaluation_marker_in_allowed_product_fields_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "help_ticket_order_info"
            source = source_root / "售后样本" / "03_漏发货_负样本" / "999" / "order_info_snapshot.json"
            snapshot(source)
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["goods_list"][0]["name"] = "人工结论：负样本"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            (root / "03_漏发货" / "02_负样本__人工拒绝或审核不通过" / "999").mkdir(parents=True)

            report = plan_sync(root, source_root)

        self.assertEqual(report["status_counts"], {"invalid_source": 1})
        self.assertIn("goods_1_forbidden_evaluation_marker", report["rows"][0]["validation_errors"])


if __name__ == "__main__":
    unittest.main()
