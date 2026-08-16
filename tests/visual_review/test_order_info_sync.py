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
    def test_source_inventory_reports_ticket_directories_without_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "_extracted" / "help_ticket_order_info"
            (source_root / "第一批" / "01_商品有伤" / "ticket_100").mkdir(parents=True)

            report = plan_sync(root, source_root)

        self.assertEqual(report["source_inventory"]["ticket_directories"], 1)
        self.assertEqual(report["source_inventory"]["snapshots"], 0)
        self.assertEqual(report["source_inventory"]["missing_snapshots"], 1)
        self.assertEqual(report["missing_snapshot_rows"][0]["ticket_id"], "100")

    def test_new_archive_ticket_prefix_and_batch_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "_extracted" / "help_ticket_order_info"
            snapshot(source_root / "第一批" / "01_商品有伤" / "ticket_617341" / "order_info_snapshot.json")
            expected = root / "第一批次样本" / "人工标签复核版" / "01_商品有伤__product_damage" / "03_不确定样本" / "617341"
            expected.mkdir(parents=True)
            other_batch = root / "第二批次样本" / "五场景重整理" / "01_商品有伤_负样本" / "617341"
            other_batch.mkdir(parents=True)

            report = plan_sync(root, source_root)

        self.assertEqual(report["status_counts"], {"ready": 1})
        self.assertEqual(report["rows"][0]["ticket_id"], "617341")
        self.assertIn("第一批次样本", report["rows"][0]["target"])

    def test_unknown_source_label_does_not_guess_between_duplicate_case_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "_extracted" / "help_ticket_order_info"
            snapshot(source_root / "第一批" / "02_发错货" / "ticket_114145" / "order_info_snapshot.json")
            (root / "第一批次样本" / "样本" / "02_发错货__wrong_item" / "01_正样本" / "114145").mkdir(parents=True)
            (root / "第一批次样本" / "样本" / "02_发错货__wrong_item" / "02_负样本" / "114145").mkdir(parents=True)

            report = plan_sync(root, source_root)

        self.assertEqual(report["status_counts"], {"ambiguous_target": 1})
        self.assertEqual(report["rows"][0]["target"], "")

    def test_raw_order_export_directory_is_not_considered_a_case_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "_extracted" / "help_ticket_order_info"
            snapshot(source_root / "第一批" / "03_漏发货" / "ticket_500" / "order_info_snapshot.json")
            expected = root / "第一批次样本" / "样本" / "03_漏发货__missing_item" / "01_正样本" / "500"
            expected.mkdir(parents=True)
            (root / "第一批次样本" / "按订单id-第一批次样本对应的订单信息" / "03_漏发货" / "500").mkdir(parents=True)

            report = plan_sync(root, source_root)

        self.assertEqual(report["status_counts"], {"ready": 1})
        self.assertIn("03_漏发货__missing_item", report["rows"][0]["target"])

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
