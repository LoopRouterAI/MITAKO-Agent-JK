# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from poc.visual_review_poc import workbench_server
from poc.visual_review_poc.object_continuity import (
    aggregate_object_continuity,
    apply_object_continuity_guard,
)


def continuity(verdict="continuous", duration=0.0):
    events = []
    if duration:
        events.append(
            {
                "start_timestamp": "00:10.00",
                "end_timestamp": "00:13.00",
                "duration_seconds": duration,
                "visibility": "out_of_frame",
            }
        )
    return {
        "tracked_subjects": [
            {
                "subject_id": "claimed_item",
                "description": "争议商品",
                "visibility_coverage": 0.8,
                "out_of_frame_events": events,
            }
        ],
        "continuity_verdict": verdict,
        "longest_out_of_frame_seconds": duration,
    }


class ObjectContinuityTest(unittest.TestCase):
    def test_product_damage_ignores_shipping_package_absence_after_claimed_item_exposure(self):
        result = apply_object_continuity_guard(
            {
                "predicted_label": "positive",
                "confidence": 0.91,
                "damage_causality_assessment": {"damage_presence": "confirmed"},
                "object_continuity_assessment": {
                    "continuity_verdict": "long_absence",
                    "longest_out_of_frame_seconds": 31.8,
                    "tracked_subjects": [
                        {
                            "subject_id": "shipping_package",
                            "out_of_frame_events": [{"duration_seconds": 31.8}],
                        },
                        {
                            "subject_id": "claimed_item",
                            "visibility_coverage": 1.0,
                            "out_of_frame_events": [],
                        },
                    ],
                },
            },
            "product_damage",
            True,
            {"out_of_frame_warning_seconds": 3.0},
        )

        self.assertEqual(result["predicted_label"], "positive")
        self.assertEqual(result["continuity_recommendation"], "continue")
        self.assertEqual(result["object_continuity_assessment"]["relevant_subject_id"], "claimed_item")
        self.assertEqual(result["object_continuity_assessment"]["relevant_longest_out_of_frame_seconds"], 0.0)

    def test_missing_subject_timeline_cannot_claim_continuity(self):
        result = apply_object_continuity_guard(
            {"predicted_label": "positive", "confidence": 0.95},
            "product_damage",
            True,
        )
        self.assertEqual(result["predicted_label"], "review")
        self.assertEqual(result["confidence"], 0.95)
        self.assertIn("没有定义", result["continuity_guard_reason"])

    def test_missing_timeline_does_not_erase_confirmed_damage_fact(self):
        result = apply_object_continuity_guard(
            {
                "predicted_label": "positive",
                "confidence": 0.91,
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "claim_support": "insufficient",
                },
            },
            "product_damage",
            True,
        )
        self.assertEqual(result["predicted_label"], "positive")
        self.assertEqual(result["continuity_recommendation"], "continue_with_warning")
        self.assertIn("不覆盖已确认的可见伤情", result["continuity_guard_reason"])

    def test_configurable_long_absence_preserves_label_and_requests_more_material(self):
        result = apply_object_continuity_guard(
            {
                "predicted_label": "positive",
                "confidence": 0.92,
                "object_continuity_assessment": continuity("continuous", 3.0),
            },
            "product_damage",
            True,
            {"out_of_frame_warning_seconds": 2.0},
        )
        self.assertEqual(result["predicted_label"], "positive")
        self.assertEqual(result["continuity_recommendation"], "request_more_material")
        self.assertFalse(result["continuity_requires_human_review"])
        self.assertIn("3.00 秒", result["continuity_guard_reason"])

    def test_brief_occlusion_within_threshold_preserves_label(self):
        result = apply_object_continuity_guard(
            {
                "predicted_label": "positive",
                "confidence": 0.88,
                "object_continuity_assessment": continuity("brief_occlusion", 0.8),
            },
            "product_damage",
            True,
            {"out_of_frame_warning_seconds": 2.0},
        )
        self.assertEqual(result["predicted_label"], "positive")

    def test_chunk_aggregation_keeps_longest_absence(self):
        combined = aggregate_object_continuity(
            [
                {"object_continuity_assessment": continuity("continuous", 0.0)},
                {"object_continuity_assessment": continuity("long_absence", 5.5)},
            ]
        )
        self.assertEqual(combined["continuity_verdict"], "long_absence")
        self.assertEqual(combined["longest_out_of_frame_seconds"], 5.5)

    def test_not_yet_exposed_is_not_counted_and_frame_timeline_derives_absence(self):
        findings = []
        states = [
            (0, "not_yet_exposed"),
            (26, "visible"),
            (28, "out_of_frame"),
            (29, "out_of_frame"),
            (30, "out_of_frame"),
            (31, "out_of_frame"),
            (32, "visible"),
        ]
        for index, (timestamp, state) in enumerate(states, start=1):
            findings.append(
                {
                    "global_frame_index": index,
                    "timestamp": f"00:{timestamp:02d}.00",
                    "subject_visibility": [{"subject_id": "product_package", "state": state}],
                }
            )
        frames = [
            {
                "video_index": 1,
                "global_frame_index": finding["global_frame_index"],
                "timestamp": finding["timestamp"],
            }
            for finding in findings
        ]
        combined = aggregate_object_continuity(
            [{"frame_findings": findings, "object_continuity_assessment": continuity("continuous", 0.0)}],
            frames,
        )
        subject = next(item for item in combined["tracked_subjects"] if item["subject_id"] == "product_package")
        self.assertEqual(combined["timeline_derivation"], "deterministic_frame_timeline")
        self.assertEqual(subject["longest_out_of_frame_seconds"], 4.0)
        self.assertEqual(combined["longest_out_of_frame_seconds"], 4.0)
        event = subject["out_of_frame_events"][0]
        self.assertEqual(event["duration_basis"], "sampled_source_timestamps")
        self.assertFalse(event["duration_is_exact"])
        self.assertEqual(event["duration_lower_bound_seconds"], 3.0)
        self.assertEqual(event["duration_upper_bound_seconds"], 6.0)
        self.assertEqual(event["sampling_resolution_seconds"], 2.0)
        self.assertEqual(combined["longest_out_of_frame_lower_bound_seconds"], 3.0)
        self.assertEqual(combined["longest_out_of_frame_upper_bound_seconds"], 6.0)

    def test_trailing_absence_has_no_finite_upper_bound_without_video_end_anchor(self):
        findings = [
            {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00", "subject_visibility": [{"subject_id": "claimed_item", "state": "visible"}]},
            {"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00", "subject_visibility": [{"subject_id": "claimed_item", "state": "out_of_frame"}]},
            {"video_index": 1, "global_frame_index": 3, "timestamp": "00:02.00", "subject_visibility": [{"subject_id": "claimed_item", "state": "out_of_frame"}]},
        ]
        frames = [
            {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
            {"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00"},
            {"video_index": 1, "global_frame_index": 3, "timestamp": "00:02.00"},
        ]

        combined = aggregate_object_continuity([{"frame_findings": findings}], frames)
        event = combined["out_of_frame_events"][0]

        self.assertEqual(event["duration_seconds"], 1.0)
        self.assertEqual(event["duration_lower_bound_seconds"], 1.0)
        self.assertIsNone(event["duration_upper_bound_seconds"])
        self.assertFalse(event["duration_is_exact"])
        self.assertIsNone(combined["longest_out_of_frame_upper_bound_seconds"])

    def test_public_contract_keeps_deterministic_duration_bounds(self):
        projected = workbench_server._public_parsed(
            {
                "object_continuity_assessment": {
                    "longest_out_of_frame_seconds": 4.0,
                    "longest_out_of_frame_lower_bound_seconds": 3.0,
                    "longest_out_of_frame_upper_bound_seconds": 6.0,
                    "out_of_frame_events": [{
                        "duration_seconds": 4.0,
                        "duration_basis": "sampled_source_timestamps",
                        "duration_is_exact": False,
                        "duration_lower_bound_seconds": 3.0,
                        "duration_upper_bound_seconds": 6.0,
                        "sampling_resolution_seconds": 2.0,
                    }],
                }
            },
            "product_damage",
        )

        assessment = projected["object_continuity_assessment"]
        self.assertEqual(assessment["longest_out_of_frame_lower_bound_seconds"], 3.0)
        self.assertEqual(assessment["longest_out_of_frame_upper_bound_seconds"], 6.0)
        event = assessment["out_of_frame_events"][0]
        self.assertEqual(event["duration_basis"], "sampled_source_timestamps")
        self.assertEqual(event["sampling_resolution_seconds"], 2.0)

    def test_short_return_after_absence_is_a_local_risk_not_a_whole_case_veto(self):
        findings = [
            {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00", "subject_visibility": [{"subject_id": "product_package", "state": "visible"}]},
            {"video_index": 1, "global_frame_index": 2, "timestamp": "00:00.50", "subject_visibility": [{"subject_id": "product_package", "state": "out_of_frame"}]},
            {"video_index": 1, "global_frame_index": 3, "timestamp": "00:01.00", "subject_visibility": [{"subject_id": "product_package", "state": "visible"}]},
        ]
        frames = [
            {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00", "source_timestamp": "00:20.00"},
            {"video_index": 1, "global_frame_index": 2, "timestamp": "00:00.50", "source_timestamp": "00:20.50"},
            {"video_index": 1, "global_frame_index": 3, "timestamp": "00:01.00", "source_timestamp": "00:21.00"},
        ]
        combined = aggregate_object_continuity([{"frame_findings": findings}], frames, {"out_of_frame_warning_seconds": 2.0})
        guarded = apply_object_continuity_guard(
            {"predicted_label": "positive", "confidence": 0.9, "object_continuity_assessment": combined},
            "wrong_item",
            True,
            {"out_of_frame_warning_seconds": 2.0},
        )
        self.assertEqual(combined["continuity_verdict"], "brief_occlusion")
        self.assertEqual(combined["out_of_frame_events"][0]["start_timestamp"], "00:20.50")
        self.assertFalse(combined["out_of_frame_events"][0]["identity_reestablished"])
        self.assertEqual(guarded["predicted_label"], "positive")

    def test_unknown_frames_reduce_visibility_coverage(self):
        findings = [
            {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00", "subject_visibility": [{"subject_id": "claimed_item", "state": "visible"}]},
            {"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00", "subject_visibility": [{"subject_id": "claimed_item", "state": "unknown"}]},
        ]
        frames = [
            {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
            {"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00"},
        ]

        combined = aggregate_object_continuity([{"frame_findings": findings}], frames)
        subject = next(item for item in combined["tracked_subjects"] if item["subject_id"] == "claimed_item")

        self.assertEqual(subject["visibility_coverage"], 0.5)
        self.assertEqual(combined["continuity_verdict"], "continuous")

    def test_timelines_do_not_merge_across_videos_with_same_timestamps(self):
        rows = [
            {
                "frame_findings": [
                    {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00", "subject_visibility": [{"subject_id": "claimed_item", "state": "visible"}]},
                    {"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00", "subject_visibility": [{"subject_id": "claimed_item", "state": "out_of_frame"}]},
                    {"video_index": 2, "global_frame_index": 3, "timestamp": "00:00.00", "subject_visibility": [{"subject_id": "claimed_item", "state": "visible"}]},
                ]
            }
        ]
        frames = [
            {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
            {"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00"},
            {"video_index": 2, "global_frame_index": 3, "timestamp": "00:00.00"},
        ]
        combined = aggregate_object_continuity(rows, frames)
        video_one = next(item for item in combined["tracked_subjects"] if item["video_index"] == 1)
        self.assertFalse(video_one["out_of_frame_events"][0]["identity_reestablished"])
        self.assertEqual(combined["continuity_verdict"], "indeterminate")

    def test_complete_reference_anchored_timeline_can_confirm_claimed_item_never_appeared(self):
        findings = [
            {
                "video_index": 1,
                "global_frame_index": index,
                "timestamp": f"00:0{index}.00",
                "subject_visibility": [
                    {"subject_id": "claimed_item", "state": "not_yet_exposed", "identity_match": "not_matched"}
                ],
            }
            for index in (1, 2, 3)
        ]
        frames = [
            {"video_index": 1, "global_frame_index": index, "timestamp": f"00:0{index}.00"}
            for index in (1, 2, 3)
        ]
        combined = aggregate_object_continuity(
            [{
                "frame_findings": findings,
                "object_continuity_assessment": {"claimed_item_reference_status": "available"},
            }],
            frames,
        )

        self.assertTrue(combined["claimed_item_never_exposed"])
        self.assertTrue(combined["claimed_item_timeline_complete"])
        self.assertEqual(combined["claimed_item_reference_status"], "available")

    def test_unknown_identity_frames_do_not_claim_never_exposed(self):
        findings = [{
            "video_index": 1,
            "global_frame_index": 1,
            "timestamp": "00:01.00",
            "subject_visibility": [{"subject_id": "claimed_item", "state": "unknown", "identity_match": "uncertain"}],
        }]
        combined = aggregate_object_continuity(
            [{
                "frame_findings": findings,
                "object_continuity_assessment": {"claimed_item_reference_status": "available"},
            }],
            [{"video_index": 1, "global_frame_index": 1, "timestamp": "00:01.00"}],
        )

        self.assertFalse(combined["claimed_item_never_exposed"])


if __name__ == "__main__":
    unittest.main()
