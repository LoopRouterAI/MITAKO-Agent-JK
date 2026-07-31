# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
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
        self.assertEqual(audit["wave_workers"], [3, 1, 2, 1])
        self.assertEqual(audit["throttle_events"], 1)
        self.assertEqual(audit["recovery_events"], 2)

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
