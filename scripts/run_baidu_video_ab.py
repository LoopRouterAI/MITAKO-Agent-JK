# -*- coding: utf-8 -*-
"""在标签隔离条件下比较百度 Gemini 的三种视频审核链路。"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poc.visual_review_poc.local_video_triage_demo import load_env
from poc.visual_review_poc.model_auth import gemini_channel_options
from poc.visual_review_poc.model_catalog import MODEL_CONFIGS
from poc.visual_review_poc.model_selection_e2e import (
    call_model,
    call_model_chunked,
    call_opening_start_verification,
    derive_claim_identity,
    load_case_bundle,
    merge_opening_start_verification,
)
from poc.visual_review_poc.unified_model_pass import native_dimension_gaps

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
INLINE_RAW_MEDIA_LIMIT = 70 * 1024 * 1024


def native_media_part_count(case: Dict[str, Any]) -> int:
    return (
        (1 if case.get("native_video") else 0)
        + len(case.get("frames") or [])
        + len(case.get("supplemental_images") or [])
        + len(case.get("official_reference_images") or [])
    )


def result_summary(result: Dict[str, Any], *, native_media_parts: int = 0) -> Dict[str, Any]:
    parsed = result.get("parsed") or {}
    raw_parsed = result.get("parsed_before_boundary") or parsed
    chunking = result.get("chunking") or {}
    channels = chunking.get("channels") or {}
    model_calls = chunking.get("total_model_calls")
    if model_calls is None:
        model_calls = 1 if result.get("status") == "success" else 0
    opening_verification = result.get("opening_start_verification") or {}
    opening_incurred = 1 if opening_verification.get("status") not in {None, "skipped"} else 0
    model_calls = int(model_calls or 0) + opening_incurred
    model_media_parts = sum(
        int((value or {}).get("model_images") or 0)
        for value in channels.values()
        if isinstance(value, dict)
    ) or native_media_parts
    overall = raw_parsed.get("overall_audit") or {}
    findings = raw_parsed.get("frame_findings") or []
    continuity = raw_parsed.get("object_continuity_assessment") or {}
    video_audit = raw_parsed.get("video_audit_conclusion") or {}
    opening = video_audit.get("opening_video_compliance") or {}
    damage = raw_parsed.get("damage_causality_assessment") or {}
    claim_facts = raw_parsed.get("claim_fact_assessment") or {}
    required_dimensions = {
        "overall_audit": isinstance(overall, dict) and bool(overall.get("conclusion")),
        "frame_findings": isinstance(findings, list) and any(
            isinstance(item, dict) and item.get("timestamp") and item.get("visible_facts")
            for item in findings
        ),
        "object_continuity": (
            isinstance(continuity, dict)
            and bool(continuity.get("continuity_verdict"))
            and bool(continuity.get("tracked_subjects"))
        ),
        "opening_video_compliance": (
            isinstance(opening, dict)
            and all(isinstance(opening.get(field), bool) for field in (
                "sealed_start", "waybill_visible", "single_take_continuity"
            ))
            and "issue_visible_in_continuous_opening" in opening
            and opening.get("result") in {"compliant", "noncompliant", "indeterminate"}
        ),
        "damage_causality": (
            isinstance(damage, dict)
            and bool(damage.get("damage_presence"))
            and bool(damage.get("claim_support"))
        ),
        "claim_facts": (
            isinstance(claim_facts, dict)
            and isinstance(claim_facts.get("atomic_claim_results"), list)
            and isinstance(claim_facts.get("order_linkage"), dict)
            and isinstance(claim_facts.get("scene_match"), dict)
            and isinstance(claim_facts.get("assembly"), dict)
        ),
    }
    raw_response = result.get("raw_response") or {}
    usage = dict(result.get("usage") or {})
    opening_usage = opening_verification.get("usage") or {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        usage[key] = int(usage.get(key) or 0) + int(opening_usage.get(key) or 0)
    cost = dict(result.get("cost") or {})
    opening_cost = opening_verification.get("cost") or {}
    if cost or opening_cost:
        cost["estimated_usd"] = round(
            float(cost.get("estimated_usd") or 0) + float(opening_cost.get("estimated_usd") or 0),
            6,
        )
        if cost.get("currency") == opening_cost.get("currency") and cost.get("amount") is not None:
            cost["amount"] = round(float(cost.get("amount") or 0) + float(opening_cost.get("amount") or 0), 6)
    total_latency = round(
        float(result.get("latency_seconds") or 0) + float(opening_verification.get("latency_seconds") or 0),
        2,
    )
    return {
        "status": result.get("status"),
        "predicted_label_after_guards": parsed.get("predicted_label"),
        "predicted_label_before_guards": raw_parsed.get("predicted_label"),
        "confidence_after_guards": parsed.get("confidence"),
        "dimension_completeness": required_dimensions,
        "complete_dimension_count": sum(required_dimensions.values()),
        "opening_video_compliance": {
            field: opening.get(field)
            for field in (
                "sealed_start",
                "waybill_visible",
                "single_take_continuity",
                "issue_visible_in_continuous_opening",
                "result",
            )
        },
        "model_calls": model_calls,
        "model_media_parts": model_media_parts,
        "wall_seconds": total_latency,
        "model_latency_seconds_sum": result.get("model_latency_seconds_sum") or total_latency,
        "usage": usage,
        "estimated_cost": cost,
        "request_ids": [raw_response["id"]] if raw_response.get("id") else [],
        "route_attempts": (result.get("_channel_route_attempts") or []) + (opening_verification.get("_channel_route_attempts") or []),
        "opening_start_verification": {
            "status": opening_verification.get("status") or "not_run",
            "latency_seconds": opening_verification.get("latency_seconds"),
        },
        "unified_multitask": chunking.get("unified_multitask") or {},
        "guard_effect": {
            "continuity": parsed.get("continuity_guard_reason"),
            "causality": parsed.get("causality_guard_reason"),
        },
    }


def write_checkpoint(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="百度 Gemini 视频审核链路真实 A/B")
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--modes", default="unified,native,legacy")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    if not modes or any(item not in {"legacy", "unified", "native"} for item in modes):
        raise SystemExit("modes 只能包含 legacy、unified、native")
    load_env()
    cfg = dict(MODEL_CONFIGS["gemini35lite"])
    channels = gemini_channel_options(cfg["model"])
    if not channels or channels[0].get("channel") != "baidu":
        raise SystemExit("百度 Gemini 通道未处于首选可用状态")

    report: Dict[str, Any] = {
        "experiment": "baidu_gemini_video_ab_v1",
        "label_isolation": "推理阶段只读取盲测包；人工标签和原始答卷不进入模型请求。",
        "case_dir": args.case_dir.name,
        "provider": "baidu",
        "model": cfg["model"],
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "results": {},
    }
    if args.resume and args.output.exists():
        report = json.loads(args.output.read_text(encoding="utf-8"))

    run_parent = ROOT / "tmp" / "baidu_video_ab"
    run_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=run_parent) as temp_dir:
        bundle_args = SimpleNamespace(
            fps=1.0,
            sampling_mode="dense",
            max_frames_per_video=1200,
            api_frame_limit=24,
            probe_seconds=12.0,
            frame_width=960,
            supplemental_image_limit=48,
        )
        case = load_case_bundle(
            args.case_dir,
            bundle_args,
            Path(temp_dir),
            scenario_override="product_damage",
        )
        structured = dict(case.get("structured_business_context") or {})
        structured.update({
            "business_scenario": "product_damage",
            "continuity_policy": {
                "out_of_frame_warning_seconds": 2.0,
                "force_dense_scan": True,
                "scan_fps": 1.0,
                "require_identity_reestablishment": True,
            },
            "damage_causality_policy": {
                "force_action_scan": True,
                "dedicated_chunk_frames": 20,
                "context_frames": 6,
            },
        })
        case["structured_business_context"] = structured
        structured["continuity_claim_identity"] = derive_claim_identity([], case)
        video_paths = sorted(
            path for path in args.case_dir.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        )
        if len(video_paths) != 1:
            raise SystemExit("原生视频 A/B 当前只接受恰好一个视频的盲测包")
        native_case = load_case_bundle(
            args.case_dir,
            bundle_args,
            Path(temp_dir) / "native",
            scenario_override="product_damage",
            native_video={
                "video_index": 1,
                "api_path": str(video_paths[0]),
                "api_mime_type": "video/mp4",
            },
        )
        native_case["structured_business_context"] = copy.deepcopy(structured)
        native_case["structured_business_context"]["native_video_review"] = {"enabled": True}
        native_media_bytes = video_paths[0].stat().st_size + sum(
            Path(item["api_path"]).stat().st_size
            for key in ("frames", "supplemental_images", "official_reference_images")
            for item in native_case.get(key) or []
        )
        if native_media_bytes > INLINE_RAW_MEDIA_LIMIT:
            raise SystemExit("原生视频与图片的 Base64 载荷预算超过 100 MB 请求安全线")
        report["evidence"] = {
            "video_count": len(video_paths),
            "sampled_frame_count": len(case.get("frames") or []),
            "native_start_anchor_count": len(native_case.get("frames") or []),
            "supplemental_image_count": len(case.get("supplemental_images") or []),
            "official_reference_count": len(case.get("official_reference_images") or []),
            "native_raw_media_bytes": native_media_bytes,
        }

        for mode in modes:
            if args.resume and (report.get("results") or {}).get(mode, {}).get("status") == "success":
                continue
            started = time.time()
            current = copy.deepcopy(native_case if mode == "native" else case)
            if mode == "native":
                result = call_model(cfg, current, timeout=600, retries=1)
                native_gaps = native_dimension_gaps(result.get("parsed") or {}, "product_damage")
                if (
                    result.get("status") == "success"
                    and set(native_gaps).issubset({"opening_start_verification", "opening_video_hard_failure_candidate"})
                ):
                    opening_verification = call_opening_start_verification(
                        cfg,
                        current,
                        timeout=600,
                        retries=1,
                    )
                    result = merge_opening_start_verification(
                        result,
                        opening_verification,
                        current.get("frames") or [],
                        scenario="product_damage",
                    )
                summary = result_summary(
                    result,
                    native_media_parts=(
                        native_media_part_count(current)
                        + (
                            len(current.get("frames") or [])
                            if (result.get("opening_start_verification") or {}).get("status") not in {None, "skipped"}
                            else 0
                        )
                    ),
                )
            else:
                result = call_model_chunked(
                    {**cfg, "unified_multitask": mode == "unified"},
                    current,
                    timeout=600,
                    retries=1,
                )
                summary = result_summary(result)
            summary["process_wall_seconds"] = round(time.time() - started, 2)
            report.setdefault("results", {})[mode] = summary
            write_checkpoint(args.output, report)
            print(json.dumps({"mode": mode, **summary}, ensure_ascii=False))

    report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S %z")
    write_checkpoint(args.output, report)
    return 0 if all((report["results"].get(mode) or {}).get("status") == "success" for mode in modes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
