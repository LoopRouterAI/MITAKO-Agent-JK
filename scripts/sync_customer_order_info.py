# -*- coding: utf-8 -*-
"""将甲方补充的订单/SKU 快照按工单、场景和标签安全同步到原始样本目录。"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any


SCENARIO_TOKENS = {
    "product_damage": ("商品有伤",),
    "wrong_item": ("发错货",),
    "missing_item": ("漏发货",),
    "opening_video": ("开箱视频", "开箱"),
}
FORBIDDEN_EVALUATION_MARKERS = (
    "人工结论",
    "正样本",
    "负样本",
    "审核通过",
    "审核不通过",
    "人工认可",
    "人工拒绝",
    "expected_label",
    "ground_truth",
)


def classify_path(path: Path) -> tuple[str, str]:
    text = "/".join(path.parts)
    scenario = next(
        (name for name, tokens in SCENARIO_TOKENS.items() if any(token in text for token in tokens)),
        "unknown",
    )
    if "负样本" in text or "不合格" in text:
        label = "negative"
    elif "正样本" in text or "合格" in text:
        label = "positive"
    else:
        label = "unknown"
    return scenario, label


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_snapshot(path: Path) -> tuple[bool, list[str], dict[str, Any]]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return False, [f"invalid_json:{exc.__class__.__name__}"], {}
    if not isinstance(payload, dict):
        return False, ["root_not_object"], {}
    goods = payload.get("goods_list")
    if not isinstance(goods, list) or not goods:
        errors.append("goods_list_missing_or_empty")
        goods = []
    for index, item in enumerate(goods, start=1):
        if not isinstance(item, dict):
            errors.append(f"goods_{index}_not_object")
            continue
        if not str(item.get("number") or "").strip() and item.get("id") in (None, ""):
            errors.append(f"goods_{index}_missing_sku_identity")
        if not str(item.get("name") or item.get("des") or "").strip():
            errors.append(f"goods_{index}_missing_name")
        model_fields = "\n".join(str(item.get(key) or "") for key in ("name", "des", "intro"))
        if any(marker.lower() in model_fields.lower() for marker in FORBIDDEN_EVALUATION_MARKERS):
            errors.append(f"goods_{index}_forbidden_evaluation_marker")
        try:
            if int(item.get("goods_num") or 0) <= 0:
                errors.append(f"goods_{index}_invalid_quantity")
        except (TypeError, ValueError):
            errors.append(f"goods_{index}_invalid_quantity")
    summary = {
        "goods_lines": len(goods),
        "total_quantity": sum(
            int(item.get("goods_num") or 0)
            for item in goods
            if isinstance(item, dict) and str(item.get("goods_num") or "").isdigit()
        ),
        "with_main_image": sum(
            1 for item in goods if isinstance(item, dict) and str(item.get("main_img") or "").strip()
        ),
    }
    return not errors, errors, summary


def plan_sync(root: Path, source_root: Path) -> dict[str, Any]:
    source_files = sorted(source_root.rglob("order_info_snapshot.json"))
    target_dirs: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if not path.is_dir() or not path.name.isdigit() or source_root == path or source_root in path.parents:
            continue
        target_dirs.setdefault(path.name, []).append(path)

    rows: list[dict[str, Any]] = []
    for source in source_files:
        ticket_id = source.parent.name
        source_scenario, source_label = classify_path(source.relative_to(source_root))
        candidates = list(target_dirs.get(ticket_id) or [])
        scenario_matches = [path for path in candidates if classify_path(path.relative_to(root))[0] == source_scenario]
        label_matches = [path for path in scenario_matches if classify_path(path.relative_to(root))[1] == source_label]
        filtered = label_matches
        valid, errors, content_summary = validate_snapshot(source)
        status = "ready"
        target: Path | None = filtered[0] if len(filtered) == 1 else None
        if not valid:
            status = "invalid_source"
        elif not candidates:
            status = "target_missing"
        elif not filtered:
            status = "scenario_or_label_mismatch"
        elif len(filtered) > 1:
            status = "ambiguous_target"
        target_file = target / "order_info_snapshot.json" if target else None
        source_hash = sha256(source)
        if status == "ready" and target_file and target_file.exists():
            status = "already_synced" if sha256(target_file) == source_hash else "target_conflict"
        rows.append({
            "ticket_id": ticket_id,
            "source": str(source),
            "source_scenario": source_scenario,
            "source_label": source_label,
            "source_sha256": source_hash,
            "target": str(target_file) if target_file else "",
            "candidate_targets": [str(path) for path in filtered or candidates],
            "status": status,
            "validation_errors": errors,
            "content_summary": content_summary,
        })
    by_target: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["status"] == "ready" and row["target"]:
            by_target.setdefault(row["target"], []).append(row)
    for target_rows in by_target.values():
        if len(target_rows) > 1:
            for row in target_rows:
                row["status"] = "ambiguous_source_target"
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(root),
        "source_root": str(source_root),
        "source_snapshots": len(source_files),
        "status_counts": counts,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    source_root = (args.source_root or root / "help_ticket_order_info").resolve()
    if not root.is_dir() or not source_root.is_dir() or root not in source_root.parents:
        raise SystemExit("样本根目录或补充目录不存在，或补充目录不在指定样本根目录下。")
    report = plan_sync(root, source_root)
    copied = 0
    if args.apply:
        for row in report["rows"]:
            if row["status"] != "ready":
                continue
            source = Path(row["source"])
            target = Path(row["target"])
            if target.parent.resolve() == source_root or source_root in target.parent.resolve().parents:
                raise RuntimeError(f"拒绝写回补充数据源目录：{target}")
            shutil.copy2(source, target)
            if sha256(target) != row["source_sha256"]:
                raise RuntimeError(f"复制后哈希不一致：{target}")
            row["status"] = "copied"
            copied += 1
        report["applied"] = True
        report["copied"] = copied
        counts: dict[str, int] = {}
        for row in report["rows"]:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        report["status_counts"] = counts
    else:
        report["applied"] = False
        report["copied"] = 0
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "applied": report["applied"],
        "copied": report["copied"],
        "source_snapshots": report["source_snapshots"],
        "status_counts": report["status_counts"],
        "report": str(args.report.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
