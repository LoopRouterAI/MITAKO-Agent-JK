# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from PIL import Image
from pypdf import PdfWriter

from review_service.material_readiness import (
    build_review_inventory,
    derive_material_readiness,
)
from review_service.schemas import ReviewJobResult, ReviewPayload


class MaterialReadinessTest(unittest.TestCase):
    def test_inventory_marks_duplicate_assets_by_upload_sha256(self) -> None:
        digest = "a" * 64
        inventory = build_review_inventory({
            "scenario": "minor_refund",
            "assets": [
                {
                    "asset_id": "IMG-1",
                    "original_name": "identity-front.jpg",
                    "mime_type": "image/jpeg",
                    "size": 100,
                    "sha256": digest,
                },
                {
                    "asset_id": "IMG-2",
                    "original_name": "identity-front-copy.jpg",
                    "mime_type": "image/jpeg",
                    "size": 100,
                    "sha256": digest,
                },
                {
                    "asset_id": "IMG-3",
                    "original_name": "identity-back.jpg",
                    "mime_type": "image/jpeg",
                    "size": 120,
                    "sha256": "b" * 64,
                },
            ],
        })

        rows = {item["asset_id"]: item for item in inventory["assets"]}
        self.assertEqual(rows["IMG-1"]["sha256"], digest)
        self.assertIsNone(rows["IMG-1"]["duplicate_of"])
        self.assertEqual(rows["IMG-2"]["duplicate_of"], "IMG-1")
        self.assertIsNone(rows["IMG-3"]["duplicate_of"])
        self.assertEqual(inventory["unique_asset_count"], 2)
        self.assertEqual(inventory["duplicate_asset_count"], 1)

    def test_inventory_records_real_image_decode_status_and_pdf_page_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "valid.jpg"
            buffer = io.BytesIO()
            Image.new("RGB", (64, 48), (30, 120, 180)).save(buffer, format="JPEG")
            image_path.write_bytes(buffer.getvalue())
            (root / "broken.jpg").write_bytes(b"not-an-image")
            (root / "broken.pdf").write_bytes(b"not-a-pdf")
            pdf_path = root / "proof.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.add_blank_page(width=100, height=100)
            with pdf_path.open("wb") as stream:
                writer.write(stream)

            inventory = build_review_inventory({
                "scenario": "minor_refund",
                "assets": [
                    {"asset_id": "IMG-OK", "stored_name": "valid.jpg", "mime_type": "image/jpeg"},
                    {"asset_id": "IMG-BAD", "stored_name": "broken.jpg", "mime_type": "image/jpeg"},
                    {"asset_id": "PDF-OK", "stored_name": "proof.pdf", "mime_type": "application/pdf"},
                    {"asset_id": "PDF-BAD", "stored_name": "broken.pdf", "mime_type": "application/pdf"},
                ],
            }, job_dir=root)

        rows = {item["asset_id"]: item for item in inventory["assets"]}
        self.assertEqual(rows["IMG-OK"]["technical_status"], "completed")
        self.assertEqual(rows["IMG-OK"]["pixel_size"], {"width": 64, "height": 48})
        self.assertEqual(rows["IMG-BAD"]["technical_status"], "failed")
        self.assertEqual(rows["PDF-OK"]["technical_status"], "completed")
        self.assertEqual(rows["PDF-OK"]["page_count"], 2)
        self.assertEqual(rows["PDF-BAD"]["technical_status"], "failed")
        self.assertEqual(rows["PDF-BAD"]["technical_reason"], "pdf_decode_failed")

    def test_inventory_scans_received_assets_without_claiming_video_semantics(self) -> None:
        inventory = build_review_inventory({
            "scenario": "product_damage",
            "metadata": {
                "customer_claim": "商品表面有划痕",
                "conversation_history": [{"role": "customer", "content": "补充了划痕位置"}],
                "order_no": "ORDER-1",
                "order_items": [{"sku": "SKU-1", "name": "摆件"}],
                "product_master_data": {"sku": "SKU-1"},
                "logistics": {"snapshot_at": "2026-08-12T10:00:00+08:00", "packages": [{"package_ref": "P1"}]},
                "warehouse_master_data": {"source": "customer_warehouse"},
            },
            "assets": [{
                "asset_id": "RA-1",
                "original_name": "clip.mp4",
                "mime_type": "video/mp4",
                "size": 1234,
                "fields": ["unboxing_video"],
            }],
        }, media_forensics={
            "assets": [{
                "asset_id": "RA-1",
                "status": "completed",
                "container": {"duration_seconds": 31.5},
            }],
        })

        self.assertEqual(inventory["received_asset_count"], 1)
        self.assertEqual(inventory["media_counts"]["video"], 1)
        self.assertEqual(inventory["assets"][0]["declared_fields"], ["unboxing_video"])
        self.assertEqual(inventory["assets"][0]["technical_status"], "completed")
        self.assertEqual(inventory["assets"][0]["duration_seconds"], 31.5)
        self.assertTrue(inventory["business_inputs"]["conversation_history_present"])
        self.assertEqual(inventory["business_inputs"]["order_item_count"], 1)
        self.assertTrue(inventory["business_inputs"]["product_reference_present"])
        self.assertTrue(inventory["business_inputs"]["logistics_present"])
        self.assertTrue(inventory["business_inputs"]["warehouse_data_present"])
        self.assertNotIn("is_opening_video", inventory["assets"][0])

    def test_inventory_includes_media_preflight_plan_without_claiming_execution(self) -> None:
        inventory = build_review_inventory({
            "scenario": "product_damage",
            "assets": [
                {
                    "asset_id": "VIDEO-HIGH",
                    "original_name": "high.mp4",
                    "mime_type": "video/mp4",
                    "size": 120 * 1024 * 1024,
                },
                {
                    "asset_id": "IMAGE-1",
                    "original_name": "closeup.png",
                    "mime_type": "image/png",
                    "size": 8 * 1024 * 1024,
                },
            ],
        }, media_forensics={
            "assets": [{
                "asset_id": "VIDEO-HIGH",
                "status": "completed",
                "container": {"duration_seconds": 60.0, "bit_rate": 8_000_000},
                "streams": [{
                    "type": "video",
                    "width": 1920,
                    "height": 1080,
                    "average_fps": 30.0,
                }],
            }],
        })

        plan = inventory["media_preflight"]
        rows = {item["asset_id"]: item for item in plan["assets"]}
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(rows["VIDEO-HIGH"]["quality_action"], "create_quality_proxy")
        self.assertEqual(
            rows["VIDEO-HIGH"]["quality_reasons"],
            ["fps_above_24", "bitrate_above_6mbps", "source_above_100mb"],
        )
        self.assertEqual(rows["VIDEO-HIGH"]["delivery"], "https_url")
        self.assertEqual(rows["IMAGE-1"]["quality_action"], "individual_webp")
        self.assertEqual(rows["IMAGE-1"]["resize_trigger_long_edge"], 3840)
        self.assertEqual(rows["IMAGE-1"]["max_long_edge"], 2560)
        self.assertEqual(rows["IMAGE-1"]["encoding_order"], ["lossless", "quality_90"])
        self.assertFalse(plan["execution_claimed"])

    def test_product_damage_requires_semantically_verified_initial_opening_video(self) -> None:
        job = {
            "scenario": "product_damage",
            "metadata": {"customer_claim": "商品表面有划痕"},
            "assets": [{"asset_id": "RA-1", "mime_type": "video/mp4", "size": 1234}],
        }
        readiness = derive_material_readiness(job, {
            "confidence": 0.86,
            "opening_video_evidence": {
                "present": True,
                "sop_compliant": True,
                "confidence": 0.91,
                "reason": "从封箱状态连续记录初次拆包。",
                "evidence_refs": [
                    {"asset_ref": "native_video_1", "timestamp": "00:00.00", "fact": "封箱起始"},
                    {"asset_ref": "native_video_1", "timestamp": "00:06.00", "fact": "连续拆封"},
                ],
                "validated_requirements": [
                    "sealed_start", "waybill_visible", "continuous",
                    "claimed_item_presentation", "issue_assessable",
                ],
            },
        }, {"full_review_ready": True, "missing_required": []})

        self.assertEqual(readiness["status"], "complete")
        opening = next(item for item in readiness["checklist"] if item["requirement_id"] == "initial_opening_video")
        self.assertEqual(opening["status"], "present")
        self.assertEqual(len(opening["evidence_refs"]), 2)
        compliance = next(
            item for item in readiness["checklist"]
            if item["requirement_id"] == "opening_video_sop_compliance"
        )
        self.assertEqual(compliance["status"], "present")

    def test_product_opening_is_not_complete_when_key_semantics_are_missing(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "product_damage",
                "metadata": {"customer_claim": "商品表面有划痕"},
                "assets": [{"asset_id": "RA-1", "mime_type": "video/mp4", "size": 1234}],
            },
            {
                "opening_video_evidence": {
                    "present": True,
                    "sop_compliant": False,
                    "confidence": 0.92,
                    "evidence_refs": [{
                        "asset_ref": "native_video_1", "timestamp": "00:00.00", "fact": "封箱起始",
                    }],
                    "validated_requirements": ["sealed_start", "continuous"],
                },
            },
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["status"], "incomplete")
        action = next(
            item for item in readiness["checklist"]
            if item["requirement_id"] == "initial_opening_video"
        )
        compliance = next(
            item for item in readiness["checklist"]
            if item["requirement_id"] == "opening_video_sop_compliance"
        )
        self.assertEqual(action["status"], "present")
        self.assertEqual(compliance["status"], "invalid")

    def test_product_video_file_without_semantic_result_is_indeterminate(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "product_damage",
                "metadata": {"customer_claim": "商品表面有划痕"},
                "assets": [{"asset_id": "RA-1", "mime_type": "video/mp4", "size": 1234}],
            },
            {},
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["status"], "indeterminate")
        self.assertIn("尚未确认", readiness["reason"])

    def test_missing_product_video_is_incomplete_not_indeterminate(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "product_damage",
                "metadata": {"customer_claim": "商品表面有划痕"},
                "assets": [{"asset_id": "RA-1", "mime_type": "image/jpeg", "size": 1234}],
            },
            {},
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["status"], "incomplete")
        self.assertTrue(any("初次" in item and "开箱" in item for item in readiness["missing_items"]))

    def test_wrong_item_uses_fulfillment_semantics_not_product_damage_fields(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "wrong_item",
                "metadata": {},
                "assets": [{"asset_id": "RA-1", "mime_type": "image/jpeg", "size": 1234}],
            },
            {
                "fulfillment_reconciliation": {
                    "evidence_sufficiency": "sufficient",
                    "observed_items": [{
                        "product_name": "实收款式 B",
                        "package_ref": "PKG-1",
                        "observed_quantity": 1,
                        "evidence_refs": [{
                            "asset_ref": "supplemental_image_1",
                            "timestamp": None,
                            "field": "observed_item",
                            "fact": "实收款式 B 清晰可见。",
                        }],
                    }],
                    "package_observations": [{
                        "package_ref": "PKG-1",
                        "evidence_refs": [{
                            "asset_ref": "supplemental_image_1",
                            "timestamp": None,
                            "field": "same_package_linkage",
                            "fact": "商品、包装和面单在同一张全景图内。",
                        }],
                    }],
                    "confidence": 0.87,
                }
            },
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["scenario"], "wrong_item")
        self.assertEqual(readiness["status"], "complete")
        self.assertTrue(any(item["requirement_id"] == "received_item_evidence" for item in readiness["checklist"]))
        self.assertTrue(any(item["requirement_id"] == "expected_item_identity_baseline" for item in readiness["checklist"]))
        self.assertTrue(any(item["requirement_id"] == "same_package_linkage" for item in readiness["checklist"]))
        self.assertFalse(any(item["requirement_id"] == "complete_package_coverage" for item in readiness["checklist"]))
        self.assertFalse(any(item["requirement_id"] == "initial_opening_video" for item in readiness["checklist"]))

    def test_wrong_item_requires_distinct_received_and_same_package_evidence(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "wrong_item",
                "metadata": {},
                "assets": [{"asset_id": "RA-1", "mime_type": "image/jpeg", "size": 1234}],
            },
            {
                "fulfillment_reconciliation": {
                    "evidence_sufficiency": "sufficient",
                    "observed_items": [{
                        "product_name": "实收款式 B",
                        "observed_quantity": 1,
                        "package_ref": "unassigned",
                        "evidence_refs": [{
                            "asset_ref": "supplemental_image_1",
                            "timestamp": None,
                            "field": "observed_item",
                            "fact": "图片只展示实收商品，没有面单或包装关联。",
                        }],
                    }],
                    "package_observations": [],
                    "confidence": 0.87,
                }
            },
            {"full_review_ready": True, "missing_required": []},
        )

        checks = {item["requirement_id"]: item for item in readiness["checklist"]}
        self.assertEqual(checks["received_item_evidence"]["status"], "present")
        self.assertEqual(checks["same_package_linkage"]["status"], "invalid")
        self.assertEqual(readiness["status"], "incomplete")

    def test_wrong_item_static_three_images_are_complete_for_warehouse_review(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "wrong_item",
                "metadata": {},
                "assets": [{"asset_id": "RA-1", "mime_type": "image/jpeg", "size": 1234}],
            },
            {
                "fulfillment_reconciliation": {
                    "evidence_route": "static_three_images",
                    "user_materials_complete": True,
                    "evidence_sufficiency": "insufficient",
                    "observed_items": [{
                        "product_name": "实收款式 B",
                        "package_ref": "PKG-1",
                        "evidence_refs": [{
                            "asset_ref": "supplemental_image_1",
                            "field": "observed_item",
                            "fact": "实收商品清晰可见。",
                        }],
                    }],
                    "package_observations": [{
                        "package_ref": "PKG-1",
                        "evidence_refs": [{
                            "asset_ref": "supplemental_image_1",
                            "field": "received_group_photo_complete",
                            "fact": "商品、包装和面单属于同一包裹。",
                        }],
                    }],
                    "warehouse_check": {"state": "pending", "outcome": None},
                    "observation_confidence": 0.88,
                },
            },
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["status"], "complete")
        self.assertEqual(readiness["missing_items"], [])
        self.assertTrue(any("仓库" in item for item in readiness["warnings"]))

    def test_fulfillment_material_confidence_uses_observation_confidence_when_verdict_is_guarded(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "wrong_item",
                "metadata": {},
                "assets": [{"asset_id": "RA-1", "mime_type": "image/jpeg", "size": 1234}],
            },
            {
                "fulfillment_reconciliation": {
                    "evidence_sufficiency": "insufficient",
                    "observed_items": [{
                        "product_name": "实收款式 B",
                        "package_ref": "PKG-1",
                        "evidence_refs": [{
                            "asset_ref": "supplemental_image_1",
                            "timestamp": None,
                            "field": "observed_item",
                            "fact": "实收款式 B 清晰可见。",
                        }],
                    }],
                    "package_observations": [{
                        "package_ref": "PKG-1",
                        "evidence_refs": [{
                            "asset_ref": "supplemental_image_1",
                            "timestamp": None,
                            "field": "same_package_linkage",
                            "fact": "商品、包装和面单在同一张全景图内。",
                        }],
                    }],
                    "observation_confidence": 0.95,
                    "confidence": 0.0,
                }
            },
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["status"], "incomplete")
        self.assertEqual(readiness["confidence"], 0.95)

    def test_missing_item_trusted_warehouse_verification_is_complete(self) -> None:
        readiness = derive_material_readiness(
            {"scenario": "missing_item", "metadata": {}, "assets": []},
            {
                "fulfillment_reconciliation": {
                    "evidence_sufficiency": "sufficient",
                    "resolution_basis": "warehouse_verification",
                    "warehouse_verification": {
                        "status": "confirmed_not_missing",
                        "verification_ref": "WH-1",
                    },
                    "confidence": 1.0,
                }
            },
            {"full_review_ready": True, "missing_required": [], "warehouse_verification": {"status": "confirmed_not_missing"}},
        )

        self.assertEqual(readiness["status"], "complete")
        self.assertEqual(readiness["confidence"], 1.0)
        self.assertTrue(any(item["requirement_id"] == "warehouse_final_verification" for item in readiness["checklist"]))
        self.assertTrue(any(item["requirement_id"] == "expected_quantity_baseline" for item in readiness["checklist"]))
        self.assertFalse(any(item["requirement_id"] == "received_item_evidence" for item in readiness["checklist"]))

    def test_wrong_item_cannot_use_missing_item_warehouse_final_as_received_evidence(self) -> None:
        readiness = derive_material_readiness(
            {"scenario": "wrong_item", "metadata": {}, "assets": []},
            {
                "fulfillment_reconciliation": {
                    "evidence_sufficiency": "sufficient",
                    "resolution_basis": "warehouse_verification",
                    "warehouse_verification": {
                        "status": "confirmed_not_missing",
                        "verification_ref": "WH-WRONG-1",
                    },
                    "observed_items": [],
                    "package_observations": [],
                    "confidence": 1.0,
                }
            },
            {
                "full_review_ready": True,
                "missing_required": [],
                "warehouse_verification": {"status": "confirmed_not_missing"},
            },
        )

        self.assertEqual(readiness["status"], "incomplete")
        checks = {item["requirement_id"]: item for item in readiness["checklist"]}
        self.assertEqual(checks["received_item_evidence"]["status"], "invalid")
        self.assertEqual(checks["same_package_linkage"]["status"], "invalid")
        self.assertEqual(checks["received_item_evidence"]["evidence_refs"], [])

    def test_missing_item_requires_a_complete_user_evidence_route_without_warehouse_final(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "missing_item",
                "metadata": {},
                "assets": [{"asset_id": "RA-1", "mime_type": "image/jpeg", "size": 1234}],
            },
            {
                "fulfillment_reconciliation": {
                    "evidence_sufficiency": "insufficient",
                    "observed_items": [{
                        "product_name": "实收商品 A",
                        "evidence_refs": [{"asset_ref": "supplemental_image_1", "timestamp": None}],
                    }],
                    "confidence": 0.7,
                },
            },
            {
                "full_review_ready": False,
                "missing_required": ["complete_evidence_coverage", "all_expected_packages_delivered"],
            },
        )

        self.assertEqual(readiness["status"], "incomplete")
        ids = {item["requirement_id"] for item in readiness["checklist"]}
        self.assertIn("missing_item_user_evidence_route", ids)
        self.assertIn("all_expected_packages_delivered", ids)
        self.assertNotIn("same_package_linkage", ids)

    def test_missing_item_does_not_claim_delivery_status_when_trusted_snapshot_is_absent(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "missing_item",
                "metadata": {},
                "assets": [{"asset_id": "RA-1", "mime_type": "video/mp4", "size": 1234}],
            },
            {
                "fulfillment_reconciliation": {
                    "evidence_route": "insufficient",
                    "evidence_sufficiency": "insufficient",
                    "observed_items": [{
                        "product_name": "已看到的实收商品",
                        "evidence_refs": [{"asset_ref": "native_video_1", "timestamp": "00:10"}],
                    }],
                    "confidence": 0.8,
                },
            },
            {
                "full_review_ready": True,
                "missing_required": [],
                "fulfillment_readiness": {"all_expected_packages_delivered": False},
            },
        )

        checks = {item["requirement_id"]: item for item in readiness["checklist"]}
        delivery = checks["all_expected_packages_delivered"]
        self.assertEqual(delivery["status"], "missing")
        self.assertFalse(delivery["required"])
        self.assertIn("物流", delivery["reason"])
        self.assertNotIn(delivery["label"], readiness["missing_items"])

    def test_missing_item_static_three_images_are_user_material_complete_but_wait_for_warehouse(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "missing_item",
                "metadata": {},
                "assets": [
                    {"asset_id": f"RA-{index}", "mime_type": "image/jpeg", "size": 1234}
                    for index in range(1, 4)
                ],
            },
            {
                "fulfillment_reconciliation": {
                    "evidence_route": "static_three_images",
                    "user_materials_complete": True,
                    "evidence_sufficiency": "insufficient",
                    "observed_items": [{
                        "product_name": "全部到手实物",
                        "evidence_refs": [{
                            "asset_ref": "supplemental_image_1",
                            "timestamp": None,
                            "field": "observed_item",
                            "fact": "全家福可见全部到手实物。",
                        }],
                    }],
                    "package_observations": [{
                        "package_ref": "PKG-1",
                        "evidence_refs": [
                            {
                                "asset_ref": "supplemental_image_1",
                                "timestamp": None,
                                "field": "received_group_photo_complete",
                                "fact": "全家福完整。",
                            },
                            {
                                "asset_ref": "supplemental_image_2",
                                "timestamp": None,
                                "field": "green_bag_visible",
                                "fact": "绿色自封袋清晰可见。",
                            },
                            {
                                "asset_ref": "supplemental_image_3",
                                "timestamp": None,
                                "field": "waybill_visible",
                                "fact": "面单清晰可见。",
                            },
                        ],
                    }],
                    "confidence": 0.9,
                },
            },
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["status"], "complete")
        route = next(
            item for item in readiness["checklist"]
            if item["requirement_id"] == "missing_item_user_evidence_route"
        )
        self.assertEqual(route["status"], "present")
        self.assertIn("静态三类材料", route["reason"])
        self.assertTrue(any("仓库实发明细" in item for item in readiness["warnings"]))

    def test_missing_item_product_composition_resolution_is_complete_without_opening_video(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "missing_item",
                "metadata": {},
                "assets": [{"asset_id": "RA-1", "mime_type": "image/jpeg", "size": 1234}],
            },
            {
                "fulfillment_reconciliation": {
                    "evidence_route": "not_required",
                    "user_materials_complete": False,
                    "resolution_basis": "trusted_expected_item_resolution",
                    "evidence_sufficiency": "sufficient",
                    "verdict": "matched",
                    "product_composition_resolution": {
                        "claimed_item": "标题中的非独立应发描述",
                        "resolution_ref": "PRODUCT-COMPOSITION-1",
                        "reason": "可信商品规则确认该描述不是独立订单行。",
                    },
                    "observed_items": [{
                        "product_name": "订单商品本体",
                        "evidence_refs": [{"asset_ref": "supplemental_image_1", "fact": "实收本体可见。"}],
                    }],
                    "confidence": 0.88,
                },
            },
            {"full_review_ready": False, "missing_required": ["complete_evidence_coverage"]},
        )

        self.assertEqual(readiness["status"], "not_required")
        route = next(
            item for item in readiness["checklist"]
            if item["requirement_id"] == "missing_item_user_evidence_route"
        )
        self.assertEqual(route["status"], "not_applicable")
        self.assertIn("商品构成", route["reason"])

    def test_minor_five_usable_groups_are_complete_without_workflow_wording(self) -> None:
        checklist = [
            {
                "requirement_id": requirement_id,
                "label": label,
                "status": "present",
                "quality_status": "usable",
                "validation_status": "visual_consistency_matched",
                "evidence_image_indices": [index],
            }
            for index, (requirement_id, label) in enumerate((
                ("identity", "未成年人及监护人身份证明"),
                ("relationship", "监护关系证明"),
                ("commitment", "双方签字退款申请承诺书"),
                ("payment", "订单或支付凭证"),
                ("mobile_realname", "绑定手机号实名归属证明"),
            ), start=1)
        ]
        readiness = derive_material_readiness(
            {
                "scenario": "minor_refund",
                "metadata": {},
                "assets": [{"asset_id": f"RA-{index}", "mime_type": "image/jpeg", "size": 1234} for index in range(1, 6)],
            },
            {
                "confidence": 0.88,
                "minor_material_assessment": {
                    "processing_status": "completed",
                    "coverage_complete": True,
                    "checklist": checklist,
                },
            },
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["status"], "complete")
        self.assertEqual(readiness["missing_items"], [])
        self.assertNotIn("人工", readiness["reason"])
        self.assertNotIn("流程", readiness["reason"])

    def test_minor_under_ten_payment_process_gaps_are_part_of_material_readiness(self) -> None:
        checklist = [
            {
                "requirement_id": requirement_id,
                "label": label,
                "status": "present",
                "quality_status": "usable",
                "validation_status": "visual_consistency_matched",
                "evidence_image_indices": [index],
            }
            for index, (requirement_id, label) in enumerate((
                ("identity", "未成年人及监护人身份证明"),
                ("relationship", "监护关系证明"),
                ("commitment", "双方签字退款申请承诺书"),
                ("payment", "订单或支付凭证"),
                ("mobile_realname", "绑定手机号实名归属证明"),
            ), start=1)
        ]
        readiness = derive_material_readiness(
            {
                "scenario": "minor_refund",
                "metadata": {},
                "assets": [
                    {"asset_id": f"RA-{index}", "mime_type": "image/jpeg", "size": 1234}
                    for index in range(1, 6)
                ],
            },
            {
                "confidence": 0.9,
                "minor_material_assessment": {
                    "processing_status": "completed",
                    "coverage_complete": True,
                    "checklist": checklist,
                    "payment_capability_risk": {
                        "low_age": True,
                        "requires_more_material": True,
                        "evidence_image_indices": [1],
                    },
                    "field_consistency": {
                        "checks": [{
                            "check_id": "identity_age",
                            "low_age": True,
                            "field_results": [
                                {
                                    "field_name": "payment_password_access",
                                    "status": "uncertain",
                                    "evidence_image_indices": [1],
                                },
                                {
                                    "field_name": "guardian_discovery_process",
                                    "status": "not_assessed",
                                    "evidence_image_indices": [],
                                },
                            ],
                        }],
                    },
                },
            },
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["status"], "incomplete")
        process_checks = {
            item["requirement_id"]: item
            for item in readiness["checklist"]
            if item["requirement_id"] in {
                "payment_password_access_explanation",
                "guardian_discovery_process_explanation",
            }
        }
        self.assertEqual(set(process_checks), {
            "payment_password_access_explanation",
            "guardian_discovery_process_explanation",
        })
        self.assertTrue(all(item["required"] for item in process_checks.values()))
        self.assertTrue(all(item["status"] in {"missing", "invalid"} for item in process_checks.values()))
        self.assertIn("支付密码", "；".join(readiness["missing_items"]))
        self.assertIn("监护人如何、何时发现消费", "；".join(readiness["missing_items"]))

    def test_derive_reuses_real_review_inventory_snapshot(self) -> None:
        inventory = build_review_inventory({
            "scenario": "product_damage",
            "assets": [{"asset_id": "VIDEO-1", "mime_type": "video/mp4", "size": 1234}],
        }, media_forensics={
            "assets": [{
                "asset_id": "VIDEO-1",
                "status": "completed",
                "container": {"duration_seconds": 42.5},
            }],
        })

        with patch(
            "review_service.material_readiness.build_review_inventory",
            side_effect=AssertionError("不应降级重建已存在的盘点快照"),
        ):
            readiness = derive_material_readiness(
                {
                    "scenario": "product_damage",
                    "metadata": {"customer_claim": "商品表面有划痕"},
                    "assets": [{"asset_id": "VIDEO-1", "mime_type": "video/mp4", "size": 1234}],
                },
                {},
                {
                    "full_review_ready": True,
                    "missing_required": [],
                    "review_inventory": inventory,
                },
            )

        opening = next(
            item for item in readiness["checklist"]
            if item["requirement_id"] == "initial_opening_video"
        )
        self.assertEqual(opening["status"], "unknown")

    def test_minor_explicit_field_conflict_makes_material_invalid(self) -> None:
        checklist = [
            {
                "requirement_id": requirement_id,
                "label": label,
                "status": "present",
                "quality_status": "usable",
                "validation_status": (
                    "visual_consistency_mismatched"
                    if requirement_id == "relationship"
                    else "visual_consistency_matched"
                ),
                "evidence_image_indices": [index],
            }
            for index, (requirement_id, label) in enumerate(
                (
                    ("identity", "未成年人及监护人身份证明"),
                    ("relationship", "监护关系证明"),
                    ("commitment", "双方签字退款申请承诺书"),
                    ("payment", "订单或支付凭证"),
                    ("mobile_realname", "绑定手机号实名归属证明"),
                ),
                start=1,
            )
        ]

        readiness = derive_material_readiness(
            {
                "scenario": "minor_refund",
                "metadata": {},
                "assets": [
                    {"asset_id": f"RA-{index}", "mime_type": "image/jpeg", "size": 1234}
                    for index in range(1, 6)
                ],
            },
            {
                "minor_material_assessment": {
                    "processing_status": "completed",
                    "coverage_complete": True,
                    "field_consistency": {"verdict": "mismatched"},
                    "checklist": checklist,
                },
            },
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["status"], "incomplete")
        relationship = next(
            item for item in readiness["checklist"]
            if item["requirement_id"] == "relationship"
        )
        self.assertEqual(relationship["status"], "invalid")

    def test_minor_partial_checklist_cannot_be_reported_as_complete(self) -> None:
        readiness = derive_material_readiness(
            {
                "scenario": "minor_refund",
                "metadata": {},
                "assets": [{"asset_id": "RA-1", "mime_type": "image/jpeg", "size": 1234}],
            },
            {
                "confidence": 0.95,
                "minor_material_assessment": {
                    "processing_status": "completed",
                    "coverage_complete": True,
                    "checklist": [{
                        "requirement_id": "identity",
                        "label": "身份证明",
                        "status": "present",
                        "quality_status": "usable",
                        "evidence_image_indices": [1],
                    }],
                },
            },
            {"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(readiness["status"], "incomplete")
        self.assertEqual(len(readiness["missing_items"]), 4)


def test_public_contract_validates_material_readiness_shape() -> None:
    readiness = {
        "scenario": "wrong_item",
        "status": "complete",
        "confidence": 0.91,
        "reason": "应收基线与实收证据均可回看。",
        "checklist": [{
            "requirement_id": "received_item_evidence",
            "label": "实收商品身份与同包裹证据",
            "required": True,
            "status": "present",
            "source": "model",
            "confidence": 0.91,
            "evidence_refs": [{"asset_ref": "native_video_1", "timestamp": "00:08"}],
            "reason": "视频中可见实收商品。",
        }],
        "missing_items": [],
        "warnings": [],
    }

    payload = ReviewPayload(material_readiness=readiness)
    result = ReviewJobResult(material_readiness=readiness)

    assert payload.material_readiness.status == "complete"
    assert result.material_readiness.checklist[0].source == "model"


def test_actual_derived_material_readiness_validates_in_public_contract() -> None:
    job = {
        "scenario": "product_damage",
        "metadata": {"customer_claim": "商品表面有划痕"},
        "assets": [{"asset_id": "RA-1", "mime_type": "video/mp4", "size": 1234}],
    }
    readiness = derive_material_readiness(
        job,
        {},
        {"full_review_ready": True, "missing_required": []},
    )

    payload = ReviewPayload(material_readiness=readiness)
    result = ReviewJobResult(
        client_case_id="CASE-1",
        scenario="product_damage",
        material_readiness=readiness,
        input_readiness={"review_inventory": build_review_inventory(job)},
    )

    assert payload.material_readiness.status == "indeterminate"
    assert result.input_readiness["review_inventory"]["received_asset_count"] == 1
    assert "review_inventory" not in readiness


def test_fulfillment_material_readiness_without_model_confidence_is_publicly_serializable() -> None:
    readiness = derive_material_readiness(
        {
            "scenario": "missing_item",
            "metadata": {},
            "assets": [{"asset_id": "RA-1", "mime_type": "image/jpeg", "size": 1234}],
        },
        {
            "fulfillment_reconciliation": {
                "evidence_sufficiency": "insufficient",
                "observed_items": [],
                "package_observations": [],
                "evidence_route": "insufficient",
            }
        },
        {"full_review_ready": True, "missing_required": []},
    )

    payload = ReviewPayload(material_readiness=readiness)

    assert readiness["status"] == "incomplete"
    assert readiness["confidence"] == 0.0
    assert payload.material_readiness.confidence == 0.0


@pytest.mark.parametrize(
    "field,value",
    (
        ("scenario", "general"),
        ("status", "ready"),
        ("confidence", 1.2),
    ),
)
def test_public_contract_rejects_invalid_material_readiness(field: str, value: object) -> None:
    readiness = {
        "scenario": "product_damage",
        "status": "indeterminate",
        "confidence": 0.5,
        "reason": "待确认。",
        "checklist": [],
        "missing_items": [],
        "warnings": [],
    }
    readiness[field] = value

    with pytest.raises(ValidationError):
        ReviewPayload(material_readiness=readiness)


def test_public_contract_rejects_invalid_material_check_source() -> None:
    with pytest.raises(ValidationError):
        ReviewPayload(material_readiness={
            "scenario": "minor_refund",
            "status": "incomplete",
            "checklist": [{
                "requirement_id": "identity",
                "label": "身份材料",
            "required": True,
            "status": "missing",
            "source": "guess",
            "confidence": None,
            "evidence_refs": [],
            "reason": "本轮未收到身份材料。",
        }],
        "confidence": 0.5,
        "reason": "材料不齐全。",
        "missing_items": ["身份材料"],
        "warnings": [],
    })


def test_public_contract_rejects_empty_material_readiness_shell() -> None:
    with pytest.raises(ValidationError):
        ReviewPayload(material_readiness={})


if __name__ == "__main__":
    unittest.main()
