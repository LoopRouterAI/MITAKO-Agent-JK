from __future__ import annotations

from typing import Any, Dict


FINAL_WAREHOUSE_STATUSES = {"confirmed_missing", "confirmed_not_missing"}


def trusted_warehouse_verification(baseline: Dict[str, Any]) -> Dict[str, str]:
    """仅接受甲方仓库字段中的可追溯终态，避免模型推断绕过证据门禁。"""
    if not isinstance(baseline, dict) or not baseline.get("baseline_version"):
        return {}
    if not any(isinstance(item, dict) for item in baseline.get("expected_items") or []):
        return {}
    verification = baseline.get("warehouse_verification") or {}
    if not isinstance(verification, dict):
        return {}
    status = str(verification.get("status") or "").strip()
    source = str(verification.get("source") or "").strip()
    reference = str(verification.get("verification_ref") or "").strip()
    if status not in FINAL_WAREHOUSE_STATUSES or source != "customer_warehouse" or not reference:
        return {}
    return {"status": status, "source": source, "verification_ref": reference}
