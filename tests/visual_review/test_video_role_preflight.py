# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import unittest
from pathlib import Path

from poc.visual_review_poc.video_role_preflight import (
    build_opening_role_case,
    declared_video_roles,
    opening_role_batches,
    select_opening_video_candidates,
)
from prompts.visual_review.review_model_prompt import build_opening_video_role_prompt


class VideoRolePreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.videos = [Path("001_closeup.mp4"), Path("002_opening.mp4")]

    def test_declared_role_is_only_a_routing_hint(self) -> None:
        context = {
            "asset_manifest": json.dumps({
                "assets": [
                    {"original_name": "001_closeup.mp4", "fields": ["damage_closeup"]},
                    {"original_name": "002_opening.mp4", "fields": ["opening_video"]},
                ],
            }, ensure_ascii=False),
        }
        roles = declared_video_roles(context, self.videos)
        case = build_opening_role_case(self.videos, [], roles)
        prompt = build_opening_video_role_prompt(case)

        self.assertEqual(roles["002_opening.mp4"], ["opening_video"])
        self.assertTrue(case["videos"][1]["declared_opening_role"])
        self.assertIn("只是路由提示，不能替代画面证据", prompt)

    def test_high_confidence_visual_evidence_only_moves_opening_candidate_first(self) -> None:
        parsed = {
            "candidates": [
                {
                    "video_index": 1,
                    "is_opening_video": False,
                    "sealed_package_visible": False,
                    "opening_action_visible": False,
                    "confidence": 0.91,
                    "reason": "只见商品特写。",
                    "evidence_refs": [{"global_frame_index": 1, "timestamp": "00:00.000"}],
                },
                {
                    "video_index": 2,
                    "is_opening_video": True,
                    "sealed_package_visible": True,
                    "opening_action_visible": True,
                    "confidence": 0.94,
                    "reason": "闭合包裹开始拆封。",
                    "evidence_refs": [{"global_frame_index": 11, "timestamp": "00:00.000"}],
                },
            ],
        }

        result = select_opening_video_candidates(self.videos, parsed, {})

        self.assertEqual(result["selected_videos"], [self.videos[1], self.videos[0]])
        self.assertEqual(result["routing_decision"], "opening_candidates_ranked_first")
        self.assertFalse(result["preview_is_full_compliance"])

    def test_uncertain_preflight_keeps_every_video(self) -> None:
        result = select_opening_video_candidates(
            self.videos,
            {"candidates": [{
                "video_index": 2,
                "is_opening_video": True,
                "sealed_package_visible": True,
                "opening_action_visible": None,
                "confidence": 0.62,
                "reason": "起始画面遮挡。",
                "evidence_refs": [{"global_frame_index": 11, "timestamp": "00:00.000"}],
            }]},
            {},
        )

        self.assertEqual(result["selected_videos"], self.videos)
        self.assertEqual(result["routing_decision"], "keep_all_candidates")

    def test_role_preflight_batches_at_most_two_videos_per_model_request(self) -> None:
        videos = [Path(f"{index:03d}.mp4") for index in range(1, 6)]

        batches = opening_role_batches(videos)

        self.assertEqual([len(batch) for batch in batches], [2, 2, 1])
        self.assertEqual(
            [[index for index, _video in batch] for batch in batches],
            [[1, 2], [3, 4], [5]],
        )

    def test_batched_role_case_preserves_global_video_indices(self) -> None:
        videos = [Path("003.mp4"), Path("004.mp4")]

        case = build_opening_role_case(
            videos,
            [{"video_index": 3, "global_frame_index": 21, "timestamp": "00:00.000"}],
            {},
            video_indices=[3, 4],
        )

        self.assertEqual([item["video_index"] for item in case["videos"]], [3, 4])
        self.assertEqual(case["frames"][0]["video_index"], 3)


if __name__ == "__main__":
    unittest.main()
