# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_blind_damage_regression import blind_case_id, technical_scenario


class BlindRegressionRoutingTest(unittest.TestCase):
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
