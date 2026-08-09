# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_blind_damage_regression import (
    blind_case_id,
    internal_metrics_fields,
    internal_metrics_headers,
    technical_scenario,
)


class BlindRegressionRoutingTest(unittest.TestCase):
    def test_internal_metrics_headers_require_existing_signing_secret(self) -> None:
        with patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "secret-value"}, clear=False):
            headers = internal_metrics_headers()

        self.assertEqual(headers["X-MITAKO-Internal-Metrics"], "1")
        self.assertEqual(headers["X-MITAKO-Internal-Token"], "secret-value")

    def test_internal_metrics_request_declares_trusted_mitako_rule_tenant(self) -> None:
        with patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "secret-value"}, clear=False):
            fields = internal_metrics_fields()

        self.assertEqual(fields, {"rule_tenant_id": "mitako"})

    def test_business_scenarios_use_matching_technical_pipeline(self) -> None:
        self.assertEqual(technical_scenario("product_damage"), "product_damage")
        self.assertEqual(technical_scenario("wrong_item"), "video_unboxing")
        self.assertEqual(technical_scenario("missing_item"), "video_unboxing")
        self.assertEqual(technical_scenario("minor_refund"), "minor_material")

    def test_case_id_does_not_expose_source_folder_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="正样本_人工通过_") as temp_dir:
            case_id = blind_case_id(Path(temp_dir))

        self.assertRegex(case_id, r"^CASE-[A-F0-9]{12}$")
        self.assertNotIn("正样本", case_id)


if __name__ == "__main__":
    unittest.main()
