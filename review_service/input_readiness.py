# -*- coding: utf-8 -*-
"""按审核场景评估结构化输入是否足以支撑完整判断。"""
from __future__ import annotations

from typing import Any, Dict, List


IDENTIFIER_KEYS = {"sku", "sku_id", "item_id", "product_id", "barcode", "gtin", "packaging_code"}
NAME_KEYS = {"name", "product_name", "item_name", "title"}
SPEC_KEYS = {"spec", "specification", "variant", "style", "size", "character"}


def _nonempty(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    return bool(str(value).strip()) if not isinstance(value, (list, dict)) else bool(value)


def _order_baseline_rows(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    fulfillment = metadata.get("fulfillment_baseline") or {}
    expected = fulfillment.get("expected_items") or [] if isinstance(fulfillment, dict) else []
    if expected:
        return [item for item in expected if isinstance(item, dict)]
    return [item for item in metadata.get("order_items") or [] if isinstance(item, dict)]


def _row_is_identifiable(row: Dict[str, Any]) -> bool:
    if any(_nonempty(row.get(key)) for key in IDENTIFIER_KEYS):
        return True
    return any(_nonempty(row.get(key)) for key in NAME_KEYS) and any(
        _nonempty(row.get(key)) for key in SPEC_KEYS
    )


def _has_order_baseline(metadata: Dict[str, Any]) -> bool:
    rows = _order_baseline_rows(metadata)
    return bool(rows) and all(_row_is_identifiable(row) for row in rows)


def _has_quantity(metadata: Dict[str, Any]) -> bool:
    fulfillment = metadata.get("fulfillment_baseline") or {}
    expected = fulfillment.get("expected_items") or [] if isinstance(fulfillment, dict) else []
    if expected:
        rows = [item for item in expected if isinstance(item, dict)]
        return len(rows) == len(expected) and all(_nonempty(item.get("expected_quantity")) for item in rows)
    order_items = [item for item in metadata.get("order_items") or [] if isinstance(item, dict)]
    return bool(order_items) and all(_nonempty(item.get("quantity")) for item in order_items)


def _fulfillment_state(metadata: Dict[str, Any]) -> Dict[str, bool]:
    baseline = metadata.get("fulfillment_baseline") or {}
    coverage = metadata.get("evidence_coverage") or {}
    if not isinstance(baseline, dict):
        baseline = {}
    if not isinstance(coverage, dict):
        coverage = {}
    expected_items = [item for item in baseline.get("expected_items") or [] if isinstance(item, dict)]
    item_refs = [str(item.get("item_ref") or "").strip() for item in expected_items]
    valid_item_refs = bool(item_refs) and all(item_refs) and len(item_refs) == len(set(item_refs))
    packages = [item for item in baseline.get("packages") or [] if isinstance(item, dict)]
    expected_count = int(baseline.get("expected_package_count") or 0)
    package_refs = [str(item.get("package_ref") or "").strip() for item in packages]
    valid_package_refs = (
        bool(expected_count)
        and len(packages) == expected_count
        and all(package_refs)
        and len(package_refs) == len(set(package_refs))
    )
    mapped_item_refs = [
        str(item_ref).strip()
        for package in packages
        for item_ref in package.get("expected_item_refs") or []
        if str(item_ref).strip()
    ]
    mapping_covers_expected = valid_item_refs and set(mapped_item_refs) == set(item_refs)
    mapping_has_no_duplicates = len(mapped_item_refs) == len(set(mapped_item_refs))
    linked_packages = (
        valid_package_refs
        and mapping_covers_expected
        and (mapping_has_no_duplicates or baseline.get("split_shipment") is True)
    )
    submitted_refs = {
        str(value).strip() for value in coverage.get("submitted_package_refs") or [] if str(value).strip()
    }
    expected_tracking = {
        str(item.get("tracking_no") or "").strip() for item in packages if str(item.get("tracking_no") or "").strip()
    }
    submitted_tracking = {
        str(value).strip() for value in coverage.get("submitted_tracking_nos") or [] if str(value).strip()
    }
    submitted_mapping_complete = linked_packages and (
        set(package_refs).issubset(submitted_refs)
        or (bool(expected_tracking) and expected_tracking.issubset(submitted_tracking))
    )
    return {
        "baseline_versioned": _nonempty(baseline.get("baseline_version")),
        "package_baseline_complete": linked_packages,
        "submitted_package_mapping_complete": submitted_mapping_complete,
        "benefit_rules_complete": baseline.get("benefit_rules_complete") is True,
        "selection_rules_complete": baseline.get("selection_rules_complete") is True,
        "all_packages_uploaded": coverage.get("all_packages_uploaded") is True,
        "all_items_displayed": coverage.get("all_items_displayed") is True,
    }


def assess_input_readiness(metadata: Dict[str, Any]) -> Dict[str, Any]:
    scenario = str(metadata.get("scenario") or "")
    missing_required: List[str] = []
    missing_recommended: List[str] = []
    alternatives: List[str] = []
    warnings: List[str] = []
    has_baseline = _has_order_baseline(metadata)
    has_product_master = bool(metadata.get("product_master_data"))
    fulfillment = _fulfillment_state(metadata)

    if not _nonempty(metadata.get("customer_claim")):
        missing_recommended.append("customer_claim")

    if scenario == "wrong_item":
        if not has_baseline:
            missing_required.append("order_item_baseline")
        if not _has_quantity(metadata):
            missing_required.append("all_expected_item_quantities")
        if not has_product_master:
            missing_recommended.append("product_master_data")
        if not fulfillment["baseline_versioned"]:
            missing_recommended.append("fulfillment_baseline.baseline_version")
        if not fulfillment["selection_rules_complete"]:
            missing_recommended.append("fulfillment_baseline.selection_rules_complete")
        alternatives.append("SKU/条码/包装编码任一唯一标识，或商品名+规格/款式/角色/数量的可唯一组合")
        warnings.append("缺少订单商品基准时仍可审核开箱连续性，但不能可靠判断是否发错货。")
    elif scenario == "missing_item":
        if not has_baseline:
            missing_required.append("order_item_baseline")
        if not _has_quantity(metadata):
            missing_required.append("all_expected_item_quantities")
        if not fulfillment["baseline_versioned"]:
            missing_required.append("fulfillment_baseline.baseline_version")
        if not fulfillment["package_baseline_complete"]:
            missing_required.append("package_item_mapping")
        if not fulfillment["benefit_rules_complete"]:
            missing_required.append("benefit_rules_declaration")
        if not fulfillment["submitted_package_mapping_complete"]:
            missing_required.append("submitted_package_mapping")
        if not fulfillment["all_packages_uploaded"] or not fulfillment["all_items_displayed"]:
            missing_required.append("complete_evidence_coverage")
        if not has_product_master:
            missing_recommended.append("product_master_data_or_standard_packing_list")
        alternatives.append("SKU/条码/包装编码或可唯一商品组合 + 每项应发数量 + 版本化规则 + 包裹关联")
        warnings.append("视频未完整展示全部包裹、商品、配件或赠品时只能输出证据不足并转人工，不能直接认定漏发。")
    elif scenario == "product_damage":
        if not has_product_master:
            missing_recommended.append("product_master_data")
        alternatives.append("SKU 不是判断可见损伤的前提；商品主图、材质、正常纹理、包装结构或质检标准均可作为参照")
        warnings.append("没有商品参照仍可判断明显破损和视频连续性，但细微纹理、反光与设计特征的置信度会降低。")
    elif scenario == "minor_refund":
        if not metadata.get("sop_context"):
            missing_recommended.append("sop_context")
        warnings.append("材料完整仅表示可进入人工审核，不代表自动通过退款。")

    full_review_ready = not missing_required
    capabilities = {
        "opening_continuity": True,
        "video_edit_risk": True,
        "visible_damage_detection": scenario == "product_damage",
        "damage_origin_assessment": scenario == "product_damage",
        "wrong_item_decision": scenario == "wrong_item" and full_review_ready,
        "missing_item_decision": scenario == "missing_item" and full_review_ready,
        "minor_material_review": scenario == "minor_refund",
    }
    return {
        "scenario": scenario,
        "status": "ready_for_full_review" if full_review_ready else "degraded_review",
        "full_review_ready": full_review_ready,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "accepted_alternatives": alternatives,
        "warnings": warnings,
        "capabilities": capabilities,
        "privacy_boundary": "审核不需要姓名、手机号、身份证号等用户隐私；订单侧数据按 SKU/商品基准/数量/规则最小化传递。",
        "fulfillment_readiness": fulfillment,
    }
