# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from pydantic import ValidationError

from prompts.visual_review.response_validation import ModelResponseValidationError, validate_model_response
from prompts.visual_review.schemas import MINOR_MATERIAL_INVENTORY_RESPONSE_SCHEMA
from review_service.schemas import ReviewMinorMaterialObservation


class ReviewMinorMaterialObservationTest(unittest.TestCase):
    def test_order_payment_classification_fields_are_closed_enums(self) -> None:
        observation = ReviewMinorMaterialObservation.model_validate({
            "image_index": 1,
            "asset_ref": "supplemental_image_1",
            "document_type": "order_payment_proof",
            "document_types": ["order_payment_proof"],
            "subject_role": "not_applicable",
            "document_side": "page",
            "readability": "clear",
            "document_state": "filled",
            "sop_eligibility": "valid",
            "order_payment_evidence_type": "payment",
            "application_scope_coverage": "complete",
            "document_box_2d": [120, 80, 880, 920],
            "quality_issues": [],
            "editing_evidence_codes": [],
        })

        self.assertEqual(observation.order_payment_evidence_type, "payment")
        self.assertEqual(observation.application_scope_coverage, "complete")
        self.assertEqual(observation.document_box_2d, [120, 80, 880, 920])
        for field_name, invalid_value in (
            ("order_payment_evidence_type", "filename_guess"),
            ("application_scope_coverage", "assumed_complete"),
        ):
            payload = observation.model_dump(mode="json")
            payload[field_name] = invalid_value
            with self.subTest(field_name=field_name), self.assertRaises(ValidationError):
                ReviewMinorMaterialObservation.model_validate(payload)

    def test_inventory_response_schema_preserves_order_payment_classification(self) -> None:
        parsed = validate_model_response(
            {
                "schema_version": "minor_inventory_v2",
                "coverage_ack": {"expected_image_indices": [1], "observed_image_indices": [1]},
                "material_observations": [{
                    "image_index": 1,
                    "asset_ref": "supplemental_image_1",
                    "document_type": "order_payment_proof",
                    "subject_role": "not_applicable",
                    "document_side": "page",
                    "issuing_country_or_region": "unknown",
                    "readability": "clear",
                    "document_state": "filled",
                    "sop_eligibility": "valid",
                    "order_payment_evidence_type": "order",
                    "application_scope_coverage": "complete",
                    "document_box_2d": [120, 80, 880, 920],
                    "quality_issues": [],
                    "editing_evidence_codes": [],
                }],
                "batch_limitations": [],
            },
            MINOR_MATERIAL_INVENTORY_RESPONSE_SCHEMA,
        )

        observation = parsed["material_observations"][0]
        self.assertEqual(observation["order_payment_evidence_type"], "order")
        self.assertEqual(observation["application_scope_coverage"], "complete")
        self.assertEqual(observation["document_box_2d"], [120, 80, 880, 920])

    def test_inventory_response_requires_an_explicit_document_box(self) -> None:
        with self.assertRaises(ModelResponseValidationError):
            validate_model_response(
                {
                    "schema_version": "minor_inventory_v2",
                    "coverage_ack": {"expected_image_indices": [1], "observed_image_indices": [1]},
                    "material_observations": [{
                        "image_index": 1,
                        "asset_ref": "supplemental_image_1",
                        "document_type": "identity_card",
                        "subject_role": "guardian",
                        "document_side": "front",
                        "issuing_country_or_region": "unknown",
                        "readability": "clear",
                        "document_state": "filled",
                        "sop_eligibility": "valid",
                        "order_payment_evidence_type": "unknown",
                        "application_scope_coverage": "unknown",
                        "quality_issues": [],
                        "editing_evidence_codes": [],
                    }],
                    "batch_limitations": [],
                },
                MINOR_MATERIAL_INVENTORY_RESPONSE_SCHEMA,
            )

    def test_document_box_must_be_a_valid_normalized_rectangle(self) -> None:
        base = {
            "image_index": 1,
            "asset_ref": "supplemental_image_1",
            "document_type": "identity_card",
            "document_types": ["identity_card"],
            "subject_role": "guardian",
            "document_side": "front",
            "readability": "clear",
            "quality_issues": [],
        }

        for invalid_box in ([200, 100, 100, 900], [-1, 0, 500, 500], [0, 0, 1001, 1000], [0, 0, 500]):
            with self.subTest(box=invalid_box), self.assertRaises(ValidationError):
                ReviewMinorMaterialObservation.model_validate({**base, "document_box_2d": invalid_box})

    def test_passport_schema_keeps_only_structured_non_pii_fields(self) -> None:
        observation = ReviewMinorMaterialObservation.model_validate({
            "image_index": 1,
            "asset_ref": "supplemental_image_1",
            "document_type": "passport",
            "document_types": ["passport"],
            "subject_role": "minor",
            "document_side": "page",
            "issuing_country_or_region": "中国",
            "readability": "clear",
            "quality_issues": [],
        })

        self.assertEqual(observation.document_type, "passport")
        self.assertEqual(observation.issuing_country_or_region, "中国")

    def test_schema_rejects_private_or_unknown_output_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewMinorMaterialObservation.model_validate({
                "image_index": 1,
                "asset_ref": "supplemental_image_1",
                "document_type": "passport",
                "document_types": ["passport"],
                "subject_role": "minor",
                "document_side": "page",
                "issuing_country_or_region": "中国",
                "readability": "clear",
                "quality_issues": [],
                "passport_number": "E12345678",
            })


if __name__ == "__main__":
    unittest.main()
