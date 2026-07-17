# -*- coding: utf-8 -*-
import unittest

from poc.visual_review_poc.workbench_server import _internal_inference_estimate


class InternalInferenceEstimateTest(unittest.TestCase):
    def test_preserves_cost_and_channel_totals_for_protected_api(self):
        estimate = _internal_inference_estimate(
            {
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                "cost": {"estimated_usd": 0.0012344},
                "chunking": {
                    "segment_count": 3,
                    "total_model_calls": 7,
                    "channels": {
                        "main_review": {"model_calls": 3, "total_tokens": 60, "estimated_usd": 0.0006},
                        "object_continuity": {"model_calls": 2, "total_tokens": 30, "estimated_usd": 0.0003},
                        "damage_causality": {"model_calls": 2, "total_tokens": 30, "estimated_usd": 0.0003344},
                    },
                },
            }
        )
        self.assertEqual(estimate["total_tokens"], 120)
        self.assertEqual(estimate["total_model_calls"], 7)
        self.assertEqual(estimate["channels"]["main_review"]["model_calls"], 3)
        self.assertEqual(estimate["estimated_usd"], 0.001234)
        self.assertNotIn("provider", estimate)
        self.assertNotIn("model_name", estimate)


if __name__ == "__main__":
    unittest.main()
