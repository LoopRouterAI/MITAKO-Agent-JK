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
        self.assertIn('"independent_payment_min_age":10', workbench)
        self.assertIn("申请时未满 10 周岁会加强核对支付密码来源和监护人发现消费过程", workbench)
        self.assertIn("高置信未满 9 周岁时要求人工重点核对独立支付能力", workbench)
        self.assertIn("年龄本身不决定退款或支持结论", workbench)
        self.assertIn("开始审核未成年人资料", workbench)
        self.assertNotIn("开始审核资料材料", workbench)
        self.assertIn("标准视觉初审（默认，不依赖外部接口）", workbench)
        self.assertNotIn("始终VIP客服终审", workbench)
        self.assertNotIn("最终结论必须由VIP客服复核确认", workbench)

    def test_workbench_exposes_four_independent_business_scenarios(self) -> None:
        workbench = workbench_server.INDEX_HTML.read_text(encoding="utf-8")

        for scenario in ("product_damage", "wrong_item", "missing_item", "minor_material"):
            self.assertIn(f'data-scenario="{scenario}"', workbench)
        self.assertIn("4 条业务入口", workbench)
        self.assertNotIn("入口 01 / 开箱与发错货", workbench)
        self.assertEqual(self.client.get("/wrong-item").status_code, 200)
        self.assertEqual(self.client.get("/missing-item").status_code, 200)

    def test_workbench_batch_api_preserves_wrong_and_missing_business_scenarios(self) -> None:
        scenarios = {
            "wrong_item": "video_unboxing",
            "missing_item": "video_unboxing",
            "minor_refund": "minor_material",
        }
        for business_scenario, technical_scenario in scenarios.items():
            with self.subTest(business_scenario=business_scenario), patch.object(
                workbench_server,
                "_group_batch_folder_uploads",
                return_value={"case-1": [object()]},
            ), patch.object(
                workbench_server,
                "_save_folder_uploads",
                return_value=(Path("case"), {"accepted_count": 1}),
            ), patch.object(
                workbench_server,
                "_run_folder_agent_review",
                return_value={"ok": True, "review": {"summary": {"review_status": "completed"}}},
            ) as run_review:
                response = self.client.post(
                    "/api/review-folders-batch",
                    data={
                        "scenario": business_scenario,
                    },
                    files={"files": ("evidence.jpg", b"image", "image/jpeg")},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(run_review.call_args.args[1], technical_scenario)
                self.assertEqual(run_review.call_args.args[3]["business_scenario"], business_scenario)

    def test_review_scenario_normalization_rejects_conflicting_business_context(self) -> None:
        self.assertEqual(
            workbench_server._normalize_review_scenario("video_unboxing", "wrong_item"),
            ("video_unboxing", "wrong_item"),
        )
        self.assertEqual(
            workbench_server._normalize_review_scenario("video_unboxing", "missing_item"),
            ("video_unboxing", "missing_item"),
        )
        self.assertEqual(
            workbench_server._normalize_review_scenario("minor_material", "minor_refund"),
            ("minor_material", "minor_refund"),
        )

        response = self.client.post(
            "/api/review-folder",
            data={"scenario": "product_damage", "business_scenario": "missing_item"},
            files={"files": ("evidence.jpg", b"image", "image/jpeg")},
        )

        self.assertEqual(response.status_code, 422)

    def test_sample_api_preserves_business_scenario(self) -> None:
        with patch.object(
            workbench_server,
            "_run_sample_agent_review",
            return_value={"ok": True, "review": {"summary": {"review_status": "completed"}}},
        ) as run_review:
            response = self.client.post(
                "/api/review-sample",
                json={
                    "sample_id": "sample_001",
                    "scenario": "video_unboxing",
                    "business_scenario": "wrong_item",
                    "model_key": "auto",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(run_review.call_args.args[3], "wrong_item")

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
                "video_deduplication": {
                    "submitted_count": 2,
                    "unique_count": 1,
                    "duplicate_count": 1,
                    "duplicates": [{
                        "kept": "customer-real-name.mp4",
                        "ignored": "customer-copy.mp4",
                        "sha256": "secret-hash",
                    }],
                },
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
            dedupe = response["agent_report"]["evidence_package"]["video_deduplication"]
            self.assertEqual(dedupe, {"submitted_count": 2, "unique_count": 1, "duplicate_count": 1})
            self.assertNotIn("secret-hash", str(response["agent_report"]))

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

    def test_registered_root_runtime_media_remains_available(self) -> None:
        root_tmp = workbench_server.ROOT / "tmp"
        root_tmp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root_tmp) as temp_dir:
            media = Path(temp_dir) / "report-evidence.jpg"
            media.write_bytes(b"image")

            url = workbench_server._media_url(media)

            self._assert_signed(url)
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

    def test_health_declares_adaptive_native_video_and_frame_transport(self) -> None:
        payload = workbench_server.health()
        transport = payload["model_media_transport"]

        self.assertEqual(transport["mode"], "adaptive_native_video_or_inline_frames")
        self.assertIs(transport["supplier_file_uri_required"], False)
        self.assertIn("image/webp", transport["accepted_model_media_types"])
        self.assertIn("video/mp4", transport["accepted_model_media_types"])
        self.assertEqual(transport["native_video_max_unique_files"], 1)

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

    def test_product_damage_public_projection_preserves_speed_and_opening_review_facts(self) -> None:
        parsed = {
            "damage_causality_assessment": {
                "appearance_difference": "visible",
                "business_defect_qualification": "indeterminate",
                "supplemental_damage_presence": "confirmed",
                "special_product_rule": "required_but_not_quantified",
            },
            "video_audit_conclusion": {
                "playback_speed": "accelerated",
                "sampling_fps": 1.0,
                "speed_review_impact": {
                    "status": "uncertain",
                    "critical_evidence_observable": False,
                    "affected_review_items": ["opening_action"],
                    "evidence_refs": [{
                        "video_index": 1,
                        "global_frame_index": 2,
                        "timestamp": "00:01.00",
                    }],
                    "source": "segment_consensus",
                },
                "opening_video_compliance": {
                    "sealed_start": True,
                    "waybill_visible": False,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": None,
                    "validated_fields": ["waybill_visible"],
                    "result": "noncompliant",
                },
            },
            "internal_prompt": "不得公开",
        }

        projected = workbench_server._public_parsed(parsed, "product_damage")
        video = projected["video_audit_conclusion"]

        self.assertEqual(video["sampling_fps"], 1.0)
        self.assertEqual(video["speed_review_impact"]["status"], "uncertain")
        self.assertEqual(video["opening_video_compliance"]["waybill_visible"], False)
        self.assertEqual(video["opening_video_compliance"]["validated_fields"], ["waybill_visible"])
        self.assertEqual(
            projected["damage_causality_assessment"]["business_defect_qualification"],
            "indeterminate",
        )
        self.assertEqual(
            projected["damage_causality_assessment"]["supplemental_damage_presence"],
            "confirmed",
        )
        self.assertNotIn("internal_prompt", projected)

    def test_product_damage_public_projection_preserves_atomic_claim_facts(self) -> None:
        projected = workbench_server._public_parsed({
            "claim_fact_assessment": {
                "atomic_claim_results": [{
                    "claim_id": "CLM-1",
                    "subject_ref": "SKU-1",
                    "support_status": "supported",
                    "evidence_refs": [{"video_index": 1, "global_frame_index": 8}],
                    "reason": "争议部位可见。",
                    "internal_chain": "不得公开",
                }],
                "order_linkage": {
                    "status": "verified",
                    "expected_package_fact": "极兔",
                    "observed_package_fact": "极兔",
                    "reason": "包裹一致。",
                },
                "scene_match": {"status": "matched", "claimed_scene": "product_damage"},
                "assembly": {
                    "state": "not_applicable",
                    "reassembly_result": "not_tested",
                    "permanent_damage": "insufficient",
                },
            },
        }, "product_damage")

        claim_facts = projected["claim_fact_assessment"]
        self.assertEqual(claim_facts["atomic_claim_results"][0]["subject_ref"], "SKU-1")
        self.assertEqual(claim_facts["order_linkage"]["status"], "verified")
        self.assertNotIn("internal_chain", claim_facts["atomic_claim_results"][0])

    def test_product_damage_public_projection_preserves_opening_field_refs(self) -> None:
        projected = workbench_server._public_parsed({
            "video_audit_conclusion": {
                "opening_video_compliance": {
                    "sealed_start": True,
                    "waybill_visible": False,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": False,
                    "source": "opening_compliance_verification",
                    "validated_fields": ["waybill_visible"],
                    "evidence_refs": [{
                        "field": "waybill_visible",
                        "video_index": 9,
                        "global_frame_index": 35,
                        "timestamp": "00:00.00",
                    }],
                },
            },
        }, "product_damage")

        reference = projected["video_audit_conclusion"]["opening_video_compliance"]["evidence_refs"][0]
        self.assertEqual(reference["field"], "waybill_visible")

    def test_fulfillment_public_projection_preserves_trusted_warehouse_basis(self) -> None:
        projected = workbench_server._public_parsed({
            "fulfillment_reconciliation": {
                "resolution_basis": "warehouse_verification",
                "evidence_sufficiency": "sufficient",
                "warehouse_verification": {
                    "status": "confirmed_not_missing",
                    "source": "customer_warehouse",
                    "verification_ref": "WH-CHECK-1",
                },
                "suspected_missing_items": [],
                "internal_note": "不得公开",
            },
        }, "missing_item")

        fulfillment = projected["fulfillment_reconciliation"]
        self.assertEqual(fulfillment["resolution_basis"], "warehouse_verification")
        self.assertEqual(fulfillment["warehouse_verification"]["status"], "confirmed_not_missing")
        self.assertEqual(fulfillment["warehouse_verification"]["verification_ref"], "WH-CHECK-1")
        self.assertNotIn("internal_note", fulfillment)

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
                "material_inventory": [{
                    "image_index": 1,
                    "asset_ref": "supplemental_image_1",
                    "document_type": "passport",
                    "document_types": ["passport"],
                    "subject_role": "minor",
                    "document_side": "page",
                    "issuing_country_or_region": "中国",
                    "readability": "clear",
                    "quality_issues": ["blur"],
                    "ocr_text": "张三 320000200801011234",
                    "passport_number": "E12345678",
                }],
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
                    "checks": [{
                        "check_id": "identity_age",
                        "relationship_evidence_type": "not_applicable",
                        "status": "mismatched",
                        "payment_capability_risk": "high",
                    }],
                    "unknown": "不得公开",
                },
                "required_materials": ["请补充说明未成年人如何获得或得知支付密码。"],
                "payment_capability_risk": {
                    "level": "high",
                    "effect": "需补充支付过程说明，不自动决定退款。",
                    "evidence_image_indices": [1],
                    "under_nine": True,
                    "age_confidence": "high",
                    "requires_review": False,
                    "requires_more_material": True,
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
        passport = public_parsed["minor_material_assessment"]["material_inventory"][0]
        self.assertEqual(passport, {
            "image_index": 1,
            "asset_ref": "supplemental_image_1",
            "document_type": "passport",
            "subject_role": "minor",
            "document_side": "page",
            "issuing_country_or_region": "中国",
            "readability": "clear",
            "quality_issues": ["blur"],
        })
        authenticity = public_parsed["minor_material_assessment"]["authenticity_assessment"]
        self.assertEqual(authenticity["risk_percent"], 25)
        self.assertEqual(authenticity["missing_exif_image_indices"], [4])
        self.assertNotIn("raw_ocr", authenticity)
        assessment = public_parsed["minor_material_assessment"]
        self.assertEqual(assessment["required_materials"], ["请补充说明未成年人如何获得或得知支付密码。"])
        self.assertEqual(assessment["payment_capability_risk"]["level"], "high")
        self.assertTrue(assessment["payment_capability_risk"]["under_nine"])
        self.assertEqual(assessment["payment_capability_risk"]["age_confidence"], "high")
        self.assertFalse(assessment["payment_capability_risk"]["requires_review"])
        self.assertTrue(assessment["payment_capability_risk"]["requires_more_material"])
        self.assertEqual(
            assessment["field_consistency"]["checks"][0]["payment_capability_risk"],
            "high",
        )
        self.assertEqual(
            assessment["field_consistency"]["checks"][0]["relationship_evidence_type"],
            "not_applicable",
        )
        for forbidden in (
            "unknown_top_level",
            "unknown_nested",
            "unknown_assessment",
            "unknown_item",
            "ocr_text",
            "raw_value",
            "passport_number",
            "18012345678",
            "320000200801011234",
            "model_limitations",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_health_does_not_expose_schema_placeholders(self) -> None:
        health = self.client.get("/api/health").json()

        self.assertNotIn("payment_capability_risk", health)

    def test_other_scenarios_use_strict_public_dto_and_redact_identifiers(self) -> None:
        parsed = {
            "predicted_label": "positive",
            "confidence": 0.9,
            "customer_phone": "18012345678",
            "custom_business_field": {"address": "上海市某路1号"},
            "supporting_evidence": [{"source_type": "image", "fact": "联系电话 18012345678"}],
            "decision_policy_audit": {
                "rule_id": "PD-N-NONCOMPLIANT-OPENING-VIDEO",
                "evidence_verdict_before_policy": {
                    "predicted_label": "positive",
                    "confidence": 0.65,
                    "conclusion": "视频事实层发现疑似损伤。",
                    "internal_prompt": "不得公开",
                },
            },
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
        before_policy = payload["parsed"]["decision_policy_audit"]["evidence_verdict_before_policy"]
        self.assertEqual(before_policy["predicted_label"], "positive")
        self.assertNotIn("internal_prompt", before_policy)

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

    def test_public_report_does_not_expose_raw_customer_media_urls(self) -> None:
        public = workbench_server._sanitize_public_report_data({
            "agent_report": {
                "scenario": "product_damage",
                "parsed": {"predicted_label": "review"},
                "media_gallery": {
                    "videos": [{"video_index": 1, "url": "/media-item/raw-video"}],
                    "frames": [{
                        "global_frame_index": 1,
                        "url": "/media-item/raw-frame",
                        "video_url": "/media-item/raw-video#t=1",
                    }],
                    "images": [{"image_index": 1, "url": "/media-item/raw-waybill"}],
                    "official_references": [{"reference_index": 1, "url": "/media-item/official"}],
                },
            },
        })

        gallery = public["agent_report"]["media_gallery"]
        self.assertTrue(gallery["restricted_original_evidence"])
        self.assertNotIn("url", gallery["videos"][0])
        self.assertNotIn("url", gallery["frames"][0])
        self.assertNotIn("video_url", gallery["frames"][0])
        self.assertNotIn("url", gallery["images"][0])
        self.assertIn("url", gallery["official_references"][0])

    def test_redaction_preserves_opaque_media_url_that_resembles_identifier(self) -> None:
        url = (
            "/media-item/a988c0e7f6f72ff030325199142651e3"
            "?expires=1786210503&sig=6c5a5cbba18afdb4fc3e07656b7a2b8560f6520dc79d362b4fd4173076d8a15f"
        )

        self.assertEqual(workbench_server._redact_minor_identifiers(url), url)

    def test_public_report_strips_local_paths_embedded_after_punctuation(self) -> None:
        private_path = r"D:\private\case.mp4"

        public = workbench_server._sanitize_public_report_data({
            "agent_report": {
                "scenario": "product_damage",
                "parsed": {
                    "supporting_evidence": [{"fact": f"证据来源={private_path}"}],
                },
            },
        })

        self.assertNotIn(private_path, json.dumps(public, ensure_ascii=False))

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

    def test_workbench_policy_keeps_verified_unsealed_start_before_public_projection(self) -> None:
        with tempfile.TemporaryDirectory(dir=workbench_server.WORKBENCH_DIR) as temp_dir:
            sample_dir = Path(temp_dir)
            video = sample_dir / "opening.mp4"
            video.write_bytes(b"video")
            case = {
                "case_id": "damage-unsealed-start",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "customer_claim": "商品开箱后发现损伤",
                "videos": [{"video_index": 1, "file": str(video)}],
                "frames": [],
                "supplemental_images": [],
                "structured_business_context": {"business_scenario": "product_damage"},
            }
            parsed = {
                "predicted_label": "positive",
                "confidence": 0.65,
                "overall_audit": {"conclusion": "可见商品损伤。"},
                "object_continuity_assessment": {"continuity_verdict": "continuous"},
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "claim_support": "supported",
                },
                "video_audit_conclusion": {
                    "opening_video_compliance": {
                        "sealed_start": False,
                        "waybill_visible": True,
                        "single_take_continuity": True,
                        "field_sources": {"sealed_start": "opening_start_verification"},
                        "validated_fields": ["sealed_start"],
                        "evidence_refs": [{
                            "field": "sealed_start",
                            "video_index": 1,
                            "global_frame_index": 1,
                            "timestamp": "00:00.00",
                        }],
                    },
                },
            }
            with patch.object(workbench_server, "score_result", return_value={}), patch.object(
                workbench_server,
                "inspect_job_media",
                return_value={"status": "completed", "summary": {"risk_level": "none"}},
            ):
                response = workbench_server._agent_report_response(
                    case,
                    sample_dir,
                    {"status": "success", "parsed": parsed},
                    "unsealed",
                    include_html_report=False,
                )

        projected = response["agent_report"]["parsed"]
        self.assertEqual(projected["predicted_label"], "negative")
        self.assertEqual(
            projected["decision_policy_audit"]["rule_id"],
            "PD-N-NONCOMPLIANT-OPENING-VIDEO",
        )

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
