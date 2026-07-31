# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from pydantic import ValidationError

from review_service.schemas import ReviewMinorMaterialObservation


class ReviewMinorMaterialObservationTest(unittest.TestCase):
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
