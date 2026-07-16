from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from poc.visual_review_poc.model_selection_e2e import gemini_payload, openai_messages
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


if __name__ == "__main__":
    unittest.main()
