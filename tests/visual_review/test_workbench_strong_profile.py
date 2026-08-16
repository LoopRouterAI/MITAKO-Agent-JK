# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from poc.visual_review_poc import workbench_server
from poc.visual_review_poc import media_preflight


class WorkbenchStrongProfileTest(unittest.TestCase):
    def test_runtime_temp_resolver_prefers_explicit_environment_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            configured = root / "configured-runtime"
            with patch.dict(
                os.environ,
                {"VISUAL_RUNTIME_MEDIA_DIR": str(configured)},
                clear=False,
            ), patch.object(
                media_preflight, "_runtime_directory_available"
            ) as available:
                resolved = media_preflight.resolve_runtime_temp_dir(root)

        self.assertEqual(resolved, configured.resolve())
        available.assert_not_called()

    def test_runtime_temp_resolver_prefers_available_e_drive_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preferred = Path(r"E:\MITAKO_Agent_Runtime")
            with patch.dict(os.environ, {}, clear=True), patch.object(
                media_preflight,
                "_runtime_directory_available",
                return_value=True,
            ) as available:
                resolved = media_preflight.resolve_runtime_temp_dir(
                    root,
                    preferred_root=preferred,
                )

        self.assertEqual(resolved, preferred.resolve())
        available.assert_called_once_with(preferred)

    def test_runtime_temp_resolver_falls_back_inside_project_tmp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preferred = root / "unavailable-external-drive"
            with patch.dict(os.environ, {}, clear=True), patch.object(
                media_preflight,
                "_runtime_directory_available",
                return_value=False,
            ):
                resolved = media_preflight.resolve_runtime_temp_dir(
                    root,
                    preferred_root=preferred,
                )

        self.assertEqual(resolved, (root / "tmp" / "visual_review_runtime").resolve())

    def test_role_preflight_order_is_applied_to_loaded_video_and_frame_indices(self) -> None:
        videos = [Path("002_opening.mp4"), Path("001_closeup.mp4")]
        case = {
            "videos": [
                {"video_index": 1, "file": "001_closeup.mp4"},
                {"video_index": 2, "file": "002_opening.mp4"},
            ],
            "frames": [
                {"video_index": 1, "global_frame_index": 1, "video_file": "001_closeup.mp4"},
                {"video_index": 2, "global_frame_index": 2, "video_file": "002_opening.mp4"},
            ],
        }

        workbench_server._apply_video_review_order(case, videos)

        self.assertEqual(
            [(row["video_index"], row["file"]) for row in case["videos"]],
            [(1, "002_opening.mp4"), (2, "001_closeup.mp4")],
        )
        self.assertEqual(
            [
                (row["video_index"], row["global_frame_index"], row["video_file"])
                for row in case["frames"]
            ],
            [(1, 1, "002_opening.mp4"), (2, 2, "001_closeup.mp4")],
        )

    def test_folder_role_preflight_is_disabled_until_deferred_video_review_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            videos = [folder / "001.mp4", folder / "002.mp4"]
            for video in videos:
                video.write_bytes(b"video")
            routed = {"ok": True, "summary": {"review_status": "completed"}}
            with patch.dict("os.environ", {}, clear=False), patch.object(
                workbench_server, "discover_case_videos", return_value=(videos, [])
            ), patch.object(
                workbench_server, "call_model"
            ) as model, patch.object(
                workbench_server, "_run_review", return_value=routed
            ) as review:
                workbench_server._run_folder_agent_review(
                    folder, "product_damage", "auto", {}, "adaptive", 1.0, 24, 24, 12
                )

        model.assert_not_called()
        self.assertEqual(review.call_args.kwargs["selected_videos"], videos)
        self.assertEqual(
            review.call_args.kwargs["preflight_result"]["routing_decision"],
            "disabled_keep_all_videos",
        )

    def test_folder_role_preflight_batches_five_videos_into_three_requests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            videos = [folder / f"{index:03d}.mp4" for index in range(1, 6)]
            for video in videos:
                video.write_bytes(b"video")
            seen_indices = []

            def previews(batch_videos, _output, *, video_indices, **_kwargs):
                return [
                    {
                        "video_index": index,
                        "global_frame_index": (index - 1) * 10 + 1,
                        "timestamp": "00:00.000",
                        "api_path": str(batch_videos[offset]),
                        "api_mime_type": "image/webp",
                    }
                    for offset, index in enumerate(video_indices)
                ]

            def model(_config, case, **_kwargs):
                indices = [item["video_index"] for item in case["videos"]]
                seen_indices.append(indices)
                return {
                    "status": "success",
                    "model_http_request_count": 1,
                    "usage": {"total_tokens": 10},
                    "cost": {"estimated_usd": 0.001},
                    "parsed": {"candidates": [
                        {
                            "video_index": index,
                            "is_opening_video": index == 3,
                            "sealed_package_visible": index == 3,
                            "opening_action_visible": index == 3,
                            "confidence": 0.95,
                            "reason": "仅视频3可见闭合包裹开始拆封。",
                            "evidence_refs": [{"global_frame_index": 1, "timestamp": "00:00.000"}],
                        }
                        for index in indices
                    ]},
                }

            routed = {"ok": True, "summary": {"review_status": "completed"}}
            with patch.dict(
                "os.environ", {"REVIEW_ENABLE_OPENING_ROLE_PREFLIGHT": "true"}
            ), patch.object(
                workbench_server, "discover_case_videos", return_value=(videos, [])
            ), patch.object(
                workbench_server, "extract_opening_role_previews", side_effect=previews
            ), patch.object(
                workbench_server, "call_model", side_effect=model
            ), patch.object(
                workbench_server, "_run_review", return_value=routed
            ) as review:
                workbench_server._run_folder_agent_review(
                    folder, "product_damage", "auto", {}, "adaptive", 1.0, 24, 24, 12
                )

        self.assertEqual(seen_indices, [[1, 2], [3, 4], [5]])
        self.assertEqual(
            review.call_args.kwargs["selected_videos"],
            [videos[2], videos[0], videos[1], videos[3], videos[4]],
        )
        self.assertEqual(
            review.call_args.kwargs["preflight_result"]["deferred_video_indices"],
            [],
        )
        self.assertEqual(
            review.call_args.kwargs["preflight_billing"]["model_http_request_count"],
            3,
        )

    def test_folder_role_preflight_failure_keeps_all_videos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            videos = [folder / f"{index:03d}.mp4" for index in range(1, 4)]
            for video in videos:
                video.write_bytes(b"video")

            def previews(batch_videos, _output, *, video_indices, **_kwargs):
                return [{
                    "video_index": video_indices[0],
                    "global_frame_index": 1,
                    "timestamp": "00:00.000",
                    "api_path": str(batch_videos[0]),
                    "api_mime_type": "image/webp",
                }]

            results = [
                {"status": "success", "model_http_request_count": 1, "parsed": {"candidates": []}},
                {"status": "failed", "model_http_request_count": 1},
            ]
            routed = {"ok": True, "summary": {"review_status": "completed"}}
            with patch.dict(
                "os.environ", {"REVIEW_ENABLE_OPENING_ROLE_PREFLIGHT": "true"}
            ), patch.object(
                workbench_server, "discover_case_videos", return_value=(videos, [])
            ), patch.object(
                workbench_server, "extract_opening_role_previews", side_effect=previews
            ), patch.object(
                workbench_server, "call_model", side_effect=results
            ), patch.object(
                workbench_server, "_run_review", return_value=routed
            ) as review:
                workbench_server._run_folder_agent_review(
                    folder, "missing_item", "auto", {}, "adaptive", 1.0, 24, 24, 12
                )

        self.assertEqual(review.call_args.kwargs["selected_videos"], videos)
        self.assertEqual(
            review.call_args.kwargs["preflight_result"]["routing_decision"],
            "keep_all_candidates",
        )

    def test_preflight_billing_is_counted_as_real_model_work(self) -> None:
        result = workbench_server._merge_preflight_billing(
            {
                "usage": {"total_tokens": 100},
                "cost": {"estimated_usd": 0.01},
                "chunking": {"total_model_calls": 1, "channels": {}},
            },
            {
                "usage": {"total_tokens": 60},
                "cost": {"estimated_usd": 0.006},
                "model_http_request_count": 3,
            },
        )

        self.assertEqual(result["usage"]["total_tokens"], 160)
        self.assertEqual(result["chunking"]["total_model_calls"], 4)
        self.assertEqual(
            result["chunking"]["channels"]["video_role_preflight"]["model_calls"],
            3,
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
                    "error_summary": "inlineData video is not accepted",
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
        self.assertEqual(
            estimate["native_video"]["error_summary"],
            "inlineData video is not accepted",
        )
        self.assertNotIn("file_uri", estimate["native_video"])

    def test_browser_does_not_expose_fixed_offscreen_material_threshold(self) -> None:
        html = workbench_server.INDEX_HTML.read_text(encoding="utf-8")
        self.assertNotIn("离镜补件提示阈值", html)
        self.assertNotIn("out_of_frame_warning_seconds", html)

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

    def test_auto_model_route_never_silently_uses_explicit_only_model(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash-lite",
                "VISUAL_REVIEW_FALLBACK_MODELS": "gemini-3.7-flash",
            },
            clear=True,
        ):
            model_keys = workbench_server._configured_model_keys("auto")

        self.assertEqual(model_keys, ["gemini35lite"])
        self.assertEqual(workbench_server._configured_model_keys("gemini36"), [])
        self.assertEqual(workbench_server._configured_model_keys("gemini37"), ["gemini37"])

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
                    folder, "video_unboxing", "gemini35lite", {}, "adaptive", 1.0, 24, 24, 12
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

    def test_large_native_video_prefers_original_signed_url_over_lossy_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
            with patch.object(
                workbench_server, "NATIVE_INLINE_MEDIA_MAX_BYTES", 32
            ), patch.dict(
                "os.environ",
                {"VISUAL_WORKBENCH_PUBLIC_BASE_URL": "https://audit.example.com"},
                clear=False,
            ), patch.object(
                workbench_server,
                "_media_url",
                return_value="/media-item/opaque?expires=123&sig=abc",
            ), patch.object(
                workbench_server, "prepare_native_video_proxy"
            ) as prepare_proxy:
                source = workbench_server._native_video_source(
                    video, root / "prepared"
                )

        prepare_proxy.assert_not_called()
        self.assertEqual(
            source["file_uri"],
            "https://audit.example.com/media-item/opaque?expires=123&sig=abc",
        )
        self.assertNotIn("api_path", source)

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

    def test_high_bitrate_1080p_uses_smaller_quality_proxy_before_inline_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "evidence.mp4"
            proxy = root / "proxy.mp4"
            video.write_bytes(b"x" * 128)
            proxy.write_bytes(b"y" * 64)
            with patch.object(
                workbench_server,
                "NATIVE_INLINE_MEDIA_MAX_BYTES",
                1024,
            ), patch.object(
                workbench_server,
                "video_proxy_recommendation",
                return_value={"recommended": True, "reasons": ["bitrate_above_6mbps"]},
            ), patch.object(
                workbench_server,
                "prepare_native_video_proxy",
                return_value={
                    "status": "ready",
                    "path": str(proxy),
                    "mime_type": "video/mp4",
                    "proxy_bytes": proxy.stat().st_size,
                },
            ):
                source = workbench_server._native_video_source(video, root / "prepared")

        self.assertEqual(source["api_path"], str(proxy))
        self.assertEqual(
            source["proxy"]["recommendation"]["reasons"],
            ["bitrate_above_6mbps"],
        )

    def test_failed_quality_proxy_does_not_send_inline_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "evidence.mp4"
            video.write_bytes(b"x" * 128)
            with patch.object(
                workbench_server,
                "NATIVE_INLINE_MEDIA_MAX_BYTES",
                1024,
            ), patch.object(
                workbench_server,
                "video_proxy_recommendation",
                return_value={"recommended": True, "reasons": ["bitrate_above_6mbps"]},
            ), patch.object(
                workbench_server,
                "prepare_native_video_proxy",
                return_value={"status": "failed", "error_type": "quality_budget_conflict"},
            ):
                source = workbench_server._native_video_source(video, root / "prepared")

        self.assertIsNone(source)

    def test_failed_quality_proxy_does_not_trigger_expensive_full_frame_fallback(self) -> None:
        observed = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

            def load_bundle(_sample_dir, args, _run_dir, scenario_override="", **_kwargs):
                observed.update({
                    "fps": args.fps,
                    "sampling_mode": args.sampling_mode,
                    "max_frames": args.max_frames_per_video,
                })
                return {
                    "case_id": "CASE-PROXY-FALLBACK",
                    "scenario": scenario_override,
                    "scenario_label": "商品有伤审核",
                    "videos": [{"sampled_frames": 2}],
                    "frames": [{"global_frame_index": 1}, {"global_frame_index": 2}],
                    "supplemental_images": [],
                    "structured_business_context": {},
                }

            def report_response(_case, _sample_dir, model_result, *_args, **_kwargs):
                observed["model_result"] = model_result
                return {
                    "summary": {"review_status": "completed"},
                    "agent_report": {"parsed": dict(model_result.get("parsed") or {})},
                }

            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "discover_case_videos", return_value=([video], {})
            ), patch.object(
                workbench_server,
                "video_proxy_recommendation",
                return_value={"recommended": True, "reasons": ["source_above_100mb"]},
            ), patch.object(
                workbench_server, "_native_video_source_context", return_value=contextmanager(lambda: (yield None))()
            ), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "freeze_rule_snapshot", side_effect=lambda current, _tenant: current.setdefault("_business_rule_snapshot", {})
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server,
                "_call_model_chunked_with_fallback",
                return_value={"status": "success", "parsed": {"predicted_label": "review"}},
            ) as frame_model, patch.object(
                workbench_server,
                "_agent_report_response",
                side_effect=report_response,
            ):
                result = workbench_server._run_review(
                    video,
                    "product_damage",
                    0.25,
                    24,
                    24,
                    12,
                    "standard",
                    {},
                    requested_model_key="gemini35lite",
                )

        self.assertEqual(observed["fps"], 0.25)
        self.assertEqual(observed["sampling_mode"], "adaptive")
        self.assertEqual(observed["max_frames"], 24)
        self.assertEqual(frame_model.call_count, 0)
        self.assertEqual(
            observed["model_result"]["parsed"]["processing_status"],
            "technical_processing_incomplete",
        )
        self.assertEqual(observed["model_result"]["parsed"]["system_action"], "system_retry")
        fallback = result["media_preflight_execution"]["frame_fallback"]
        self.assertFalse(fallback["used"])
        self.assertIsNone(fallback["sampling_fps"])

    def test_failed_quality_proxy_does_not_bypass_quality_gate_with_original_url(self) -> None:
        class Tunnel:
            url = "https://unit-test.trycloudflare.com/media/token"
            diagnostics = {"status": "ready"}

        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"video")

            with patch.object(
                workbench_server,
                "_native_video_proxy_source_context",
                return_value=contextmanager(lambda: (yield None))(),
            ), patch.object(
                workbench_server,
                "_native_video_source",
                return_value=None,
            ), patch.object(
                workbench_server,
                "open_secure_media_tunnel",
                return_value=contextmanager(lambda: (yield Tunnel()))(),
            ):
                with workbench_server._native_video_source_context(
                    video,
                    Path(temp_dir) / "proxy",
                    recommendation={"recommended": True, "reasons": ["source_above_100mb"]},
                ) as source:
                    captured = dict(source or {})

        self.assertEqual(captured, {})

    def test_failed_quality_proxy_does_not_bypass_quality_gate_with_configured_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"video")

            with patch.dict(
                "os.environ",
                {"VISUAL_WORKBENCH_PUBLIC_BASE_URL": "https://media.example.test"},
                clear=False,
            ), patch.object(
                workbench_server,
                "_native_video_proxy_source_context",
                return_value=contextmanager(lambda: (yield None))(),
            ), patch.object(
                workbench_server,
                "_media_url",
                return_value="/media-item/signed-original",
            ), patch.object(
                workbench_server,
                "open_secure_media_tunnel",
            ) as tunnel:
                with workbench_server._native_video_source_context(
                    video,
                    Path(temp_dir) / "proxy",
                    recommendation={"recommended": True, "reasons": ["source_above_100mb"]},
                ) as source:
                    captured = dict(source or {})

        self.assertEqual(captured, {})
        tunnel.assert_not_called()

    def test_proxy_url_failure_does_not_reencode_to_lower_quality_inline_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "evidence.mp4"
            url_proxy = root / "url-proxy.webm"
            video.write_bytes(b"source")
            url_proxy.write_bytes(b"u" * 90)
            with patch.object(
                workbench_server,
                "NATIVE_URL_MEDIA_MAX_BYTES",
                100,
            ), patch.object(
                workbench_server,
                "NATIVE_INLINE_MEDIA_MAX_BYTES",
                70,
            ), patch.object(
                workbench_server,
                "prepare_native_video_proxy",
                return_value={
                    "status": "ready",
                    "path": str(url_proxy),
                    "mime_type": "video/webm",
                    "proxy_bytes": url_proxy.stat().st_size,
                },
            ) as prepare_proxy, patch.object(
                workbench_server,
                "open_secure_media_tunnel",
                side_effect=FileNotFoundError("cloudflared unavailable"),
            ):
                with workbench_server._native_video_proxy_source_context(
                    video,
                    root / "prepared",
                ) as source:
                    captured = dict(source or {})

        self.assertEqual(prepare_proxy.call_count, 1)
        self.assertEqual(prepare_proxy.call_args_list[0].args[2], 100)
        self.assertEqual(captured, {})

    def test_quality_proxy_does_not_reopen_tunnel_after_transport_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "evidence.mp4"
            proxy = root / "quality-proxy.webm"
            video.write_bytes(b"source")
            proxy.write_bytes(b"p" * 90)

            @contextmanager
            def ready_tunnel():
                yield SimpleNamespace(
                    url="https://media.example.test/token",
                    diagnostics={"status": "ready"},
                )

            with patch.object(
                workbench_server,
                "NATIVE_URL_MEDIA_MAX_BYTES",
                100,
            ), patch.object(
                workbench_server,
                "NATIVE_INLINE_MEDIA_MAX_BYTES",
                70,
            ), patch.object(
                workbench_server,
                "prepare_native_video_proxy",
                return_value={
                    "status": "ready",
                    "path": str(proxy),
                    "mime_type": "video/webm",
                    "proxy_bytes": proxy.stat().st_size,
                },
            ) as prepare_proxy, patch.object(
                workbench_server,
                "open_secure_media_tunnel",
                side_effect=RuntimeError("quick tunnel unavailable"),
            ) as tunnel:
                with workbench_server._native_video_proxy_source_context(
                    video,
                    root / "prepared",
                ) as source:
                    captured = dict(source or {})

        prepare_proxy.assert_called_once()
        self.assertEqual(
            prepare_proxy.call_args.kwargs["cache_dir"],
            workbench_server.RUNTIME_MEDIA_DIR / "native_video_proxy_cache",
        )
        self.assertEqual(tunnel.call_count, 1)
        self.assertEqual(captured, {})

    def test_quality_proxy_under_inline_limit_does_not_open_tunnel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "evidence.mp4"
            proxy = root / "quality-proxy.webm"
            video.write_bytes(b"source")
            proxy.write_bytes(b"p" * 60)
            with patch.object(
                workbench_server,
                "NATIVE_URL_MEDIA_MAX_BYTES",
                100,
            ), patch.object(
                workbench_server,
                "NATIVE_INLINE_MEDIA_MAX_BYTES",
                70,
            ), patch.object(
                workbench_server,
                "prepare_native_video_proxy",
                return_value={
                    "status": "ready",
                    "path": str(proxy),
                    "mime_type": "video/webm",
                    "proxy_bytes": proxy.stat().st_size,
                },
            ), patch.object(
                workbench_server,
                "open_secure_media_tunnel",
            ) as tunnel:
                with workbench_server._native_video_proxy_source_context(
                    video,
                    root / "prepared",
                ) as source:
                    captured = dict(source or {})

        tunnel.assert_not_called()
        self.assertEqual(captured["api_path"], str(proxy))
        self.assertEqual(captured["transport"], "full_duration_quality_proxy")

    def test_multi_video_preflight_keeps_native_sources_open_and_records_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            videos = [root / "001.mp4", root / "002.mp4"]
            for video in videos:
                video.write_bytes(b"source")

            @contextmanager
            def source_context(video, *_args, **_kwargs):
                index = videos.index(video) + 1
                yield {
                    "video_index": 1,
                    "file_uri": f"https://media.example/video-{index}",
                    "api_mime_type": "video/webm",
                    "transport": "ephemeral_proxy_url",
                    "proxy": {
                        "status": "ready",
                        "codec_profile": "vp9_webm",
                        "source_bytes": 120 * 1024 * 1024,
                        "proxy_bytes": 80 * 1024 * 1024,
                        "source_sha256": "source-sha",
                        "proxy_sha256": "proxy-sha",
                        "cache_hit": True,
                        "source_width": 3840,
                        "source_height": 2160,
                        "proxy_width": 1920,
                        "proxy_height": 1080,
                        "proxy_fps": 24.0,
                        "proxy_bitrate_bps": 5_500_000,
                    },
                }

            with patch.object(
                workbench_server,
                "video_proxy_recommendation",
                return_value={"recommended": True, "reasons": ["source_above_100mb"]},
            ), patch.object(
                workbench_server,
                "_native_video_source_context",
                side_effect=source_context,
            ) as prepare_source:
                with workbench_server._prepared_folder_video_sources(videos, root / "prepared") as prepared:
                    routed_videos = list(prepared["videos"])
                    native_videos = list(prepared["native_videos"])
                    execution = list(prepared["execution"])
                    self.assertEqual(len(routed_videos), 2)
                    self.assertEqual(routed_videos, videos)
                    self.assertEqual(
                        [row["video_index"] for row in native_videos],
                        [1, 2],
                    )
                    self.assertEqual(
                        [row["file_uri"] for row in native_videos],
                        [
                            "https://media.example/video-1",
                            "https://media.example/video-2",
                        ],
                    )

            self.assertEqual(prepare_source.call_count, 2)
            self.assertEqual(
                [row["submitted_source"] for row in execution],
                ["quality_proxy", "quality_proxy"],
            )
            self.assertEqual(
                [row["quality_reasons"] for row in execution],
                [["source_above_100mb"], ["source_above_100mb"]],
            )
            self.assertEqual(execution[0]["source_sha256"], "source-sha")
            self.assertEqual(execution[0]["proxy_sha256"], "proxy-sha")
            self.assertTrue(execution[0]["cache_hit"])
            self.assertEqual(execution[0]["source_width"], 3840)
            self.assertEqual(execution[0]["submitted_width"], 1920)

    def test_multi_video_proxy_failure_stops_without_complete_one_fps_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            videos = [root / "001.mp4", root / "002.mp4"]
            for video in videos:
                video.write_bytes(b"source")

            with patch.dict(
                os.environ,
                {"VISUAL_REVIEW_EPHEMERAL_TUNNEL": "0"},
                clear=False,
            ), patch.object(
                workbench_server,
                "video_proxy_recommendation",
                return_value={"recommended": True, "reasons": ["source_above_100mb"]},
            ), patch.object(
                workbench_server,
                "prepare_native_video_proxy",
                side_effect=[
                    {"status": "failed", "error_type": "quality_budget_conflict"},
                    {"status": "failed", "error_type": "proxy_unavailable"},
                ],
            ):
                with workbench_server._prepared_folder_video_sources(
                    videos, root / "prepared"
                ) as prepared:
                    captured = dict(prepared)

        self.assertEqual(captured["videos"], [])
        self.assertTrue(captured["technical_processing_incomplete"])
        self.assertFalse(captured["requires_complete_frame_fallback"])
        self.assertEqual(
            [row["status"] for row in captured["execution"]],
            ["proxy_failed", "proxy_failed"],
        )
        self.assertNotIn(
            "complete_1fps_frames",
            {row["submitted_source"] for row in captured["execution"]},
        )

    def test_multi_video_folder_forwards_native_sources_to_one_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            videos = [folder / "001.mp4", folder / "002.mp4"]
            for video in videos:
                video.write_bytes(b"video")
            native_videos = [
                {
                    "video_index": index,
                    "file_uri": f"https://media.example/video-{index}",
                    "api_mime_type": "video/webm",
                }
                for index in (1, 2)
            ]

            @contextmanager
            def prepared_context(*_args, **_kwargs):
                yield {
                    "videos": videos,
                    "native_videos": native_videos,
                    "execution": [],
                    "requires_complete_frame_fallback": False,
                    "technical_processing_incomplete": False,
                }

            with patch.object(
                workbench_server, "discover_case_videos", return_value=(videos, {})
            ), patch.object(
                workbench_server, "_prepared_folder_video_sources", side_effect=prepared_context
            ), patch.object(
                workbench_server,
                "_run_review",
                return_value={"ok": True, "summary": {"review_status": "completed"}},
            ) as run_review:
                workbench_server._run_folder_agent_review(
                    folder, "product_damage", "auto", {}, "adaptive", 1.0, 24, 24, 12
                )

        self.assertEqual(
            run_review.call_args.kwargs["native_video_sources"],
            native_videos,
        )

    def test_single_video_folder_reuses_run_review_proxy_path_without_folder_transcode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "001.mp4"
            video.write_bytes(b"video")
            routed = {
                "ok": True,
                "summary": {"review_status": "completed"},
                "media_preflight_execution": {"video": {"submitted_source": "quality_proxy"}},
            }
            with patch.object(
                workbench_server, "discover_case_videos", return_value=([video], {})
            ), patch.object(
                workbench_server, "_prepared_folder_video_sources"
            ) as folder_prepare, patch.object(
                workbench_server, "_run_review", return_value=routed
            ):
                response = workbench_server._run_folder_agent_review(
                    folder, "product_damage", "auto", {}, "adaptive", 1.0, 24, 24, 12
                )

        folder_prepare.assert_not_called()
        self.assertEqual(
            response["review"]["media_preflight_execution"]["video"]["submitted_source"],
            "quality_proxy",
        )

    def test_auto_model_route_does_not_silently_use_high_quality_candidate_after_transport_failure(self) -> None:
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
        with patch.dict(
            "os.environ",
            {
                "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash-lite",
                "VISUAL_REVIEW_FALLBACK_MODELS": "gemini-3.7-flash",
            },
            clear=False,
        ), patch.object(
            workbench_server,
            "call_model_chunked",
            return_value=failed,
        ) as model:
            result = workbench_server._call_model_chunked_with_fallback(
                "auto", {"case_id": "CASE-ROUTE"}, timeout=180, retries=0
            )

        self.assertEqual(model.call_count, 1)
        self.assertEqual(model.call_args.args[0]["model"], "gemini-3.5-flash-lite")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["route_fallback_count"], 0)
        self.assertEqual(result["cost_status"], "unknown")
        self.assertEqual(result["unknown_cost_calls"], 2)
        self.assertEqual(result["chunking"]["total_model_calls"], 2)
        self.assertEqual(
            [item["channel"] for item in result["_channel_route_attempts"]],
            ["primary-channel"],
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
                "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash-lite",
                "VISUAL_REVIEW_FALLBACK_MODELS": "gemini-3.7-flash",
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

    def test_auto_model_route_does_not_escalate_cost_when_primary_credentials_are_unavailable(self) -> None:
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
        with patch.dict(
            "os.environ",
            {
                "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash-lite",
                "VISUAL_REVIEW_FALLBACK_MODELS": "gemini-3.7-flash",
            },
            clear=False,
        ), patch.object(
            workbench_server,
            "call_model_chunked",
            return_value=failed,
        ) as model:
            result = workbench_server._call_model_chunked_with_fallback(
                "auto", {"case_id": "CASE-AUTH-FAILOVER"}, timeout=180, retries=0
            )

        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["route_fallback_count"], 0)

    def test_auto_model_route_counts_skipped_primary_as_fallback(self) -> None:
        skipped = {
            "status": "skipped",
            "error": "missing_api_key",
            "cost_status": "not_incurred",
            "chunking": {"total_model_calls": 0},
        }
        with patch.dict(
            "os.environ",
            {
                "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash-lite",
                "VISUAL_REVIEW_FALLBACK_MODELS": "gemini-3.7-flash",
            },
            clear=False,
        ), patch.object(
            workbench_server,
            "call_model_chunked",
            return_value=skipped,
        ) as model:
            result = workbench_server._call_model_chunked_with_fallback(
                "auto", {"case_id": "CASE-SKIPPED-FAILOVER"}, timeout=180, retries=0
            )

        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["route_fallback_count"], 0)

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
                    "gemini35lite",
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

    def test_standard_profile_uses_one_complete_native_video_call_without_reencoding_small_source(self) -> None:
        observed = {}
        clock = {"now": 100.0}

        class Tunnel:
            url = "https://unit-test.trycloudflare.com/media/token"
            diagnostics = {"status": "ready"}

        @contextmanager
        def fake_tunnel(*_args, **_kwargs):
            clock["now"] = 800.0
            yield Tunnel()

        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

            def load_bundle(sample_dir, args, run_dir, scenario_override="", native_video=None):
                clock["now"] = 800.0
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
                "claimed_item_assessment": {"appeared": True},
                "video_audit_conclusion": {
                    "opening_video_compliance": {
                        "sealed_start": True,
                        "waybill_visible": True,
                        "single_take_continuity": True,
                        "issue_visible_in_continuous_opening": True,
                        "evidence_refs": [
                            {
                                "field": field,
                                "video_index": 1,
                                "timestamp": "00:01.00",
                                "visible_facts": "完整视频中的对应事实",
                            }
                            for field in (
                                "sealed_start",
                                "waybill_visible",
                                "single_take_continuity",
                                "issue_visible_in_continuous_opening",
                            )
                        ],
                        "validated_fields": [
                            "sealed_start",
                            "waybill_visible",
                            "single_take_continuity",
                            "issue_visible_in_continuous_opening",
                        ],
                        "field_sources": {
                            field: "native_full_video_perception"
                            for field in (
                                "sealed_start",
                                "waybill_visible",
                                "single_take_continuity",
                                "issue_visible_in_continuous_opening",
                            )
                        },
                        "result": "compliant",
                    },
                },
                "evidence_refs": [
                    {
                        "field": "claimed_item",
                        "asset_ref": "native_video_1",
                        "timestamp": timestamp,
                        "fact": "争议商品在有效展示窗口内可见",
                    }
                    for timestamp in ("00:01.00", "00:08.20")
                ],
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
            with patch.dict(
                "os.environ",
                {
                    "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash",
                    "REVIEW_CASE_DEADLINE_SECONDS": "600",
                },
                clear=False,
            ), patch.object(
                workbench_server.time, "monotonic", side_effect=lambda: clock["now"]
            ), patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server, "open_secure_media_tunnel", side_effect=fake_tunnel
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
        self.assertEqual(native_model.call_args.kwargs["deadline_at"], 1400.0)
        self.assertEqual(opening_model.call_count, 0)
        self.assertEqual(compliance_model.call_count, 0)
        self.assertEqual(chunked_model.call_count, 0)
        self.assertEqual(observed["native_video"]["api_path"], str(video))
        self.assertEqual(observed["native_video"]["transport"], "raw_original_inline")
        self.assertEqual(result["sampling"]["sampling_mode"], "native_video")
        self.assertEqual(result["sampling"]["sampled_frames"], 2)
        self.assertEqual(result["media_preflight_execution"]["video"]["submitted_source"], "original")
        self.assertEqual(result["media_preflight_execution"]["video"]["delivery"], "inline_data")
        self.assertEqual(result["media_preflight_execution"]["video"]["native_sampling_fps"], 1.0)
        self.assertFalse(result["media_preflight_execution"]["frame_fallback"]["used"])

    def test_fulfillment_native_review_uses_source_isolated_chunked_route_and_preserves_call_count(self) -> None:
        captured = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

            def load_bundle(_sample_dir, _args, _run_dir, scenario_override="", native_video=None):
                return {
                    "case_id": "CASE-FULFILLMENT-SOURCE-ISOLATED",
                    "scenario": scenario_override,
                    "scenario_label": "发错货审核",
                    "videos": [{"sampled_frames": 0}],
                    "frames": [
                        {"api_path": "opening-first.webp", "global_frame_index": 1},
                        {"api_path": "opening-last.webp", "global_frame_index": 2},
                    ],
                    "supplemental_images": [{"api_path": "waybill.webp", "image_index": 1}],
                    "native_video": dict(native_video or {}),
                    "structured_business_context": {"business_scenario": "wrong_item"},
                }

            chunked_result = {
                "status": "success",
                "parsed": {"predicted_label": "review", "confidence": 0.7},
                "usage": {"total_tokens": 200},
                "cost": {"estimated_usd": 0.02},
                "model_http_request_count": 2,
                "chunking": {
                    "pipeline_mode": "source_isolated_fulfillment",
                    "segment_count": 2,
                    "total_model_calls": 2,
                    "channels": {},
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
                workbench_server,
                "_native_video_source_context",
                return_value=contextmanager(lambda: (yield {
                    "api_path": str(video),
                    "api_mime_type": "video/mp4",
                    "transport": "raw_original_inline",
                }))(),
            ), patch.object(
                workbench_server, "_call_model_chunked_with_fallback", return_value=chunked_result
            ) as chunked_model, patch.object(
                workbench_server, "call_model", return_value=chunked_result
            ) as direct_model, patch.object(
                workbench_server, "_agent_report_response", side_effect=capture
            ):
                workbench_server._run_review(
                    video,
                    "wrong_item",
                    1.0,
                    24,
                    24,
                    12,
                    "standard",
                    {},
                    requested_model_key="gemini35lite",
                )

        chunked_model.assert_called_once()
        direct_model.assert_not_called()
        self.assertEqual(captured["result"]["chunking"]["total_model_calls"], 2)
        self.assertEqual(
            workbench_server._internal_inference_estimate(captured["result"])["total_model_calls"],
            2,
        )

    def test_incomplete_native_opening_is_preserved_without_frame_overwrite(self) -> None:
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
            def capture(_case, _sample_dir, result, *_args, **_kwargs):
                captured["parsed"] = result["parsed"]
                return {"summary": {"review_status": "completed"}, "agent_report": {}}

            fallback = {
                "status": "success",
                "parsed": {
                    "predicted_label": "review",
                    "video_audit_conclusion": {
                        "opening_video_compliance": {
                            "sealed_start": None,
                            "waybill_visible": None,
                            "single_take_continuity": None,
                            "issue_visible_in_continuous_opening": None,
                            "result": "indeterminate",
                        }
                    },
                },
            }

            with patch.dict(
                "os.environ", {"VISUAL_REVIEW_EPHEMERAL_TUNNEL": "0"}, clear=False
            ), patch.object(workbench_server, "load_visual_env"), patch.object(
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
                return_value=["opening_video_compliance"],
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
                workbench_server,
                "call_opening_compliance_verification",
                return_value={
                    "status": "success",
                    "parsed": {
                        "sealed_start": True,
                        "waybill_visible": False,
                        "single_take_continuity": True,
                        "issue_visible_in_continuous_opening": True,
                        "evidence_refs": [
                            {
                                "field": field,
                                "video_index": 1,
                                "global_frame_index": 2,
                            }
                            for field in (
                                "waybill_visible",
                                "single_take_continuity",
                                "issue_visible_in_continuous_opening",
                            )
                        ],
                    },
                },
            ) as compliance_model, patch.object(
                workbench_server,
                "_call_model_chunked_with_fallback",
                return_value=fallback,
            ) as frame_pipeline, patch.object(
                workbench_server,
                "merge_opening_compliance_verification",
                wraps=workbench_server.merge_opening_compliance_verification,
            ), patch.object(
                workbench_server, "_agent_report_response", side_effect=capture
            ):
                workbench_server._run_review(
                    video, "product_damage", 1.0, 24, 24, 12, "standard", {}
                )

        opening = captured["parsed"]["video_audit_conclusion"]["opening_video_compliance"]
        self.assertEqual(compliance_model.call_count, 0)
        self.assertEqual(frame_pipeline.call_count, 0)
        self.assertIsNone(opening["sealed_start"])
        self.assertIsNone(opening["waybill_visible"])

    def test_verified_hard_opening_failure_is_not_a_native_dimension_gap(self) -> None:
        gaps = workbench_server.native_dimension_gaps(
            {
                "overall_audit": {"conclusion": "面单未清晰展示，开箱视频不合格。"},
                "frame_findings": [{"timestamp": "00:01.00", "visible_facts": "开始拆箱"}],
                "object_continuity_assessment": {
                    "continuity_verdict": "continuous",
                    "tracked_subjects": [{"subject_id": "claimed_item"}],
                },
                "video_audit_conclusion": {
                    "opening_video_compliance": {
                        "result": "noncompliant",
                        "sealed_start": True,
                        "waybill_visible": False,
                        "single_take_continuity": True,
                        "issue_visible_in_continuous_opening": True,
                        "validated_fields": [
                            "sealed_start",
                            "waybill_visible",
                            "single_take_continuity",
                            "issue_visible_in_continuous_opening",
                        ],
                        "field_sources": {
                            "sealed_start": "opening_start_verification",
                            "waybill_visible": "opening_compliance_verification",
                        },
                        "evidence_refs": [
                            {"field": "sealed_start", "video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
                            {"field": "waybill_visible", "video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00"},
                        ],
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
            },
            "product_damage",
        )

        self.assertNotIn("opening_video_hard_failure_candidate", gaps)

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

            with patch.dict(
                "os.environ", {"VISUAL_REVIEW_EPHEMERAL_TUNNEL": "0"}, clear=False
            ), patch.object(workbench_server, "load_visual_env"), patch.object(
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

    def test_standard_profile_does_not_add_frame_cost_after_native_success_by_default(self) -> None:
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

            with patch.dict(
                "os.environ", {"VISUAL_REVIEW_EPHEMERAL_TUNNEL": "0"}, clear=False
            ), patch.object(workbench_server, "load_visual_env"), patch.object(
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
                    requested_model_key="gemini35lite",
                )

        self.assertEqual(observed_modes, ["native"])
        self.assertEqual(observed_rule_versions, [1])
        self.assertEqual(published_version["value"], 1)
        self.assertEqual(chunked_model.call_count, 0)
        self.assertEqual(result["sampling"]["sampling_mode"], "native_video")
        self.assertFalse(result["media_preflight_execution"]["frame_fallback"]["used"])
        self.assertEqual(
            result["media_preflight_execution"]["frame_fallback"]["representation"],
            "not_used",
        )
        self.assertIsNone(result["media_preflight_execution"]["frame_fallback"]["sampling_fps"])

    def test_native_model_failure_keeps_cost_and_returns_system_retry_without_frames(self) -> None:
        observed = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

            def load_bundle(_sample_dir, _args, _run_dir, scenario_override="", native_video=None):
                return {
                    "case_id": "CASE-NATIVE-MODEL-FAILURE",
                    "scenario": scenario_override,
                    "scenario_label": "商品有伤审核",
                    "videos": [{"sampled_frames": 0}],
                    "frames": [],
                    "supplemental_images": [],
                    "native_video": dict(native_video or {}),
                    "structured_business_context": {},
                }

            def capture(_case, _sample_dir, model_result, *_args, **_kwargs):
                observed["result"] = model_result
                return {
                    "summary": {"review_status": "completed"},
                    "agent_report": {"parsed": dict(model_result.get("parsed") or {})},
                }

            native_failure = {
                "status": "failed",
                "error_type": "soft",
                "status_code": 503,
                "usage": {"input_tokens": 1200, "output_tokens": 0, "total_tokens": 1200},
                "cost": {"estimated_usd": 0.0021, "currency": "USD"},
                "model_http_request_count": 1,
                "model_latency_seconds_sum": 12.5,
            }
            with patch.dict(
                "os.environ",
                {"REVIEW_ENABLE_ONE_FPS_FRAME_FALLBACK": "false"},
                clear=False,
            ), patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "freeze_rule_snapshot", side_effect=lambda current, _tenant: current.setdefault("_business_rule_snapshot", {})
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server,
                "_native_video_source_context",
                return_value=contextmanager(
                    lambda: (yield {
                        "api_path": str(video),
                        "api_mime_type": "video/mp4",
                        "transport": "raw_original_inline",
                    })
                )(),
            ), patch.object(
                workbench_server, "call_model", return_value=native_failure
            ), patch.object(
                workbench_server, "_call_model_chunked_with_fallback"
            ) as frame_model, patch.object(
                workbench_server, "_agent_report_response", side_effect=capture
            ):
                response = workbench_server._run_review(
                    video,
                    "product_damage",
                    0.25,
                    24,
                    24,
                    12,
                    "standard",
                    {},
                    requested_model_key="gemini35lite",
                )

        frame_model.assert_not_called()
        parsed = observed["result"]["parsed"]
        self.assertEqual(parsed["processing_status"], "technical_processing_incomplete")
        self.assertEqual(parsed["system_action"], "system_retry")
        self.assertEqual(observed["result"]["usage"]["total_tokens"], 1200)
        self.assertAlmostEqual(observed["result"]["cost"]["estimated_usd"], 0.0021)
        self.assertEqual(observed["result"]["chunking"]["total_model_calls"], 1)
        self.assertFalse(response["media_preflight_execution"]["frame_fallback"]["used"])

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
