# -*- coding: utf-8 -*-
"""验证实际同步的甲方订单快照可转换为最小化审核基准。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poc.visual_review_poc.local_video_triage_demo import order_info_context


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    sync = json.loads(args.sync_report.read_text(encoding="utf-8-sig"))
    rows = []
    for item in sync.get("rows") or []:
        if item.get("status") not in {"copied", "already_synced"}:
            continue
        target = Path(str(item.get("target") or ""))
        context = order_info_context(target)
        serialized = json.dumps(context, ensure_ascii=False)
        order_items = context.get("order_items") or []
        baseline = context.get("fulfillment_baseline") or {}
        checks = {
            "target_exists": target.is_file(),
            "order_items_present": bool(order_items),
            "all_quantities_positive": bool(order_items) and all(int(row.get("expected_quantity") or 0) > 0 for row in order_items),
            "all_sku_identified": bool(order_items) and all(str(row.get("sku") or "").strip() for row in order_items),
            "baseline_matches_items": baseline.get("expected_items") == order_items,
            "privacy_fields_absent": all(token not in serialized for token in ('"user"', '"user_address"', '"price"', '"price_fen"')),
        }
        rows.append({
            "ticket_id": item.get("ticket_id"),
            "scenario": item.get("source_scenario"),
            "label": item.get("source_label"),
            "order_line_count": len(order_items),
            "total_expected_quantity": sum(int(row.get("expected_quantity") or 0) for row in order_items),
            "product_image_refs_present": sum(bool(str(row.get("product_image_ref") or "").strip()) for row in order_items),
            "checks": checks,
            "ok": all(checks.values()),
        })
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cases": len(rows),
        "passed": sum(item["ok"] for item in rows),
        "failed": sum(not item["ok"] for item in rows),
        "privacy_boundary": "报告不记录 SKU 原值、用户、地址或价格。",
        "rows": rows,
    }
    payload["ok"] = payload["cases"] > 0 and payload["failed"] == 0
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("ok", "cases", "passed", "failed")}, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
