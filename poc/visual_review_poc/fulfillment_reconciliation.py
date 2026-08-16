from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Tuple

from review_service.warehouse_verification import trusted_warehouse_verification


PACKAGE_OBSERVATION_FIELDS = (
    "sealed_start",
    "waybill_visible",
    "waybill_matches_order",
    "single_take_continuity",
    "opening_complete",
    "all_contents_laid_out",
    "received_group_photo_complete",
    "green_bag_visible",
)
OPENING_VIDEO_ROUTE_FIELDS = (
    "sealed_start",
    "waybill_visible",
    "waybill_matches_order",
    "single_take_continuity",
    "opening_complete",
    "all_contents_laid_out",
)
STATIC_REVIEW_ROUTE_FIELDS = (
    "green_bag_visible",
    "waybill_visible",
    "waybill_matches_order",
)
TRUSTED_COMPOSITION_SOURCES = {
    "order_system",
    "product_master",
    "versioned_activity_rule",
}
IDENTITY_DEFINING_FIELDS = (
    "specification",
    "item_role",
    "series",
    "edition",
    "physical_form",
    "included_parts",
)


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
    value = str(item.get("specification") or item.get("spec") or item.get("style") or "").strip().lower()
    if value in {"-", "--", "—", "——", "–", "/", "n/a", "na", "none", "null", "无", "未提供", "不适用"}:
        return ""
    return value


def _identity_value(item: Dict[str, Any], field: str) -> str:
    if field == "specification":
        return _item_spec(item)
    value = item.get(field)
    if isinstance(value, (list, tuple, set)):
        return "|".join(sorted(
            str(part).strip().lower() for part in value if str(part).strip()
        ))
    return str(value or "").strip().lower()


def _item_base_key(item: Dict[str, Any]) -> str:
    for key in ("sku", "barcode", "packaging_identifier", "item_ref"):
        if item.get(key):
            return f"{key}:{str(item[key]).strip().lower()}"
    name = str(item.get("product_name") or item.get("name") or "").strip().lower()
    return f"name:{name}" if name else ""


def _item_key(item: Dict[str, Any]) -> str:
    base = _item_base_key(item)
    identity = [
        f"{field}:{value}"
        for field in IDENTITY_DEFINING_FIELDS
        if (value := _identity_value(item, field))
    ]
    return "|".join([base, *identity]) if base else ""


def _identity_match(expected: Dict[str, Any], observed: Dict[str, Any]) -> str:
    unknown = False
    for field in IDENTITY_DEFINING_FIELDS:
        expected_value = _identity_value(expected, field)
        if not expected_value:
            continue
        observed_value = _identity_value(observed, field)
        if not observed_value:
            unknown = True
        elif observed_value != expected_value:
            return "mismatch"
    return "unknown" if unknown else "match"


def _is_gift_item(item: Dict[str, Any]) -> bool:
    return item.get("is_gift") is True or any(
        str(item.get(field) or "").strip().lower() in {
            "gift", "free_gift", "promotion_gift", "promotional_gift", "bonus",
        }
        for field in ("item_role", "obligation_type")
    )


def _quantity(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _submitted_asset_refs(case: Dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for video in case.get("videos") or []:
        if not isinstance(video, dict):
            continue
        video_index = video.get("video_index")
        asset_ref = str(video.get("asset_ref") or "").strip()
        if asset_ref:
            refs.add(asset_ref)
        if video_index not in (None, ""):
            refs.add(f"native_video_{video_index}")
    for frame in case.get("frames") or []:
        if not isinstance(frame, dict):
            continue
        asset_ref = str(frame.get("asset_ref") or "").strip()
        video_index = frame.get("video_index")
        frame_index = frame.get("global_frame_index")
        if asset_ref:
            refs.add(asset_ref)
        if video_index not in (None, "") and frame_index not in (None, ""):
            refs.add(f"video_{video_index}_frame_{frame_index}")
    for image in case.get("supplemental_images") or []:
        if not isinstance(image, dict):
            continue
        image_index = image.get("image_index")
        asset_ref = str(image.get("asset_ref") or "").strip()
        if asset_ref:
            refs.add(asset_ref)
        if image_index not in (None, ""):
            refs.add(f"supplemental_image_{image_index}")
    return refs


def _valid_evidence_refs(value: Any, allowed_asset_refs: set[str]) -> List[Dict[str, Any]]:
    refs = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        asset_ref = str(item.get("asset_ref") or "").strip()
        fact = str(item.get("fact") or "").strip()
        timestamp = str(item.get("timestamp") or "").strip()
        source_is_reviewable = asset_ref in allowed_asset_refs
        if source_is_reviewable and fact and (
            not asset_ref.startswith(("native_video_", "video_")) or timestamp
        ):
            refs.append({
                "asset_ref": asset_ref,
                "timestamp": timestamp or None,
                "field": str(item.get("field") or "").strip(),
                "fact": fact,
                "observed_identifier": (
                    str(item.get("observed_identifier") or "").strip() or None
                ),
            })
    return refs


def _waybill_match_from_observed_identifier(
    observation: Dict[str, Any],
    package_ref: str,
    identifiers_by_package: Dict[str, Iterable[Any]],
    observed_identifiers: Iterable[Any] = (),
) -> bool | None:
    candidates = {
        candidate_package: {
            normalized
            for value in values
            if len(normalized := "".join(
                char.lower() for char in str(value or "") if char.isalnum()
            )) >= 4
        }
        for candidate_package, values in identifiers_by_package.items()
    }
    observed = {
        normalized
        for value in observed_identifiers
        if len(normalized := "".join(
            char.lower() for char in str(value or "") if char.isalnum()
        )) >= 4
    } | {
        normalized
        for ref in observation.get("evidence_refs") or []
        if isinstance(ref, dict)
        and ref.get("field") == "waybill_observed_identifier"
        if len(normalized := "".join(
            char.lower()
            for char in str(ref.get("observed_identifier") or "")
            if char.isalnum()
        )) >= 4
    }
    if not candidates.get(package_ref) or not observed:
        return None
    if len(observed) != 1:
        return None
    matched_packages = {
        candidate_package
        for token in observed
        for candidate_package, identifiers in candidates.items()
        if token in identifiers
    }
    if not matched_packages or package_ref not in matched_packages:
        return False
    return True if matched_packages == {package_ref} else None


def _field_has_evidence(observation: Dict[str, Any], field: str, source: str) -> bool:
    for ref in observation.get("evidence_refs") or []:
        if not isinstance(ref, dict) or ref.get("field") != field:
            continue
        asset_ref = str(ref.get("asset_ref") or "")
        if source == "video" and asset_ref.startswith(("native_video_", "video_")):
            return True
        if source == "image" and asset_ref.startswith("supplemental_image_"):
            return True
    return False


def _package_route_complete(
    observation: Dict[str, Any],
    fields: Tuple[str, ...],
    source: str,
) -> bool:
    return all(
        observation.get(field) is True and _field_has_evidence(observation, field, source)
        for field in fields
    )


def _frontdesk(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    structured = case.get("structured_business_context") or {}
    package = structured.get("frontdesk_evidence_package") or {}
    asset_manifest = package.get("asset_manifest") or {}
    if not isinstance(asset_manifest, dict):
        asset_manifest = {}
    baseline = package.get("fulfillment_baseline") or asset_manifest.get("fulfillment_baseline") or {}
    coverage = package.get("evidence_coverage") or asset_manifest.get("evidence_coverage") or {}
    return (baseline if isinstance(baseline, dict) else {}, coverage if isinstance(coverage, dict) else {})


def _trusted_product_composition_resolution(
    baseline: Dict[str, Any],
    expected_by_key: Dict[str, Dict[str, Any]],
    observed_by_key: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    resolution = baseline.get("claim_expected_item_resolution")
    if not isinstance(resolution, dict):
        return {}
    if (
        resolution.get("is_expected") is not False
        or resolution.get("source") not in TRUSTED_COMPOSITION_SOURCES
        or str(resolution.get("baseline_version") or "") != str(baseline.get("baseline_version") or "")
        or not str(resolution.get("resolution_ref") or "").strip()
        or not str(resolution.get("claimed_item") or "").strip()
        or not str(resolution.get("reason") or "").strip()
    ):
        return {}
    required_refs = {
        str(item).strip()
        for item in resolution.get("required_received_item_refs") or []
        if str(item).strip()
    }
    if not required_refs:
        return {}
    expected_keys_for_ref: Dict[str, str] = {}
    for key, item in expected_by_key.items():
        item_refs = [str(ref) for ref in item.get("item_refs") or []]
        if item.get("item_ref"):
            item_refs.append(str(item["item_ref"]))
        for item_ref in item_refs:
            expected_keys_for_ref[item_ref] = key
    if not required_refs.issubset(expected_keys_for_ref):
        return {}
    for item_ref in required_refs:
        key = expected_keys_for_ref[item_ref]
        expected_quantity = _int(expected_by_key[key].get("expected_quantity"))
        observed_quantity = _int((observed_by_key.get(key) or {}).get("observed_quantity"))
        if expected_quantity <= 0 or observed_quantity < expected_quantity:
            return {}
    return {
        "claimed_item": str(resolution["claimed_item"]).strip(),
        "is_expected": False,
        "baseline_version": str(resolution["baseline_version"]),
        "source": str(resolution["source"]),
        "resolution_ref": str(resolution["resolution_ref"]).strip(),
        "reason": str(resolution["reason"]).strip(),
        "required_received_item_refs": sorted(required_refs),
    }


def aggregate_fulfillment_reconciliation(
    rows: Iterable[Dict[str, Any]],
    case: Dict[str, Any],
    scenario: str,
) -> Dict[str, Any]:
    rows = [row.get("fulfillment_reconciliation") or {} for row in rows]
    rows = [row for row in rows if isinstance(row, dict)]
    baseline, coverage = _frontdesk(case)
    allowed_asset_refs = _submitted_asset_refs(case)
    waybill_identifiers_by_package = {
        str(package["package_ref"]): (
            package.get("tracking_no"),
            package.get("order_reference"),
        )
        for package in baseline.get("packages") or []
        if isinstance(package, dict) and package.get("package_ref")
    }
    package_refs_by_item_ref: Dict[str, List[str]] = {}
    for package in baseline.get("packages") or []:
        if not isinstance(package, dict) or not package.get("package_ref"):
            continue
        package_ref = str(package["package_ref"])
        for item_ref in package.get("expected_item_refs") or []:
            normalized_ref = str(item_ref).strip()
            if normalized_ref:
                package_refs_by_item_ref.setdefault(normalized_ref, []).append(package_ref)
    expected_by_key: Dict[str, Dict[str, Any]] = {}
    expected_source_rows: List[Tuple[Dict[str, Any], str, int]] = []
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
        expected_source_rows.append((item, key, quantity))
    expected = list(expected_by_key.values()) + unkeyed_expected
    expected_keys_by_base: Dict[str, List[str]] = {}
    for key, item in expected_by_key.items():
        expected_keys_by_base.setdefault(_item_base_key(item), []).append(key)
    package_expected_candidates: Dict[Tuple[str, str], Dict[str, Any]] = {}
    package_assignment_totals: Dict[str, int] = {}
    unresolved_package_keys = set()
    for item, key, quantity in expected_source_rows:
        direct_package_ref = str(item.get("package_ref") or "").strip()
        package_refs = [direct_package_ref] if direct_package_ref else package_refs_by_item_ref.get(
            str(item.get("item_ref") or "").strip(), []
        )
        package_refs = list(dict.fromkeys(package_refs))
        if len(package_refs) == 1:
            quantity_per_package = quantity
        elif package_refs and quantity > 0 and quantity % len(package_refs) == 0:
            quantity_per_package = quantity // len(package_refs)
        else:
            unresolved_package_keys.add(key)
            continue
        for package_ref in package_refs:
            group = (package_ref, key)
            current = package_expected_candidates.setdefault(
                group,
                {**expected_by_key[key], "package_ref": package_ref, "expected_quantity": 0},
            )
            current["expected_quantity"] += quantity_per_package
            package_assignment_totals[key] = package_assignment_totals.get(key, 0) + quantity_per_package
    package_scoped_keys = {
        key
        for key, assigned_quantity in package_assignment_totals.items()
        if key not in unresolved_package_keys
        and assigned_quantity == _int(expected_by_key[key].get("expected_quantity"))
    }
    expected_by_package = {
        group: item
        for group, item in package_expected_candidates.items()
        if group[1] in package_scoped_keys
    }
    package_quantities: Dict[Tuple[str, str], Dict[str, Any]] = {}
    unconfirmed: List[Any] = []
    package_observations: Dict[str, Dict[str, Any]] = {}
    package_flag_values: Dict[str, Dict[str, set[bool]]] = {}
    package_confidence_values: Dict[str, List[float]] = {}
    package_reasons: Dict[str, List[str]] = {}
    package_observed_waybill_identifiers: Dict[str, set[str]] = {}
    evidence_conflicts: List[Dict[str, Any]] = []

    for row in rows:
        row_confidence = _confidence(row.get("confidence"))
        row_reason = str(row.get("observation_reason") or "").strip()
        for item in row.get("observed_items") or []:
            if not isinstance(item, dict):
                continue
            evidence_refs = _valid_evidence_refs(item.get("evidence_refs"), allowed_asset_refs)
            if not evidence_refs:
                unconfirmed.append({**item, "reason": "missing_reviewable_evidence_ref"})
                continue
            key = _item_key(item)
            if not key:
                unconfirmed.append(item)
                continue
            candidate_keys = expected_keys_by_base.get(_item_base_key(item), [])
            if key not in expected_by_key and candidate_keys:
                candidate_matches = {
                    candidate: _identity_match(expected_by_key[candidate], item)
                    for candidate in candidate_keys
                }
                compatible = [
                    candidate for candidate, state in candidate_matches.items()
                    if state == "match"
                ]
                if len(compatible) == 1:
                    key = compatible[0]
                elif any(state != "mismatch" for state in candidate_matches.values()):
                    unconfirmed.append({**item, "reason": "identity_attributes_unconfirmed"})
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
                package_quantities[group] = {
                    **item,
                    "observed_quantity": quantity,
                    "package_ref": package_ref,
                    "confidence": row_confidence,
                    "reason": row_reason,
                    "evidence_refs": evidence_refs,
                }
            else:
                existing["confidence"] = max(_confidence(existing.get("confidence")), row_confidence)
                if row_reason and row_reason not in str(existing.get("reason") or ""):
                    existing["reason"] = "；".join(filter(None, (str(existing.get("reason") or ""), row_reason)))
                existing["evidence_refs"] = list({
                    (ref["asset_ref"], ref.get("timestamp"), ref.get("field"), ref["fact"]): ref
                    for ref in existing.get("evidence_refs", []) + evidence_refs
                }.values())
        unconfirmed.extend(row.get("unconfirmed_items") or [])
        for item in row.get("package_observations") or []:
            if not isinstance(item, dict) or not item.get("package_ref"):
                continue
            package_ref = str(item["package_ref"])
            current = package_observations.setdefault(
                package_ref,
                {
                    "package_ref": package_ref,
                    **{field: None for field in PACKAGE_OBSERVATION_FIELDS},
                    "evidence_refs": [],
                },
            )
            evidence_refs = _valid_evidence_refs(item.get("evidence_refs"), allowed_asset_refs)
            observed_waybill_identifier = str(
                item.get("observed_waybill_identifier") or ""
            ).strip()
            if (
                observed_waybill_identifier
                and item.get("waybill_visible") is True
                and any(ref.get("field") == "waybill_visible" for ref in evidence_refs)
            ):
                package_observed_waybill_identifiers.setdefault(package_ref, set()).add(
                    observed_waybill_identifier
                )
            if evidence_refs:
                package_confidence_values.setdefault(package_ref, []).append(row_confidence)
                if row_reason:
                    package_reasons.setdefault(package_ref, []).append(row_reason)
            current["evidence_refs"] = list({
                (ref["asset_ref"], ref.get("timestamp"), ref.get("field"), ref["fact"]): ref
                for ref in current["evidence_refs"] + evidence_refs
            }.values())
            flag_values = package_flag_values.setdefault(package_ref, {
                field: set() for field in PACKAGE_OBSERVATION_FIELDS
            })
            for field in PACKAGE_OBSERVATION_FIELDS:
                if isinstance(item.get(field), bool):
                    flag_values[field].add(item[field])

    for package_ref, observation in package_observations.items():
        for field, values in package_flag_values.get(package_ref, {}).items():
            if len(values) == 1:
                observation[field] = next(iter(values))
            elif len(values) > 1:
                observation[field] = None
                evidence_conflicts.append({
                    "package_ref": package_ref,
                    "field": field,
                    "reason": "同一包裹的不同证据对该字段给出相反事实。",
                })
        declared_waybill_match = observation.get("waybill_matches_order")
        observation["waybill_matches_order"] = _waybill_match_from_observed_identifier(
            observation,
            package_ref,
            waybill_identifiers_by_package,
            package_observed_waybill_identifiers.get(package_ref, ()),
        )
        if isinstance(observation["waybill_matches_order"], bool):
            waybill_ref = next((
                ref for ref in observation.get("evidence_refs") or []
                if ref.get("field") in {"waybill_visible", "waybill_observed_identifier"}
            ), None)
            if waybill_ref:
                observation["evidence_refs"].append({
                    "asset_ref": waybill_ref["asset_ref"],
                    "timestamp": waybill_ref.get("timestamp"),
                    "field": "waybill_matches_order",
                    "fact": (
                        "面单完整编号与受信包裹编号精确一致。"
                        if observation["waybill_matches_order"]
                        else "面单完整编号与受信包裹编号不一致。"
                    ),
                    "observed_identifier": None,
                })
        if declared_waybill_match is not None and observation["waybill_matches_order"] is None:
            unconfirmed.append({
                "package_ref": package_ref,
                "reason": "面单匹配未由完整编号或全案唯一的末四位支持，不能作为已核验事实。",
            })
        if not observation.get("evidence_refs"):
            unconfirmed.append({
                "package_ref": package_ref,
                "reason": "missing_reviewable_package_evidence_ref",
            })
        confidence_values = package_confidence_values.get(package_ref) or []
        observation["confidence"] = round(min(confidence_values), 4) if confidence_values else None
        observation["reason"] = "；".join(dict.fromkeys(package_reasons.get(package_ref) or []))
        observation["atomic_facts"] = []
        for field in PACKAGE_OBSERVATION_FIELDS:
            refs = [
                ref for ref in observation.get("evidence_refs") or []
                if ref.get("field") == field
            ]
            reason = "；".join(dict.fromkeys(
                str(ref.get("fact") or "").strip() for ref in refs if str(ref.get("fact") or "").strip()
            )) or observation["reason"] or "本轮没有形成可回看的该项事实。"
            observation["atomic_facts"].append({
                "field": field,
                "value": observation.get(field) if isinstance(observation.get(field), bool) else None,
                "confidence": observation["confidence"] if refs else None,
                "reason": reason,
                "evidence_refs": refs,
            })

    observed_by_key: Dict[str, Dict[str, Any]] = {}
    for (_, key), item in package_quantities.items():
        is_new = key not in observed_by_key
        current = observed_by_key.setdefault(key, {**item, "observed_quantity": 0, "package_refs": []})
        current["observed_quantity"] += _int(item.get("observed_quantity"))
        current["package_refs"] = list(dict.fromkeys(current["package_refs"] + [item.get("package_ref")]))
        if not is_new:
            current["confidence"] = min(
                _confidence(current.get("confidence")),
                _confidence(item.get("confidence")),
            )
            item_reason = str(item.get("reason") or "")
            if item_reason and item_reason not in str(current.get("reason") or ""):
                current["reason"] = "；".join(filter(None, (str(current.get("reason") or ""), item_reason)))
            current["evidence_refs"] = list({
                (ref["asset_ref"], ref.get("timestamp"), ref.get("field"), ref["fact"]): ref
                for ref in current.get("evidence_refs", []) + item.get("evidence_refs", [])
            }.values())

    product_composition_resolution = (
        _trusted_product_composition_resolution(baseline, expected_by_key, observed_by_key)
        if scenario == "missing_item"
        else {}
    )

    expected_keys = {_item_key(item): item for item in expected if _item_key(item)}
    missing = []
    for key, item in expected_keys.items():
        if key in package_scoped_keys:
            continue
        observed_quantity = _int((observed_by_key.get(key) or {}).get("observed_quantity"))
        expected_quantity = _int(item.get("expected_quantity") or item.get("quantity"))
        if observed_quantity < expected_quantity:
            missing.append({**item, "observed_quantity": observed_quantity})
    for group, item in expected_by_package.items():
        observed_quantity = _int((package_quantities.get(group) or {}).get("observed_quantity"))
        if observed_quantity < _int(item.get("expected_quantity")):
            missing.append({**item, "observed_quantity": observed_quantity})
    unexpected = []
    for (package_ref, key), observed_item in package_quantities.items():
        if key in package_scoped_keys:
            expected_item = expected_by_package.get((package_ref, key))
            expected_quantity = _int((expected_item or {}).get("expected_quantity"))
            surplus_quantity = _int(observed_item.get("observed_quantity")) - expected_quantity
            if surplus_quantity > 0:
                unexpected.append({
                    **observed_item,
                    "observed_quantity": surplus_quantity,
                    "difference_type": "unexpected_in_package" if expected_item is None else "surplus_received",
                })
        elif key not in expected_keys:
            unexpected.append(observed_item)
    if scenario == "wrong_item":
        for key, observed_item in observed_by_key.items():
            if key in package_scoped_keys:
                continue
            expected_item = expected_keys.get(key)
            if not expected_item:
                continue
            surplus_quantity = (
                _int(observed_item.get("observed_quantity"))
                - _int(expected_item.get("expected_quantity") or expected_item.get("quantity"))
            )
            if surplus_quantity > 0:
                unexpected.append({
                    **observed_item,
                    "observed_quantity": surplus_quantity,
                    "difference_type": "surplus_received",
                })
    non_gift_unexpected = [item for item in unexpected if not _is_gift_item(item)]

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
        if _package_route_complete(item, OPENING_VIDEO_ROUTE_FIELDS, "video")
    }
    static_complete_packages = {
        key
        for key, item in package_observations.items()
        if _package_route_complete(item, STATIC_REVIEW_ROUTE_FIELDS, "image")
        and any(
            item.get(field) is True and _field_has_evidence(item, field, "image")
            for field in ("all_contents_laid_out", "received_group_photo_complete")
        )
    }
    coverage_verified = bool(expected_packages) and expected_packages.issubset(visually_complete_packages)
    all_user_routes = visually_complete_packages | static_complete_packages
    user_materials_complete = bool(expected_packages) and expected_packages.issubset(all_user_routes)
    static_materials_verified = bool(expected_packages) and expected_packages.issubset(static_complete_packages)
    baseline_ready = bool(
        baseline.get("baseline_version") and expected and expected_packages and baseline_quantity_valid
    )
    selection_rules_applicable = bool(baseline.get("selection_rules"))
    selection_rules_ready = not selection_rules_applicable or baseline.get("selection_rules_complete") is True
    benefit_rules_ready = scenario != "missing_item" or baseline.get("benefit_rules_complete") is True
    visual_evidence_sufficient = (
        baseline_ready
        and coverage_verified
        and selection_rules_ready
        and benefit_rules_ready
        and not unconfirmed
        and not unknown_package_refs
        and not evidence_conflicts
    )
    warehouse_verification = (
        trusted_warehouse_verification(baseline) if scenario == "missing_item" else {}
    )
    evidence_route = (
        "not_required"
        if scenario == "missing_item" and product_composition_resolution
        else "compliant_opening_video"
        if coverage_verified
        else "static_three_images"
        if user_materials_complete
        else "insufficient"
    )
    evidence_sufficient = bool(
        warehouse_verification or product_composition_resolution or visual_evidence_sufficient
    )
    wrong_item_to_missing = bool(
        scenario == "wrong_item" and missing and not non_gift_unexpected and visual_evidence_sufficient
    )
    wrong_item_signal_in_missing_scene = bool(
        scenario == "missing_item"
        and missing
        and non_gift_unexpected
        and visual_evidence_sufficient
        and not warehouse_verification
        and not product_composition_resolution
    )
    mismatch = (
        warehouse_verification.get("status") == "confirmed_missing"
        if warehouse_verification
        else False
        if product_composition_resolution
        else bool(missing) if scenario == "missing_item" else bool(missing and non_gift_unexpected)
    )
    verdict = (
        "indeterminate"
        if wrong_item_signal_in_missing_scene or wrong_item_to_missing
        else "mismatched" if evidence_sufficient and mismatch
        else "matched" if evidence_sufficient
        else "indeterminate"
    )
    post_decision_reminders = []
    if scenario == "missing_item" and verdict == "mismatched" and evidence_sufficient:
        paper_refs = [
            str(item.get("item_ref") or item.get("sku") or "").strip()
            for item in missing
            if item.get("item_form") == "flat_paper"
        ]
        paper_refs = [item for item in paper_refs if item]
        if paper_refs:
            post_decision_reminders.append({
                "type": "flat_paper_self_check",
                "item_refs": paper_refs,
                "message": "可提醒用户再检查纸类商品是否叠放、贴在背面或夹在包装夹层；这不是漏发判定的前置条件，也不改变当前证据结论。",
                "affects_verdict": False,
            })
    observation_confidence = max((_confidence(row.get("confidence")) for row in rows), default=0.0)
    boundary = (
        "甲方已提供可追溯的仓库终核，历史待核实备注不覆盖该终态。"
        if warehouse_verification
        else f"可信订单或商品规则确认“{product_composition_resolution.get('claimed_item')}”不是独立应发项，且其关联订单商品已经实收证据核验；本案属于商品构成理解差异。"
        if product_composition_resolution
        else "仅发现应发商品短缺、未发现错误实收商品，应转漏发场景继续审核。"
        if wrong_item_to_missing
        else "同时存在应发商品缺少和未购商品多出的视觉线索，更符合错发场景；本轮不直接认定漏发。"
        if wrong_item_signal_in_missing_scene
        else "已完成版本化应发基准、实收商品身份、包裹映射与全家福证据链核对。"
        if scenario == "wrong_item" and visual_evidence_sufficient and not coverage_verified
        else "用户静态三类材料已齐全，下一步应由人工客服读取仓库实发明细进行双重核验。"
        if evidence_route == "static_three_images"
        else "已完成版本化应发基准、全部包裹合规开箱和全部内容展示的视觉对账。"
        if visual_evidence_sufficient
        else "应发基准、包裹关联、合规开箱视频或静态三类材料尚未形成完整路径，应先补齐可获得的材料再复核。"
    )
    return {
        "baseline_version": baseline.get("baseline_version") or "",
        "expected_items": expected,
        "observed_items": list(observed_by_key.values()),
        "suspected_missing_items": missing,
        "unexpected_items": unexpected,
        "unconfirmed_items": unconfirmed[:100],
        "evidence_conflicts": evidence_conflicts,
        "package_observations": list(package_observations.values()),
        "package_coverage": (
            "仓库终核已覆盖本案履约事实；本轮不以开箱视频数量作为结论门槛"
            if warehouse_verification
            else f"{len(visually_complete_packages)}/{len(expected_packages)} 个应发包裹完成开箱并铺开展示"
        ),
        "all_packages_uploaded": coverage.get("all_packages_uploaded") is True,
        "all_items_displayed": coverage.get("all_items_displayed") is True,
        "visual_coverage_verified": coverage_verified,
        "static_materials_verified": static_materials_verified,
        "user_materials_complete": user_materials_complete,
        "evidence_route": evidence_route,
        "submitted_package_mapping_complete": submitted_mapping_complete,
        "selection_rules_complete": selection_rules_ready,
        "benefit_rules_complete": benefit_rules_ready,
        "unknown_package_refs": unknown_package_refs,
        "warehouse_verification": warehouse_verification,
        "warehouse_check": (
            {"state": "verified", "outcome": warehouse_verification.get("status")}
            if warehouse_verification
            else {"state": "pending", "outcome": None}
            if (
                evidence_route == "static_three_images"
                or (
                    isinstance(baseline.get("warehouse_verification"), dict)
                    and baseline["warehouse_verification"].get("status") in {
                        "pending", "confirmed_missing", "confirmed_not_missing"
                    }
                    and baseline["warehouse_verification"].get("source") == "customer_warehouse"
                )
            )
            else {"state": "not_available", "outcome": None}
        ),
        "product_composition_resolution": product_composition_resolution,
        "resolution_basis": (
            "warehouse_verification"
            if warehouse_verification
            else "trusted_expected_item_resolution"
            if product_composition_resolution
            else "visual_reconciliation"
            if visual_evidence_sufficient
            else "none"
        ),
        "evidence_sufficiency": "sufficient" if evidence_sufficient else "insufficient",
        "verdict": verdict,
        "observation_confidence": observation_confidence,
        "confidence": observation_confidence if evidence_sufficient else 0.0,
        "decision_boundary": boundary,
        "scenario": scenario,
        "scenario_transition": (
            "missing_item" if wrong_item_to_missing
            else "wrong_item" if wrong_item_signal_in_missing_scene
            else None
        ),
        "post_decision_reminders": post_decision_reminders,
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
        static_route = reconciliation.get("evidence_route") == "static_three_images"
        output["decision"] = "manual_review" if static_route else "request_more_material"
        output["confidence"] = min(_confidence(output.get("confidence")), 0.69)
        output["fulfillment_guard_reason"] = reconciliation.get("decision_boundary") or "履约证据不足，应先补齐可获得的材料。"
        if static_route:
            output["next_step"] = "用户静态三类材料已齐全，请人工客服读取仓库实发明细并完成双重核验。"
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
