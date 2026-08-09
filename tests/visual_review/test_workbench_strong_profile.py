# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from poc.visual_review_poc import workbench_server


class WorkbenchStrongProfileTest(unittest.TestCase):
    def test_native_positive_requires_all_opening_fields_verified(self) -> None:
        result = {
            "parsed": {
                "predicted_label": "positive",
                "video_audit_conclusion": {
                    "opening_video_compliance": {
                        "validated_fields": ["sealed_start", "waybill_visible"],
                    }
                },
            }
        }

        self.assertFalse(
            workbench_server._native_positive_opening_fully_verified(result, "product_damage")
        )
        result["parsed"]["video_audit_conclusion"]["opening_video_compliance"]["validated_fields"] = [
            "sealed_start",
            "waybill_visible",
            "single_take_continuity",
            "issue_visible_in_continuous_opening",
        ]
        self.assertTrue(
            workbench_server._native_positive_opening_fully_verified(result, "product_damage")
        )

    def test_model_call_accounting_ignores_skipped_opening_verification(self) -> None:
        self.assertEqual(workbench_server._incurred_model_call({"status": "skipped"}), 0)
        self.assertEqual(workbench_server._incurred_model_call({"status": "success"}), 1)
        self.assertEqual(workbench_server._incurred_model_call({"status": "error"}), 1)

    def test_internal_estimate_exposes_native_fallback_reason_without_media_url(self) -> None:
        estimate = workbench_server._internal_inference_estimate({
            "chunking": {
                "native_video": {
                    "status": "fallback_to_frames",
                    "technical_status": "success",
                    "dimension_gaps": ["opening_video_hard_failure_candidate"],
                    "opening_start_verification_status": "success",
                    "status_code": 200,
                    "file_uri": "https://private.example.com/video.mp4",
                },
            },
        })

        self.assertEqual(estimate["native_video"]["status"], "fallback_to_frames")
        self.assertEqual(
            estimate["native_video"]["dimension_gaps"],
            ["opening_video_hard_failure_candidate"],
        )
        self.assertNotIn("file_uri", estimate["native_video"])

    def test_browser_default_continuity_policy_does_not_force_dense_scan(self) -> None:
        html = workbench_server.INDEX_HTML.read_text(encoding="utf-8")
        selected = next(
            line for line in html.splitlines()
            if "continuity_policy" not in line and "selected" in line and "out_of_frame_warning_seconds" in line
        )

        self.assertNotIn('"force_dense_scan":true', selected)

    def test_model_route_tolerates_invalid_nested_numeric_diagnostics(self) -> None:
        succeeded = {
            "status": "success",
            "latency_seconds": "slow",
            "model_latency_seconds_sum": "slow",
            "unknown_cost_calls": "many",
            "chunking": {"total_model_calls": "many"},
            "parsed": {"predicted_label": "review"},
        }
        with patch.object(
            workbench_server, "_configured_model_keys", return_value=["gemini35lite"]
        ), patch.object(
            workbench_server, "call_model_chunked", return_value=succeeded
        ):
            result = workbench_server._call_model_chunked_with_fallback(
                "auto", {"case_id": "CASE-BAD-NUMBERS"}, timeout=180, retries=0
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunking"]["total_model_calls"], 0)
        self.assertEqual(result["model_latency_seconds_sum"], 0.0)

    def test_auto_model_route_defaults_to_gemini_35_flash_lite(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            model_keys = workbench_server._configured_model_keys("auto")

        self.assertEqual(model_keys, ["gemini35lite"])

    def test_folder_review_prepares_official_references_after_frontdesk_context_merge(self) -> None:
        observed = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            case = {
                "case_id": "CASE-OFFICIAL-REF",
                "scenario": "video_unboxing",
                "scenario_label": "发错货审核",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
            }

            def merge_context(current, *_):
                current["structured_business_context"] = {
                    "frontdesk_evidence_package": {
                        "fulfillment_baseline": {"expected_items": [{"item_ref": "LINE-1", "sku": "SKU-1"}]},
                    }
                }
                return current

            def prepare(current, *_):
                self.assertIn("frontdesk_evidence_package", current["structured_business_context"])
                current["official_reference_images"] = [{"reference_index": 1}]
                return current

            def model_result(_cfg, current, **_kwargs):
                observed["official_count"] = len(current.get("official_reference_images") or [])
                return {"status": "success", "parsed": {"predicted_label": "review", "confidence": 0.6}}

            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", return_value=case
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=merge_context
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=prepare
            ), patch.object(
                workbench_server, "call_model_chunked", side_effect=model_result
            ), patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "completed"}},
            ):
                workbench_server._run_folder_agent_review(
                    folder, "video_unboxing", "gemini35", {}, "adaptive", 1.0, 24, 24, 12
                )

        self.assertEqual(observed["official_count"], 1)

    def test_folder_review_reuses_single_video_native_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
            routed = {"ok": True, "summary": {"review_status": "completed"}}
            legacy_case = {
                "case_id": "CASE-FOLDER-NATIVE",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [{"file": video.name}],
                "frames": [{"global_frame_index": 1}],
                "supplemental_images": [],
                "structured_business_context": {},
            }

            with patch.object(workbench_server, "_run_review", return_value=routed) as review, patch.object(
                workbench_server, "load_case_bundle", return_value=legacy_case
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server,
                "call_model_chunked",
                return_value={"status": "success", "parsed": {"predicted_label": "review"}},
            ), patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "completed"}},
            ):
                result = workbench_server._run_folder_agent_review(
                    folder,
                    "product_damage",
                    "auto",
                    {"business_scenario": "product_damage"},
                    "dense",
                    1.0,
                    1200,
                    24,
                    12,
                )

        review.assert_called_once()
        self.assertEqual(review.call_args.kwargs["requested_model_key"], "auto")
        self.assertEqual(review.call_args.kwargs["sampling_mode_override"], "dense")
        self.assertIs(result["review"], routed)

    def test_large_native_video_uses_approved_https_signed_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
            with patch.object(workbench_server, "NATIVE_INLINE_MEDIA_MAX_BYTES", 32), patch.dict(
                "os.environ",
                {"VISUAL_WORKBENCH_PUBLIC_BASE_URL": "https://audit.example.com"},
                clear=False,
            ), patch.object(
                workbench_server,
                "_media_url",
                return_value="/media-item/opaque?expires=123&sig=abc",
            ):
                source = workbench_server._native_video_source(video)

        self.assertNotIn("api_path", source)
        self.assertEqual(
            source["file_uri"],
            "https://audit.example.com/media-item/opaque?expires=123&sig=abc",
        )

    def test_large_native_video_without_approved_https_url_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
            with patch.object(workbench_server, "NATIVE_INLINE_MEDIA_MAX_BYTES", 32), patch.dict(
                "os.environ", {"VISUAL_WORKBENCH_PUBLIC_BASE_URL": "http://127.0.0.1:7864"}, clear=False
            ):
                source = workbench_server._native_video_source(video)

        self.assertIsNone(source)

    def test_large_native_video_prefers_validated_inline_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "evidence.mp4"
            proxy = root / "proxy.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
            proxy.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"1" * 32)
            with patch.object(workbench_server, "NATIVE_INLINE_MEDIA_MAX_BYTES", 32), patch.object(
                workbench_server,
                "prepare_native_video_proxy",
                create=True,
                return_value={"status": "ready", "path": str(proxy), "proxy_bytes": proxy.stat().st_size},
            ):
                source = workbench_server._native_video_source(video, root / "prepared")

        self.assertEqual(source["api_path"], str(proxy))
        self.assertEqual(source["proxy"]["status"], "ready")

    def test_auto_model_route_uses_configured_fallback_after_primary_transport_failure(self) -> None:
        failed = {
            "status": "failed",
            "error_type": "soft",
            "status_code": 503,
            "latency_seconds": 10.0,
            "model_latency_seconds_sum": 20.0,
            "cost_status": "unknown",
            "unknown_cost_calls": 2,
            "chunking": {"total_model_calls": 2},
            "_channel_route_attempts": [
                {"channel": "primary-channel", "status_code": 503, "decision": "exhausted"}
            ],
        }
        succeeded = {
            "status": "success",
            "latency_seconds": 30.0,
            "model_latency_seconds_sum": 50.0,
            "cost_status": "estimated",
            "unknown_cost_calls": 0,
            "chunking": {"total_model_calls": 5},
            "parsed": {"predicted_label": "review"},
            "_channel_route_attempts": [
                {"channel": "fallback-channel", "status_code": 200, "decision": "selected"}
            ],
        }
        with patch.dict(
            "os.environ",
            {
                "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash",
                "VISUAL_REVIEW_FALLBACK_MODELS": "qwen3.5-flash",
            },
            clear=False,
        ), patch.object(
            workbench_server,
            "call_model_chunked",
            side_effect=[failed, succeeded],
        ) as model:
            result = workbench_server._call_model_chunked_with_fallback(
                "auto", {"case_id": "CASE-ROUTE"}, timeout=180, retries=0
            )

        self.assertEqual(model.call_count, 2)
        self.assertEqual(model.call_args_list[0].args[0]["model"], "gemini-3.5-flash")
        self.assertEqual(model.call_args_list[1].args[0]["model"], "qwen3.5-flash")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["route_fallback_count"], 1)
        self.assertEqual(result["cost_status"], "partial_unknown")
        self.assertEqual(result["unknown_cost_calls"], 2)
        self.assertEqual(result["chunking"]["total_model_calls"], 7)
        self.assertEqual(
            [item["channel"] for item in result["_channel_route_attempts"]],
            ["primary-channel", "fallback-channel"],
        )

    def test_auto_model_route_does_not_fallback_after_non_retryable_failure(self) -> None:
        failed = {
            "status": "failed",
            "error_type": "hard",
            "status_code": 400,
            "latency_seconds": 1.0,
            "model_latency_seconds_sum": 1.0,
            "cost_status": "unknown",
            "unknown_cost_calls": 1,
            "chunking": {"total_model_calls": 1},
        }
        with patch.dict(
            "os.environ",
            {
                "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash",
                "VISUAL_REVIEW_FALLBACK_MODELS": "qwen3.5-flash",
            },
            clear=False,
        ), patch.object(
            workbench_server,
            "call_model_chunked",
            return_value=failed,
        ) as model:
            result = workbench_server._call_model_chunked_with_fallback(
                "auto", {"case_id": "CASE-HARD-FAIL"}, timeout=180, retries=0
            )

        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["route_fallback_count"], 0)
        self.assertEqual(result["route_attempts"][0]["decision"], "stop_non_retryable")

    def test_auto_model_route_falls_back_when_primary_credentials_are_unavailable(self) -> None:
        failed = {
            "status": "failed",
            "error_type": "hard",
            "status_code": 401,
            "latency_seconds": 1.0,
            "model_latency_seconds_sum": 1.0,
            "cost_status": "unknown",
            "unknown_cost_calls": 1,
            "chunking": {"total_model_calls": 1},
        }
        succeeded = {
            "status": "success",
            "latency_seconds": 2.0,
            "model_latency_seconds_sum": 2.0,
            "cost_status": "estimated",
            "unknown_cost_calls": 0,
            "chunking": {"total_model_calls": 1},
            "parsed": {"predicted_label": "review"},
        }
        with patch.dict(
            "os.environ",
            {
                "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash",
                "VISUAL_REVIEW_FALLBACK_MODELS": "qwen3.5-flash",
            },
            clear=False,
        ), patch.object(
            workbench_server,
            "call_model_chunked",
            side_effect=[failed, succeeded],
        ) as model:
            result = workbench_server._call_model_chunked_with_fallback(
                "auto", {"case_id": "CASE-AUTH-FAILOVER"}, timeout=180, retries=0
            )

        self.assertEqual(model.call_count, 2)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["route_fallback_count"], 1)
        self.assertEqual(result["route_attempts"][0]["decision"], "fallback_provider_unavailable")

    def test_auto_model_route_counts_skipped_primary_as_fallback(self) -> None:
        skipped = {
            "status": "skipped",
            "error": "missing_api_key",
            "cost_status": "not_incurred",
            "chunking": {"total_model_calls": 0},
        }
        succeeded = {
            "status": "success",
            "cost_status": "estimated",
            "chunking": {"total_model_calls": 1},
            "parsed": {"predicted_label": "review"},
        }
        with patch.dict(
            "os.environ",
            {
                "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash",
                "VISUAL_REVIEW_FALLBACK_MODELS": "qwen3.5-flash",
            },
            clear=False,
        ), patch.object(
            workbench_server,
            "call_model_chunked",
            side_effect=[skipped, succeeded],
        ):
            result = workbench_server._call_model_chunked_with_fallback(
                "auto", {"case_id": "CASE-SKIPPED-FAILOVER"}, timeout=180, retries=0
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["route_fallback_count"], 1)
        self.assertEqual(result["route_attempts"][0]["decision"], "fallback_provider_unavailable")

    def test_folder_review_uses_configured_model_timeout_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            case = {
                "case_id": "CASE-FOLDER-CONFIG",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
            }
            with patch.dict(
                "os.environ",
                {"REVIEW_MODEL_TIMEOUT_SECONDS": "181", "REVIEW_MODEL_RETRIES": "1"},
                clear=False,
            ), patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", return_value=case
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "call_model_chunked", return_value={"status": "failed"}
            ) as model, patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "failed"}},
            ):
                workbench_server._run_folder_agent_review(
                    folder,
                    "product_damage",
                    "gemini35",
                    {},
                    "dense",
                    1.0,
                    1200,
                    24,
                    12,
                )

        self.assertEqual(model.call_args.kwargs["timeout"], 181)
        self.assertEqual(model.call_args.kwargs["retries"], 1)

    def test_single_upload_uses_dense_chunked_engine_for_strong_profile(self) -> None:
        observed = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"video")
            case = {
                "case_id": "CASE-STRONG",
                "scenario": "video_unboxing",
                "scenario_label": "开箱视频审核",
                "videos": [{"duration_seconds": 452}],
                "frames": [{} for _ in range(905)],
                "supplemental_images": [],
            }

            def load_bundle(sample_dir, args, run_dir, scenario_override=""):
                observed.update(
                    {
                        "sample_dir": sample_dir,
                        "sampling_mode": args.sampling_mode,
                        "fps": args.fps,
                        "max_frames": args.max_frames_per_video,
                        "api_frame_limit": args.api_frame_limit,
                        "scenario_override": scenario_override,
                    }
                )
                return case

            response = {
                "summary": {"review_status": "completed"},
                "agent_report": {"inference_estimate": {"segment_count": 38}},
            }
            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "call_model_chunked", return_value={"status": "success"}
            ) as model, patch.object(
                workbench_server, "_agent_report_response", return_value=response
            ):
                result = workbench_server._run_review(
                    video,
                    "video_unboxing",
                    fps=2.0,
                    max_frames=24,
                    api_frame_limit=24,
                    probe_seconds=12,
                    review_model="backup",
                    evidence_context={},
                )

        self.assertEqual(observed["sample_dir"], video.parent)
        self.assertEqual(observed["sampling_mode"], "dense")
        self.assertEqual(observed["fps"], 2.0)
        self.assertEqual(observed["max_frames"], 1800)
        self.assertEqual(observed["api_frame_limit"], 24)
        self.assertEqual(observed["scenario_override"], "video_unboxing")
        self.assertEqual(model.call_count, 1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["sampling"]["sampled_frames"], 905)
        self.assertEqual(result["sampling"]["model_segments"], 38)

    def test_standard_profile_uses_native_video_plus_lightweight_opening_check(self) -> None:
        observed = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

            def load_bundle(sample_dir, args, run_dir, scenario_override="", native_video=None):
                observed["native_video"] = dict(native_video or {})
                return {
                    "case_id": "CASE-NATIVE-STANDARD",
                    "scenario": "product_damage",
                    "scenario_label": "商品有伤审核",
                    "videos": [{"sampled_frames": 0}],
                    "frames": [
                        {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
                        {"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00"},
                    ],
                    "supplemental_images": [],
                    "native_video": dict(native_video or {}),
                    "structured_business_context": {"native_video_review": {"enabled": True}},
                }

            parsed = {
                "predicted_label": "positive",
                "confidence": 0.9,
                "overall_audit": {"conclusion": "可见压痕"},
                "frame_findings": [{"timestamp": "00:08.20", "visible_facts": "边角压痕"}],
                "object_continuity_assessment": {
                    "continuity_verdict": "continuous",
                    "tracked_subjects": [{"subject_id": "claimed_item"}],
                },
                "video_audit_conclusion": {
                    "opening_video_compliance": {
                        "sealed_start": True,
                        "waybill_visible": True,
                        "single_take_continuity": True,
                        "issue_visible_in_continuous_opening": True,
                        "evidence_refs": {},
                        "result": "compliant",
                    },
                },
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "claim_support": "supported",
                },
                "claim_fact_assessment": {
                    "atomic_claim_results": [],
                    "order_linkage": {},
                    "scene_match": {},
                    "assembly": {},
                },
            }
            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server, "call_model", return_value={"status": "success", "parsed": parsed}
            ) as native_model, patch.object(
                workbench_server,
                "call_opening_start_verification",
                return_value={
                    "status": "success",
                    "parsed": {
                        "result": "sealed",
                        "sealed_start": True,
                        "evidence_refs": [{"video_index": 1, "global_frame_index": 1, "timestamp": "0s"}],
                        "reason": "完整未拆封外箱可见。",
                    },
                },
            ) as opening_model, patch.object(
                workbench_server,
                "call_opening_compliance_verification",
                return_value={
                    "status": "success",
                    "parsed": {
                        "sealed_start": True,
                        "waybill_visible": True,
                        "single_take_continuity": True,
                        "issue_visible_in_continuous_opening": True,
                        "evidence_refs": [
                            {"field": field, "video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00"}
                            for field in (
                                "sealed_start", "waybill_visible", "single_take_continuity",
                                "issue_visible_in_continuous_opening",
                            )
                        ],
                    },
                },
            ) as compliance_model, patch.object(
                workbench_server, "call_model_chunked"
            ) as chunked_model, patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "completed"}, "agent_report": {}},
            ):
                result = workbench_server._run_review(
                    video, "product_damage", 1.0, 24, 24, 12, "standard", {}
                )

        self.assertEqual(native_model.call_count, 1)
        self.assertEqual(opening_model.call_count, 1)
        self.assertEqual(compliance_model.call_count, 1)
        self.assertEqual(chunked_model.call_count, 0)
        self.assertEqual(observed["native_video"]["api_path"], str(video))
        self.assertEqual(result["sampling"]["sampling_mode"], "native_video")
        self.assertEqual(result["sampling"]["sampled_frames"], 2)

    def test_native_fallback_keeps_verified_opening_start_evidence(self) -> None:
        captured = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

            def load_bundle(_sample_dir, _args, _run_dir, scenario_override="", native_video=None):
                return {
                    "case_id": "CASE-NATIVE-FALLBACK",
                    "scenario": "product_damage",
                    "scenario_label": "商品有伤审核",
                    "videos": [{"sampled_frames": 2}],
                    "frames": [
                        {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
                        {"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00"},
                    ],
                    "supplemental_images": [],
                    "native_video": dict(native_video or {}),
                    "structured_business_context": {},
                }

            native = {
                "status": "success",
                "parsed": {
                    "predicted_label": "positive",
                    "confidence": 0.9,
                    "video_audit_conclusion": {"opening_video_compliance": {"sealed_start": True}},
                },
            }
            frames = {
                "status": "success",
                "parsed": {
                    "predicted_label": "positive",
                    "confidence": 0.8,
                    "video_audit_conclusion": {
                        "opening_video_compliance": {
                            "sealed_start": True,
                            "waybill_visible": False,
                            "single_take_continuity": True,
                        },
                    },
                },
                "chunking": {"total_model_calls": 1},
            }

            def capture(_case, _sample_dir, result, *_args, **_kwargs):
                captured["parsed"] = result["parsed"]
                return {"summary": {"review_status": "completed"}, "agent_report": {}}

            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server, "call_model", return_value=native
            ), patch.object(
                workbench_server,
                "native_dimension_gaps",
                side_effect=[
                    ["opening_start_verification", "opening_video_hard_failure_candidate"],
                    ["opening_video_hard_failure_candidate"],
                ],
            ), patch.object(
                workbench_server,
                "call_opening_start_verification",
                return_value={
                    "status": "success",
                    "parsed": {
                        "result": "unsealed",
                        "sealed_start": False,
                        "evidence_refs": [{
                            "video_index": 1,
                            "global_frame_index": 1,
                            "timestamp": "00:00.00",
                        }],
                        "reason": "首帧已是气泡内包装。",
                    },
                },
            ), patch.object(
                workbench_server, "_call_model_chunked_with_fallback", return_value=frames
            ), patch.object(
                workbench_server, "_agent_report_response", side_effect=capture
            ):
                workbench_server._run_review(
                    video, "product_damage", 1.0, 24, 24, 12, "standard", {}
                )

        opening = captured["parsed"]["video_audit_conclusion"]["opening_video_compliance"]
        self.assertIs(opening["sealed_start"], False)
        self.assertEqual(opening["field_sources"]["sealed_start"], "opening_start_verification")

    def test_standard_profile_keeps_distinct_multi_video_case_on_frame_path(self) -> None:
        observed_modes = []
        with tempfile.TemporaryDirectory() as temp_dir:
            first_video = Path(temp_dir) / "001_first.mp4"
            second_video = Path(temp_dir) / "002_second.mp4"
            first_video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"1" * 64)
            second_video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"2" * 64)

            def load_bundle(_sample_dir, _args, _run_dir, scenario_override="", native_video=None):
                observed_modes.append("native" if native_video else "frames")
                return {
                    "case_id": "CASE-MULTI-VIDEO",
                    "scenario": scenario_override,
                    "scenario_label": "漏发审核",
                    "videos": [{"file": first_video.name}, {"file": second_video.name}],
                    "frames": [{"global_frame_index": 1}, {"global_frame_index": 2}],
                    "supplemental_images": [],
                    "structured_business_context": {},
                }

            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server, "call_model"
            ) as native_model, patch.object(
                workbench_server,
                "call_model_chunked",
                return_value={
                    "status": "success",
                    "parsed": {"predicted_label": "review", "confidence": 0.6},
                    "chunking": {"total_model_calls": 1},
                },
            ) as chunked_model, patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "completed"}, "agent_report": {}},
            ):
                result = workbench_server._run_review(
                    first_video, "missing_item", 1.0, 24, 24, 12, "standard", {}
                )

        self.assertEqual(observed_modes, ["frames"])
        native_model.assert_not_called()
        chunked_model.assert_called_once()
        self.assertEqual(result["sampling"]["sampling_mode"], "adaptive")

    def test_multi_video_damage_runs_one_opening_compliance_fallback(self) -> None:
        captured = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            first_video = Path(temp_dir) / "001_closeup.mp4"
            opening_video = Path(temp_dir) / "002_opening.mp4"
            first_video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"1" * 64)
            opening_video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"2" * 64)

            def load_bundle(_sample_dir, _args, _run_dir, scenario_override="", native_video=None):
                return {
                    "case_id": "CASE-MULTI-DAMAGE",
                    "scenario": scenario_override,
                    "scenario_label": "商品有伤审核",
                    "videos": [
                        {"video_index": 1, "duration_seconds": 2.0},
                        {"video_index": 2, "duration_seconds": 96.0},
                    ],
                    "frames": [
                        {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
                        {"video_index": 2, "global_frame_index": 2, "timestamp": "00:00.00"},
                        {"video_index": 2, "global_frame_index": 3, "timestamp": "01:36.00"},
                    ],
                    "supplemental_images": [],
                    "structured_business_context": {},
                }

            frame_result = {
                "status": "success",
                "parsed": {"video_audit_conclusion": {"opening_video_compliance": {
                    "sealed_start": False,
                    "waybill_visible": False,
                    "single_take_continuity": False,
                    "issue_visible_in_continuous_opening": False,
                    "evidence_refs": [],
                    "validated_fields": [],
                    "result": "noncompliant",
                }}},
                "chunking": {"total_model_calls": 2, "channels": {}},
            }
            verification = {
                "status": "success",
                "parsed": {
                    "sealed_start": True,
                    "waybill_visible": False,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": False,
                    "evidence_refs": [
                        {
                            "field": field,
                            "video_index": 2,
                            "global_frame_index": 2,
                            "timestamp": "00:00.00",
                        }
                        for field in (
                            "sealed_start", "waybill_visible", "single_take_continuity",
                            "issue_visible_in_continuous_opening",
                        )
                    ],
                    "result": "noncompliant",
                },
            }

            def capture(_case, _sample_dir, result, *_args, **_kwargs):
                captured["result"] = result
                return {"summary": {"review_status": "completed"}, "agent_report": {}}

            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server, "_call_model_chunked_with_fallback", return_value=frame_result
            ), patch.object(
                workbench_server, "call_opening_compliance_verification", return_value=verification
            ) as verifier, patch.object(
                workbench_server, "_agent_report_response", side_effect=capture
            ):
                workbench_server._run_review(
                    first_video, "product_damage", 1.0, 24, 24, 12, "standard", {}
                )

        verifier.assert_called_once()
        opening = captured["result"]["parsed"]["video_audit_conclusion"]["opening_video_compliance"]
        self.assertIs(opening["sealed_start"], True)
        self.assertIs(opening["waybill_visible"], False)
        self.assertEqual(opening["result"], "noncompliant")
        self.assertEqual(captured["result"]["chunking"]["total_model_calls"], 3)

    def test_standard_profile_falls_back_to_frames_when_native_output_is_incomplete(self) -> None:
        observed_modes = []
        observed_rule_versions = []
        published_version = {"value": 0}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

            def load_bundle(_sample_dir, _args, _run_dir, scenario_override="", native_video=None):
                observed_modes.append("native" if native_video else "frames")
                return {
                    "case_id": "CASE-NATIVE-FALLBACK",
                    "scenario": scenario_override,
                    "scenario_label": "商品有伤审核",
                    "videos": [{}],
                    "frames": [] if native_video else [{"global_frame_index": 1}],
                    "supplemental_images": [],
                    "native_video": dict(native_video or {}),
                    "structured_business_context": {},
                }

            def freeze_snapshot(current, _tenant_id):
                published_version["value"] += 1
                current["_business_rule_snapshot"] = {"version": published_version["value"]}
                return current

            def native_call(_config, current, **_kwargs):
                observed_rule_versions.append(current["_business_rule_snapshot"]["version"])
                return {"status": "success", "parsed": {"overall_audit": {}}}

            def frame_call(_config, current, **_kwargs):
                observed_rule_versions.append(current["_business_rule_snapshot"]["version"])
                return {
                    "status": "success",
                    "parsed": {"predicted_label": "review", "confidence": 0.6},
                    "chunking": {"total_model_calls": 2},
                }

            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server, "freeze_rule_snapshot", side_effect=freeze_snapshot
            ), patch.object(
                workbench_server,
                "call_model",
                side_effect=native_call,
            ), patch.object(
                workbench_server,
                "call_model_chunked",
                side_effect=frame_call,
            ) as chunked_model, patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "completed"}, "agent_report": {}},
            ):
                result = workbench_server._run_review(
                    video,
                    "product_damage",
                    1.0,
                    24,
                    24,
                    12,
                    "standard",
                    {},
                    requested_model_key="gemini31lite",
                )

        self.assertEqual(observed_modes, ["native", "frames"])
        self.assertEqual(observed_rule_versions, [1, 1])
        self.assertEqual(published_version["value"], 1)
        self.assertEqual(chunked_model.call_count, 1)
        self.assertEqual(chunked_model.call_args.args[0]["model"], workbench_server.MODEL_CONFIGS["gemini31lite"]["model"])
        self.assertEqual(result["sampling"]["sampling_mode"], "adaptive")

    def test_standard_profile_uses_bounded_adaptive_sampling(self) -> None:
        observed = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"video")

            def load_bundle(sample_dir, args, run_dir, scenario_override=""):
                observed.update({
                    "sampling_mode": args.sampling_mode,
                    "fps": args.fps,
                    "max_frames": args.max_frames_per_video,
                    "scenario_override": scenario_override,
                })
                return {
                    "case_id": "CASE-STANDARD",
                    "scenario": "product_damage",
                    "scenario_label": "商品有伤审核",
                    "videos": [{"duration_seconds": 72}],
                    "frames": [{} for _ in range(73)],
                    "supplemental_images": [],
                }

            with patch.dict(
                "os.environ", {"VISUAL_REVIEW_PRIMARY_MODEL": "qwen3.5-flash"}, clear=False
            ), patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "call_model_chunked", return_value={"status": "success"}
            ), patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "completed"}, "agent_report": {"inference_estimate": {"segment_count": 4}}},
            ):
                workbench_server._run_review(video, "product_damage", 0.2, 24, 24, 12, "standard", {})

        self.assertEqual(observed, {
            "sampling_mode": "adaptive",
            "fps": 0.2,
            "max_frames": 24,
            "scenario_override": "product_damage",
        })

    def test_standard_profile_does_not_force_damage_causality_scan_by_default(self) -> None:
        observed = {}

        def run_review(*args, **_kwargs):
            observed.update(args[7])
            return {"ok": True}

        with patch.object(
            workbench_server, "_save_upload", return_value=Path("evidence.mp4")
        ), patch.object(workbench_server, "_run_review", side_effect=run_review):
            response = TestClient(workbench_server.app).post(
                "/api/review",
                data={"scenario": "product_damage", "review_model": "standard"},
                files={"file": ("evidence.mp4", b"video", "video/mp4")},
            )

        self.assertEqual(response.status_code, 200)
        policy = json.loads(observed.get("damage_causality_policy") or "{}")
        self.assertFalse(policy.get("force_action_scan", False))


if __name__ == "__main__":
    unittest.main()
