# -*- coding: utf-8 -*-
import unittest

from poc.visual_review_poc.workbench_server import _internal_inference_estimate


class InternalInferenceEstimateTest(unittest.TestCase):
    def test_preserves_cost_and_channel_totals_for_protected_api(self):
        estimate = _internal_inference_estimate(
            {
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                "cost": {"estimated_usd": 0.0012344},
                "cost_status": "partial_unknown",
                "unknown_cost_calls": 1,
                "_channel_route_attempts": [{
                    "channel": "bananarouter",
                    "model": "configured-model",
                    "status_code": 503,
                    "error_type": "soft",
                    "decision": "fallback_retryable",
                    "endpoint": "https://must-not-leak.invalid",
                    "headers": {"Authorization": "must-not-leak"},
                }],
                "chunking": {
                    "segment_count": 3,
                    "total_frames": 213,
                    "main_review_frames": 48,
                    "total_model_calls": 7,
                    "concurrency": {
                        "configured_workers": 3,
                        "wave_workers": [3, 1, 2],
                        "throttle_events": 1,
                        "recovery_events": 1,
                    },
                    "channels": {
                        "main_review": {"model_calls": 3, "total_tokens": 60, "estimated_usd": 0.0006},
                        "object_continuity": {"model_calls": 2, "repair_calls": 1, "total_tokens": 30, "estimated_usd": 0.0003},
                        "damage_causality": {"model_calls": 2, "total_tokens": 30, "estimated_usd": 0.0003344},
                    },
                    "main_review_pass": {
                        "status": "degraded",
                        "failures": [{"chunk_index": 2, "error": "provider_timeout", "latency_seconds": 180}],
                    },
                },
            }
        )
        self.assertEqual(estimate["total_tokens"], 120)
        self.assertEqual(estimate["total_model_calls"], 7)
        self.assertEqual(estimate["total_frames"], 213)
        self.assertEqual(estimate["main_review_frames"], 48)
        self.assertEqual(estimate["channels"]["main_review"]["model_calls"], 3)
        self.assertEqual(estimate["channels"]["object_continuity"]["repair_calls"], 1)
        self.assertEqual(estimate["estimated_usd"], 0.001234)
        self.assertEqual(estimate["cost_status"], "partial_unknown")
        self.assertEqual(estimate["unknown_cost_calls"], 1)
        self.assertEqual(estimate["channel_route_attempts"][0]["decision"], "fallback_retryable")
        self.assertNotIn("endpoint", estimate["channel_route_attempts"][0])
        self.assertNotIn("headers", estimate["channel_route_attempts"][0])
        self.assertEqual(estimate["concurrency"]["wave_workers"], [3, 1, 2])
        self.assertEqual(estimate["degraded_passes"]["main_review"]["failures"][0]["chunk_index"], 2)
        self.assertEqual(estimate["degraded_passes"]["main_review"]["failures"][0]["error"], "provider_timeout")
        self.assertNotIn("provider", estimate)
        self.assertNotIn("model_name", estimate)


if __name__ == "__main__":
    unittest.main()
