# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.reconcile_customer_order_info import reconcile_plan
from scripts.sync_customer_order_info import sha256


class OrderInfoReconcileTest(unittest.TestCase):
    def test_only_unchanged_cross_label_legacy_copy_is_removable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "help_ticket_order_info"
            source = source_root / "发错货_负样本" / "123" / "order_info_snapshot.json"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({"goods_list": [{
                "id": 1, "number": "SKU-1", "name": "商品", "goods_num": 1,
            }]}, ensure_ascii=False), encoding="utf-8")
            target = root / "02_发错货" / "01_正样本__人工认可或审核通过" / "123" / "order_info_snapshot.json"
            target.parent.mkdir(parents=True)
            target.write_bytes(source.read_bytes())
            applied = root / "applied.json"
            applied.write_text(json.dumps({"rows": [{
                "ticket_id": "123",
                "source": str(source),
                "target": str(target),
                "source_sha256": sha256(source),
                "status": "copied",
            }]}, ensure_ascii=False), encoding="utf-8")

            report = reconcile_plan(root.resolve(), source_root.resolve(), applied.resolve())

        self.assertEqual(report["status_counts"], {"ready_to_remove": 1})

    def test_modified_target_is_never_removed_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "help_ticket_order_info"
            source = source_root / "漏发货_负样本" / "456" / "order_info_snapshot.json"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({"goods_list": [{
                "id": 1, "number": "SKU-1", "name": "商品", "goods_num": 1,
            }]}, ensure_ascii=False), encoding="utf-8")
            original_hash = sha256(source)
            target = root / "03_漏发货" / "01_正样本__人工认可或审核通过" / "456" / "order_info_snapshot.json"
            target.parent.mkdir(parents=True)
            target.write_text("modified", encoding="utf-8")
            applied = root / "applied.json"
            applied.write_text(json.dumps({"rows": [{
                "ticket_id": "456",
                "source": str(source),
                "target": str(target),
                "source_sha256": original_hash,
                "status": "copied",
            }]}, ensure_ascii=False), encoding="utf-8")

            report = reconcile_plan(root.resolve(), source_root.resolve(), applied.resolve())

        self.assertEqual(report["status_counts"], {"target_changed_not_removed": 1})
