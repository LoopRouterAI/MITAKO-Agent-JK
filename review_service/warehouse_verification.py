from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


FINAL_WAREHOUSE_STATUSES = {"confirmed_missing", "confirmed_not_missing"}


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _valid_timestamp(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _expected_quantities(baseline: Dict[str, Any]) -> Dict[str, int]:
    quantities: Dict[str, int] = {}
    for item in baseline.get("expected_items") or []:
        if not isinstance(item, dict):
            continue
        item_ref = str(item.get("item_ref") or "").strip()
        quantity = _positive_int(item.get("expected_quantity"))
        if item_ref and quantity is not None and quantity > 0:
            quantities[item_ref] = quantities.get(item_ref, 0) + quantity
    return quantities


def _verified_package_rows(baseline: Dict[str, Any], verification: Dict[str, Any]) -> List[Dict[str, Any]]:
    expected_packages = {
        str(package.get("package_ref") or "").strip(): {
            "tracking_no": str(package.get("tracking_no") or "").strip(),
            "expected_item_refs": {
                str(item_ref).strip()
                for item_ref in package.get("expected_item_refs") or []
                if str(item_ref).strip()
            },
        }
        for package in baseline.get("packages") or []
        if isinstance(package, dict) and str(package.get("package_ref") or "").strip()
    }
    if not expected_packages or any(
        not package["expected_item_refs"] for package in expected_packages.values()
    ):
        return []
    verified_rows: List[Dict[str, Any]] = []
    seen_packages = set()
    for package in verification.get("packages") or []:
        if not isinstance(package, dict):
            return []
        package_ref = str(package.get("package_ref") or "").strip()
        tracking_no = str(package.get("tracking_no") or "").strip()
        if package_ref not in expected_packages or package_ref in seen_packages:
            return []
        expected_package = expected_packages[package_ref]
        expected_tracking = expected_package["tracking_no"]
        if expected_tracking and tracking_no != expected_tracking:
            return []
        shipped_items = []
        for item in package.get("actual_shipped_items") or []:
            if not isinstance(item, dict):
                return []
            item_ref = str(item.get("item_ref") or "").strip()
            shipped_quantity = _positive_int(item.get("shipped_quantity"))
            if (
                not item_ref
                or item_ref not in expected_package["expected_item_refs"]
                or shipped_quantity is None
            ):
                return []
            shipped_items.append({"item_ref": item_ref, "shipped_quantity": shipped_quantity})
        if not shipped_items:
            return []
        seen_packages.add(package_ref)
        verified_rows.append({
            "package_ref": package_ref,
            "tracking_no": tracking_no,
            "actual_shipped_items": shipped_items,
        })
    return verified_rows if seen_packages == set(expected_packages) else []


def trusted_warehouse_verification(baseline: Dict[str, Any]) -> Dict[str, Any]:
    """只接受可按订单基线逐项重算的甲方仓库终态。"""
    if not isinstance(baseline, dict) or not baseline.get("baseline_version"):
        return {}
    expected_quantities = _expected_quantities(baseline)
    if not expected_quantities:
        return {}
    verification = baseline.get("warehouse_verification") or {}
    if not isinstance(verification, dict):
        return {}
    status = str(verification.get("status") or "").strip()
    source = str(verification.get("source") or "").strip()
    reference = str(verification.get("verification_ref") or "").strip()
    verification_baseline = str(verification.get("baseline_version") or "").strip()
    snapshot_ref = str(verification.get("snapshot_ref") or "").strip()
    if (
        status not in FINAL_WAREHOUSE_STATUSES
        or source != "customer_warehouse"
        or not reference
        or verification_baseline != str(baseline.get("baseline_version") or "").strip()
        or not snapshot_ref
        or not _valid_timestamp(verification.get("verified_at"))
    ):
        return {}
    packages = _verified_package_rows(baseline, verification)
    if not packages:
        return {}
    actual_quantities: Dict[str, int] = {}
    for package in packages:
        for item in package["actual_shipped_items"]:
            item_ref = item["item_ref"]
            if item_ref not in expected_quantities:
                return {}
            actual_quantities[item_ref] = actual_quantities.get(item_ref, 0) + item["shipped_quantity"]
    calculated_missing = any(
        actual_quantities.get(item_ref, 0) < quantity
        for item_ref, quantity in expected_quantities.items()
    )
    if (status == "confirmed_missing") != calculated_missing:
        return {}

    return {
        "status": status,
        "source": source,
        "verification_ref": reference,
        "baseline_version": verification_baseline,
        "verified_at": str(verification.get("verified_at")),
        "snapshot_ref": snapshot_ref,
        "packages": packages,
        "traceability_complete": True,
    }
