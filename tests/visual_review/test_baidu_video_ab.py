from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.run_baidu_video_ab import native_media_part_count, result_summary


ROOT = Path(__file__).resolve().parents[2]


class BaiduVideoAbTest(unittest.TestCase):
    def test_internal_ab_runner_exists(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("scripts.run_baidu_video_ab"))

    def test_runner_can_start_as_a_direct_script(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_baidu_video_ab.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn(b"--case-dir", completed.stdout)

    def test_summary_does_not_count_empty_structured_shells_as_complete(self) -> None:
        summary = result_summary({
            "status": "success",
            "parsed_before_boundary": {
                "overall_audit": {},
                "frame_findings": [],
                "object_continuity_assessment": {},
                "damage_causality_assessment": {},
                "claim_fact_assessment": {},
            },
        })

        self.assertEqual(summary["complete_dimension_count"], 0)
        self.assertFalse(any(summary["dimension_completeness"].values()))

    def test_summary_preserves_sanitized_opening_video_compliance(self) -> None:
        summary = result_summary({
            "status": "success",
            "parsed_before_boundary": {
                "video_audit_conclusion": {
                    "opening_video_compliance": {
                        "sealed_start": False,
                        "waybill_visible": True,
                        "single_take_continuity": True,
                        "issue_visible_in_continuous_opening": True,
                        "result": "noncompliant",
                        "evidence_refs": [{"timestamp": "00:00.00"}],
                    },
                },
            },
        })

        self.assertTrue(summary["dimension_completeness"]["opening_video_compliance"])
        self.assertEqual(summary["opening_video_compliance"], {
            "sealed_start": False,
            "waybill_visible": True,
            "single_take_continuity": True,
            "issue_visible_in_continuous_opening": True,
            "result": "noncompliant",
        })

    def test_native_media_part_count_includes_start_anchors(self) -> None:
        self.assertEqual(native_media_part_count({
            "native_video": {"api_path": "evidence.mp4"},
            "frames": [{}, {}],
            "supplemental_images": [{}, {}, {}, {}],
            "official_reference_images": [{}],
        }), 8)

    def test_summary_counts_lightweight_opening_verification_cost(self) -> None:
        summary = result_summary({
            "status": "success",
            "latency_seconds": 30.0,
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            "cost": {"estimated_usd": 0.01},
            "opening_start_verification": {
                "status": "success",
                "latency_seconds": 4.0,
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.002},
                "_channel_route_attempts": [{"channel": "baidu", "decision": "selected"}],
            },
        }, native_media_parts=10)

        self.assertEqual(summary["model_calls"], 2)
        self.assertEqual(summary["model_media_parts"], 10)
        self.assertEqual(summary["model_latency_seconds_sum"], 34.0)
        self.assertEqual(summary["usage"]["total_tokens"], 135)
        self.assertEqual(summary["estimated_cost"]["estimated_usd"], 0.012)


if __name__ == "__main__":
    unittest.main()
