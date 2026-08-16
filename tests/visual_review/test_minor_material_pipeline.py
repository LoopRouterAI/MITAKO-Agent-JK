# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import html
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from poc.visual_review_poc.minor_material_pipeline import (
    _checklist,
    _consistency_image_jobs,
    _normalize_consistency_checks,
    aggregate_minor_material_results,
    run_minor_material_pipeline,
)
from poc.visual_review_poc.local_video_triage_demo import image_meta
from poc.visual_review_poc.minor_material_model_prompt import (
    build_minor_material_consistency_prompt,
    build_minor_material_inventory_prompt,
)
from poc.visual_review_poc.review_model_prompt import build_selection_prompt
from poc.visual_review_poc.report_assessment_sections import render_minor_material_panel
from review_service.schemas import ReviewCaseMetadata


def _image(index: int) -> dict:
    return {
        "image_index": index,
        "api_path": __file__,
        "api_mime_type": "image/jpeg",
        "width": 1600,
        "height": 1200,
        "has_exif": False,
    }


def _frame(index: int) -> dict:
    return {
        "video_index": 1,
        "global_frame_index": index,
        "timestamp": f"00:{index:02d}.00",
        "api_path": __file__,
        "api_mime_type": "image/jpeg",
    }


def _case(image_count: int = 20, frame_count: int = 3) -> dict:
    return {
        "case_id": "blind-case",
        "scenario": "minor_material",
        "scenario_label": "未成年人退款资料审核",
        "customer_claim": "申请退款",
        "order_context": {"created_at": "2026-08-01"},
        "evidence_assets": [
            {"file": f"asset_{index:03d}.jpg", "status": "downloaded"}
            for index in range(1, image_count + 1)
        ],
        "structured_business_context": {"business_scenario": "minor_refund"},
        "supplemental_images": [_image(index) for index in range(1, image_count + 1)],
        "frames": [_frame(index) for index in range(1, frame_count + 1)],
        "videos": [{"video_index": 1, "duration_seconds": 3}],
        "model_frames_per_call": 24,
    }


def _observation(index: int) -> dict:
    mapping = {
        1: ("identity_card", "guardian", "front"),
        2: ("identity_card", "guardian", "back"),
        3: ("identity_card", "minor", "front"),
        4: ("identity_card", "minor", "back"),
        5: ("household_register", "not_applicable", "page"),
        7: ("signed_commitment", "not_applicable", "page"),
        8: ("order_payment_proof", "not_applicable", "page"),
        16: ("carrier_invoice", "guardian", "page"),
        18: ("birth_certificate", "not_applicable", "page"),
    }
    document_type, role, side = mapping.get(index, ("other", "not_applicable", "page"))
    observation = {
        "image_index": index,
        "asset_ref": f"supplemental_image_{index}",
        "document_types": [document_type],
        "subject_role": role,
        "document_side": side,
        "readability": "clear",
        "document_state": "filled" if document_type != "other" else "unknown",
        "sop_eligibility": "valid" if document_type != "other" else "unknown",
        "editing_evidence": [],
        "quality_issues": [],
        "document_box_2d": [100, 100, 900, 900],
        "ocr_text": "不应进入聚合结果的个人信息 18012345678 320000200801011234",
    }
    if document_type == "order_payment_proof":
        observation["order_payment_evidence_type"] = "combined"
        observation["application_scope_coverage"] = "complete"
    return observation


def _order_payment_observation(index: int, evidence_type: str) -> dict:
    observation = _observation(8)
    observation.update({
        "image_index": index,
        "asset_ref": f"supplemental_image_{index}",
        "order_payment_evidence_type": evidence_type,
        "application_scope_coverage": "complete",
    })
    return observation


def _consistency_result(check_id: str, status: str = "matched") -> dict:
    fields = {
        "identity_age": [
            "guardian_identity", "minor_identity", "age_eligibility",
            "payment_password_access", "guardian_discovery_process",
        ],
        "guardian_relationship": [
            "guardian_identity", "minor_identity", "relationship_document_linkage",
            "explicit_relationship_entry", "relationship_link", "applicant_guardian_role",
        ],
        "commitment_signatures": [
            "guardian_signer", "minor_signer", "signature_presence", "signature_method", "field_alignment",
            "commitment_content", "refund_scope", "recipient_information", "signed_date",
            "account_bound_phone", "account_nickname", "consumption_time_range",
            "refund_amount", "refund_method", "payment_recipient",
        ],
        "order_payment": [
            "order_reference", "order_item_scope", "item_quantity", "order_status",
            "payer_identity", "payment_status", "transaction_time", "amount",
            "merchant_identity", "transaction_id", "merchant_order_id",
            "transaction_scope", "commitment_amount",
        ],
        "mobile_realname": [
            "subscriber_identity", "account_mobile", "invoice_identity", "invoice_phone",
            "number_status", "ownership_proof", "guardian_phone_holder",
        ],
    }[check_id]
    return {
        "status": "success",
        "parsed": {
            "coverage_ack": {"expected_image_indices": [1, 3], "observed_image_indices": [1, 3]},
            "consistency_check": {
                "check_id": check_id,
                "relationship_evidence_type": (
                    "birth_certificate" if check_id == "guardian_relationship" else "not_applicable"
                ),
                "minor_birth_date_iso": "2010-01-01" if check_id == "identity_age" else None,
                "age_band": "10_to_17" if check_id == "identity_age" else "unknown",
                "low_age": False if check_id == "identity_age" else None,
                "under_nine": False if check_id == "identity_age" else None,
                "age_confidence": "high" if check_id == "identity_age" else "unknown",
                "payment_capability_risk": "none",
                "relationship_document_groups": [],
                "field_results": [{
                    "field_name": field_name,
                    "status": status,
                    "visibility": "complete",
                    "evidence_image_indices": [1, 3],
                } for field_name in fields],
                "tamper_risk": "low",
                "risk_reason_codes": [],
                "raw_value": "18012345678 320000200801011234",
            }
        },
        "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        "cost": {"estimated_usd": 0.002},
        "latency_seconds": 0.2,
    }


class MinorMaterialPipelineTest(unittest.TestCase):

    def test_consistency_stage_uses_original_image_detail_crop(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.png"
            Image.new("RGB", (4000, 3000), (120, 180, 220)).save(source)
            prepared = root / "prepared.webp"
            Image.new("RGB", (2560, 1920), (120, 180, 220)).save(prepared)
            case = _case(image_count=1, frame_count=0)
            case["supplemental_images"] = [{
                **_image(1),
                "path": source,
                "api_path": str(prepared),
                "api_mime_type": "image/webp",
            }]
            consistency_paths = []
            detail_contexts = []

            def invoke(batch_case: dict) -> dict:
                mode = batch_case["structured_business_context"]["analysis_mode"]
                if mode == "minor_material_inventory":
                    return {"status": "success", "parsed": {"material_observations": [_observation(1)]}}
                consistency_paths.extend(item["api_path"] for item in batch_case["supplemental_images"])
                detail_contexts.extend(
                    batch_case["structured_business_context"]["minor_consistency_check"]["material_context"]
                )
                return _consistency_result(
                    batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
                )

            result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

            self.assertTrue(consistency_paths)
            self.assertTrue(all("detail_crops" in path for path in consistency_paths))
            self.assertTrue(any(item["detail_crop_applied"] is True for item in detail_contexts))
            self.assertEqual(result["chunking"]["document_detail_crop_count"], 1)

    def test_consistency_stage_skips_irrelevant_images_before_detail_crop(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.png"
            prepared = root / "prepared.webp"
            Image.new("RGB", (4000, 3000), (120, 180, 220)).save(source)
            Image.new("RGB", (2560, 1920), (120, 180, 220)).save(prepared)
            case = _case(image_count=2, frame_count=0)
            case["supplemental_images"] = [
                {
                    **_image(index),
                    "path": source,
                    "api_path": str(prepared),
                    "api_mime_type": "image/webp",
                }
                for index in (1, 2)
            ]
            consistency_indices = []

            def invoke(batch_case: dict) -> dict:
                mode = batch_case["structured_business_context"]["analysis_mode"]
                if mode == "minor_material_inventory":
                    irrelevant = {
                        **_observation(2),
                        "document_types": ["other"],
                        "subject_role": "not_applicable",
                        "document_state": "unknown",
                        "sop_eligibility": "unknown",
                    }
                    return {
                        "status": "success",
                        "parsed": {"material_observations": [_observation(1), irrelevant]},
                    }
                consistency_indices.extend(
                    int(item["image_index"])
                    for item in batch_case["supplemental_images"]
                )
                return _consistency_result(
                    batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
                )

            result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

            self.assertNotIn(2, consistency_indices)
            self.assertEqual(result["chunking"]["document_detail_crop_count"], 1)

    def test_pipeline_preserves_consistent_model_request_profile(self) -> None:
        case = _case(image_count=1, frame_count=0)
        profile = {
            "provider": "gemini_native",
            "model": "gemini-3.5-flash-lite",
            "thinking_level": "high",
            "media_resolution": "high",
            "max_output_tokens": "provider_default",
            "native_video_count": 0,
            "sampling_fps": None,
            "transport": "none",
        }

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            if mode == "minor_material_inventory":
                parsed = {"material_observations": [_observation(1)]}
            else:
                parsed = _consistency_result(
                    batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
                )["parsed"]
            return {
                "status": "success",
                "parsed": parsed,
                "request_profile": dict(profile),
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(result["request_profile"], profile)
    def test_combined_order_payment_proof_remains_present_when_authoritative_use_is_limited(self) -> None:
        combined_proof = _observation(8)
        combined_proof["order_payment_evidence_type"] = "combined"
        combined_proof["sop_eligibility"] = "supporting_only"

        row = next(
            item for item in _checklist([combined_proof], True)
            if item["requirement_id"] == "payment"
        )

        self.assertEqual(row["status"], "present")
        self.assertEqual(row["quality_status"], "needs_manual_confirmation")

    def test_order_page_without_payment_record_does_not_satisfy_order_payment_requirement(self) -> None:
        order_page = _order_payment_observation(8, "order")

        row = next(
            item for item in _checklist([order_page], True)
            if item["requirement_id"] == "payment"
        )

        self.assertEqual(row["status"], "not_observed_after_full_scan")
        self.assertIn("订单材料和支付材料", row["rule_note"])

    def test_payment_record_without_order_page_does_not_satisfy_order_payment_requirement(self) -> None:
        payment_record = _order_payment_observation(8, "payment")

        row = next(
            item for item in _checklist([payment_record], True)
            if item["requirement_id"] == "payment"
        )

        self.assertEqual(row["status"], "not_observed_after_full_scan")
        self.assertIn("订单材料和支付材料", row["rule_note"])

    def test_order_and_payment_records_together_satisfy_order_payment_requirement(self) -> None:
        order_page = _order_payment_observation(8, "order")
        payment_record = _order_payment_observation(9, "payment")

        row = next(
            item for item in _checklist([order_page, payment_record], True)
            if item["requirement_id"] == "payment"
        )

        self.assertEqual(row["status"], "present")
        self.assertEqual(row["quality_status"], "usable")

    def test_partial_payment_coverage_does_not_satisfy_application_scope(self) -> None:
        order_page = _order_payment_observation(8, "order")
        payment_record = _order_payment_observation(9, "payment")
        payment_record["application_scope_coverage"] = "partial"

        row = next(
            item for item in _checklist([order_page, payment_record], True)
            if item["requirement_id"] == "payment"
        )

        self.assertEqual(row["status"], "not_observed_after_full_scan")
        self.assertIn("覆盖申请范围", row["rule_note"])

    def test_combined_order_payment_record_satisfies_both_required_sources(self) -> None:
        combined_record = _order_payment_observation(8, "combined")

        row = next(
            item for item in _checklist([combined_record], True)
            if item["requirement_id"] == "payment"
        )

        self.assertEqual(row["status"], "present")
        self.assertEqual(row["quality_status"], "usable")

    def test_minor_sop_prompt_covers_field_level_business_rules(self) -> None:
        metadata = ReviewCaseMetadata.model_validate({
            "client_case_id": "MINOR-SOP-GUIDE",
            "scenario": "minor_refund",
        })
        self.assertFalse(hasattr(metadata.minor_refund_policy, "independent_payment_min_age"))

        case = {
            "supplemental_images": [{"image_index": 1}],
            "structured_business_context": {
                "minor_refund_policy": metadata.minor_refund_policy.model_dump(mode="json"),
                "minor_consistency_check": {
                    "check_id": "identity_age",
                    "expected_image_indices": [1],
                },
            },
        }
        inventory_prompt = build_minor_material_inventory_prompt(case)
        consistency_prompt = build_minor_material_consistency_prompt(case)

        for rule in (
            "仅允许遮挡住址门牌号和身份证号后三位",
            "密集水印",
            "哥哥或姐姐不是法定监护人",
            "电脑录入姓名不能视为亲笔签名",
            "金额与订单可退款范围一致",
            "支付截图不能替代手机号实名归属证明",
            "销户或原号码归属证明",
            "红色填写说明",
            "样本水印",
            "order_payment_evidence_type",
            "application_scope_coverage",
            "不得根据文件名",
            "只有订单页或只有支付页都不齐全",
        ):
            self.assertIn(rule, inventory_prompt)
        for rule in (
            "低于 10 周岁",
            "payment_password_access",
            "guardian_discovery_process",
            "如何获得或得知支付密码",
            "监护人如何、何时发现消费",
            "未满 9 周岁且年龄证据为高置信",
            "空白签字栏",
            "打印或电脑录入的姓名",
            "两本户口本",
            "relationship_link 必须为 uncertain",
            "每张关系材料按可见户号",
            "relationship_document_linkage",
            "explicit_relationship_entry",
            "account_bound_phone",
            "account_nickname",
            "consumption_time_range",
            "refund_method",
            "payment_status",
            "transaction_time",
            "merchant_identity",
            "transaction_id",
            "merchant_order_id",
            "订单材料和支付材料必须分别出现",
            "明确的跨来源金额或主体冲突才输出 mismatched",
        ):
            self.assertIn(rule, consistency_prompt)
        self.assertIn("盖章的合法监护证明", inventory_prompt)
        self.assertIn("主副卡关系证明", inventory_prompt)
        self.assertIn("销户或原号码归属证明", inventory_prompt)

    def test_field_level_minor_anomalies_return_specific_required_materials(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]

        field_statuses = {
            "applicant_guardian_role": "mismatched",
            "signature_method": "mismatched",
            "field_alignment": "mismatched",
            "commitment_amount": "mismatched",
            "invoice_phone": "uncertain",
            "number_status": "uncertain",
            "ownership_proof": "uncertain",
        }
        for check in checks:
            for field in check["parsed"]["consistency_check"]["field_results"]:
                if field["field_name"] in field_statuses:
                    field["status"] = field_statuses[field["field_name"]]
        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        required = "；".join(parsed["minor_material_assessment"]["required_materials"])

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["system_yes_no"], "REVIEW")
        self.assertIn("非法定监护人", required)
        self.assertIn("双方亲笔签名", required)
        self.assertIn("字段填写位置正确", required)
        self.assertIn("金额与订单可退款范围一致", required)
        self.assertIn("显示平台绑定业务手机号", required)
        self.assertIn("核验号码当前状态", required)
        self.assertIn("支付截图不能替代手机号实名归属材料", required)
        self.assertNotIn("号码已注销时", required)

    def test_normal_payment_capability_does_not_request_low_age_process_details(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        identity = next(
            check for check in checks
            if check["parsed"]["consistency_check"]["check_id"] == "identity_age"
        )["parsed"]["consistency_check"]
        identity["payment_capability_risk"] = "none"
        for field in identity["field_results"]:
            if field["field_name"] in {"payment_password_access", "guardian_discovery_process"}:
                field["status"] = "uncertain"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        required = "；".join(parsed["minor_material_assessment"]["required_materials"])

        self.assertNotIn("支付密码", required)
        self.assertNotIn("发现消费", required)

    def test_exif_editor_software_is_an_orange_risk_signal_not_fraud_proof(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "edited.jpg"
            exif = Image.Exif()
            exif[305] = "Adobe Photoshop 25.0"
            Image.new("RGB", (16, 16), "white").save(path, exif=exif)

            metadata = image_meta(path)

        self.assertTrue(metadata["has_exif"])
        self.assertTrue(metadata["editor_metadata_present"])
        self.assertIn("Adobe Photoshop", metadata["exif_software"])

    def test_two_household_books_without_direct_relationship_link_request_specific_proof(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        relationship = next(
            item for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "guardian_relationship"
        )
        relationship["parsed"]["consistency_check"]["relationship_evidence_type"] = (
            "separate_household_books_without_bridge"
        )
        for field in relationship["parsed"]["consistency_check"]["field_results"]:
            if field["field_name"] == "relationship_link":
                field["status"] = "uncertain"
            elif field["field_name"] == "relationship_document_linkage":
                field["status"] = "mismatched"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertTrue(any("直接亲子或监护关系" in item for item in parsed["material_gaps"]))
        self.assertTrue(any(
            "直接亲子或监护关系" in item
            for item in parsed["minor_material_assessment"]["required_materials"]
        ))
        panel = render_minor_material_panel(
            parsed["minor_material_assessment"], lambda value: html.escape(str(value))
        )
        self.assertIn('status-card status-amber"><h3>监护关系证明', panel)
        self.assertIn("未建立直接监护关系，需补关系证明", panel)
        self.assertIn("同一本户口本直接关系页、出生证明或法定监护证明", panel)
        self.assertNotIn("visual_relationship_link_unresolved", panel)

    def test_separate_household_books_override_a_false_matched_relationship_link(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        relationship = next(
            item for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "guardian_relationship"
        )
        relationship["parsed"]["consistency_check"]["relationship_evidence_type"] = (
            "separate_household_books_without_bridge"
        )

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        relationship_check = next(
            item for item in parsed["minor_material_assessment"]["field_consistency"]["checks"]
            if item["check_id"] == "guardian_relationship"
        )
        relationship_link = next(
            item for item in relationship_check["field_results"]
            if item["field_name"] == "relationship_link"
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(relationship_check["relationship_evidence_type"], "separate_household_books_without_bridge")
        self.assertEqual(relationship_link["status"], "uncertain")
        self.assertTrue(any("直接亲子或监护关系" in item for item in parsed["material_gaps"]))

    def test_uncertain_relationship_evidence_cannot_keep_a_matched_relationship_link(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        relationship = next(
            item for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "guardian_relationship"
        )
        relationship["parsed"]["consistency_check"]["relationship_evidence_type"] = "uncertain"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertTrue(any("直接亲子或监护关系" in item for item in parsed["material_gaps"]))

    def test_same_household_claim_requires_document_and_explicit_relationship_link(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        relationship = next(
            item for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "guardian_relationship"
        )
        relationship["parsed"]["consistency_check"]["relationship_evidence_type"] = "same_household_direct_link"
        linkage = next(
            item for item in relationship["parsed"]["consistency_check"]["field_results"]
            if item["field_name"] == "relationship_document_linkage"
        )
        linkage["status"] = "mismatched"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        relationship_check = next(
            item for item in parsed["minor_material_assessment"]["field_consistency"]["checks"]
            if item["check_id"] == "guardian_relationship"
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(
            relationship_check["relationship_evidence_type"],
            "separate_household_books_without_bridge",
        )
        self.assertTrue(any("直接亲子或监护关系" in item for item in parsed["material_gaps"]))

    def test_same_household_claim_requires_minor_and_guardian_pages_in_one_group(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        relationship = next(
            item for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "guardian_relationship"
        )
        relationship["parsed"]["consistency_check"].update({
            "relationship_evidence_type": "same_household_direct_link",
            "relationship_document_groups": [
                {
                    "image_index": 1,
                    "document_type": "household_register",
                    "subject_role": "minor",
                    "document_group": "group_1",
                },
                {
                    "image_index": 3,
                    "document_type": "household_register",
                    "subject_role": "guardian",
                    "document_group": "group_2",
                },
            ],
        })

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        relationship_check = next(
            item for item in parsed["minor_material_assessment"]["field_consistency"]["checks"]
            if item["check_id"] == "guardian_relationship"
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(
            relationship_check["relationship_evidence_type"],
            "separate_household_books_without_bridge",
        )
        self.assertTrue(any("直接亲子或监护关系" in item for item in parsed["material_gaps"]))

    def test_relationship_consistency_job_excludes_identity_cards(self) -> None:
        observations = [
            {"image_index": 1, "document_types": ["identity_card"], "subject_role": "guardian", "readability": "clear", "quality_issues": []},
            {"image_index": 2, "document_types": ["identity_card"], "subject_role": "minor", "readability": "clear", "quality_issues": []},
            {"image_index": 3, "document_types": ["household_register"], "subject_role": "minor", "readability": "clear", "quality_issues": []},
            {"image_index": 4, "document_types": ["household_register"], "subject_role": "guardian", "readability": "clear", "quality_issues": []},
        ]
        images = [{"image_index": index} for index in range(1, 5)]

        jobs = _consistency_image_jobs(observations, images)
        relationship_job = next(item for item in jobs if item["check_id"] == "guardian_relationship")

        self.assertEqual(
            [item["image_index"] for item in relationship_job["selected"]],
            [3, 4],
        )

    def test_under_ten_payment_process_gap_requests_material_without_forcing_human_review(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        identity = next(
            item for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "identity_age"
        )
        identity["parsed"]["consistency_check"]["low_age"] = True
        identity["parsed"]["consistency_check"]["age_band"] = "under_10"
        identity["parsed"]["consistency_check"]["minor_birth_date_iso"] = "2017-01-01"
        identity["parsed"]["consistency_check"]["payment_capability_risk"] = "high"
        for field in identity["parsed"]["consistency_check"]["field_results"]:
            if field["field_name"] in {"payment_password_access", "guardian_discovery_process"}:
                field["status"] = "uncertain"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        assessment = parsed["minor_material_assessment"]

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertFalse(parsed["human_required"])
        self.assertEqual(parsed["decision"], "request_more_material")
        self.assertTrue(assessment["payment_capability_risk"]["requires_more_material"])
        self.assertFalse(assessment["payment_capability_risk"]["requires_review"])
        required = "；".join(assessment["required_materials"])
        self.assertIn("如何获得或得知支付密码", required)
        self.assertIn("监护人如何、何时发现消费", required)

    def test_identity_requires_both_sides_for_guardian_and_minor(self) -> None:
        observations = [
            _observation(1),
            _observation(3),
            _observation(5),
        ]

        identity = next(
            item for item in _checklist(observations, True)
            if item["requirement_id"] == "identity"
        )

        self.assertEqual(identity["status"], "not_observed_after_full_scan")
        self.assertEqual(identity["quality_status"], "needs_manual_confirmation")

    def test_stamped_legal_guardianship_proof_reaches_relationship_check(self) -> None:
        images = [_image(1)]
        observations = [{
            "image_index": 1,
            "asset_ref": "supplemental_image_1",
            "document_type": "other",
            "document_types": ["other"],
            "subject_role": "not_applicable",
            "document_side": "multiple",
            "readability": "clear",
            "document_state": "filled",
            "sop_eligibility": "valid",
            "quality_issues": [],
        }]

        relationship = next(
            item for item in _checklist(observations, True)
            if item["requirement_id"] == "relationship"
        )
        job = next(
            item for item in _consistency_image_jobs(observations, images)
            if item["check_id"] == "guardian_relationship"
        )

        self.assertEqual(relationship["status"], "present")
        self.assertEqual([item["image_index"] for item in job["selected"]], [1])

    def test_official_phone_exception_proof_reaches_mobile_check(self) -> None:
        images = [_image(1)]
        observations = [{
            "image_index": 1,
            "asset_ref": "supplemental_image_1",
            "document_type": "other",
            "document_types": ["other"],
            "subject_role": "guardian",
            "document_side": "multiple",
            "readability": "clear",
            "document_state": "filled",
            "sop_eligibility": "valid",
            "quality_issues": [],
        }]

        job = next(
            item for item in _consistency_image_jobs(observations, images)
            if item["check_id"] == "mobile_realname"
        )

        self.assertEqual([item["image_index"] for item in job["selected"]], [1])

    def test_payment_process_statement_reaches_identity_age_check(self) -> None:
        images = [_image(1)]
        observations = [{
            "image_index": 1,
            "asset_ref": "supplemental_image_1",
            "document_type": "other",
            "document_types": ["other"],
            "subject_role": "not_applicable",
            "document_side": "page",
            "readability": "clear",
            "document_state": "filled",
            "sop_eligibility": "valid",
            "quality_issues": [],
        }]

        job = next(
            item for item in _consistency_image_jobs(observations, images)
            if item["check_id"] == "identity_age"
        )

        self.assertEqual([item["image_index"] for item in job["selected"]], [1])

    def test_order_payment_check_receives_commitment_for_amount_alignment(self) -> None:
        images = [_image(7), _image(8)]
        observations = [_observation(7), _observation(8)]

        job = next(
            item for item in _consistency_image_jobs(observations, images)
            if item["check_id"] == "order_payment"
        )

        self.assertEqual([item["image_index"] for item in job["selected"]], [8, 7])

    def test_uncertain_required_commitment_field_requests_specific_correction(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        commitment = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "commitment_signatures"
        )
        field = next(item for item in commitment["field_results"] if item["field_name"] == "account_nickname")
        field["status"] = "uncertain"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["decision"], "request_more_material")
        self.assertIn("账号昵称", "；".join(parsed["minor_material_assessment"]["required_materials"]))

    def test_typed_names_request_corrected_commitment_without_forcing_manual_review(self) -> None:
        parsed = self._aggregate_with_commitment_field_status("signature_method", "mismatched")

        self.assertEqual(parsed["decision"], "request_more_material")
        self.assertFalse(parsed["human_required"])
        self.assertIn("电脑录入姓名", "；".join(parsed["minor_material_assessment"]["required_materials"]))

    def test_single_signature_requests_corrected_commitment_without_forcing_manual_review(self) -> None:
        parsed = self._aggregate_with_commitment_field_status("signature_presence", "mismatched")

        self.assertEqual(parsed["decision"], "request_more_material")
        self.assertFalse(parsed["human_required"])
        self.assertIn("双方亲笔签名", "；".join(parsed["minor_material_assessment"]["required_materials"]))

    def test_missing_signed_date_requests_corrected_commitment_without_forcing_manual_review(self) -> None:
        parsed = self._aggregate_with_commitment_field_status("signed_date", "mismatched")

        self.assertEqual(parsed["decision"], "request_more_material")
        self.assertFalse(parsed["human_required"])
        self.assertIn("签署日期", "；".join(parsed["minor_material_assessment"]["required_materials"]))

    def test_cross_source_commitment_amount_conflict_still_requires_manual_review(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(
            list(range(1, 21)),
            {"parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}},
        )]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        order_payment = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "order_payment"
        )
        next(
            field for field in order_payment["field_results"]
            if field["field_name"] == "commitment_amount"
        )["status"] = "mismatched"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["decision"], "manual_review")
        self.assertTrue(parsed["human_required"])

    def _aggregate_with_commitment_field_status(self, field_name: str, status: str) -> dict:
        case = _case(image_count=20, frame_count=0)
        rows = [(
            list(range(1, 21)),
            {"parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}},
        )]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        commitment = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "commitment_signatures"
        )
        next(field for field in commitment["field_results"] if field["field_name"] == field_name)["status"] = status
        return aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

    def test_model_high_payment_risk_without_confirmed_low_age_does_not_request_material(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        for low_age in (False, None):
            with self.subTest(low_age=low_age):
                checks = [
                    _consistency_result(check_id)
                    for check_id in (
                        "identity_age", "guardian_relationship", "commitment_signatures",
                        "order_payment", "mobile_realname",
                    )
                ]
                identity = next(
                    item for item in checks
                    if item["parsed"]["consistency_check"]["check_id"] == "identity_age"
                )
                identity["parsed"]["consistency_check"]["low_age"] = low_age
                identity["parsed"]["consistency_check"]["payment_capability_risk"] = "high"
                for field in identity["parsed"]["consistency_check"]["field_results"]:
                    if field["field_name"] in {"payment_password_access", "guardian_discovery_process"}:
                        field["status"] = "uncertain"

                parsed = aggregate_minor_material_results(
                    case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
                )
                assessment = parsed["minor_material_assessment"]
                required = "；".join(assessment["required_materials"])

                self.assertFalse(assessment["payment_capability_risk"]["requires_more_material"])
                self.assertNotIn("支付密码", required)
                self.assertNotIn("如何、何时发现消费", required)
                panel = render_minor_material_panel(assessment, lambda value: html.escape(str(value)))
                self.assertNotIn("低龄支付过程核验", panel)
                self.assertNotIn("支付过程信息待确认", panel)

    def test_explicit_field_conflict_precedes_low_age_payment_process_gap(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        identity = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "identity_age"
        )
        identity["low_age"] = True
        identity["age_band"] = "under_10"
        identity["minor_birth_date_iso"] = "2017-01-01"
        identity["payment_capability_risk"] = "high"
        for field in identity["field_results"]:
            if field["field_name"] in {"payment_password_access", "guardian_discovery_process"}:
                field["status"] = "uncertain"
        commitment = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "commitment_signatures"
        )
        next(field for field in commitment["field_results"] if field["field_name"] == "guardian_signer")["status"] = "mismatched"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["system_yes_no"], "REVIEW")
        self.assertTrue(parsed["human_required"])
        self.assertIn("明确冲突", parsed["minor_material_assessment"]["conclusion"])
        self.assertIn("回看", parsed["next_step"])
        self.assertIn("支付密码来源", parsed["next_step"])
        self.assertNotIn("独立完成支付", parsed["minor_material_assessment"]["conclusion"])

    def test_commitment_guardian_conflict_invalidates_matched_applicant_guardian_role(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        commitment = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "commitment_signatures"
        )
        next(
            field for field in commitment["field_results"]
            if field["field_name"] == "guardian_signer"
        )["status"] = "mismatched"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        consistency = parsed["minor_material_assessment"]["field_consistency"]
        relationship = next(
            item for item in consistency["checks"]
            if item["check_id"] == "guardian_relationship"
        )
        applicant_role = next(
            field for field in relationship["field_results"]
            if field["field_name"] == "applicant_guardian_role"
        )

        self.assertEqual(relationship["status"], "mismatched")
        self.assertEqual(applicant_role["status"], "mismatched")
        self.assertEqual(consistency["verdict"], "mismatched")
        self.assertTrue(parsed["human_required"])

    def test_low_age_with_matched_payment_process_does_not_override_positive_material_result(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        identity = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "identity_age"
        )
        identity["low_age"] = True
        identity["age_band"] = "under_10"
        identity["minor_birth_date_iso"] = "2017-01-01"
        identity["payment_capability_risk"] = "high"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        risk = parsed["minor_material_assessment"]["payment_capability_risk"]

        self.assertEqual(parsed["predicted_label"], "positive")
        self.assertFalse(parsed["human_required"])
        self.assertTrue(risk["low_age"])
        self.assertFalse(risk["requires_review"])
        self.assertEqual(risk["process_evidence_status"], "matched")
        self.assertEqual(parsed["next_step"], "")

    def test_high_confidence_under_nine_requires_human_review_without_changing_fact_label(self) -> None:
        case = _case(image_count=20, frame_count=0)
        case["order_context"]["created_at"] = "2026-08-01"
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        identity = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "identity_age"
        )
        identity.update({
            "minor_birth_date_iso": "2018-01-01",
            "age_band": "under_10",
            "low_age": True,
            "under_nine": True,
            "age_confidence": "high",
            "payment_capability_risk": "none",
        })

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        risk = parsed["minor_material_assessment"]["payment_capability_risk"]

        self.assertEqual(parsed["predicted_label"], "positive")
        self.assertTrue(parsed["human_required"])
        self.assertTrue(risk["under_nine"])
        self.assertEqual(risk["age_confidence"], "high")
        self.assertTrue(risk["requires_review"])
        self.assertIn("未满 9 周岁", risk["effect"])

    def test_under_ten_process_gap_and_under_nine_attention_coexist(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        identity = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "identity_age"
        )
        identity.update({
            "minor_birth_date_iso": "2018-01-01",
            "age_band": "under_10",
            "low_age": True,
            "under_nine": True,
            "age_confidence": "high",
            "payment_capability_risk": "high",
        })
        for field in identity["field_results"]:
            if field["field_name"] in {"payment_password_access", "guardian_discovery_process"}:
                field["status"] = "uncertain"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        risk = parsed["minor_material_assessment"]["payment_capability_risk"]

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["system_yes_no"], "REVIEW")
        self.assertEqual(parsed["decision"], "request_more_material")
        self.assertTrue(parsed["human_required"])
        self.assertTrue(risk["requires_more_material"])
        self.assertTrue(risk["requires_review"])
        self.assertIn("同时", risk["effect"])

    def test_under_nine_without_high_confidence_does_not_force_human_review(self) -> None:
        case = _case(image_count=20, frame_count=0)
        case["order_context"]["created_at"] = "2026-08-01"
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        identity = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "identity_age"
        )
        identity.update({
            "minor_birth_date_iso": None,
            "age_band": "under_10",
            "low_age": True,
            "under_nine": True,
            "age_confidence": "low",
            "payment_capability_risk": "none",
        })

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        risk = parsed["minor_material_assessment"]["payment_capability_risk"]

        self.assertFalse(parsed["human_required"])
        self.assertFalse(risk["requires_review"])
        self.assertNotEqual(risk["age_confidence"], "high")

    def test_model_age_flags_cannot_override_program_date_calculation(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        identity = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "identity_age"
        )
        identity["age_band"] = "10_to_17"
        identity["low_age"] = True
        identity["payment_capability_risk"] = "high"
        for field in identity["field_results"]:
            if field["field_name"] in {"payment_password_access", "guardian_discovery_process"}:
                field["status"] = "uncertain"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        risk = parsed["minor_material_assessment"]["payment_capability_risk"]
        required = "；".join(parsed["minor_material_assessment"]["required_materials"])

        self.assertFalse(risk["low_age"])
        self.assertFalse(risk["requires_more_material"])
        self.assertNotIn("支付密码", required)

    def test_all_images_are_reviewed_in_batches_and_five_categories_are_present(self) -> None:
        case = _case()
        reviewed_image_indices = []
        consistency_checks = []
        consistency_contexts = {}

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            if mode == "minor_material_inventory":
                indices = [item["image_index"] for item in batch_case["supplemental_images"]]
                reviewed_image_indices.extend(indices)
                parsed = {
                    "material_observations": [_observation(index) for index in indices],
                    "coverage_ack": {
                        "expected_image_indices": indices,
                        "observed_image_indices": indices,
                    },
                }
            elif mode == "minor_material_process_video":
                frame = batch_case["frames"][0]
                parsed = {
                    "process_observations": [{
                        "video_index": frame["video_index"],
                        "global_frame_index": frame["global_frame_index"],
                        "timestamp": frame["timestamp"],
                        "asset_ref": "video_1_frame_1",
                        "process_type": "invoice_generation",
                        "evidence_quality": "clear",
                    }]
                }
            else:
                check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
                consistency_checks.append(check_id)
                consistency_contexts[check_id] = batch_case["structured_business_context"]["minor_consistency_check"].get("material_context")
                result = _consistency_result(check_id)
                indices = [item["image_index"] for item in batch_case["supplemental_images"]]
                result["parsed"]["coverage_ack"] = {
                    "expected_image_indices": indices,
                    "observed_image_indices": indices,
                }
                for field in result["parsed"]["consistency_check"]["field_results"]:
                    field["evidence_image_indices"] = indices[:2]
                return result
            return {
                "status": "success",
                "parsed": parsed,
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "latency_seconds": 0.1,
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=4)
        parsed = result["parsed"]
        assessment = parsed["minor_material_assessment"]

        self.assertEqual(sorted(reviewed_image_indices), list(range(1, 21)))
        self.assertEqual(parsed["predicted_label"], "positive")
        self.assertEqual(parsed["decision"], "visual_precheck_passed")
        self.assertEqual(parsed["system_yes_no"], "YES")
        self.assertTrue(assessment["coverage_complete"])
        self.assertEqual(assessment["visual_precheck_status"], "passed")
        self.assertEqual(assessment["processed_image_count"], 20)
        self.assertTrue(all(item["status"] == "present" for item in assessment["checklist"]))
        mobile = next(item for item in assessment["checklist"] if item["requirement_id"] == "mobile_realname")
        self.assertEqual(mobile["validation_status"], "visual_consistency_matched")
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 5)
        self.assertEqual(
            set(consistency_checks),
            {"identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname"},
        )
        self.assertTrue(consistency_contexts["guardian_relationship"])
        self.assertTrue(all("document_type" in item and "subject_role" in item for item in consistency_contexts["guardian_relationship"]))
        self.assertEqual(assessment["field_consistency"]["status"], "completed")
        self.assertEqual(len(assessment["field_consistency"]["checks"]), 5)
        self.assertEqual(assessment["authoritative_verification"]["status"], "not_configured_optional")
        self.assertEqual(assessment["authenticity_assessment"]["severity"], "warning")
        self.assertFalse(assessment["authenticity_assessment"]["blocks_visual_precheck"])
        self.assertEqual(result["chunking"]["channels"]["minor_field_consistency"]["model_calls"], 5)
        serialized = json.dumps(parsed, ensure_ascii=False)
        self.assertNotIn("不支持", serialized)
        self.assertNotIn("18012345678", serialized)
        self.assertNotIn("320000200801011234", serialized)

    def test_explicit_authoritative_required_policy_keeps_minor_case_in_manual_review(self) -> None:
        case = _case(image_count=20, frame_count=0)
        case["structured_business_context"]["minor_refund_policy"] = {
            "authoritative_verification": "required",
            "review_mode": "strict",
        }
        rows = [(
            list(range(1, 21)),
            {"parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}},
        )]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertTrue(parsed["human_required"])
        self.assertEqual(parsed["minor_material_assessment"]["visual_precheck_status"], "needs_review")
        self.assertEqual(
            parsed["minor_material_assessment"]["authoritative_verification"]["status"],
            "customer_integration_required",
        )

    def test_single_suspected_editing_signal_is_warning_not_blocking(self) -> None:
        case = _case(image_count=20, frame_count=0)
        observations = [_observation(index) for index in range(1, 21)]
        observations[2]["quality_issues"] = ["suspected_editing"]
        rows = [(list(range(1, 21)), {"parsed": {"material_observations": observations}})]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        authenticity = parsed["minor_material_assessment"]["authenticity_assessment"]

        self.assertEqual(authenticity["severity"], "warning")
        self.assertFalse(authenticity["blocks_visual_precheck"])
        self.assertIn(3, authenticity["evidence_image_indices"])
        self.assertEqual(parsed["challenging_evidence"], [])

    def test_blank_template_does_not_satisfy_mobile_realname_requirement(self) -> None:
        case = _case(image_count=20, frame_count=0)
        observations = [_observation(index) for index in range(1, 21)]
        observations[15]["document_state"] = "blank_template"
        observations[15]["sop_eligibility"] = "invalid"
        rows = [(list(range(1, 21)), {"parsed": {"material_observations": observations}})]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        checklist = {
            item["requirement_id"]: item
            for item in parsed["minor_material_assessment"]["checklist"]
        }

        self.assertEqual(checklist["mobile_realname"]["status"], "not_observed_after_full_scan")
        self.assertTrue(any("绑定手机号实名归属证明" in item for item in parsed["material_gaps"]))

    def test_recognized_identity_with_unknown_sop_state_is_present_but_requires_quality_check(self) -> None:
        case = _case(image_count=20, frame_count=0)
        observations = [_observation(index) for index in range(1, 21)]
        for item in observations[:4]:
            item["document_state"] = "unknown"
            item["sop_eligibility"] = "unknown"
            item["quality_issues"] = ["incomplete_page"]

        parsed = aggregate_minor_material_results(
            case,
            [(list(range(1, 21)), {"parsed": {"material_observations": observations}})],
            [],
            [],
            [],
        )
        identity = next(
            item for item in parsed["minor_material_assessment"]["checklist"]
            if item["requirement_id"] == "identity"
        )

        self.assertEqual(identity["status"], "present")
        self.assertEqual(identity["quality_status"], "needs_manual_confirmation")

    def test_operator_account_screenshot_is_supporting_evidence_only(self) -> None:
        case = _case(image_count=20, frame_count=0)
        observations = [_observation(index) for index in range(1, 21)]
        observations[15].update({
            "document_type": "mobile_realname_proof",
            "document_types": ["mobile_realname_proof"],
            "document_state": "filled",
            "sop_eligibility": "supporting_only",
        })
        rows = [(list(range(1, 21)), {"parsed": {"material_observations": observations}})]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        checklist = {
            item["requirement_id"]: item
            for item in parsed["minor_material_assessment"]["checklist"]
        }

        self.assertEqual(checklist["mobile_realname"]["status"], "not_observed_after_full_scan")
        self.assertTrue(any("绑定手机号实名归属证明" in item for item in parsed["material_gaps"]))

    def test_minor_held_phone_invoice_does_not_pass_guardian_holder_check(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        mobile = next(
            item for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "mobile_realname"
        )
        holder = next(
            field for field in mobile["parsed"]["consistency_check"]["field_results"]
            if field["field_name"] == "guardian_phone_holder"
        )
        holder["status"] = "mismatched"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        required = "；".join(parsed["minor_material_assessment"]["required_materials"])

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["system_yes_no"], "REVIEW")
        self.assertIn("申请监护人", required)

    def test_uncertain_guardian_phone_holder_requests_material_instead_of_passing(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        mobile = next(
            item for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "mobile_realname"
        )
        holder = next(
            field for field in mobile["parsed"]["consistency_check"]["field_results"]
            if field["field_name"] == "guardian_phone_holder"
        )
        holder["status"] = "uncertain"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["minor_material_assessment"]["readiness"], "needs_guardian_phone_ownership")

    def test_incomplete_commitment_note_requests_complete_document(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        commitment = next(
            item for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "commitment_signatures"
        )
        for field in commitment["parsed"]["consistency_check"]["field_results"]:
            if field["field_name"] in {"commitment_content", "refund_scope", "recipient_information", "signed_date"}:
                field["status"] = "mismatched"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        required = "；".join(parsed["minor_material_assessment"]["required_materials"])

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["system_yes_no"], "REVIEW")
        self.assertIn("完整承诺内容", required)
        self.assertIn("签署日期", required)

    def test_minor_prompt_limits_school_form_to_supporting_evidence(self) -> None:
        case = _case(image_count=2, frame_count=0)

        inventory_prompt = build_minor_material_inventory_prompt(case)
        consistency_prompt = build_minor_material_consistency_prompt(case)

        self.assertIn("学校盖章报名表", inventory_prompt)
        self.assertIn("只能作为辅助线索", inventory_prompt)
        self.assertIn("guardian_phone_holder", consistency_prompt)
        self.assertIn("commitment_content", consistency_prompt)

    def test_repeated_generic_edit_warnings_do_not_become_critical(self) -> None:
        case = _case(image_count=20, frame_count=0)
        observations = [_observation(index) for index in range(1, 21)]
        for item in observations[:6]:
            item["quality_issues"] = ["suspected_editing"]
            item["editing_evidence"] = []
        rows = [(list(range(1, 21)), {"parsed": {"material_observations": observations}})]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        authenticity = parsed["minor_material_assessment"]["authenticity_assessment"]

        self.assertEqual(authenticity["severity"], "warning")
        self.assertFalse(authenticity["blocks_visual_precheck"])
        self.assertEqual(parsed["challenging_evidence"], [])

    def test_single_page_consistency_evidence_can_match(self) -> None:
        result = _consistency_result("order_payment")
        result["_expected_check_id"] = "order_payment"
        result["_expected_image_indices"] = [1]
        result["_required_image_indices"] = [1]
        result["parsed"]["coverage_ack"] = {
            "expected_image_indices": [1], "observed_image_indices": [1],
        }
        for field in result["parsed"]["consistency_check"]["field_results"]:
            field["evidence_image_indices"] = [1]

        normalized = _normalize_consistency_checks([result], [])

        row = next(item for item in normalized["checks"] if item["check_id"] == "order_payment")
        self.assertEqual(row["status"], "matched")

    def test_minor_pipeline_uses_bounded_dedicated_parallelism(self) -> None:
        case = _case(image_count=24, frame_count=0)
        active = 0
        peak = 0
        lock = threading.Lock()

        def invoke(batch_case: dict) -> dict:
            nonlocal active, peak
            mode = batch_case["structured_business_context"]["analysis_mode"]
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            if mode == "minor_material_inventory":
                indices = [item["image_index"] for item in batch_case["supplemental_images"]]
                return {"status": "success", "parsed": {"material_observations": [_observation(i) for i in indices]}}
            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            result = _consistency_result(check_id)
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field["evidence_image_indices"] = indices[:2]
            return result

        with patch.dict("os.environ", {"REVIEW_MINOR_IMAGE_BATCH_SIZE": "4"}):
            result = run_minor_material_pipeline(case, invoke=invoke, workers=6)

        self.assertGreaterEqual(peak, 6)
        self.assertLessEqual(result["chunking"]["effective_workers"], 8)

    def test_observed_but_partially_readable_material_still_runs_all_consistency_checks(self) -> None:
        case = _case(image_count=20, frame_count=0)
        consistency_checks = []

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if mode == "minor_material_inventory":
                observations = [_observation(index) for index in indices]
                for item in observations:
                    if item["image_index"] == 7:
                        item["readability"] = "partial"
                return {
                    "status": "success",
                    "parsed": {
                        "material_observations": observations,
                        "coverage_ack": {
                            "expected_image_indices": indices,
                            "observed_image_indices": indices,
                        },
                    },
                    "usage": {},
                    "cost": {},
                }

            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            consistency_checks.append(check_id)
            result = _consistency_result(check_id, "uncertain" if check_id == "commitment_signatures" else "matched")
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field["evidence_image_indices"] = indices[:2]
            return result

        result = run_minor_material_pipeline(case, invoke=invoke, workers=4)
        assessment = result["parsed"]["minor_material_assessment"]
        commitment = next(
            item for item in assessment["checklist"] if item["requirement_id"] == "commitment"
        )

        self.assertEqual(commitment["status"], "present")
        self.assertEqual(commitment["quality_status"], "needs_manual_confirmation")
        self.assertEqual(
            set(consistency_checks),
            {"identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname"},
        )
        self.assertEqual(assessment["field_consistency"]["status"], "completed")
        self.assertTrue(all(item["status"] != "not_assessed" for item in assessment["field_consistency"]["checks"]))
        self.assertEqual(result["chunking"]["channels"]["minor_field_consistency"]["model_calls"], 5)

    def test_missing_one_material_does_not_skip_other_consistency_checks(self) -> None:
        case = _case(image_count=20, frame_count=0)
        consistency_checks = []

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if mode == "minor_material_inventory":
                observations = [_observation(index) for index in indices]
                for item in observations:
                    if item["image_index"] == 16:
                        item["document_state"] = "example"
                        item["sop_eligibility"] = "invalid"
                return {"status": "success", "parsed": {"material_observations": observations}}
            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            consistency_checks.append(check_id)
            result = _consistency_result(check_id)
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field["evidence_image_indices"] = indices[:2]
            if check_id == "commitment_signatures":
                for field in result["parsed"]["consistency_check"]["field_results"]:
                    if field["field_name"] == "signature_method":
                        field["status"] = "uncertain"
            return result

        result = run_minor_material_pipeline(case, invoke=invoke, workers=4)

        assessment = result["parsed"]["minor_material_assessment"]
        checklist = assessment["checklist"]
        mobile = next(item for item in checklist if item["requirement_id"] == "mobile_realname")
        self.assertNotEqual(mobile["status"], "present")
        self.assertIn("commitment_signatures", consistency_checks)
        self.assertGreater(result["chunking"]["channels"]["minor_field_consistency"]["model_calls"], 0)
        self.assertEqual(assessment["required_materials"], result["parsed"]["material_gaps"])
        self.assertEqual(len(assessment["required_materials"]), 2)
        self.assertTrue(any("双方亲笔签名" in item for item in assessment["required_materials"]))
        self.assertEqual(len(result["parsed"]["material_gaps"]), 2)
        self.assertIn("号码已注销", result["parsed"]["material_gaps"][0])
        self.assertIn("支付截图不能替代", result["parsed"]["material_gaps"][0])
        self.assertIn("另有字段待补正", result["parsed"]["overall_audit"]["conclusion"])

    def test_uncertain_required_field_uses_check_evidence_to_request_material(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        order = next(
            item for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "order_payment"
        )
        for field in order["parsed"]["consistency_check"]["field_results"]:
            if field["field_name"] == "commitment_amount":
                field["status"] = "uncertain"
                field["visibility"] = "unreadable"
                field["evidence_image_indices"] = []

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertIn(
            "金额与订单可退款范围一致",
            "；".join(parsed["minor_material_assessment"]["required_materials"]),
        )
        self.assertEqual(parsed["decision"], "request_more_material")

    def test_uncertain_required_commitment_fields_each_request_specific_correction(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(list(range(1, 21)), {
            "parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}
        })]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age", "guardian_relationship", "commitment_signatures",
                "order_payment", "mobile_realname",
            )
        ]
        commitment = next(
            item["parsed"]["consistency_check"] for item in checks
            if item["parsed"]["consistency_check"]["check_id"] == "commitment_signatures"
        )
        for field in commitment["field_results"]:
            if field["field_name"] in {"signature_method", "refund_scope", "recipient_information"}:
                field["status"] = "uncertain"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        required = parsed["minor_material_assessment"]["required_materials"]

        self.assertEqual(len(required), 3)
        self.assertIn("双方亲笔签名", required[0])
        self.assertIn("退款范围", "；".join(required))
        self.assertIn("收款信息", "；".join(required))

    def test_material_completeness_without_field_consistency_cannot_pass(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]

        parsed = aggregate_minor_material_results(case, rows, [], [], [])

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["decision"], "manual_consistency_review")
        self.assertEqual(parsed["minor_material_assessment"]["field_consistency"]["status"], "not_completed")
        self.assertIn("字段仍不清楚", parsed["overall_audit"]["conclusion"])

    def test_consistency_mismatch_forces_review_without_exposing_raw_values(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]
        checks = [
            _consistency_result(check_id, "mismatched" if check_id == "guardian_relationship" else "matched")
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]

        parsed = aggregate_minor_material_results(
            case,
            rows,
            [],
            [],
            [],
            consistency_results=checks,
            consistency_failures=[],
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["system_yes_no"], "REVIEW")
        self.assertEqual(parsed["minor_material_assessment"]["field_consistency"]["verdict"], "mismatched")
        relationship = next(
            item
            for item in parsed["minor_material_assessment"]["field_consistency"]["checks"]
            if item["check_id"] == "guardian_relationship"
        )
        self.assertIn("监护关系材料", relationship["message"])
        self.assertIn("监护人身份", relationship["message"])
        self.assertIn("图片 1、3", relationship["message"])
        serialized = json.dumps(parsed, ensure_ascii=False)
        self.assertNotIn("18012345678", serialized)
        self.assertNotIn("320000200801011234", serialized)
        self.assertIn("not_configured_optional", serialized)

    def test_masked_field_cannot_be_promoted_to_explicit_mismatch(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        mobile = checks[-1]["parsed"]["consistency_check"]
        mobile["field_results"][0].update({"status": "mismatched", "visibility": "masked"})
        mobile["risk_reason_codes"] = ["conflicting_fields"]

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        mobile_check = next(
            item for item in parsed["minor_material_assessment"]["field_consistency"]["checks"]
            if item["check_id"] == "mobile_realname"
        )

        self.assertEqual(mobile_check["status"], "uncertain")
        self.assertEqual(parsed["predicted_label"], "positive")
        self.assertEqual(parsed["minor_material_assessment"]["visual_precheck_status"], "passed")

    def test_partial_but_sufficient_visible_fields_can_match(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        checks[0]["parsed"]["consistency_check"]["field_results"][0]["visibility"] = "partial"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["minor_material_assessment"]["field_consistency"]["verdict"], "matched")
        self.assertEqual(parsed["predicted_label"], "positive")
        self.assertEqual(parsed["minor_material_assessment"]["visual_precheck_status"], "passed")

    def test_consistency_jobs_cover_all_related_images_and_uncertain_guardian_holder_blocks_pass(self) -> None:
        case = _case(image_count=20, frame_count=0)
        consistency_segments = []

        def observation(index: int) -> dict:
            if index <= 8:
                return _observation(index)
            item = _observation(index)
            item.update({
                "document_types": ["carrier_invoice"],
                "subject_role": "guardian",
            })
            return item

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if mode == "minor_material_inventory":
                return {
                    "status": "success",
                    "parsed": {
                        "material_observations": [observation(index) for index in indices],
                        "coverage_ack": {
                            "expected_image_indices": indices,
                            "observed_image_indices": indices,
                        },
                    },
                }
            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            consistency_segments.append((check_id, indices))
            result = _consistency_result(check_id)
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            status = "uncertain" if check_id == "mobile_realname" and 20 in indices else "matched"
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field.update({
                    "status": status,
                    "visibility": "partial" if status == "uncertain" else "complete",
                    "evidence_image_indices": indices[:2],
                })
            return result

        with patch.dict("os.environ", {"REVIEW_MINOR_CONSISTENCY_IMAGE_LIMIT": "4"}):
            result = run_minor_material_pipeline(case, invoke=invoke, workers=4)

        mobile_segments = [indices for check_id, indices in consistency_segments if check_id == "mobile_realname"]
        covered = {index for indices in mobile_segments for index in indices}
        self.assertGreater(len(mobile_segments), 1)
        self.assertTrue(set(range(9, 21)).issubset(covered))
        mobile_check = next(
            item for item in result["parsed"]["minor_material_assessment"]["field_consistency"]["checks"]
            if item["check_id"] == "mobile_realname"
        )
        self.assertTrue(set(range(9, 21)).issubset(set(mobile_check["evidence_image_indices"])))
        self.assertEqual(mobile_check["status"], "uncertain")
        self.assertEqual(result["parsed"]["predicted_label"], "review")

    def test_partially_readable_related_image_is_covered_as_non_blocking_warning(self) -> None:
        case = _case(image_count=20, frame_count=0)
        consistency_segments = []

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if mode == "minor_material_inventory":
                observations = [_observation(index) for index in indices]
                for item in observations:
                    if item["image_index"] == 2:
                        item["readability"] = "partial"
                return {"status": "success", "parsed": {"material_observations": observations}}
            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            consistency_segments.append((check_id, indices))
            result = _consistency_result(check_id)
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field["evidence_image_indices"] = indices[:2]
            return result

        result = run_minor_material_pipeline(case, invoke=invoke, workers=4)

        related_coverage = {
            index
            for check_id, indices in consistency_segments
            if check_id in {"identity_age", "guardian_relationship", "commitment_signatures"}
            for index in indices
        }
        self.assertIn(2, related_coverage)
        assessment = result["parsed"]["minor_material_assessment"]
        self.assertEqual(assessment["field_consistency"]["verdict"], "uncertain")
        self.assertEqual(assessment["visual_precheck_status"], "passed")
        self.assertFalse(result["parsed"]["human_required"])

    def test_uncertain_guardian_phone_holder_requires_material_in_default_policy(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]
        checks = [_consistency_result(check_id) for check_id in (
            "identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname"
        )]
        checks[-1] = _consistency_result("mobile_realname", "uncertain")

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["decision"], "request_more_material")
        self.assertFalse(parsed["human_required"])

    def test_unreadable_identity_fields_require_clear_identity_materials(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [(
            list(range(1, 21)),
            {"parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}},
        )]
        checks = [_consistency_result(check_id) for check_id in (
            "identity_age", "guardian_relationship", "commitment_signatures",
            "order_payment", "mobile_realname",
        )]
        identity = checks[0]["parsed"]["consistency_check"]
        identity["status"] = "uncertain"
        for field in identity["field_results"]:
            if field["field_name"] in {"guardian_identity", "minor_identity"}:
                field["status"] = "uncertain"
                field["visibility"] = "unreadable"

        parsed = aggregate_minor_material_results(
            case,
            rows,
            [],
            [],
            [],
            consistency_results=checks,
            consistency_failures=[],
        )

        assessment = parsed["minor_material_assessment"]
        identity_item = next(
            item for item in assessment["checklist"]
            if item["requirement_id"] == "identity"
        )
        self.assertEqual(identity_item["status"], "present")
        self.assertEqual(identity_item["quality_status"], "needs_manual_confirmation")
        self.assertTrue(any("清晰" in item and "身份" in item for item in assessment["required_materials"]))
        self.assertEqual(parsed["decision"], "request_more_material")
        self.assertFalse(parsed["human_required"])

    def test_failed_consistency_call_is_included_in_usage_and_cost(self) -> None:
        case = _case(image_count=20, frame_count=0)

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if mode == "minor_material_inventory":
                return {
                    "status": "success",
                    "parsed": {"material_observations": [_observation(index) for index in indices]},
                    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    "cost": {"estimated_usd": 0.001},
                }
            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            if check_id == "identity_age":
                return {
                    "status": "failed",
                    "error": "provider_timeout",
                    "usage": {"input_tokens": 17, "output_tokens": 3, "total_tokens": 20},
                    "cost": {"estimated_usd": 0.005},
                }
            result = _consistency_result(check_id)
            if check_id == "guardian_relationship":
                result.update({
                    "cost_status": "partial_unknown",
                    "unknown_cost_calls": 1,
                    "estimated_cost_calls": 1,
                })
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field["evidence_image_indices"] = indices[:2]
            return result

        result = run_minor_material_pipeline(case, invoke=invoke, workers=4)
        channel = result["chunking"]["channels"]["minor_field_consistency"]

        self.assertEqual(channel["model_calls"], 5)
        self.assertEqual(channel["total_tokens"], 140)
        self.assertEqual(channel["estimated_usd"], 0.013)
        self.assertEqual(result["usage"]["total_tokens"], 215)
        self.assertEqual(result["cost"]["estimated_usd"], 0.018)
        self.assertEqual(result["cost_status"], "partial_unknown")
        self.assertEqual(result["unknown_cost_calls"], 1)

    def test_all_failed_image_batches_preserve_provider_status_for_route_fallback(self) -> None:
        case = _case(image_count=1, frame_count=0)

        def invoke(_batch_case: dict) -> dict:
            return {
                "status": "failed",
                "status_code": 401,
                "error_type": "hard",
                "error": "provider_credentials_unavailable",
                "_channel_route_attempts": [
                    {"channel": "primary", "status_code": 401, "decision": "stop_non_retryable"}
                ],
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["status_code"], 401)
        self.assertEqual(result["error_type"], "hard")
        self.assertEqual(result["_channel_route_attempts"][0]["status_code"], 401)

    def test_unclassified_image_requests_system_retry_without_user_material_gap(self) -> None:
        case = _case(image_count=5, frame_count=0)
        rows = [
            (
                [1, 2, 3, 4, 5],
                {
                    "parsed": {"material_observations": [_observation(index) for index in range(1, 5)]},
                },
            )
        ]
        parsed = aggregate_minor_material_results(case, rows, [], [], [])
        assessment = parsed["minor_material_assessment"]

        self.assertFalse(assessment["coverage_complete"])
        self.assertEqual(assessment["unclassified_image_indices"], [5])
        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["processing_status"], "technical_processing_incomplete")
        self.assertEqual(parsed["system_action"], "system_retry")
        self.assertIsNone(parsed["confidence"])
        self.assertEqual(parsed["material_gaps"], [])
        self.assertFalse(parsed["human_required"])
        self.assertIn("受控重跑整案", parsed["next_step"])

    def test_structural_retry_recovers_omitted_image_indices_and_counts_cost(self) -> None:
        case = _case(image_count=4, frame_count=0)
        attempts = 0

        def invoke(batch_case: dict) -> dict:
            nonlocal attempts
            mode = batch_case["structured_business_context"]["analysis_mode"]
            if mode == "minor_material_consistency":
                check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
                result = _consistency_result(check_id)
                result["usage"] = {}
                result["cost"] = {}
                result["cost_status"] = "not_incurred"
                return result
            attempts += 1
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            observations = [] if attempts == 1 else [_observation(index) for index in indices]
            return {
                "status": "success",
                "parsed": {"material_observations": observations},
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "cost_status": "partial_unknown" if attempts == 1 else "estimated",
                "unknown_cost_calls": 2 if attempts == 1 else 0,
                "estimated_cost_calls": 1,
                "latency_seconds": 0.1,
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(attempts, 2)
        self.assertTrue(result["parsed"]["minor_material_assessment"]["coverage_complete"])
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 2)
        self.assertEqual(result["usage"]["total_tokens"], 30)
        self.assertEqual(result["cost"]["estimated_usd"], 0.002)
        self.assertEqual(result["cost_status"], "partial_unknown")
        self.assertEqual(result["unknown_cost_calls"], 2)
        self.assertEqual(result["estimated_cost_calls"], 2)

    def test_default_structural_retry_is_bounded_before_system_retry(self) -> None:
        case = _case(image_count=4, frame_count=0)
        attempts = 0

        def invoke(batch_case: dict) -> dict:
            nonlocal attempts
            mode = batch_case["structured_business_context"]["analysis_mode"]
            if mode == "minor_material_consistency":
                check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
                result = _consistency_result(check_id)
                result["usage"] = {}
                result["cost"] = {}
                return result
            attempts += 1
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            return {
                "status": "success",
                "parsed": {
                    "material_observations": (
                        [_observation(index) for index in indices] if attempts == 3 else []
                    )
                },
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(attempts, 6)
        self.assertFalse(result["parsed"]["minor_material_assessment"]["coverage_complete"])
        self.assertEqual(result["parsed"]["system_action"], "system_retry")
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 6)

    def test_persistent_batch_omission_falls_back_to_single_image_recovery(self) -> None:
        case = _case(image_count=4, frame_count=0)
        batch_attempts = 0
        single_attempts = []

        def invoke(batch_case: dict) -> dict:
            nonlocal batch_attempts
            mode = batch_case["structured_business_context"]["analysis_mode"]
            if mode == "minor_material_consistency":
                check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
                result = _consistency_result(check_id)
                result["usage"] = {}
                result["cost"] = {}
                return result
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if len(indices) == 1:
                single_attempts.extend(indices)
                observations = [_observation(indices[0])]
            else:
                batch_attempts += 1
                observations = []
            return {
                "status": "success",
                "parsed": {"material_observations": observations},
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(batch_attempts, 2)
        self.assertEqual(single_attempts, [1, 2, 3, 4])
        self.assertTrue(result["parsed"]["minor_material_assessment"]["coverage_complete"])
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 6)

    def test_single_image_recovery_runs_once_after_batch_repair(self) -> None:
        case = _case(image_count=1, frame_count=0)
        batch_attempts = 0
        recovery_attempts = 0

        def invoke(batch_case: dict) -> dict:
            nonlocal batch_attempts, recovery_attempts
            recovery = bool(
                batch_case["structured_business_context"]["minor_material_batch"].get(
                    "single_image_recovery"
                )
            )
            if recovery:
                recovery_attempts += 1
            else:
                batch_attempts += 1
            observations = [_observation(1)] if recovery else []
            return {
                "status": "success",
                "parsed": {"material_observations": observations},
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(batch_attempts, 2)
        self.assertEqual(recovery_attempts, 1)
        self.assertTrue(result["parsed"]["minor_material_assessment"]["coverage_complete"])
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 3)

    def test_recovery_exception_preserves_prior_usage_and_marks_processing_incomplete(self) -> None:
        case = _case(image_count=1, frame_count=0)
        attempts = 0

        def invoke(batch_case: dict) -> dict:
            nonlocal attempts
            mode = batch_case["structured_business_context"]["analysis_mode"]
            if mode == "minor_material_consistency":
                check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
                result = _consistency_result(check_id)
                result["usage"] = {}
                result["cost"] = {}
                return result
            attempts += 1
            if attempts > 1:
                raise RuntimeError("supplier timeout")
            return {
                "status": "success",
                "parsed": {"material_observations": []},
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        assessment = result["parsed"]["minor_material_assessment"]
        self.assertEqual(attempts, 3)
        self.assertEqual(assessment["processing_status"], "technical_processing_incomplete")
        self.assertEqual(result["usage"]["total_tokens"], 15)
        self.assertEqual(result["cost"]["estimated_usd"], 0.001)
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 3)

    def test_malformed_usage_cost_and_latency_do_not_abort_successful_semantic_result(self) -> None:
        case = _case(image_count=1, frame_count=0)

        def invoke(batch_case: dict) -> dict:
            return {
                "status": "success",
                "parsed": {"material_observations": [_observation(1)]},
                "usage": {"input_tokens": "many", "output_tokens": "unknown", "total_tokens": "n/a"},
                "cost": {"estimated_usd": "unknown"},
                "latency_seconds": "slow",
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["usage"]["total_tokens"], 0)
        self.assertEqual(result["cost"]["estimated_usd"], 0.0)
        self.assertEqual(result["model_latency_seconds_sum"], 0.0)

    def test_case_level_recovery_budget_bounds_persistent_omissions(self) -> None:
        case = _case(image_count=200, frame_count=0)
        attempts = 0

        def invoke(batch_case: dict) -> dict:
            nonlocal attempts
            attempts += 1
            return {"status": "success", "parsed": {"material_observations": []}}

        result = run_minor_material_pipeline(case, invoke=invoke, workers=8)

        self.assertLessEqual(attempts, 66)
        self.assertEqual(result["parsed"]["processing_status"], "technical_processing_incomplete")
        self.assertEqual(result["chunking"]["recovery_calls_used"], 16)

    def test_household_register_or_birth_certificate_satisfies_relationship_rule(self) -> None:
        case = _case(image_count=8, frame_count=0)
        rows = [([1, 2, 3, 4, 5, 6, 7, 8], {"parsed": {"material_observations": [_observation(index) for index in range(1, 9)]}})]
        parsed = aggregate_minor_material_results(case, rows, [], [], [])
        relationship = next(
            item for item in parsed["minor_material_assessment"]["checklist"]
            if item["requirement_id"] == "relationship"
        )

        self.assertEqual(relationship["status"], "present")
        self.assertIn("二选一", relationship["rule_note"])

    def test_declared_images_exceeding_accepted_images_blocks_full_coverage(self) -> None:
        case = _case(image_count=4, frame_count=0)
        case["structured_business_context"]["frontdesk_evidence_package"] = {
            "asset_manifest": {
                "assets": [
                    {"mime_type": "image/jpeg"} for _ in range(5)
                ]
            }
        }
        rows = [([1, 2, 3, 4], {"parsed": {"material_observations": [_observation(index) for index in range(1, 5)]}})]
        parsed = aggregate_minor_material_results(case, rows, [], [], [])
        assessment = parsed["minor_material_assessment"]

        self.assertFalse(assessment["ingestion_complete"])
        self.assertFalse(assessment["coverage_complete"])
        self.assertEqual(assessment["coverage_ratio"], 0.8)

    def test_inventory_prompt_forbids_pii_and_does_not_include_evaluation_labels(self) -> None:
        case = _case(image_count=2, frame_count=0)
        case["customer_claim"] = "contact 18012345678 identity 320000200801011234"
        case["structured_business_context"].update({
            "analysis_mode": "minor_material_inventory",
            "minor_material_batch": {
                "index": 1,
                "total": 1,
                "expected_image_indices": [1, 2],
                "global_image_count": 2,
            },
        })
        prompt = build_selection_prompt(case)

        self.assertIn("必须逐张返回", prompt)
        self.assertIn("户口本相关页或出生证明二选一", prompt)
        self.assertIn("不得输出姓名、手机号、证件号", prompt)
        self.assertNotIn("18012345678", prompt)
        self.assertNotIn("320000200801011234", prompt)
        self.assertNotIn("expected_predicted_label", prompt)
        self.assertNotIn("人工认可", prompt)

    def test_inventory_prompt_defines_passport_fields_and_unknown_fallback(self) -> None:
        case = _case(image_count=1, frame_count=0)
        case["structured_business_context"].update({
            "analysis_mode": "minor_material_inventory",
            "minor_material_batch": {
                "index": 1,
                "total": 1,
                "expected_image_indices": [1],
                "global_image_count": 1,
            },
        })

        prompt = build_selection_prompt(case)

        self.assertIn('"document_type": "passport"', prompt)
        self.assertIn('"issuing_country_or_region"', prompt)
        self.assertIn('"readability": "clear|partial|unknown"', prompt)
        self.assertIn("不自动替代现有 SOP 的身份证必交项", prompt)
        self.assertIn("只做视觉/OCR 初审", prompt)

    def test_passport_observation_is_structured_and_unreadable_values_become_unknown(self) -> None:
        case = _case(image_count=3, frame_count=0)
        rows = [([1, 2, 3], {"parsed": {"material_observations": [
            {
                "image_index": 1,
                "document_type": "passport",
                "subject_role": "guardian",
                "document_side": "page",
                "issuing_country_or_region": "中国",
                "readability": "clear",
                "quality_issues": [],
            },
            {
                "image_index": 2,
                "document_type": "passport",
                "subject_role": "minor",
                "document_side": "page",
                "readability": "unreadable",
                "quality_issues": ["blur"],
            },
            {
                "image_index": 3,
            },
        ]}})]

        parsed = aggregate_minor_material_results(case, rows, [], [], [])
        inventory = parsed["minor_material_assessment"]["material_inventory"]

        self.assertEqual(inventory[0]["document_type"], "passport")
        self.assertEqual(inventory[0]["document_types"], ["passport"])
        self.assertEqual(inventory[0]["issuing_country_or_region"], "中国")
        self.assertEqual(inventory[0]["readability"], "clear")
        self.assertEqual(inventory[1]["issuing_country_or_region"], "unknown")
        self.assertEqual(inventory[1]["readability"], "unknown")
        self.assertEqual(inventory[2]["document_type"], "unknown")
        self.assertEqual(inventory[2]["subject_role"], "unknown")
        self.assertEqual(inventory[2]["document_side"], "unknown")
        self.assertEqual(inventory[2]["issuing_country_or_region"], "unknown")
        self.assertEqual(inventory[2]["readability"], "unknown")

    def test_passport_participates_in_identity_and_guardianship_checks_only(self) -> None:
        images = [_image(index) for index in range(1, 5)]
        observations = [
            {
                "image_index": 1,
                "document_type": "passport",
                "document_types": ["passport"],
                "subject_role": "guardian",
                "readability": "clear",
                "quality_issues": [],
            },
            {
                "image_index": 2,
                "document_type": "passport",
                "document_types": ["passport"],
                "subject_role": "minor",
                "readability": "clear",
                "quality_issues": [],
            },
            {
                "image_index": 3,
                "document_type": "birth_certificate",
                "document_types": ["birth_certificate"],
                "subject_role": "not_applicable",
                "readability": "clear",
                "quality_issues": [],
            },
            {
                "image_index": 4,
                "document_type": "order_payment_proof",
                "document_types": ["order_payment_proof"],
                "subject_role": "not_applicable",
                "readability": "clear",
                "quality_issues": [],
            },
        ]

        jobs = _consistency_image_jobs(observations, images)
        selected = {
            item["check_id"]: [image["image_index"] for image in item["selected"]]
            for item in jobs
        }

        self.assertIn(1, selected["identity_age"])
        self.assertIn(2, selected["identity_age"])
        self.assertIn(1, selected["guardian_relationship"])
        self.assertIn(2, selected["guardian_relationship"])
        self.assertNotIn(1, selected["order_payment"])

    def test_passport_does_not_replace_required_identity_card_or_force_authoritative_review(self) -> None:
        case = _case(image_count=7, frame_count=0)
        observations = [
            {
                "image_index": 1,
                "document_type": "passport",
                "subject_role": "guardian",
                "document_side": "page",
                "issuing_country_or_region": "中国",
                "readability": "clear",
                "quality_issues": [],
            },
            {
                "image_index": 2,
                "document_type": "passport",
                "subject_role": "minor",
                "document_side": "page",
                "issuing_country_or_region": "unknown",
                "readability": "clear",
                "quality_issues": [],
            },
            {**_observation(5), "image_index": 3},
            {**_observation(7), "image_index": 4},
            {**_observation(8), "image_index": 5},
            {**_observation(16), "image_index": 6},
            {**_observation(18), "image_index": 7},
        ]
        rows = [(list(range(1, 8)), {"parsed": {"material_observations": observations}})]

        parsed = aggregate_minor_material_results(case, rows, [], [], [])
        assessment = parsed["minor_material_assessment"]
        identity = next(item for item in assessment["checklist"] if item["requirement_id"] == "identity")

        self.assertEqual(identity["status"], "not_observed_after_full_scan")
        self.assertEqual(assessment["authoritative_verification"]["status"], "not_configured_optional")
        self.assertNotIn("authoritative_verification_pending", parsed.get("human_review_reason_codes") or [])

    def test_extra_passport_does_not_force_review_when_required_materials_match(self) -> None:
        case = _case(image_count=21, frame_count=0)
        passport = {
            "image_index": 21,
            "document_type": "passport",
            "subject_role": "minor",
            "document_side": "page",
            "issuing_country_or_region": "中国",
            "readability": "clear",
            "quality_issues": [],
        }
        observations = [_observation(index) for index in range(1, 21)] + [passport]
        rows = [(list(range(1, 22)), {"parsed": {"material_observations": observations}})]
        checks = [
            _consistency_result(check_id)
            for check_id in (
                "identity_age",
                "guardian_relationship",
                "commitment_signatures",
                "order_payment",
                "mobile_realname",
            )
        ]

        parsed = aggregate_minor_material_results(
            case,
            rows,
            [],
            [],
            [],
            consistency_results=checks,
            consistency_failures=[],
        )

        self.assertEqual(parsed["predicted_label"], "positive")
        self.assertFalse(parsed["human_required"])
        self.assertEqual(
            parsed["minor_material_assessment"]["authoritative_verification"]["status"],
            "not_configured_optional",
        )

    def test_consistency_prompt_compares_fields_but_forbids_raw_pii_output(self) -> None:
        case = _case(image_count=4, frame_count=0)
        case["structured_business_context"].update({
            "analysis_mode": "minor_material_consistency",
            "minor_consistency_check": {
                "check_id": "guardian_relationship",
                "expected_image_indices": [1, 3, 4],
            },
        })
        prompt = build_selection_prompt(case)

        self.assertIn("监护关系", prompt)
        self.assertIn("relationship_evidence_type", prompt)
        self.assertIn("separate_household_books_without_bridge", prompt)
        self.assertIn("比较图片中可见字段", prompt)
        self.assertIn("不得输出任何字段原值", prompt)
        self.assertIn("默认 disabled", prompt)
        self.assertIn("护照", prompt)
        self.assertIn("签发国家/地区", prompt)
        self.assertNotIn('"authoritative_verification": "customer_integration_required"', prompt)
        self.assertNotIn("expected_predicted_label", prompt)

    def test_consistency_prompt_uses_trusted_assessment_date(self) -> None:
        case = _case(image_count=2, frame_count=0)
        case["order_context"] = {"assessment_at": "2026-08-16"}
        case["structured_business_context"].update({
            "analysis_mode": "minor_material_consistency",
            "minor_consistency_check": {
                "check_id": "identity_age",
                "expected_image_indices": [1, 2],
            },
        })

        prompt = build_selection_prompt(case)

        self.assertIn("年龄判断基准日期：2026-08-16", prompt)
        self.assertNotIn("工单创建日期未提供", prompt)

    def test_report_renders_consistency_matrix_and_authoritative_boundary(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        parsed["minor_material_assessment"]["process_evidence"] = [{
            "video_index": 1,
            "global_frame_index": 2,
            "timestamp": "00:08.00",
            "process_type": "invoice_generation",
            "evidence_quality": "clear",
        }]

        panel = render_minor_material_panel(parsed["minor_material_assessment"], lambda value: html.escape(str(value)))

        self.assertIn("视觉字段一致性初审", panel)
        self.assertIn("视觉初审结论", panel)
        self.assertIn("视觉初审通过", panel)
        self.assertIn("身份与年龄", panel)
        self.assertIn("监护关系", panel)
        self.assertIn("订单与支付", panel)
        self.assertIn("材料质量", panel)
        self.assertIn("在线验真默认关闭", panel)
        self.assertIn('href="#image-', panel)
        self.assertIn("图片真实性风险", panel)
        self.assertIn("发票或凭证生成过程", panel)
        self.assertIn("画面清晰", panel)
        self.assertNotIn("invoice_generation", panel)
        self.assertTrue(all(
            "matched" not in item["description"]
            for item in parsed["supporting_evidence"]
        ))
        self.assertIn("字段一致性未发现明显矛盾", parsed["overall_audit"]["core_reason"])
        self.assertNotIn("18012345678", panel)
        self.assertNotIn("320000200801011234", panel)

    def test_report_renders_safe_passport_fields_without_raw_ocr(self) -> None:
        assessment = {
            "material_inventory": [{
                "image_index": 1,
                "asset_ref": "supplemental_image_1",
                "document_type": "passport",
                "document_types": ["passport"],
                "subject_role": "minor",
                "document_side": "page",
                "issuing_country_or_region": "中国",
                "readability": "clear",
                "quality_issues": [],
                "ocr_text": "张三 320000200801011234",
            }],
            "checklist": [],
            "field_consistency": {},
            "authoritative_verification": {"status": "not_configured_optional"},
            "authenticity_assessment": {},
        }

        panel = render_minor_material_panel(assessment, lambda value: html.escape(str(value)))

        self.assertIn("护照", panel)
        self.assertIn("签发国家/地区", panel)
        self.assertIn("中国", panel)
        self.assertIn("清晰", panel)
        self.assertIn("不替代身份证必交项", panel)
        self.assertNotIn("张三", panel)
        self.assertNotIn("320000200801011234", panel)


if __name__ == "__main__":
    unittest.main()
