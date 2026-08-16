# -*- coding: utf-8 -*-
"""验证订单快照最小化与官方商品图按需读取，不执行模型推理。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from poc.visual_review_poc.official_reference_images import prepare_official_reference_images
from poc.visual_review_poc.order_info_adapter import build_order_info_context
from review_input_safety import assert_review_input_safe


FORBIDDEN_KEYS = ("user_address", "price_fen", "express_fee", "all_goods", "reply.json", "annotation.json")


def run(snapshot: Path, report_path: Path, limit: int) -> dict:
    started = time.time()
    context = build_order_info_context(snapshot)
    if not context:
        raise RuntimeError("order_snapshot_not_usable")
    serialized = json.dumps(context, ensure_ascii=False)
    assert_review_input_safe(context)
    leaked = [marker for marker in FORBIDDEN_KEYS if marker.lower() in serialized.lower()]
    case = {"structured_business_context": context}
    prepare_official_reference_images(case, limit=limit)
    status = case.get("official_reference_status") or {}
    result = {
        "ok": not leaked and status.get("available_count", 0) > 0,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "snapshot": str(snapshot.resolve()),
        "order_lines": len(context.get("order_items") or []),
        "expected_quantity": sum(int(item.get("expected_quantity") or 0) for item in context.get("order_items") or []),
        "package_count": len((context.get("fulfillment_baseline") or {}).get("packages") or []),
        "selection_rule_count": len((context.get("fulfillment_baseline") or {}).get("selection_rules") or []),
        "official_reference_status": status,
        "official_references": [
            {
                "reference_id": item.get("reference_id"),
                "item_ref": item.get("item_ref"),
                "cache_hit": item.get("cache_hit"),
                "compressed_bytes": item.get("api_bytes"),
                "evidence_role": item.get("evidence_role"),
            }
            for item in case.get("official_reference_images") or []
        ],
        "forbidden_input_hits": leaked,
        "elapsed_seconds": round(time.time() - started, 3),
        "boundary": "本脚本只验证当前订单按需商品图与最小化上下文，不读取整库图片，不调用模型，不使用人工标签。",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=2)
    args = parser.parse_args()
    if not args.snapshot.is_file():
        raise SystemExit("订单快照不存在")
    result = run(args.snapshot, args.report, max(1, min(args.limit, 12)))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
