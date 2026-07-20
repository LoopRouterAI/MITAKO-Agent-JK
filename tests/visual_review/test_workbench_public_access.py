# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from poc.visual_review_poc import workbench_server


class WorkbenchPublicAccessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(workbench_server.app)

    def _assert_signed(self, url: str) -> None:
        query = parse_qs(urlsplit(url).query)
        self.assertIn("expires", query)
        self.assertIn("sig", query)

    def test_report_and_media_routes_require_path_bound_unexpired_signature(self) -> None:
        report_name = "signed-report.html"
        workbench_server.ALLOWED_REPORTS[report_name] = {
            "ok": True,
            "review_label": "商品有伤审核 / 标准视觉复核",
            "summary": {"review_status": "completed"},
            "agent_report": {"parsed": {}},
        }
        workbench_server.RUNTIME_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workbench_server.RUNTIME_MEDIA_DIR) as temp_dir:
            first = Path(temp_dir) / "first.jpg"
            second = Path(temp_dir) / "second.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            first_path = "/media/" + first.relative_to(workbench_server.ROOT).as_posix()
            second_path = "/media/" + second.relative_to(workbench_server.ROOT).as_posix()
            targets = [
                (f"/reports/{report_name}", "/reports/tampered-report.html"),
                (first_path, second_path),
            ]
            for original_path, tampered_path in targets:
                with self.subTest(path=original_path):
                    valid_url = workbench_server._sign_public_url(original_path)
                    self.assertEqual(self.client.get(valid_url).status_code, 200)
                    self.assertEqual(self.client.get(original_path).status_code, 403)

                    query = urlsplit(valid_url).query
                    self.assertEqual(self.client.get(f"{tampered_path}?{query}").status_code, 403)
                    expired_url = workbench_server._sign_public_url(
                        original_path,
                        expires=int(time.time()) - 1,
                    )
                    self.assertEqual(self.client.get(expired_url).status_code, 403)

    def test_all_generated_report_and_media_urls_are_signed(self) -> None:
        (workbench_server.ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workbench_server.ROOT / "tmp") as temp_dir:
            workbench_dir = Path(temp_dir)
            sample_dir = workbench_dir / "case"
            sample_dir.mkdir()
            (sample_dir / "evidence.mp4").write_bytes(b"video")
            case = {
                "case_id": "case-1",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [{"video_index": 1, "file": "evidence.mp4"}],
                "frames": [],
                "supplemental_images": [],
            }
            result = {
                "status": "success",
                "parsed": {
                    "predicted_label": "positive",
                    "confidence": 0.9,
                    "overall_audit": {"conclusion": "发现商品损伤"},
                },
            }
            with patch.object(workbench_server, "WORKBENCH_DIR", workbench_dir), patch.object(
                workbench_server, "PUBLIC_SUMMARY_DIR", workbench_dir / "summaries"
            ), patch.object(workbench_server, "score_result", return_value={}):
                response = workbench_server._agent_report_response(case, sample_dir, result, "signed")

            self._assert_signed(response["report"]["html_url"])
            self._assert_signed(response["agent_report"]["media_gallery"]["videos"][0]["url"])

    def test_public_media_url_is_opaque_and_survives_registry_reload(self) -> None:
        workbench_server.RUNTIME_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workbench_server.RUNTIME_MEDIA_DIR) as temp_dir:
            media = Path(temp_dir) / "customer-real-name-617911.mp4"
            media.write_bytes(b"video")

            url = workbench_server._media_url(media)

            self._assert_signed(url)
            self.assertTrue(urlsplit(url).path.startswith("/media-item/"))
            self.assertNotIn(media.name, url)
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_media_registry_retries_transient_windows_replace_error_and_cleans_temp_file(self) -> None:
        workbench_server.RUNTIME_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workbench_server.RUNTIME_MEDIA_DIR) as temp_dir:
            root = Path(temp_dir)
            media = root / "evidence.jpg"
            registry = root / "registry.json"
            media.write_bytes(b"evidence")
            real_replace = workbench_server.os.replace
            attempts = 0

            def flaky_replace(source, target):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise PermissionError("sharing violation")
                return real_replace(source, target)

            with patch.object(workbench_server, "PUBLIC_MEDIA_INDEX_PATH", registry), patch.object(
                workbench_server.os, "replace", side_effect=flaky_replace
            ), patch.object(workbench_server.time, "sleep", return_value=None):
                url = workbench_server._media_url(media)

            self._assert_signed(url)
            self.assertEqual(attempts, 2)
            self.assertTrue(registry.is_file())
            self.assertEqual(list(root.glob(".registry.json.*.tmp")), [])

    def test_health_declares_inline_frame_transport_without_supplier_file_uri_dependency(self) -> None:
        payload = workbench_server.health()
        transport = payload["model_media_transport"]

        self.assertEqual(transport["mode"], "inline_base64_images")
        self.assertIs(transport["supplier_file_uri_required"], False)
        self.assertIn("image/webp", transport["accepted_model_media_types"])

    def test_minor_material_public_parsed_uses_strict_whitelist_and_redacts_identifiers(self) -> None:
        parsed = {
            "predicted_label": "review",
            "confidence": 0.66,
            "overall_audit": {
                "conclusion": "联系 18012345678，证件 320000200801011234",
                "confidence": 0.66,
                "unknown_nested": "不得公开",
            },
            "minor_material_assessment": {
                "readiness": "needs_human_gap_confirmation",
                "checklist": [{
                    "requirement_id": "identity",
                    "label": "身份证明",
                    "status": "present",
                    "quality_status": "needs_manual_confirmation",
                    "raw_value": "320000200801011234",
                    "unknown_item": "不得公开",
                }],
                "field_consistency": {
                    "status": "completed",
                    "verdict": "matched",
                    "unknown": "不得公开",
                },
                "unknown_assessment": "不得公开",
            },
            "ocr_text": "原始 OCR 18012345678",
            "raw_value": "320000200801011234",
            "unknown_top_level": "不得公开",
        }
        payload = workbench_server._public_agent_report_payload(
            case={
                "case_id": "minor-1",
                "scenario": "minor_material",
                "scenario_label": "未成年人资料审核",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
            },
            sample_dir=Path("."),
            parsed=parsed,
            result={"status": "success"},
            quality={},
            public_conclusion="需人工复核",
            public_next_step="请授权人员复核",
        )
        public_parsed = payload["parsed"]
        serialized = json.dumps(public_parsed, ensure_ascii=False)

        self.assertEqual(public_parsed["predicted_label"], "review")
        self.assertEqual(public_parsed["minor_material_assessment"]["checklist"][0]["status"], "present")
        self.assertEqual(
            public_parsed["minor_material_assessment"]["checklist"][0]["quality_status"],
            "needs_manual_confirmation",
        )
        for forbidden in (
            "unknown_top_level",
            "unknown_nested",
            "unknown_assessment",
            "unknown_item",
            "ocr_text",
            "raw_value",
            "18012345678",
            "320000200801011234",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_other_scenarios_use_strict_public_dto_and_redact_identifiers(self) -> None:
        parsed = {
            "predicted_label": "positive",
            "confidence": 0.9,
            "customer_phone": "18012345678",
            "custom_business_field": {"address": "上海市某路1号"},
            "supporting_evidence": [{"source_type": "image", "fact": "联系电话 18012345678"}],
        }
        payload = workbench_server._public_agent_report_payload(
            case={
                "case_id": "damage-1",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
            },
            sample_dir=Path("."),
            parsed=parsed,
            result={"status": "success"},
            quality={},
            public_conclusion="发现损伤",
            public_next_step="人工复核",
        )
        serialized = json.dumps(payload["parsed"], ensure_ascii=False)
        self.assertNotIn("customer_phone", serialized)
        self.assertNotIn("custom_business_field", serialized)
        self.assertNotIn("18012345678", serialized)
        self.assertIn("[已脱敏]", serialized)

    def test_public_free_text_redacts_labeled_names_and_addresses(self) -> None:
        parsed = {
            "predicted_label": "review",
            "confidence": 0.68,
            "supporting_evidence": [{
                "source_type": "image",
                "fact": "申请人姓名：张三，收货地址：上海市浦东新区世纪大道100号。",
            }],
        }
        payload = workbench_server._public_agent_report_payload(
            case={
                "case_id": "privacy-1",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
            },
            sample_dir=Path("."),
            parsed=parsed,
            result={"status": "success"},
            quality={},
            public_conclusion="需人工复核",
            public_next_step="请授权人员复核",
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("张三", serialized)
        self.assertNotIn("上海市浦东新区世纪大道100号", serialized)
        self.assertIn("[已脱敏]", serialized)

    def test_public_evidence_package_exposes_requested_and_effective_sampling_fps(self) -> None:
        payload = workbench_server._public_agent_report_payload(
            case={
                "case_id": "sampling-1",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [{
                    "video_index": 1,
                    "duration_seconds": 10.0,
                    "native_fps": 30.0,
                    "fps_requested": 2.0,
                    "sampled_frames": 21,
                }],
                "frames": [],
                "supplemental_images": [],
            },
            sample_dir=Path("."),
            parsed={"predicted_label": "review", "confidence": 0.6},
            result={"status": "success"},
            quality={},
            public_conclusion="需复核",
            public_next_step="复核",
        )

        video = payload["evidence_package"]["videos"][0]
        self.assertEqual(video["fps_requested"], 2.0)
        self.assertEqual(video["effective_sample_fps"], 2.1)

    def test_health_exposes_only_persistent_signing_configuration_state(self) -> None:
        with patch.object(workbench_server, "REPORT_SIGNING_SECRET_CONFIGURED", False), patch.object(
            workbench_server, "REQUIRE_PERSISTENT_REPORT_SIGNING_SECRET", True
        ):
            payload = workbench_server.health()
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertIs(payload["report_signing_secret_configured"], False)
        self.assertIs(payload["ok"], False)
        self.assertNotIn(workbench_server.REPORT_SIGNING_SECRET.hex(), serialized)


if __name__ == "__main__":
    unittest.main()
