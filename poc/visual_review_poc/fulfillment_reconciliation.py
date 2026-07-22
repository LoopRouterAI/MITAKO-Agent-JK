from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _item_key(item: Dict[str, Any]) -> str:
    for key in ("sku", "barcode", "packaging_identifier", "item_ref"):
        if item.get(key):
            return f"{key}:{str(item[key]).strip().lower()}"
    name = str(item.get("product_name") or item.get("name") or "").strip().lower()
    spec = str(item.get("specification") or item.get("spec") or item.get("style") or "").strip().lower()
    return f"name:{name}|spec:{spec}" if name else ""


def _frontdesk(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    structured = case.get("structured_business_context") or {}
    package = structured.get("frontdesk_evidence_package") or {}
    asset_manifest = package.get("asset_manifest") or {}
    if not isinstance(asset_manifest, dict):
        asset_manifest = {}
    baseline = package.get("fulfillment_baseline") or asset_manifest.get("fulfillment_baseline") or {}
    coverage = package.get("evidence_coverage") or asset_manifest.get("evidence_coverage") or {}
    return (baseline if isinstance(baseline, dict) else {}, coverage if isinstance(coverage, dict) else {})


def aggregate_fulfillment_reconciliation(
    rows: Iterable[Dict[str, Any]],
    case: Dict[str, Any],
    scenario: str,
) -> Dict[str, Any]:
    rows = [row.get("fulfillment_reconciliation") or {} for row in rows]
    rows = [row for row in rows if isinstance(row, dict)]
    baseline, coverage = _frontdesk(case)
    expected = [dict(item) for item in baseline.get("expected_items") or [] if isinstance(item, dict)]
    package_quantities: Dict[Tuple[str, str], Dict[str, Any]] = {}
    unconfirmed: List[Any] = []
    package_observations: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        for item in row.get("observed_items") or []:
            if not isinstance(item, dict):
                continue
            key = _item_key(item)
            if not key:
                unconfirmed.append(item)
                continue
            package_ref = str(item.get("package_ref") or "unassigned")
            group = (package_ref, key)
            existing = package_quantities.get(group)
            quantity = _int(item.get("observed_quantity") or item.get("quantity") or 1)
            if not existing or quantity > _int(existing.get("observed_quantity")):
                package_quantities[group] = {**item, "observed_quantity": quantity, "package_ref": package_ref}
        unconfirmed.extend(row.get("unconfirmed_items") or [])
        for item in row.get("package_observations") or []:
            if not isinstance(item, dict) or not item.get("package_ref"):
                continue
            package_ref = str(item["package_ref"])
            current = package_observations.setdefault(
                package_ref,
                {"package_ref": package_ref, "opening_complete": False, "all_contents_laid_out": False, "evidence_timestamps": []},
            )
            current["opening_complete"] = current["opening_complete"] or item.get("opening_complete") is True
            current["all_contents_laid_out"] = current["all_contents_laid_out"] or item.get("all_contents_laid_out") is True
            current["evidence_timestamps"] = list(dict.fromkeys(
                current["evidence_timestamps"] + [str(value) for value in item.get("evidence_timestamps") or []]
            ))

    observed_by_key: Dict[str, Dict[str, Any]] = {}
    for (_, key), item in package_quantities.items():
        current = observed_by_key.setdefault(key, {**item, "observed_quantity": 0, "package_refs": []})
        current["observed_quantity"] += _int(item.get("observed_quantity"))
        current["package_refs"] = list(dict.fromkeys(current["package_refs"] + [item.get("package_ref")]))

    expected_keys = {_item_key(item): item for item in expected if _item_key(item)}
    missing = []
    for key, item in expected_keys.items():
        observed_quantity = _int((observed_by_key.get(key) or {}).get("observed_quantity"))
        expected_quantity = _int(item.get("expected_quantity") or item.get("quantity"))
        if observed_quantity < expected_quantity:
            missing.append({**item, "observed_quantity": observed_quantity})
    unexpected = [item for key, item in observed_by_key.items() if key not in expected_keys]

    expected_packages = {
        str(item.get("package_ref"))
        for item in baseline.get("packages") or []
        if isinstance(item, dict) and item.get("package_ref")
    }
    expected_tracking = {
        str(item.get("tracking_no"))
        for item in baseline.get("packages") or []
        if isinstance(item, dict) and item.get("tracking_no")
    }
    submitted_package_refs = {
        str(value) for value in coverage.get("submitted_package_refs") or [] if value
    }
    submitted_tracking_nos = {
        str(value) for value in coverage.get("submitted_tracking_nos") or [] if value
    }
    submitted_mapping_complete = bool(expected_packages) and (
        expected_packages.issubset(submitted_package_refs)
        or (bool(expected_tracking) and expected_tracking.issubset(submitted_tracking_nos))
    )
    observed_package_refs = {
        str(item.get("package_ref"))
        for item in package_quantities.values()
        if item.get("package_ref") and item.get("package_ref") != "unassigned"
    } | set(package_observations)
    unknown_package_refs = sorted(observed_package_refs - expected_packages)
    visually_complete_packages = {
        key
        for key, item in package_observations.items()
        if item.get("opening_complete") is True and item.get("all_contents_laid_out") is True
    }
    coverage_verified = bool(expected_packages) and expected_packages.issubset(visually_complete_packages)
    input_complete = (
        coverage.get("all_packages_uploaded") is True
        and coverage.get("all_items_displayed") is True
        and submitted_mapping_complete
    )
    baseline_ready = bool(baseline.get("baseline_version") and expected and expected_packages)
    selection_rules_applicable = bool(baseline.get("selection_rules"))
    selection_rules_ready = not selection_rules_applicable or baseline.get("selection_rules_complete") is True
    benefit_rules_ready = scenario != "missing_item" or baseline.get("benefit_rules_complete") is True
    evidence_sufficient = (
        baseline_ready
        and input_complete
        and coverage_verified
        and selection_rules_ready
        and benefit_rules_ready
        and not unconfirmed
        and not unknown_package_refs
    )
    mismatch = bool(missing or unexpected)
    verdict = "mismatched" if evidence_sufficient and mismatch else "matched" if evidence_sufficient else "indeterminate"
    observation_confidence = max((float(row.get("confidence") or 0) for row in rows), default=0.0)
    boundary = (
        "已完成版本化应发基准、全部包裹开箱和全部内容展示的视觉对账。"
        if evidence_sufficient
        else "应发基准、抽赏/赠品规则、包裹覆盖、全部内容展示或未确认项不完整，只能判为证据不足并人工复核。"
    )
    return {
        "baseline_version": baseline.get("baseline_version") or "",
        "expected_items": expected,
        "observed_items": list(observed_by_key.values()),
        "suspected_missing_items": missing,
        "unexpected_items": unexpected,
        "unconfirmed_items": unconfirmed[:100],
        "package_observations": list(package_observations.values()),
        "package_coverage": f"{len(visually_complete_packages)}/{len(expected_packages)} 个应发包裹完成开箱并铺开展示",
        "all_packages_uploaded": coverage.get("all_packages_uploaded") is True,
        "all_items_displayed": coverage.get("all_items_displayed") is True,
        "visual_coverage_verified": coverage_verified,
        "submitted_package_mapping_complete": submitted_mapping_complete,
        "selection_rules_complete": selection_rules_ready,
        "benefit_rules_complete": benefit_rules_ready,
        "unknown_package_refs": unknown_package_refs,
        "evidence_sufficiency": "sufficient" if evidence_sufficient else "insufficient",
        "verdict": verdict,
        "observation_confidence": observation_confidence,
        "confidence": observation_confidence if evidence_sufficient else 0.0,
        "decision_boundary": boundary,
        "scenario": scenario,
    }


def apply_fulfillment_guard(result: Dict[str, Any], scenario: str) -> Dict[str, Any]:
    output = dict(result)
    if scenario not in {"wrong_item", "missing_item"}:
        return output
    reconciliation = output.get("fulfillment_reconciliation") or {}
    verdict = reconciliation.get("verdict")
    sufficient = reconciliation.get("evidence_sufficiency") == "sufficient"
    label = "positive" if sufficient and verdict == "mismatched" else "negative" if sufficient and verdict == "matched" else "review"
    output["predicted_label"] = label
    output["system_yes_no"] = {"positive": "YES", "negative": "NO"}.get(label, "REVIEW")
    if label == "review":
        output["decision"] = "manual_review"
        try:
            output["confidence"] = min(float(output.get("confidence") or 0.5), 0.69)
        except (TypeError, ValueError):
            output["confidence"] = 0.5
        output["fulfillment_guard_reason"] = reconciliation.get("decision_boundary") or "履约证据不足，需人工复核。"
    else:
        output["fulfillment_guard_reason"] = "版本化应发基准与全部包裹视频展示已完成结构化对账。"
    return output
