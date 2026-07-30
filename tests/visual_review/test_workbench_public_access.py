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
from poc.visual_review_poc.media_registry import MediaRegistry


class WorkbenchPublicAccessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(workbench_server.app)

    def _assert_signed(self, url: str) -> None:
        query = parse_qs(urlsplit(url).query)
        self.assertIn("expires", query)
        self.assertIn("sig", query)

    def test_minor_material_workbench_defaults_to_visual_precheck(self) -> None:
        workbench = workbench_server.INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('name="minor_refund_policy"', workbench)
        self.assertIn('"authoritative_verification":"disabled"', workbench)
        self.assertIn("标准视觉初审（默认，不依赖外部接口）", workbench)
        self.assertNotIn("始终VIP客服终审", workbench)
        self.assertNotIn("最终结论必须由VIP客服复核确认", workbench)

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
                "official_reference_images": [{
                    "reference_index": 1,
                    "reference_id": "ref-001",
                    "item_ref": "ORDER-LINE-001",
                    "sku": "SKU-001",
                    "product_name": "官方商品",
                    "api_path": str(sample_dir / "official.jpg"),
                }],
                "official_reference_status": {"status": "available", "available_count": 1},
                "structured_business_context": {
                    "fulfillment_baseline": {
                        "baseline_version": "order_info_snapshot:test",
                        "expected_items": [{
                            "item_ref": "ORDER-LINE-001",
                            "sku": "SKU-001",
                            "product_name": "官方商品",
                            "expected_quantity": 1,
                        }],
                    },
                    "logistics": {"carrier": "测试快递", "tracking_ref": "sha256:test"},
                },
            }
            (sample_dir / "official.jpg").write_bytes(b"official")
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
            self._assert_signed(response["agent_report"]["media_gallery"]["official_references"][0]["url"])
            baseline = response["agent_report"]["evidence_package"]["order_baseline"]
            self.assertEqual(baseline["expected_items"][0]["sku"], "SKU-001")
            self.assertEqual(baseline["tracking_ref"], "sha256:test")

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

    def test_external_workbench_directory_media_remains_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            external = Path(temp_dir)
            media = external / "external-evidence.jpg"
            media.write_bytes(b"image")
            registry = MediaRegistry(external / "registry.sqlite3", external)
            with patch.object(workbench_server, "WORKBENCH_DIR", external), patch.object(
                workbench_server, "PUBLIC_WORKBENCH_MEDIA_REGISTRY", registry
            ):
                url = workbench_server._media_url(media)
                response = self.client.get(url)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"image")

    def test_health_declares_inline_frame_transport_without_supplier_file_uri_dependency(self) -> None:
        payload = workbench_server.health()
        transport = payload["model_media_transport"]

        self.assertEqual(transport["mode"], "inline_base64_images")
        self.assertIs(transport["supplier_file_uri_required"], False)
        self.assertIn("image/webp", transport["accepted_model_media_types"])

    def test_technical_processing_incomplete_is_completed_transport_with_system_retry(self) -> None:
        self.assertTrue(workbench_server._structured_review_ok({
            "predicted_label": "review",
            "confidence": None,
            "processing_status": "technical_processing_incomplete",
            "system_action": "system_retry",
        }))
        self.assertFalse(workbench_server._structured_review_ok({
            "predicted_label": "review",
            "confidence": None,
        }))

    def test_minor_material_public_parsed_uses_strict_whitelist_and_redacts_identifiers(self) -> None:
        parsed = {
            "predicted_label": "review",
            "confidence": 0.66,
            "processing_status": "technical_processing_incomplete",
            "system_action": "system_retry",
            "overall_audit": {
                "conclusion": "联系 18012345678，证件 320000200801011234",
                "confidence": 0.66,
                "unknown_nested": "不得公开",
            },
            "minor_material_assessment": {
                "readiness": "needs_human_gap_confirmation",
                "processing_status": "technical_processing_incomplete",
                "system_action": "system_retry",
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
                "authenticity_assessment": {
                    "severity": "warning",
                    "risk_score": 0.25,
                    "risk_percent": 25,
                    "blocks_visual_precheck": False,
                    "evidence_image_indices": [3],
                    "missing_exif_image_indices": [4],
                    "unknown_exif_image_indices": [],
                    "conclusion": "缺少拍摄信息不等于图片造假。",
                    "boundary": "风险分数不是客观真伪概率。",
                    "raw_ocr": "18012345678",
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
        self.assertEqual(public_parsed["processing_status"], "technical_processing_incomplete")
        self.assertEqual(public_parsed["system_action"], "system_retry")
        self.assertEqual(
            public_parsed["minor_material_assessment"]["processing_status"],
            "technical_processing_incomplete",
        )
        self.assertEqual(public_parsed["minor_material_assessment"]["checklist"][0]["status"], "present")
        self.assertEqual(
            public_parsed["minor_material_assessment"]["checklist"][0]["quality_status"],
            "needs_manual_confirmation",
        )
        authenticity = public_parsed["minor_material_assessment"]["authenticity_assessment"]
        self.assertEqual(authenticity["risk_percent"], 25)
        self.assertEqual(authenticity["missing_exif_image_indices"], [4])
        self.assertNotIn("raw_ocr", authenticity)
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

    def test_health_fails_when_runtime_media_directory_is_not_writable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            blocked = Path(temp_dir) / "not-a-directory"
            blocked.write_text("blocked", encoding="ascii")
            with patch.object(workbench_server, "RUNTIME_MEDIA_DIR", blocked):
                payload = workbench_server.health()

        self.assertFalse(payload["ok"])
        self.assertFalse(payload["runtime_media_storage"]["ready"])

    def test_health_declares_on_demand_product_reference_boundary(self) -> None:
        payload = workbench_server.health()
        capability = payload["official_product_references"]

        self.assertEqual(capability["mode"], "per_review_on_demand")
        self.assertIs(capability["bulk_download_enabled"], False)
        self.assertEqual(capability["model_transport"], "compressed_inline_image")


if __name__ == "__main__":
    unittest.main()
