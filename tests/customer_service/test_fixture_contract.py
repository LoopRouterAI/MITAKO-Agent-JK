# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "customer_agent_20260818_cases.json"


def test_fixture_has_fifteen_unique_cases() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["version"] == "MITAKO-CUSTOMER-CHAT-20260818.1"
    assert len(data["cases"]) == 15
    assert len({case["case_id"] for case in data["cases"]}) == 15
    required = {
        "case_id",
        "priority",
        "persona",
        "message",
        "expected_intent",
        "expected_scenario",
        "expected_core_conclusion",
        "expected_action_status",
        "expected_next_step",
        "forbidden_claims",
    }
    assert all(required <= set(case) for case in data["cases"])


def test_fixture_covers_all_reported_failures() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    covered = {case["expected_intent"] for case in cases}
    assert {
        "minor_refund_material",
        "product_consultation",
        "entitlement_missing",
        "product_damage",
        "wrong_item",
        "missing_item",
        "human_handoff",
        "high_risk_complaint",
        "address_change",
        "privacy_deletion",
    } <= covered


def test_p1_and_control_denominators_are_frozen() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    assert sum(case["priority"] == "P1" for case in cases) == 6
    assert sum(case["priority"] == "CONTROL" for case in cases) == 5
