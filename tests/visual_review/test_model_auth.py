# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ModelAuthTest(unittest.TestCase):
    def test_dotenv_uses_last_value_in_file_without_overriding_process_env(self):
        from poc.visual_review_poc.local_video_triage_demo import load_env_file

        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "GEMINI_API_BASE_URL=https://generativelanguage.googleapis.com\n"
                "GEMINI_API_BASE_URL=https://vod.bj.baidubce.com/v3/chat/gc\n",
                encoding="utf-8",
            )
            with patch.dict("os.environ", {}, clear=True):
                load_env_file(env_file)
                self.assertEqual(
                    os.environ["GEMINI_API_BASE_URL"],
                    "https://vod.bj.baidubce.com/v3/chat/gc",
                )
            with patch.dict("os.environ", {"GEMINI_API_BASE_URL": "https://runtime.example"}, clear=True):
                load_env_file(env_file)
                self.assertEqual(os.environ["GEMINI_API_BASE_URL"], "https://runtime.example")

    def test_baidu_endpoint_uses_bearer_and_full_url_is_not_duplicated(self):
        from poc.visual_review_poc.model_auth import gemini_auth_headers, gemini_generate_endpoint

        endpoint = gemini_generate_endpoint(
            "https://vod.bj.baidubce.com/v3/chat/gc",
            "gemini-3.5-flash",
        )
        self.assertEqual(
            endpoint,
            "https://vod.bj.baidubce.com/v3/chat/gc/v1beta/models/gemini-3.5-flash:generateContent",
        )
        self.assertEqual(
            gemini_auth_headers(endpoint, "secret-value"),
            {"Authorization": "Bearer secret-value", "Content-Type": "application/json"},
        )
        self.assertEqual(gemini_generate_endpoint(endpoint, "ignored"), endpoint)

    def test_google_endpoint_uses_native_header_and_template(self):
        from poc.visual_review_poc.model_auth import endpoint_vendor_hint, gemini_auth_headers, gemini_generate_endpoint

        endpoint = gemini_generate_endpoint(
            "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            "gemini-3.5-flash",
        )
        self.assertIn("gemini-3.5-flash:generateContent", endpoint)
        self.assertEqual(
            gemini_auth_headers(endpoint, "secret-value"),
            {"x-goog-api-key": "secret-value", "Content-Type": "application/json"},
        )
        self.assertEqual(endpoint_vendor_hint(endpoint), "google")

    def test_actual_review_channels_use_shared_auth_rules(self):
        from poc.visual_review_poc.local_video_triage_demo import gemini_channels
        from poc.visual_review_poc.model_selection_e2e import gemini_request_options

        env = {
            "VISION_REVIEW_API_KEY": "gateway-secret",
            "VISION_REVIEW_GEMINI_BASE_URL": "https://vod.bj.baidubce.com/v3/chat/gc",
            "VISION_REVIEW_GEMINI_AUTH_MODE": "auto",
        }
        with patch.dict("os.environ", env, clear=True):
            channel = gemini_channels()[0]
            option = gemini_request_options({"model": "gemini-3.5-flash"})[0]

        self.assertEqual(channel["headers"]["Authorization"], "Bearer gateway-secret")
        self.assertNotIn("x-goog-api-key", channel["headers"])
        self.assertEqual(option["headers"]["Authorization"], "Bearer gateway-secret")
        self.assertTrue(option["endpoint"].endswith("/v1beta/models/gemini-3.5-flash:generateContent"))

    def test_gemini_named_credentials_are_labeled_by_baidu_endpoint(self):
        from poc.visual_review_poc.model_auth import gemini_channel_options

        with patch.dict(
            "os.environ",
            {
                "GEMINI_API_KEY": "baidu-secret",
                "GEMINI_API_BASE_URL": "https://vod.bj.baidubce.com/v3/chat/gc",
            },
            clear=True,
        ):
            options = gemini_channel_options("gemini-3.5-flash-lite")

        self.assertEqual([item["channel"] for item in options], ["baidu"])
        self.assertEqual(options[0]["headers"]["Authorization"], "Bearer baidu-secret")

    def test_channels_follow_runtime_priority_and_bananarouter_uses_bearer(self):
        from poc.visual_review_poc.local_video_triage_demo import gemini_channels
        from poc.visual_review_poc.model_selection_e2e import gemini_request_options

        env = {
            "BANANAROUTER_API_KEY": "banana-secret",
            "BANANAROUTER_GEMINI_BASE_URL": "https://banana.example/gemini",
            "BAIDU_API_KEY": "baidu-secret",
            "BAIDU_GEMINI_BASE_URL": "https://vod.bj.baidubce.com/v3/chat/gc",
            "APIYI_API_KEY": "apiyi-secret",
            "APIYI_GEMINI_BASE_URL": "https://apiyi.example/gemini",
            "GEMINI_API_KEY": "official-secret",
            "GEMINI_API_BASE_URL": "https://generativelanguage.googleapis.com",
        }
        with patch.dict("os.environ", env, clear=True):
            channels = gemini_channels()
            options = gemini_request_options({"model": "gemini-3.5-flash-lite"})

        self.assertEqual([item["channel"] for item in channels], ["baidu", "bananarouter", "apiyi", "official"])
        self.assertEqual([item["channel"] for item in options], ["baidu", "bananarouter", "apiyi", "official"])
        self.assertEqual(channels[1]["headers"]["Authorization"], "Bearer banana-secret")
        self.assertNotIn("x-goog-api-key", channels[1]["headers"])
        self.assertEqual(channels[2]["headers"]["Authorization"], "Bearer apiyi-secret")
        self.assertNotIn("x-goog-api-key", channels[2]["headers"])

    def test_channels_skip_incomplete_config_and_deduplicate_legacy_gateway(self):
        from poc.visual_review_poc.model_auth import gemini_channel_options

        env = {
            "BANANAROUTER_API_KEY": "missing-url",
            "BAIDU_GEMINI_BASE_URL": "https://unused.example",
            "APIYI_API_KEY": "apiyi-secret",
            "APIYI_GEMINI_BASE_URL": "https://apiyi.example/gemini",
            "VISION_REVIEW_API_KEY": "apiyi-secret",
            "VISION_REVIEW_GEMINI_BASE_URL": "https://apiyi.example/gemini",
        }
        with patch.dict("os.environ", env, clear=True):
            options = gemini_channel_options("gemini-3.5-flash-lite")

        self.assertEqual([item["channel"] for item in options], ["apiyi"])

    def test_legacy_baidu_gateway_keeps_priority_before_apiyi(self):
        from poc.visual_review_poc.model_auth import gemini_channel_options

        env = {
            "VISION_REVIEW_API_KEY": "legacy-baidu-secret",
            "VISION_REVIEW_GEMINI_BASE_URL": "https://vod.bj.baidubce.com/v3/chat/gc",
            "APIYI_API_KEY": "apiyi-secret",
            "APIYI_GEMINI_BASE_URL": "https://apiyi.example/gemini",
        }
        with patch.dict("os.environ", env, clear=True):
            options = gemini_channel_options("gemini-3.5-flash-lite")

        self.assertEqual([item["channel"] for item in options], ["baidu", "apiyi"])

    def test_explicit_model_then_visual_primary_then_gemini_then_default(self):
        from poc.visual_review_poc.model_auth import gemini_channel_options

        gateway = {
            "APIYI_API_KEY": "apiyi-secret",
            "APIYI_GEMINI_BASE_URL": "https://apiyi.example/gemini",
        }
        with patch.dict(
            "os.environ",
            {
                **gateway,
                "VISUAL_REVIEW_PRIMARY_MODEL": "visual-primary-model",
                "GEMINI_MODEL": "gemini-model",
            },
            clear=True,
        ):
            self.assertEqual(gemini_channel_options("explicit-model")[0]["model"], "explicit-model")
            self.assertEqual(gemini_channel_options()[0]["model"], "visual-primary-model")
        with patch.dict("os.environ", {**gateway, "GEMINI_MODEL": "gemini-model"}, clear=True):
            self.assertEqual(gemini_channel_options()[0]["model"], "gemini-model")
        with patch.dict("os.environ", gateway, clear=True):
            self.assertEqual(gemini_channel_options()[0]["model"], "gemini-3.5-flash-lite")

    def test_unknown_legacy_gateway_is_only_used_when_all_explicit_channels_are_missing(self):
        from poc.visual_review_poc.model_auth import gemini_channel_options

        legacy = {
            "VISION_REVIEW_API_KEY": "legacy-secret",
            "VISION_REVIEW_GEMINI_BASE_URL": "https://legacy.example/gemini",
        }
        explicit = {
            "BANANAROUTER_API_KEY": "banana-secret",
            "BANANAROUTER_GEMINI_BASE_URL": "https://banana.example/gemini",
            "BAIDU_API_KEY": "baidu-secret",
            "BAIDU_GEMINI_BASE_URL": "https://vod.bj.baidubce.com/v3/chat/gc",
            "APIYI_API_KEY": "apiyi-secret",
            "APIYI_GEMINI_BASE_URL": "https://apiyi.example/gemini",
            "GEMINI_API_KEY": "official-secret",
        }
        with patch.dict("os.environ", {**legacy, **explicit}, clear=True):
            options = gemini_channel_options()
        self.assertEqual([item["channel"] for item in options], ["baidu", "bananarouter", "apiyi", "official"])

        with patch.dict("os.environ", legacy, clear=True):
            fallback = gemini_channel_options()
        self.assertEqual([item["channel"] for item in fallback], ["legacy"])

    def test_official_key_wins_when_legacy_uses_the_same_google_endpoint(self):
        from poc.visual_review_poc.model_auth import gemini_channel_options

        env = {
            "VISION_REVIEW_API_KEY": "legacy-secret",
            "VISION_REVIEW_GEMINI_BASE_URL": "https://generativelanguage.googleapis.com",
            "GEMINI_API_KEY": "official-secret",
            "GEMINI_API_BASE_URL": "https://generativelanguage.googleapis.com",
        }
        with patch.dict("os.environ", env, clear=True):
            options = gemini_channel_options()

        self.assertEqual([item["channel"] for item in options], ["official"])
        self.assertEqual(options[0]["headers"]["x-goog-api-key"], "official-secret")

    def test_legacy_channel_keys_can_use_shared_base_url(self):
        from poc.visual_review_poc.model_auth import gemini_channel_options

        cases = (
            ("BROUTER_API_KEY", "https://api.bananarouter.example/gemini", "bananarouter"),
            ("BRouter_API_KEY", "https://api.bananarouter.example/gemini", "bananarouter"),
            ("APIYI_API_KEY", "https://api.apiyi.com/gemini", "apiyi"),
        )
        for key_name, shared_base, expected_channel in cases:
            with self.subTest(key_name=key_name), patch.dict(
                "os.environ",
                {key_name: "legacy-channel-secret", "VISION_REVIEW_GEMINI_BASE_URL": shared_base},
                clear=True,
            ):
                options = gemini_channel_options()
                self.assertEqual([item["channel"] for item in options], [expected_channel])

        env = {
            "BROUTER_API_KEY": "banana-secret",
            "VISION_REVIEW_GEMINI_BASE_URL": "https://api.bananarouter.example/gemini",
            "BAIDU_API_KEY": "baidu-secret",
            "BAIDU_GEMINI_BASE_URL": "https://vod.bj.baidubce.com/v3/chat/gc",
            "APIYI_API_KEY": "apiyi-secret",
            "APIYI_GEMINI_BASE_URL": "https://api.apiyi.com/gemini",
            "GEMINI_API_KEY": "official-secret",
        }
        with patch.dict("os.environ", env, clear=True):
            options = gemini_channel_options()
        self.assertEqual([item["channel"] for item in options], ["baidu", "bananarouter", "apiyi", "official"])

    def test_unknown_shared_base_remains_single_legacy_fallback(self):
        from poc.visual_review_poc.model_auth import gemini_channel_options

        for key_name in ("BROUTER_API_KEY", "BRouter_API_KEY", "APIYI_API_KEY"):
            with self.subTest(key_name=key_name), patch.dict(
                "os.environ",
                {key_name: "legacy-secret", "VISION_REVIEW_GEMINI_BASE_URL": "https://legacy.example/gemini"},
                clear=True,
            ):
                options = gemini_channel_options()
                self.assertEqual([item["channel"] for item in options], ["legacy"])

    def test_public_runtime_model_resolver_drives_default_cost(self):
        from poc.visual_review_poc import model_auth
        from poc.visual_review_poc.local_video_triage_demo import estimate_cost

        resolver = getattr(model_auth, "resolve_gemini_model", None)
        self.assertIsNotNone(resolver)
        if resolver is None:
            return
        env = {
            "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash",
            "GEMINI_MODEL": "gemini-3.5-flash-lite",
        }
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(resolver(), "gemini-3.5-flash")
            self.assertEqual(resolver("gemini-3.5-flash-lite"), "gemini-3.5-flash-lite")
            self.assertEqual(
                estimate_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000})["estimated_usd"],
                10.5,
            )

    def test_failed_single_sample_report_marks_cost_unknown_or_not_incurred(self):
        from poc.visual_review_poc import local_video_triage_demo as demo

        channel = {"channel": "official", "model": "gemini-3.5-flash", "soft_retries": 0}
        with patch.object(demo, "gemini_channels", return_value=[channel]), patch.object(
            demo,
            "post_json",
            return_value={"ok": False, "status_code": 503, "error_type": "soft", "error": "unavailable"},
        ):
            failed = demo.call_gemini({}, timeout=1, soft_retries=0)
        self.assertEqual(failed["cost_status"], "unknown")
        self.assertIsNone(failed["cost"]["estimated_usd"])

        with patch.object(demo, "gemini_channels", return_value=[]):
            not_incurred = demo.call_gemini({}, timeout=1, soft_retries=0)
        self.assertEqual(not_incurred["cost_status"], "not_incurred")

        report = {
            "gemini": failed,
            "case": {},
            "frames": [],
            "supplemental_images": [],
            "evaluation": {},
            "policy_decision": {},
        }
        with patch.dict(
            "os.environ",
            {"VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash", "GEMINI_MODEL": "gemini-3.5-flash-lite"},
            clear=True,
        ):
            html = demo.render_html(report)
        self.assertIn("gemini-3.5-flash 单样本审核报告", html)
        self.assertIn("成本未知", html)
        self.assertNotIn("$0.0", html)

    def test_successful_single_sample_without_explicit_cost_uses_winner_usage(self):
        from poc.visual_review_poc.local_video_triage_demo import render_html

        report = {
            "gemini": {
                "status": "success",
                "attempts": [{"ok": True}],
                "winner": {
                    "model": "gemini-3.5-flash-lite",
                    "parsed": {},
                    "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
                },
            },
            "case": {},
            "frames": [],
            "supplemental_images": [],
            "evaluation": {},
            "policy_decision": {},
        }

        html = render_html(report)

        self.assertIn("$2.8", html)
        self.assertNotIn("成本未知", html)

    def test_successful_fallback_marks_previous_channel_cost_unknown(self):
        from poc.visual_review_poc import local_video_triage_demo as demo
        from poc.visual_review_poc import model_selection_e2e as selection

        channels = [
            {"channel": "bananarouter", "model": "gemini-3.5-flash-lite", "soft_retries": 0},
            {"channel": "official", "model": "gemini-3.5-flash-lite", "soft_retries": 0},
        ]
        responses = [
            {"ok": False, "status_code": 503, "error_type": "soft", "error": "unavailable"},
            {
                "ok": True,
                "status_code": 200,
                "data": {
                    "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
                },
            },
        ]
        with patch.object(demo, "gemini_channels", return_value=channels), patch.object(
            demo, "post_json", side_effect=responses
        ):
            local_result = demo.call_gemini({}, timeout=1, soft_retries=0)

        cfg = dict(selection.MODEL_CONFIGS["gemini35lite"])
        case = {
            "case_id": "cost-fallback",
            "scenario": "product_damage",
            "structured_business_context": {},
            "frames": [],
            "supplemental_images": [],
            "official_reference_images": [],
        }
        options = [
            {"endpoint": "https://banana.example/gemini", "headers": {}},
            {"endpoint": "https://google.example/gemini", "headers": {}},
        ]
        with patch.object(selection, "gemini_request_options", return_value=options), patch.object(
            selection, "post_with_retries", side_effect=responses
        ):
            selection_result = selection.call_model(cfg, case, timeout=1, retries=0)

        for result in (local_result, selection_result):
            self.assertEqual(result["cost_status"], "partial_unknown")
            self.assertEqual(result["unknown_cost_calls"], 1)
            self.assertEqual(result["estimated_cost_calls"], 1)

    def test_gemini_native_payloads_omit_temperature(self):
        from poc.visual_review_poc.local_video_triage_demo import build_payload
        from poc.visual_review_poc.model_selection_e2e import gemini_payload

        local_payload = build_payload("system", "user", [], [])
        selection_payload = gemini_payload(
            "system",
            "user",
            {"frames": [], "supplemental_images": [], "official_reference_images": []},
        )

        self.assertNotIn("temperature", local_payload["generationConfig"])
        self.assertNotIn("temperature", selection_payload["generationConfig"])

    def test_gemini_native_payloads_use_rest_casing_and_structured_output(self):
        from poc.visual_review_poc.local_video_triage_demo import build_payload
        from poc.visual_review_poc.model_selection_e2e import gemini_payload

        payloads = [
            build_payload("system", "user", [], []),
            gemini_payload(
                "system",
                "user",
                {"frames": [], "supplemental_images": [], "official_reference_images": []},
            ),
        ]

        for payload in payloads:
            config = payload["generationConfig"]
            self.assertEqual(config["responseMimeType"], "application/json")
            self.assertEqual(config["responseSchema"]["type"], "object")
            self.assertIn("frame_findings", config["responseSchema"]["required"])
            self.assertIn("systemInstruction", payload)
            serialized = str(payload)
            self.assertNotIn("response_mime_type", serialized)
            self.assertNotIn("system_instruction", serialized)

    def test_gemini_frame_payload_uses_baidu_compatible_compact_schema(self):
        from poc.visual_review_poc.model_selection_e2e import gemini_payload

        payload = gemini_payload(
            "system",
            "user",
            {"frames": [], "supplemental_images": [], "official_reference_images": []},
        )

        schema = payload["generationConfig"]["responseSchema"]
        self.assertIn("frame_findings", schema["required"])
        frame_required = set(schema["properties"]["frame_findings"]["items"]["required"])
        self.assertTrue({"video_index", "global_frame_index"}.issubset(frame_required))
        for duplicate_field in (
            "supporting_evidence",
            "challenging_evidence",
            "audit_methods",
            "visual_evidence_verdict",
            "confidence_reason",
            "model_limitations",
        ):
            self.assertNotIn(duplicate_field, schema["properties"])

    def test_gemini_payload_can_attach_one_native_video_for_internal_ab(self):
        from poc.visual_review_poc.model_selection_e2e import gemini_payload

        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"video-bytes")
            payload = gemini_payload(
                "system",
                "user",
                {
                    "frames": [],
                    "supplemental_images": [],
                    "official_reference_images": [],
                    "native_video": {
                        "video_index": 1,
                        "api_path": str(video),
                        "api_mime_type": "video/mp4",
                    },
                },
            )

        parts = payload["contents"][0]["parts"]
        video_parts = [item["inlineData"] for item in parts if "inlineData" in item]
        self.assertEqual(len(video_parts), 1)
        self.assertEqual(video_parts[0]["mimeType"], "video/mp4")
        self.assertIn("native_video_1", str(parts))
        native_schema = payload["generationConfig"]["responseSchema"]
        self.assertIn(
            "opening_video_compliance",
            native_schema["properties"]["video_audit_conclusion"]["properties"],
        )
        for duplicate_field in (
            "supporting_evidence",
            "challenging_evidence",
            "audit_methods",
            "visual_evidence_verdict",
            "confidence_reason",
            "model_limitations",
        ):
            self.assertNotIn(duplicate_field, native_schema["properties"])

    def test_opening_start_verification_uses_small_dedicated_schema(self):
        from poc.visual_review_poc.model_selection_e2e import gemini_payload

        payload = gemini_payload(
            "system",
            "user",
            {
                "frames": [],
                "supplemental_images": [],
                "official_reference_images": [],
                "structured_business_context": {"analysis_mode": "opening_start_only"},
            },
        )

        schema = payload["generationConfig"]["responseSchema"]
        self.assertEqual(set(schema["required"]), {"result", "sealed_start", "evidence_refs", "reason"})
        self.assertNotIn("frame_findings", schema["properties"])
        self.assertNotIn("maxOutputTokens", payload["generationConfig"])

    def test_minor_material_modes_use_dedicated_compact_schemas(self):
        from poc.visual_review_poc.model_selection_e2e import gemini_payload

        expected_fields = {
            "minor_material_inventory": {"coverage_ack", "material_observations"},
            "minor_material_process_video": {"process_observations", "process_summary"},
            "minor_material_consistency": {"coverage_ack", "consistency_check"},
        }
        for analysis_mode, fields in expected_fields.items():
            with self.subTest(analysis_mode=analysis_mode):
                payload = gemini_payload(
                    "system",
                    "user",
                    {
                        "frames": [],
                        "supplemental_images": [],
                        "official_reference_images": [],
                        "structured_business_context": {"analysis_mode": analysis_mode},
                    },
                )
                schema = payload["generationConfig"]["responseSchema"]
                self.assertTrue(fields.issubset(schema["properties"]))
                self.assertNotIn("frame_findings", schema["properties"])
                self.assertNotIn("maxOutputTokens", payload["generationConfig"])

    def test_gemini_payload_can_reference_baidu_public_video_url(self):
        from poc.visual_review_poc.model_selection_e2e import gemini_payload

        payload = gemini_payload(
            "system",
            "user",
            {
                "frames": [],
                "supplemental_images": [],
                "official_reference_images": [],
                "native_video": {
                    "video_index": 1,
                    "file_uri": "https://media.example.com/evidence.mp4?signature=short-lived",
                    "api_mime_type": "video/mp4",
                },
            },
        )

        parts = payload["contents"][0]["parts"]
        self.assertEqual(
            [item["fileData"] for item in parts if "fileData" in item],
            [{
                "mimeType": "video/mp4",
                "fileUri": "https://media.example.com/evidence.mp4?signature=short-lived",
            }],
        )
        self.assertFalse(any("inlineData" in item for item in parts))

    def test_external_native_video_url_skips_channels_without_declared_capability(self):
        from poc.visual_review_poc import model_selection_e2e as selection

        cfg = dict(selection.MODEL_CONFIGS["gemini35lite"])
        case = {
            "case_id": "native-url-routing",
            "scenario": "product_damage",
            "structured_business_context": {},
            "frames": [],
            "supplemental_images": [],
            "official_reference_images": [],
            "native_video": {
                "video_index": 1,
                "file_uri": "https://media.example.com/evidence.mp4",
                "api_mime_type": "video/mp4",
            },
        }
        options = [
            {
                "channel": "bananarouter",
                "endpoint": "https://banana.example/gemini",
                "headers": {},
                "supports_external_file_uri": False,
            },
            {
                "channel": "baidu",
                "endpoint": "https://vod.bj.baidubce.com/gemini",
                "headers": {},
                "supports_external_file_uri": True,
            },
        ]
        response = {
            "ok": True,
            "status_code": 200,
            "latency_seconds": 0.1,
            "attempt": 1,
            "data": {
                "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                "usageMetadata": {},
            },
        }

        with patch.object(selection, "gemini_request_options", return_value=options), patch.object(
            selection, "post_with_retries", return_value=response
        ) as post:
            result = selection.call_model(cfg, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], options[1]["endpoint"])
        self.assertEqual(result["_channel_route_attempts"][0]["decision"], "skipped_unsupported_file_uri")

    def test_gemini_schema_requires_meaningful_native_video_evidence(self):
        from poc.visual_review_poc.review_response_schema import REVIEW_RESPONSE_SCHEMA

        properties = REVIEW_RESPONSE_SCHEMA["properties"]
        continuity = properties["object_continuity_assessment"]
        damage = properties["damage_causality_assessment"]
        finding = properties["frame_findings"]["items"]
        video_audit = properties["video_audit_conclusion"]
        opening = video_audit["properties"]["opening_video_compliance"]

        self.assertIn("tracked_subjects", continuity["properties"])
        self.assertIn("continuity_verdict", continuity["required"])
        self.assertIn("damage_presence", damage["required"])
        self.assertIn("claim_support", damage["required"])
        self.assertIn("timestamp", finding["required"])
        self.assertIn("subject_visibility", finding["required"])
        self.assertIn("opening_video_compliance", video_audit["required"])
        self.assertEqual(
            set(opening["required"]),
            {
                "sealed_start",
                "waybill_visible",
                "single_take_continuity",
                "issue_visible_in_continuous_opening",
                "evidence_refs",
                "result",
            },
        )
        self.assertEqual(opening["properties"]["evidence_refs"]["type"], "array")
        self.assertIn("field", opening["properties"]["evidence_refs"]["items"]["required"])

    def test_openai_compatible_payload_keeps_temperature(self):
        from poc.visual_review_poc import model_selection_e2e as selection

        cfg = {
            "provider": "openai_compatible",
            "model": "compatible-model",
            "label": "Compatible",
            "endpoint": "https://compatible.example/chat/completions",
            "key_env": "COMPATIBLE_API_KEY",
        }
        case = {"scenario": "product_damage", "structured_business_context": {}}
        with patch.dict("os.environ", {"COMPATIBLE_API_KEY": "secret"}, clear=True), patch.object(
            selection, "build_system_prompt", return_value="system"
        ), patch.object(selection, "build_selection_prompt", return_value="user"), patch.object(
            selection, "openai_messages", return_value=[]
        ), patch.object(
            selection,
            "post_with_retries",
            return_value={"ok": False, "error_type": "hard", "error": "failed"},
        ) as post:
            selection.call_model(cfg, case, timeout=1, retries=0)

        self.assertEqual(post.call_args.args[2]["temperature"], 0.1)

    def test_missing_channel_error_explains_key_and_base_url_requirements(self):
        from types import SimpleNamespace

        from poc.visual_review_poc import local_video_triage_demo as demo

        with patch.object(demo, "load_env"), patch.object(demo, "gemini_channels", return_value=[]):
            with self.assertRaises(SystemExit) as error:
                demo.run(SimpleNamespace(video=__file__))

        message = str(error.exception)
        self.assertIn("BananaRouter", message)
        self.assertIn("百度", message)
        self.assertIn("API易", message)
        self.assertIn("Key + Base URL", message)
        self.assertIn("Google 官方只需 Key", message)

    def test_default_model_and_gemini_model_override_are_resolved_at_runtime(self):
        from poc.visual_review_poc.local_video_triage_demo import gemini_channels

        gateway = {
            "BANANAROUTER_API_KEY": "banana-secret",
            "BANANAROUTER_GEMINI_BASE_URL": "https://banana.example/gemini",
        }
        with patch.dict("os.environ", gateway, clear=True):
            self.assertEqual(gemini_channels()[0]["model"], "gemini-3.5-flash-lite")
        with patch.dict("os.environ", {**gateway, "GEMINI_MODEL": "gemini-custom"}, clear=True):
            self.assertEqual(gemini_channels()[0]["model"], "gemini-custom")

    def test_flash_lite_single_sample_cost_uses_its_own_price(self):
        from poc.visual_review_poc.local_video_triage_demo import estimate_cost
        from poc.visual_review_poc.model_catalog import MODEL_CONFIGS

        cfg = MODEL_CONFIGS["gemini35lite"]
        self.assertEqual(cfg["model"], "gemini-3.5-flash-lite")
        self.assertEqual(cfg["input_price"], 0.30)
        self.assertEqual(cfg["output_price"], 2.50)
        cost = estimate_cost(
            {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
            "gemini-3.5-flash-lite",
        )
        self.assertEqual(cost["estimated_usd"], 2.8)
        self.assertEqual(cost["input_usd_per_1m"], 0.30)
        self.assertEqual(cost["output_usd_per_1m"], 2.50)

    def test_single_sample_report_uses_actual_model_and_cost_basis(self):
        from poc.visual_review_poc.local_video_triage_demo import render_html

        report = {
            "gemini": {
                "status": "success",
                "attempts": [],
                "winner": {
                    "model": "gemini-3.5-flash-lite",
                    "parsed": {},
                    "usage": {},
                    "cost": {
                        "estimated_usd": 0.01,
                        "basis": "Flash-Lite 独立价格基准",
                        "source": "pricing-source",
                    },
                },
            },
            "case": {},
            "frames": [],
            "supplemental_images": [],
            "evaluation": {},
            "policy_decision": {},
        }

        html = render_html(report)

        self.assertIn("gemini-3.5-flash-lite 单样本审核报告", html)
        self.assertIn("Flash-Lite 独立价格基准", html)
        self.assertNotIn("Gemini 3.5 Flash 单样本审核报告", html)

    def test_unknown_auth_mode_is_rejected_instead_of_silent_fallback(self):
        from poc.visual_review_poc.model_auth import gemini_auth_headers

        with self.assertRaises(ValueError):
            gemini_auth_headers("https://example.com/v1/models/demo:generateContent", "secret", "bearr")


if __name__ == "__main__":
    unittest.main()
