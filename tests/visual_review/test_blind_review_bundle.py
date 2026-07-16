# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_blind_review_bundle import build_bundle


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
            (source / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": 1,
                        "order_no": "ORDER-1",
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
            media_exists = (output / "evidence.jpg").exists()

        self.assertTrue(media_exists)
        self.assertIn("annotation.json", audit["excluded_files"])
        self.assertIn("reply.json", audit["excluded_files"])
        self.assertNotIn("annotation", manifest)
        self.assertNotIn("负样本", manifest)
        self.assertIn("撕拉拍立得需要退货", customer_context)
        self.assertNotIn("人工审核不通过", customer_context)
        self.assertEqual(audit["customer_message_count"], 1)


if __name__ == "__main__":
    unittest.main()
