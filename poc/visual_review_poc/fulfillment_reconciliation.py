from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Tuple

from review_service.warehouse_verification import trusted_warehouse_verification


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _confidence(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return max(0.0, min(parsed, 1.0))


def _item_spec(item: Dict[str, Any]) -> str:
    return str(item.get("specification") or item.get("spec") or item.get("style") or "").strip().lower()


def _item_base_key(item: Dict[str, Any]) -> str:
    for key in ("sku", "barcode", "packaging_identifier", "item_ref"):
        if item.get(key):
            return f"{key}:{str(item[key]).strip().lower()}"
    name = str(item.get("product_name") or item.get("name") or "").strip().lower()
    return f"name:{name}" if name else ""


def _item_key(item: Dict[str, Any]) -> str:
    base = _item_base_key(item)
    spec = _item_spec(item)
    return f"{base}|spec:{spec}" if base and spec else base


def _quantity(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


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
    expected_by_key: Dict[str, Dict[str, Any]] = {}
    unkeyed_expected: List[Dict[str, Any]] = []
    baseline_quantity_valid = True
    for source_item in baseline.get("expected_items") or []:
        if not isinstance(source_item, dict):
            continue
        item = dict(source_item)
        key = _item_key(item)
        if not key:
            unkeyed_expected.append(item)
            continue
        current = expected_by_key.setdefault(
            key,
            {**item, "expected_quantity": 0, "item_refs": []},
        )
        raw_quantity = item.get("expected_quantity")
        if raw_quantity in (None, ""):
            raw_quantity = item.get("quantity")
        quantity = _quantity(raw_quantity)
        if quantity is None:
            baseline_quantity_valid = False
            quantity = 0
        current["expected_quantity"] += quantity
        if item.get("item_ref"):
            current["item_refs"] = list(dict.fromkeys(current["item_refs"] + [str(item["item_ref"])]))
    expected = list(expected_by_key.values()) + unkeyed_expected
    expected_keys_by_base: Dict[str, List[str]] = {}
    for key, item in expected_by_key.items():
        expected_keys_by_base.setdefault(_item_base_key(item), []).append(key)
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
            candidate_keys = expected_keys_by_base.get(_item_base_key(item), [])
            if key not in expected_by_key and candidate_keys and (
                not _item_spec(item)
                or any(not _item_spec(expected_by_key[candidate]) for candidate in candidate_keys)
            ):
                unconfirmed.append({**item, "reason": "specification_unconfirmed"})
                continue
            package_ref = str(item.get("package_ref") or "unassigned")
            group = (package_ref, key)
            existing = package_quantities.get(group)
            raw_quantity = item.get("observed_quantity")
            if raw_quantity in (None, ""):
                raw_quantity = item.get("quantity")
            quantity = _quantity(1 if raw_quantity in (None, "") else raw_quantity)
            if quantity is None:
                unconfirmed.append({**item, "reason": "invalid_observed_quantity"})
                continue
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
    baseline_ready = bool(
        baseline.get("baseline_version") and expected and expected_packages and baseline_quantity_valid
    )
    selection_rules_applicable = bool(baseline.get("selection_rules"))
    selection_rules_ready = not selection_rules_applicable or baseline.get("selection_rules_complete") is True
    benefit_rules_ready = scenario != "missing_item" or baseline.get("benefit_rules_complete") is True
    scenario_coverage_verified = coverage_verified or (
        scenario == "wrong_item" and bool(observed_by_key)
    )
    visual_evidence_sufficient = (
        baseline_ready
        and input_complete
        and scenario_coverage_verified
        and selection_rules_ready
        and benefit_rules_ready
        and not unconfirmed
        and not unknown_package_refs
    )
    warehouse_verification = (
        trusted_warehouse_verification(baseline) if scenario == "missing_item" else {}
    )
    evidence_sufficient = bool(warehouse_verification) or visual_evidence_sufficient
    wrong_item_signal_in_missing_scene = bool(
        scenario == "missing_item" and missing and unexpected and not warehouse_verification
    )
    mismatch = (
        warehouse_verification.get("status") == "confirmed_missing"
        if warehouse_verification
        else bool(missing) if scenario == "missing_item" else bool(missing and unexpected)
    )
    verdict = (
        "indeterminate"
        if wrong_item_signal_in_missing_scene
        else "mismatched" if evidence_sufficient and mismatch
        else "matched" if evidence_sufficient
        else "indeterminate"
    )
    observation_confidence = max((_confidence(row.get("confidence")) for row in rows), default=0.0)
    boundary = (
        "甲方已提供可追溯的仓库终核，历史待核实备注不覆盖该终态。"
        if warehouse_verification
        else "同时存在应发商品缺少和未购商品多出的视觉线索，更符合错发场景；本轮不直接认定漏发。"
        if wrong_item_signal_in_missing_scene
        else "已完成版本化应发基准、实收商品身份、包裹映射与全家福证据链核对。"
        if scenario == "wrong_item" and visual_evidence_sufficient and not coverage_verified
        else "已完成版本化应发基准、全部包裹开箱和全部内容展示的视觉对账。"
        if visual_evidence_sufficient
        else "应发基准、抽赏/赠品规则、包裹覆盖、全部内容展示或未确认项不完整，应先补齐可获得的材料再复核。"
    )
    return {
        "baseline_version": baseline.get("baseline_version") or "",
        "expected_items": expected,
        "observed_items": list(observed_by_key.values()),
        "suspected_missing_items": missing,
        "unexpected_items": unexpected,
        "unconfirmed_items": unconfirmed[:100],
        "package_observations": list(package_observations.values()),
        "package_coverage": (
            "仓库终核已覆盖本案履约事实；本轮不以开箱视频数量作为结论门槛"
            if warehouse_verification
            else f"{len(visually_complete_packages)}/{len(expected_packages)} 个应发包裹完成开箱并铺开展示"
        ),
        "all_packages_uploaded": coverage.get("all_packages_uploaded") is True,
        "all_items_displayed": coverage.get("all_items_displayed") is True,
        "visual_coverage_verified": coverage_verified,
        "submitted_package_mapping_complete": submitted_mapping_complete,
        "selection_rules_complete": selection_rules_ready,
        "benefit_rules_complete": benefit_rules_ready,
        "unknown_package_refs": unknown_package_refs,
        "warehouse_verification": warehouse_verification,
        "resolution_basis": "warehouse_verification" if warehouse_verification else "visual_reconciliation",
        "evidence_sufficiency": "sufficient" if evidence_sufficient else "insufficient",
        "verdict": verdict,
        "observation_confidence": observation_confidence,
        "confidence": 1.0 if warehouse_verification else observation_confidence if evidence_sufficient else 0.0,
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
        output["decision"] = "request_more_material"
        output["confidence"] = min(_confidence(output.get("confidence")), 0.69)
        output["fulfillment_guard_reason"] = reconciliation.get("decision_boundary") or "履约证据不足，应先补齐可获得的材料。"
    elif reconciliation.get("resolution_basis") == "warehouse_verification":
        boundary = reconciliation.get("decision_boundary") or "甲方仓库已提供可追溯终核。"
        warehouse = reconciliation.get("warehouse_verification") or {}
        warehouse_status = warehouse.get("status")
        warehouse_fact = (
            "甲方可追溯仓库终核确认实收商品与应发商品一致，本案确定未漏发。"
            if warehouse_status == "confirmed_not_missing"
            else "甲方可追溯仓库终核确认本案存在漏发。"
        )
        reconciliation = dict(reconciliation)
        if warehouse_status == "confirmed_not_missing":
            reconciliation["suspected_missing_items"] = []
        output["fulfillment_reconciliation"] = reconciliation
        output["confidence"] = _confidence(reconciliation.get("confidence"))
        output["fulfillment_guard_reason"] = boundary
        output["confidence_reason"] = boundary
        output["business_follow_up_reason"] = boundary
        output["next_step"] = (
            "按甲方仓库终核结果继续处理，本轮无需因开箱材料重复补件或人工复核。"
            if label == "negative"
            else "按甲方仓库终核结果继续处理；具体补发、退款等业务动作由甲方授权系统或人员决定。"
        )
        output["visual_evidence_verdict"] = warehouse_fact
        output["overall_audit"] = {
            "conclusion": warehouse_fact,
            "confidence": output["confidence"],
            "core_reason": boundary,
            "business_follow_up_suggestion": output["next_step"],
        }
        claim_fact_assessment = output.get("claim_fact_assessment")
        if isinstance(claim_fact_assessment, dict):
            claim_fact_assessment = dict(claim_fact_assessment)
            claim_fact_assessment["atomic_claim_results"] = [
                {
                    **item,
                    "support_status": (
                        "not_supported" if warehouse_status == "confirmed_not_missing" else "supported"
                    ),
                    "reason": warehouse_fact,
                    "evidence_refs": [{
                        "source_type": "warehouse_verification",
                        "asset_ref": warehouse.get("verification_ref") or "warehouse_verification",
                        "fact": warehouse_fact,
                    }],
                }
                for item in claim_fact_assessment.get("atomic_claim_results") or []
                if isinstance(item, dict)
            ]
            output["claim_fact_assessment"] = claim_fact_assessment
        warehouse_evidence = {
            "source_type": "warehouse_verification",
            "asset_ref": warehouse.get("verification_ref") or "warehouse_verification",
            "fact": warehouse_fact,
            "why_it_matters": "可信仓库终核覆盖历史待核实备注，并决定本案履约事实。",
            "confidence": output["confidence"],
        }
        output["adopted_evidence"] = [warehouse_evidence] + [
            item for item in output.get("adopted_evidence") or []
            if isinstance(item, dict) and item.get("source_type") != "warehouse_verification"
        ]
    else:
        output["fulfillment_guard_reason"] = "版本化应发基准与全部包裹视频展示已完成结构化对账。"
    return output
