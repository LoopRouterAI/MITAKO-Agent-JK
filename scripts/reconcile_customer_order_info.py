# -*- coding: utf-8 -*-
"""撤销旧同步逻辑造成的跨标签订单快照；只处理哈希未变化的本工具历史副本。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync_customer_order_info import plan_sync, sha256


def reconcile_plan(root: Path, source_root: Path, applied_report: Path) -> dict[str, Any]:
    old = json.loads(applied_report.read_text(encoding="utf-8-sig"))
    strict = plan_sync(root, source_root)
    strict_by_source = {str(row["source"]): row for row in strict["rows"]}
    rows: list[dict[str, Any]] = []
    for old_row in old.get("rows") or []:
        if old_row.get("status") != "copied" or not old_row.get("target"):
            continue
        source = Path(str(old_row.get("source") or "")).resolve()
        target = Path(str(old_row.get("target") or "")).resolve()
        strict_row = strict_by_source.get(str(source)) or {}
        status = "keep_strict_match"
        reason = "当前严格三层匹配仍认可该目标。"
        if strict_row.get("status") == "scenario_or_label_mismatch":
            status = "ready_to_remove"
            reason = "旧逻辑跨标签回退复制，当前严格匹配拒绝。"
        if root != target.parent and root not in target.parents:
            status = "unsafe_target_not_removed"
            reason = "目标不在样本根目录内。"
        elif source_root == target.parent or source_root in target.parents:
            status = "unsafe_target_not_removed"
            reason = "目标位于补充数据源目录。"
        elif status == "ready_to_remove":
            if not source.is_file() or not target.is_file():
                status = "missing_not_removed"
                reason = "源或目标文件已不存在。"
            elif sha256(source) != str(old_row.get("source_sha256") or ""):
                status = "source_changed_not_removed"
                reason = "来源文件已变化，不能自动撤销。"
            elif sha256(target) != str(old_row.get("source_sha256") or ""):
                status = "target_changed_not_removed"
                reason = "目标文件已被修改，不能自动撤销。"
        rows.append(
            {
                "ticket_id": old_row.get("ticket_id"),
                "source": str(source),
                "target": str(target),
                "source_sha256": old_row.get("source_sha256"),
                "strict_status": strict_row.get("status"),
                "status": status,
                "reason": reason,
            }
        )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(root),
        "source_root": str(source_root),
        "applied_report": str(applied_report),
        "status_counts": counts,
        "rows": rows,
        "applied": False,
        "removed": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--applied-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    source_root = (args.source_root or root / "help_ticket_order_info").resolve()
    applied_report = args.applied_report.resolve()
    if not root.is_dir() or not source_root.is_dir() or root not in source_root.parents:
        raise SystemExit("样本根目录或补充目录不合法。")
    if not applied_report.is_file():
        raise SystemExit("旧应用报告不存在。")
    report = reconcile_plan(root, source_root, applied_report)
    if args.apply:
        for row in report["rows"]:
            if row["status"] != "ready_to_remove":
                continue
            target = Path(row["target"])
            target.unlink()
            row["status"] = "removed_unsafe_legacy_copy"
            report["removed"] += 1
        report["applied"] = True
        counts: dict[str, int] = {}
        for row in report["rows"]:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        report["status_counts"] = counts
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "applied": report["applied"],
        "removed": report["removed"],
        "status_counts": report["status_counts"],
        "report": str(args.report.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
