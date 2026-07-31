# -*- coding: utf-8 -*-
import unittest

from poc.visual_review_poc.model_selection_e2e import _apply_global_timeline_summary


class GlobalTimelineAggregation0717Test(unittest.TestCase):
    def test_chunk_end_before_later_evidence_is_not_public_conclusion(self):
        case = {
            "frames": [
                {"timestamp": "00:00.00"},
                {"timestamp": "00:11.44"},
                {"timestamp": "00:52.22"},
                {"timestamp": "01:11.60"},
            ],
            "videos": [{"duration_seconds": 71.6}],
        }
        parsed = {
            "predicted_label": "positive",
            "system_yes_no": "YES",
            "confidence": 0.95,
            "object_continuity_assessment": {
                "continuity_verdict": "long_absence",
                "longest_out_of_frame_seconds": 12.0,
                "tracked_subjects": [
                    {"subject_id": "claimed_item", "first_exposed_timestamp": "00:52.22"}
                ],
            },
        }
        rows = [{"video_audit_conclusion": {"opening_integrity": "complete", "swap_risk_level": "low"}}]
        result = _apply_global_timeline_summary(
            case,
            parsed,
            rows,
            ["视频在 00:11.44 结束，未见异常"],
        )
        self.assertEqual(result["predicted_label"], "positive")
        self.assertEqual(result["confidence"], 0.95)
        self.assertEqual(result["aggregation_warnings"][0]["code"], "chunk_end_before_later_evidence")
        self.assertNotIn("00:11.44 结束", result["overall_audit"]["conclusion"])
        self.assertIn("00:52.22", result["overall_audit"]["conclusion"])
        self.assertEqual(result["global_review_summary"]["claimed_item_first_exposed_timestamp"], "00:52.22")

    def test_summary_is_independent_of_high_confidence_chunk_narrative(self):
        case = {"frames": [{"timestamp": "00:00.00"}, {"timestamp": "00:20.00"}], "videos": [{"duration_seconds": 20.0}]}
        parsed = {
            "predicted_label": "review",
            "confidence": 0.69,
            "object_continuity_assessment": {"continuity_verdict": "indeterminate", "tracked_subjects": []},
        }
        rows = [
            {"video_audit_conclusion": {"opening_integrity": "complete", "swap_risk_level": "low"}},
            {"video_audit_conclusion": {"opening_integrity": "incomplete", "swap_risk_level": "high"}},
        ]
        first = _apply_global_timeline_summary(case, parsed, rows, ["局部 A", "局部 B"])
        second = _apply_global_timeline_summary(case, parsed, list(reversed(rows)), ["局部 B", "局部 A"])
        self.assertEqual(first["overall_audit"], second["overall_audit"])
        self.assertEqual(first["video_audit_conclusion"], second["video_audit_conclusion"])

    def test_global_summary_preserves_accelerated_playback_observation(self):
        case = {"frames": [{"timestamp": "00:00.00"}, {"timestamp": "00:20.00"}], "videos": [{"duration_seconds": 20.0}]}
        parsed = {
            "predicted_label": "review",
            "confidence": 0.69,
            "object_continuity_assessment": {"continuity_verdict": "indeterminate", "tracked_subjects": []},
        }
        rows = [
            {"video_audit_conclusion": {"playback_speed": "unknown"}},
            {"video_audit_conclusion": {"playback_speed": "accelerated"}},
        ]

        result = _apply_global_timeline_summary(case, parsed, rows, ["", ""])

        self.assertEqual(result["video_audit_conclusion"]["playback_speed"], "accelerated")
        self.assertEqual(
            result["video_audit_conclusion"]["segment_playback_speed_values"],
            ["accelerated", "unknown"],
        )

    def test_segment_opening_claim_is_not_presented_as_deterministic_completeness(self):
        case = {
            "frames": [{"timestamp": "00:00.00"}, {"timestamp": "03:31.73"}],
            "videos": [{"duration_seconds": 211.77}],
        }
        parsed = {
            "predicted_label": "review",
            "confidence": 0.69,
            "object_continuity_assessment": {
                "continuity_verdict": "indeterminate",
                "tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "first_exposed_timestamp": "00:39.93",
                    "visibility_coverage": 0.89,
                    "longest_out_of_frame_seconds": 10.0,
                }],
            },
        }
        rows = [
            {"video_audit_conclusion": {"opening_integrity": "complete", "swap_risk_level": "low"}},
            {"video_audit_conclusion": {"opening_integrity": "complete", "swap_risk_level": "low"}},
        ]

        result = _apply_global_timeline_summary(case, parsed, rows, ["", ""])

        self.assertEqual(result["video_audit_conclusion"]["opening_integrity"], "indeterminate")
        self.assertEqual(result["video_audit_conclusion"]["opening_integrity_source"], "model_segment_consensus")
        self.assertEqual(result["video_audit_conclusion"]["sampling_boundary_status"], "covered")
        self.assertEqual(result["video_audit_conclusion"]["technical_timeline_status"], "requires_media_forensics")
        self.assertEqual(result["video_audit_conclusion"]["evidence_continuity_status"], "indeterminate")
        self.assertEqual(result["global_review_summary"]["timeline_coverage_ratio"], 0.9998)

    def test_full_timeline_opening_stages_can_establish_complete_opening(self):
        case = {
            "frames": [{"timestamp": "00:00.00"}, {"timestamp": "00:03.00"}],
            "videos": [{"duration_seconds": 3.0}],
        }
        parsed = {
            "predicted_label": "review",
            "confidence": 0.8,
            "object_continuity_assessment": {"continuity_verdict": "continuous", "tracked_subjects": []},
            "continuity_frame_findings": [
                {"global_frame_index": 1, "timestamp": "00:00.00", "opening_stage": "sealed_package"},
                {"global_frame_index": 2, "timestamp": "00:01.00", "opening_stage": "opening_in_progress"},
                {"global_frame_index": 3, "timestamp": "00:02.00", "opening_stage": "item_exposed"},
                {"global_frame_index": 4, "timestamp": "00:03.00", "opening_stage": "contents_displayed"},
            ],
        }

        result = _apply_global_timeline_summary(case, parsed, [], [])

        self.assertEqual(result["video_audit_conclusion"]["opening_integrity"], "complete")
        self.assertEqual(result["video_audit_conclusion"]["opening_integrity_source"], "full_timeline_continuity")


if __name__ == "__main__":
    unittest.main()
