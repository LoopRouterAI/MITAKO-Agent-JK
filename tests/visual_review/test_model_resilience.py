# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
import math
from email.utils import formatdate
from unittest.mock import patch


class _Response:
    def __init__(self, status_code: int, *, headers=None, data=None, text="") -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


class _Client:
    def __init__(self, responses) -> None:
        self.responses = responses

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, *_args, **_kwargs):
        return self.responses.pop(0)


class ModelResilienceTest(unittest.TestCase):
    def test_product_damage_aggregation_ignores_infinite_frame_indices(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        result = selection._aggregate_chunk_results(
            {
                "case_id": "infinite-frame-index",
                "scenario": "product_damage",
                "structured_business_context": {},
                "frames": [{"video_index": 1, "global_frame_index": float("inf")}],
                "videos": [],
                "supplemental_images": [],
            },
            [{
                "status": "success",
                "parsed": {
                    "predicted_label": "review",
                    "confidence": 0.5,
                    "frame_findings": [{
                        "video_index": 1,
                        "global_frame_index": float("inf"),
                        "subject_visibility": [],
                    }],
                },
            }],
        )

        self.assertEqual(result["status"], "success")

    def test_invalid_nested_numbers_do_not_abort_chunk_aggregation(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        result = selection._aggregate_chunk_results(
            {
                "case_id": "invalid-nested-numbers",
                "scenario": "video_unboxing",
                "structured_business_context": {},
                "frames": [{
                    "video_index": "bad",
                    "global_frame_index": "high",
                    "source_timestamp": "00:01.00",
                }],
                "videos": [],
                "supplemental_images": [],
            },
            [{
                "status": "success",
                "parsed": {
                    "predicted_label": "review",
                    "confidence": 0.5,
                    "frame_findings": [{
                        "video_index": "bad",
                        "global_frame_index": "high",
                        "subject_visibility": [],
                    }],
                },
                "usage": {"input_tokens": "many", "output_tokens": "many", "total_tokens": "many"},
                "cost": {"estimated_usd": "unknown"},
                "latency_seconds": "slow",
                "repair_calls": float("inf"),
                "model_image_count": "many",
            }],
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["usage"]["total_tokens"], 0)
        self.assertEqual(result["cost"]["estimated_usd"], 0.0)
        self.assertEqual(result["latency_seconds"], 0.0)

    def test_fulfillment_review_confidence_never_returns_nan(self) -> None:
        from poc.visual_review_poc.fulfillment_reconciliation import apply_fulfillment_guard

        result = apply_fulfillment_guard(
            {
                "confidence": "NaN",
                "fulfillment_reconciliation": {
                    "verdict": "indeterminate",
                    "evidence_sufficiency": "insufficient",
                },
            },
            "wrong_item",
        )

        self.assertTrue(math.isfinite(result["confidence"]))
        self.assertEqual(result["confidence"], 0.0)

    def test_invalid_cost_observability_counts_degrade_without_error(self) -> None:
        from poc.visual_review_poc.model_catalog import summarize_cost_observability

        result = summarize_cost_observability([{
            "cost_status": "partial_unknown",
            "unknown_cost_calls": "many",
            "estimated_cost_calls": "many",
        }])

        self.assertEqual(result["cost_status"], "partial_unknown")
        self.assertEqual(result["unknown_cost_calls"], 1)
        self.assertEqual(result["estimated_cost_calls"], 1)

    def test_all_failed_chunks_tolerate_invalid_numeric_diagnostics(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        case = {
            "case_id": "all-failed-invalid-numbers",
            "scenario": "generic_review",
            "model_frames_per_call": 1,
            "structured_business_context": {},
            "frames": [{"global_frame_index": 1, "video_index": 1, "file": "frame.jpg"}],
            "videos": [],
            "supplemental_images": [],
        }
        failed = {
            "status": "failed",
            "error": "provider_failed",
            "usage": {"input_tokens": "many", "output_tokens": "many", "total_tokens": "many"},
            "cost": {"estimated_usd": "unknown"},
            "latency_seconds": "slow",
        }
        with patch.object(selection, "call_model", return_value=failed):
            result = selection.call_model_chunked({}, case, timeout=1, retries=0)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["usage"]["total_tokens"], 0)
        self.assertEqual(result["cost"]["estimated_usd"], 0.0)
        self.assertEqual(result["model_latency_seconds_sum"], 0.0)

    def test_damage_guard_ignores_invalid_frame_indices(self) -> None:
        from poc.visual_review_poc.damage_causality import apply_damage_causality_guard

        result = apply_damage_causality_guard(
            {
                "predicted_label": "review",
                "confidence": 0.5,
                "damage_causality_assessment": {
                    "damage_presence": "uncertain",
                    "damage_timing": "unknown",
                    "most_likely_origin": "indeterminate",
                    "causal_evidence_level": "insufficient",
                    "claim_support": "insufficient",
                },
            },
            "product_damage",
            [{"video_index": "bad", "global_frame_index": "high"}],
        )

        self.assertEqual(result["predicted_label"], "review")

    def test_non_numeric_damage_coverage_degrades_to_zero_without_500(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        result = selection._aggregate_damage_observability([{
            "damage_observability": {
                "status": "partial",
                "required_view_coverage": "high",
            }
        }])

        self.assertEqual(result["required_view_coverage"], 0.0)

    def test_non_numeric_model_confidence_degrades_to_review_without_500(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        result = selection._aggregate_chunk_results(
            {
                "case_id": "invalid-confidence",
                "scenario": "video_unboxing",
                "structured_business_context": {},
                "frames": [],
                "videos": [],
                "supplemental_images": [],
            },
            [{
                "status": "success",
                "parsed": {"predicted_label": "positive", "confidence": "high"},
                "usage": {},
                "cost": {},
                "latency_seconds": 0.01,
            }],
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertEqual(result["parsed"]["confidence"], 0.0)
        self.assertEqual(result["policy_decision"]["system_yes_no"], "REVIEW")

    def test_claim_identity_ignores_non_object_model_items(self) -> None:
        from poc.visual_review_poc.model_selection_e2e import derive_claim_identity

        result = derive_claim_identity(
            [{
                "parsed": {
                    "confidence": 0.8,
                    "expected_order_item": "未形成结构化订单项",
                    "actual_received_item": None,
                    "customer_claim_parse": "未形成结构化诉求",
                }
            }],
            {"customer_claim": "请审查当前商品", "structured_business_context": {}},
        )

        self.assertEqual(result, {"customer_claim": "请审查当前商品"})

    def test_claim_identity_does_not_guess_sku_from_free_text(self) -> None:
        from poc.visual_review_poc.model_selection_e2e import derive_claim_identity

        result = derive_claim_identity(
            [],
            {
                "customer_claim": "请审查商品甲标准款",
                "structured_business_context": {
                    "order_items": [{
                        "item_ref": "ITEM-A",
                        "sku": "SKU-A",
                        "product_name": "商品甲标准款",
                    }]
                },
            },
        )

        self.assertEqual(result, {"customer_claim": "请审查商品甲标准款"})

    def test_http_retry_uses_numeric_retry_after_before_exponential_backoff(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        responses = [
            _Response(429, headers={"Retry-After": "3"}, text="rate limited"),
            _Response(200, data={"ok": True}),
        ]
        with patch.object(selection.httpx, "Client", return_value=_Client(responses)), patch.object(
            selection.time, "sleep"
        ) as sleep:
            result = selection.post_with_retries("https://example.invalid", {}, {}, 10, 1)

        self.assertTrue(result["ok"])
        sleep.assert_called_once_with(3.0)

    def test_http_retry_accepts_http_date_retry_after(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        retry_at = formatdate(1_000_005, usegmt=True)
        responses = [
            _Response(503, headers={"Retry-After": retry_at}, text="temporarily unavailable"),
            _Response(200, data={"ok": True}),
        ]
        with patch.object(selection.httpx, "Client", return_value=_Client(responses)), patch.object(
            selection.time, "time", return_value=1_000_000
        ), patch.object(selection.time, "sleep") as sleep:
            result = selection.post_with_retries("https://example.invalid", {}, {}, 10, 1)

        self.assertTrue(result["ok"])
        sleep.assert_called_once_with(5.0)

    def test_http_retry_uses_exponential_backoff_without_retry_after(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        responses = [
            _Response(503, text="temporarily unavailable"),
            _Response(200, data={"ok": True}),
        ]
        with patch.object(selection.httpx, "Client", return_value=_Client(responses)), patch.object(
            selection.random, "uniform", return_value=0.25
        ), patch.object(selection.time, "sleep") as sleep:
            result = selection.post_with_retries("https://example.invalid", {}, {}, 10, 1)

        self.assertTrue(result["ok"])
        sleep.assert_called_once_with(1.25)

    def test_http_error_redacts_credentials_before_returning(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        api_key = "AI" + "zaSySecretValue1234567890"
        bearer = "bearer-secret-value-123456"
        openai_key = "sk-" + "secret-value-1234567890"
        responses = [_Response(
            403,
            text=f'api_key: {api_key}; Authorization: Bearer {bearer}; rejected {openai_key}',
        )]
        with patch.object(selection.httpx, "Client", return_value=_Client(responses)):
            result = selection.post_with_retries("https://example.invalid", {}, {}, 10, 0)

        self.assertEqual(result["status_code"], 403)
        self.assertNotIn(api_key, result["error"])
        self.assertNotIn(bearer, result["error"])
        self.assertNotIn(openai_key, result["error"])
        self.assertIn("[REDACTED]", result["error"])

    def test_channel_route_audit_survives_chunk_aggregation(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        rows = [
            {"_channel_route_attempts": [{"channel": "primary", "decision": "fallback_retryable"}]},
            {"_channel_route_attempts": [{"channel": "fallback", "decision": "selected"}]},
        ]

        self.assertEqual(
            selection.collect_channel_route_attempts(rows),
            [
                {"channel": "primary", "decision": "fallback_retryable"},
                {"channel": "fallback", "decision": "selected"},
            ],
        )

    def test_gemini_channel_fallback_only_runs_for_retryable_failure(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        cfg = dict(selection.MODEL_CONFIGS["gemini35lite"])
        case = {
            "case_id": "route-hard-error",
            "scenario": "product_damage",
            "structured_business_context": {},
            "frames": [],
            "supplemental_images": [],
            "official_reference_images": [],
        }
        options = [
            {"channel": "primary", "endpoint": "https://primary.invalid", "headers": {}},
            {"channel": "fallback", "endpoint": "https://fallback.invalid", "headers": {}},
        ]
        hard = {"ok": False, "status_code": 400, "error_type": "hard", "error": "bad request", "attempt": 1}
        with patch.object(selection, "gemini_request_options", return_value=options), patch.object(
            selection, "post_with_retries", return_value=hard
        ) as post:
            result = selection.call_model(cfg, case, timeout=1, retries=0)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result["_channel_route_attempts"][0]["channel"], "primary")
        self.assertEqual(result["_channel_route_attempts"][0]["decision"], "stop_non_retryable")

    def test_adaptive_chunk_runner_shrinks_on_rate_limit_and_recovers_on_success(self) -> None:
        from poc.visual_review_poc.specialized_model_pass import run_adaptive_tasks

        outcomes = {
            0: {"status": "success"},
            1: {"status": "failed", "status_code": 429, "error_type": "soft"},
            2: {"status": "success"},
            3: {"status": "success"},
            4: {"status": "success"},
            5: {"status": "success"},
            6: {"status": "success"},
        }
        completed, audit = run_adaptive_tasks(
            list(range(7)),
            workers=3,
            invoke=lambda value: outcomes[value],
        )

        self.assertEqual(len(completed), 7)
        self.assertEqual(audit["configured_workers"], 3)
        self.assertEqual(audit["throttle_events"], 1)
        self.assertEqual(audit["recovery_events"], 2)

    def test_adaptive_chunk_runner_refills_idle_worker_without_waiting_for_slowest_task(self) -> None:
        import threading

        from poc.visual_review_poc.specialized_model_pass import run_adaptive_tasks

        third_started = threading.Event()

        def invoke(value: int) -> dict:
            if value == 0:
                return {
                    "status": "success" if third_started.wait(0.5) else "failed",
                    "value": value,
                }
            if value == 2:
                third_started.set()
            return {"status": "success", "value": value}

        completed, audit = run_adaptive_tasks(list(range(3)), workers=2, invoke=invoke)

        self.assertEqual([item["value"] for item in completed], [0, 1, 2])
        self.assertTrue(all(item["status"] == "success" for item in completed))
        self.assertEqual(audit["scheduler"], "rolling_bounded")
        self.assertEqual(audit["peak_inflight"], 2)

    def test_all_failed_chunks_keep_internal_channel_route_audit(self) -> None:
        from poc.visual_review_poc import model_selection_e2e as selection

        case = {
            "case_id": "all-failed-route-audit",
            "scenario": "product_damage",
            "structured_business_context": {},
            "model_frames_per_call": 1,
            "frames": [{"global_frame_index": 1}, {"global_frame_index": 2}],
            "supplemental_images": [],
            "official_reference_images": [],
        }
        failed = {
            "status": "failed",
            "status_code": 503,
            "error_type": "soft",
            "cost_status": "unknown",
            "_channel_route_attempts": [
                {"channel": "primary", "status_code": 503, "decision": "exhausted"}
            ],
        }
        with patch.object(selection, "call_model", return_value=failed):
            result = selection.call_model_chunked({}, case, timeout=1, retries=0)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["_channel_route_attempts"]), 2)
        self.assertEqual(result["chunking"]["concurrency"]["throttle_events"], 1)


if __name__ == "__main__":
    unittest.main()
