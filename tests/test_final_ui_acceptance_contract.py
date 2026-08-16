# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "e2e" / "run_final_ui_acceptance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("final_ui_acceptance", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _acceptance_payload() -> dict:
    cases = []
    for scenario in ("product_damage", "wrong_item", "missing_item", "minor_refund"):
        for index in (1, 2):
            cases.append({
                "case_id": f"{scenario}-{index}",
                "scenario": scenario,
                "job_id": f"RJ-{scenario}-{index}",
                "report_json": f"tests/reports/review_0816_blind_{scenario}_{index}.json",
                "report_html": f"tests/reports/review_0816_blind_{scenario}_{index}.html",
                "evidence_preview": {
                    "video": scenario == "product_damage",
                    "image": scenario in {"wrong_item", "minor_refund"},
                    "warehouse": scenario == "missing_item",
                },
            })
    return {
        "contract_version": "MITAKO-FOUR-SCENE@20260814.1",
        "label_state": "sealed",
        "checks": {
            "all_required_random_cases_present": True,
            "all_current_business_contracts_valid": True,
            "api_html_same_job": True,
        },
        "cases": cases,
    }


def test_ui_acceptance_loads_two_sealed_blind_jobs_for_each_scene(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "review_0816_four_scenario_blind_results_latest.json"
    path.write_text(json.dumps(_acceptance_payload(), ensure_ascii=False), encoding="utf-8")

    cases = module._load_acceptance_cases(path)

    assert {case["scenario"] for case in cases} == set(module.SCENE_MARKERS)
    assert all("expected_label" not in case for case in cases)
    assert len(cases) == 8


@pytest.mark.parametrize("mutation", ("old_report", "missing_slot", "failed_gate", "duplicate_case"))
def test_ui_acceptance_rejects_stale_or_incomplete_manifest(tmp_path: Path, mutation: str) -> None:
    module = _load_module()
    payload = _acceptance_payload()
    if mutation == "old_report":
        payload["cases"][0]["report_json"] = "tests/reports/review_0809_old.json"
    elif mutation == "missing_slot":
        payload["cases"].pop()
    elif mutation == "failed_gate":
        payload["checks"]["api_html_same_job"] = False
    else:
        payload["cases"][-1] = dict(payload["cases"][0])
    path = tmp_path / "review_0816_four_scenario_blind_results_latest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        module._load_acceptance_cases(path)


def test_ui_acceptance_rejects_legacy_positive_negative_slots_even_when_old_checks_pass(tmp_path: Path) -> None:
    module = _load_module()
    payload = _acceptance_payload()
    payload.pop("contract_version")
    payload.pop("label_state")
    for case, label in zip(payload["cases"], ("positive", "negative") * 4):
        case["expected_label"] = label
        case["report_json"] = case["report_json"].replace("review_0816_blind_", "review_0813_")
        case["report_html"] = case["report_html"].replace("review_0816_blind_", "review_0813_")
    path = tmp_path / "review_0812_four_scenario_acceptance_latest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        module._load_acceptance_cases(path)


def test_ui_acceptance_source_has_scene_specific_markers_without_old_case_files() -> None:
    source = SCRIPT.read_text(encoding="utf-8-sig")

    assert "review_0816_four_scenario_blind_results_latest.json" in source
    assert "当前{scene_label}场景下的用户材料是否齐全" in source
    for marker in (
        "开箱视频九项核对",
        "发错货应收与实收核对",
        "漏发货应发与实收核对",
        "未成年人退款五类材料核对",
    ):
        assert marker in source
    assert "review_0809" not in source
    assert 'case.get("expected_label")' not in source
    assert "gemini36" not in source.lower()
    assert "598089" not in source
    assert "606669" not in source
    assert "568689" not in source


def test_ui_acceptance_writes_current_0816_qa_artifacts() -> None:
    module = _load_module()

    assert module.SCREENSHOT_DIR.name == "final_review_qa_20260816"
    source = SCRIPT.read_text(encoding="utf-8-sig")
    assert 'REPORT_DIR / "final_ui_qa_20260816.json"' in source
    assert "final_ui_qa_20260813" not in source


def test_timestamp_preview_is_required_by_actual_case_evidence_not_scenario() -> None:
    module = _load_module()

    assert module._requires_video_preview({"scenario": "product_damage", "evidence_preview": {"video": True}}) is True
    assert module._requires_video_preview({"scenario": "wrong_item", "evidence_preview": {"image": True}}) is False
    assert module._requires_video_preview({"scenario": "missing_item", "evidence_preview": {"warehouse": True}}) is False
    assert module._requires_video_preview({"scenario": "minor_refund", "evidence_preview": {"video": True}}) is True
    assert module._requires_media_preview({"evidence_preview": {"video": True}}) is True
    assert module._requires_media_preview({"evidence_preview": {"image": True}}) is True
    assert module._requires_media_preview({"evidence_preview": {"warehouse": True}}) is False


def test_business_rules_navigation_uses_the_control_rendered_for_each_viewport() -> None:
    module = _load_module()

    class Locator:
        def __init__(self, calls: list[tuple[str, str, str]], role: str, name: str) -> None:
            self.calls = calls
            self.role = role
            self.name = name

        def click(self) -> None:
            self.calls.append(("click", self.role, self.name))

        def select_option(self, value: str) -> None:
            self.calls.append(("select", self.name, value))

    class Page:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def get_by_role(self, role: str, *, name: str) -> Locator:
            return Locator(self.calls, role, name)

    desktop = Page()
    mobile = Page()

    module._open_business_rules(desktop, (1440, 1000))
    module._open_business_rules(mobile, (390, 844))

    assert desktop.calls == [("click", "button", "业务规则")]
    assert mobile.calls == [("select", "选择管理功能", "businessRules")]


def test_qa_screenshot_returns_to_the_first_viewport_and_masks_evidence_media(tmp_path: Path) -> None:
    module = _load_module()

    class Page:
        def __init__(self) -> None:
            self.calls = []
            self.mask = object()

        def evaluate(self, script: str) -> None:
            self.calls.append(("evaluate", script))

        def locator(self, selector: str):
            self.calls.append(("locator", selector))
            return self.mask

        def screenshot(self, **kwargs) -> None:
            self.calls.append(("screenshot", kwargs))

    page = Page()
    target = tmp_path / "qa.png"

    module._capture_qa_screenshot(page, target)

    assert page.calls[0] == ("evaluate", "window.scrollTo(0, 0)")
    assert page.calls[1] == ("locator", ".preview-trigger img")
    assert page.calls[2][0] == "screenshot"
    assert page.calls[2][1]["mask"] == [page.mask]
    assert page.calls[2][1]["animations"] == "disabled"
