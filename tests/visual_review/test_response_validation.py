# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from prompts.visual_review.response_validation import (
    ModelResponseValidationError,
    validate_model_response,
)


class ModelResponseValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["pass", "review"]},
                "confidence": {"type": "number", "nullable": True},
                "evidence": {
                    "type": "array",
                    "maxItems": 2,
                    "items": {
                        "type": "object",
                        "properties": {
                            "asset_ref": {"type": "string"},
                            "visible": {"type": "boolean"},
                        },
                        "required": ["asset_ref", "visible"],
                    },
                },
            },
            "required": ["verdict", "confidence", "evidence"],
        }

    def test_valid_output_is_returned_without_model_added_fields(self) -> None:
        value = validate_model_response(
            {
                "verdict": "pass",
                "confidence": 0.91,
                "evidence": [{"asset_ref": "native_video_1", "visible": True, "guess": "x"}],
                "business_action": "refund",
            },
            self.schema,
        )

        self.assertEqual(
            value,
            {
                "verdict": "pass",
                "confidence": 0.91,
                "evidence": [{"asset_ref": "native_video_1", "visible": True}],
            },
        )

    def test_missing_required_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(ModelResponseValidationError, "confidence"):
            validate_model_response(
                {"verdict": "pass", "evidence": []},
                self.schema,
            )

    def test_wrong_type_and_enum_are_rejected_without_coercion(self) -> None:
        for value in (
            {"verdict": "approved", "confidence": 0.9, "evidence": []},
            {"verdict": "pass", "confidence": "0.9", "evidence": []},
            {"verdict": "pass", "confidence": 0.9, "evidence": "native_video_1"},
        ):
            with self.subTest(value=value), self.assertRaises(ModelResponseValidationError):
                validate_model_response(value, self.schema)

    def test_nullable_and_array_limit_are_enforced(self) -> None:
        self.assertIsNone(
            validate_model_response(
                {"verdict": "review", "confidence": None, "evidence": []},
                self.schema,
            )["confidence"]
        )
        with self.assertRaisesRegex(ModelResponseValidationError, "maxItems"):
            validate_model_response(
                {
                    "verdict": "pass",
                    "confidence": 0.9,
                    "evidence": [
                        {"asset_ref": "a", "visible": True},
                        {"asset_ref": "b", "visible": True},
                        {"asset_ref": "c", "visible": True},
                    ],
                },
                self.schema,
            )

    def test_fulfillment_scene_version_cannot_cross_between_schemas(self) -> None:
        from prompts.visual_review.schemas import (
            MISSING_ITEM_OBSERVATION_RESPONSE_SCHEMA,
            WRONG_ITEM_OBSERVATION_RESPONSE_SCHEMA,
        )

        value = {
            "schema_version": "wrong_item_observation_v2",
            "confidence": 0.8,
            "fulfillment_reconciliation": {
                "observed_items": [],
                "unconfirmed_items": [],
                "package_observations": [],
                "confidence": 0.8,
                "observation_reason": "未观察到可确认实物。",
            },
        }
        self.assertEqual(
            validate_model_response(value, WRONG_ITEM_OBSERVATION_RESPONSE_SCHEMA)["schema_version"],
            "wrong_item_observation_v2",
        )
        with self.assertRaisesRegex(ModelResponseValidationError, "schema_version"):
            validate_model_response(value, MISSING_ITEM_OBSERVATION_RESPONSE_SCHEMA)


if __name__ == "__main__":
    unittest.main()
