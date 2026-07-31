# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.build_blind_review_bundle import build_bundle
from scripts.run_blind_damage_regression import submission_paths, validate_label_isolation


class BlindReviewBundleTest(unittest.TestCase):
    def test_bundle_excludes_human_answers_and_keeps_media(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source"
            output = Path(temp_dir) / "blind" / "CASE-1"
            source.mkdir()
            (source / "content.txt").write_text("商品到手有伤", encoding="utf-8")
            (source / "evidence.jpg").write_bytes(b"image")
            (source / "reply.json").write_text(
                json.dumps(
                    [
                        {"from": "user", "text": "撕拉拍立得需要退货", "created_at": "2026-07-09 10:00:00"},
                        {"from": "admin", "text": "人工审核不通过", "created_at": "2026-07-09 10:01:00"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (source / "annotation.json").write_text('{"正/负样本":"负样本"}', encoding="utf-8")
            (source / "order_info_snapshot.json").write_text(
                json.dumps(
                    {
                        "baseline_version": "ORDER-1@V1",
                        "expected_items": [{"sku": "SKU-1", "product_name": "测试商品"}],
                        "manual_label": "negative",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (source / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": 1,
                        "order_no": "ORDER-1",
                        "tag": "负样本",
                        "status": "人工审核不通过",
                        "admin_status": "rejected",
                        "resources": [{"local_file": "evidence.jpg", "fields": ["images"], "status": "downloaded"}],
                        "annotation": {"labels": {"正/负样本": "负样本"}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            audit = build_bundle(source, output)
            manifest = (output / "manifest.json").read_text(encoding="utf-8")
            customer_context = (output / "customer_context.json").read_text(encoding="utf-8")
            order_snapshot = (output / "order_info_snapshot.json").read_text(encoding="utf-8")
            media_exists = (output / "evidence.jpg").exists()
            media_reused = os.path.samefile(source / "evidence.jpg", output / "evidence.jpg")

        self.assertTrue(media_exists)
        self.assertTrue(media_reused)
        self.assertIn("annotation.json", audit["excluded_files"])
        self.assertIn("reply.json", audit["excluded_files"])
        self.assertNotIn("annotation", manifest)
        self.assertNotIn("负样本", manifest)
        self.assertNotIn('"tag"', manifest)
        self.assertNotIn('"status": "人工审核不通过"', manifest)
        self.assertNotIn("admin_status", manifest)
        self.assertIn("SKU-1", order_snapshot)
        self.assertNotIn("manual_label", order_snapshot)
        self.assertNotIn("negative", order_snapshot)
        self.assertIn("撕拉拍立得需要退货", customer_context)
        self.assertNotIn("人工审核不通过", customer_context)
        self.assertEqual(audit["customer_message_count"], 1)
        self.assertEqual(
            set(audit["included_files"]),
            {"content.txt", "customer_context.json", "evidence.jpg", "manifest.json", "order_info_snapshot.json"},
        )

    def test_runner_rejects_file_not_listed_by_bundle_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir)
            (bundle / "content.txt").write_text("商品有伤", encoding="utf-8")
            (bundle / "hidden-answer.json").write_text('{"label":"negative"}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "blind_bundle_file_set_mismatch"):
                submission_paths(bundle, {"included_files": ["content.txt"]})

    def test_runner_allows_source_without_annotation_file(self):
        validate_label_isolation({"included_files": ["content.txt"], "excluded_files": ["reply.json"]})

    def test_runner_rejects_forbidden_answer_in_submission_allowlist(self):
        with self.assertRaisesRegex(ValueError, "blind_bundle_isolation_failed"):
            validate_label_isolation({"included_files": ["content.txt", "reply.json"]})


if __name__ == "__main__":
    unittest.main()
