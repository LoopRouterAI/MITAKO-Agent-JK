from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.visual_review_poc.model_selection_e2e import call_model_chunked, gemini_payload, openai_messages
from poc.visual_review_poc.review_model_prompt import build_selection_prompt


class ModelRequestIsolationTest(unittest.TestCase):
    def test_original_media_names_and_fields_never_enter_final_requests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media = Path(temp_dir) / "02_负样本__人工拒绝_审核不通过.jpg"
            media.write_bytes(b"binary-evidence")
            case = {
                "scenario_label": "商品有伤审核",
                "customer_claim": "商品包装有压痕",
                "order_context": {},
                "structured_business_context": {},
                "evidence_assets": [],
                "videos": [
                    {
                        "video_index": 1,
                        "file": media.name,
                        "duration_seconds": 10,
                        "native_fps": 30,
                        "sampled_frames": 1,
                    }
                ],
                "frames": [
                    {
                        "video_index": 1,
                        "global_frame_index": 1,
                        "video_file": media.name,
                        "timestamp": "00:01.00",
                        "file": media.name,
                        "api_path": str(media),
                        "api_mime_type": "image/jpeg",
                    }
                ],
                "supplemental_images": [
                    {
                        "image_index": 1,
                        "file": media.name,
                        "fields": ["人工拒绝"],
                        "width": 1,
                        "height": 1,
                        "has_exif": False,
                        "api_path": str(media),
                        "api_mime_type": "image/jpeg",
                    }
                ],
            }
            prompt = build_selection_prompt(case)
            payloads = [
                gemini_payload("系统", prompt, case),
                openai_messages("系统", prompt, case),
            ]
        serialized = json.dumps(payloads, ensure_ascii=False)
        for marker in ("负样本", "人工拒绝", "审核不通过", media.name):
            self.assertNotIn(marker, serialized)
        self.assertIn("video_1_frame_1", serialized)
        self.assertIn("supplemental_image_1", serialized)

    def test_official_product_images_have_a_separate_non_customer_evidence_role(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media = Path(temp_dir) / "official.jpg"
            media.write_bytes(b"official-reference")
            case = {
                "scenario_label": "发错货审核",
                "customer_claim": "收到的款式不对",
                "order_context": {},
                "structured_business_context": {
                    "fulfillment_baseline": {
                        "expected_items": [{
                            "item_ref": "ORDER-LINE-001",
                            "sku": "SKU-001",
                            "product_name": "官方商品",
                            "expected_quantity": 1,
                        }],
                    },
                    "official_reference_summary": {"status": "available", "available_count": 1},
                },
                "evidence_assets": [],
                "videos": [],
                "frames": [],
                "supplemental_images": [],
                "official_reference_images": [{
                    "reference_index": 1,
                    "reference_id": "ref-001",
                    "item_ref": "ORDER-LINE-001",
                    "sku": "SKU-001",
                    "product_name": "官方商品",
                    "evidence_role": "official_product_reference",
                    "api_path": str(media),
                    "api_mime_type": "image/jpeg",
                }],
            }

            prompt = build_selection_prompt(case)
            payloads = [
                gemini_payload("系统", prompt, case),
                openai_messages("系统", prompt, case),
            ]

        serialized = json.dumps(payloads, ensure_ascii=False)
        self.assertIn("official_product_reference_1", serialized)
        self.assertIn("官方商品参考图", serialized)
        self.assertIn("不能作为用户开箱证据", prompt)
        self.assertNotIn("supplemental_image_1", serialized)

    def test_chunked_review_sends_official_references_to_at_most_three_segments(self):
        observed_counts = []
        case = {
            "case_id": "case-cost-boundary",
            "scenario": "wrong_item",
            "frames": [{"global_frame_index": index} for index in range(240)],
            "model_frames_per_call": 24,
            "structured_business_context": {"business_scenario": "wrong_item"},
            "official_reference_images": [{"reference_index": 1}, {"reference_index": 2}],
        }

        def fake_call_model(cfg, current, timeout, retries):
            observed_counts.append(len(current.get("official_reference_images") or []))
            return {"status": "success", "parsed": {}, "usage": {}, "cost": {}, "latency_seconds": 0.01}

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=fake_call_model), patch(
            "poc.visual_review_poc.model_selection_e2e._aggregate_chunk_results",
            return_value={"status": "success", "parsed": {}, "chunking": {}},
        ):
            result = call_model_chunked({}, case, timeout=1, retries=0)

        self.assertEqual(sum(count > 0 for count in observed_counts), 3)
        self.assertEqual(sum(observed_counts), 6)
        self.assertEqual(result["chunking"]["official_reference_model_sends"], 6)


if __name__ == "__main__":
    unittest.main()
