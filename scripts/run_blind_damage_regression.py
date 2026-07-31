# -*- coding: utf-8 -*-
"""通过公开工作台接口执行商品有伤盲测包，不读取人工标签。"""
from __future__ import annotations

import argparse
import json
import mimetypes
from contextlib import ExitStack
from pathlib import Path

import httpx


ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".txt", ".json"}
FORBIDDEN_ANSWER_FILES = {"annotation.json", "reply.json"}


def validate_label_isolation(audit: dict) -> None:
    included = {str(name).lower() for name in audit.get("included_files") or []}
    if included & FORBIDDEN_ANSWER_FILES:
        raise ValueError("blind_bundle_isolation_failed")


def submission_paths(bundle: Path, audit: dict) -> list[Path]:
    included = {str(name) for name in audit.get("included_files") or []}
    if not included:
        raise ValueError("blind_bundle_missing_included_files")
    allowed = {
        path.name
        for path in bundle.iterdir()
        if path.is_file()
        and path.name != "blind_bundle_audit.json"
        and path.suffix.lower() in ALLOWED_SUFFIXES
    }
    unexpected = sorted(allowed - included)
    missing = sorted(included - allowed)
    if unexpected or missing:
        raise ValueError(f"blind_bundle_file_set_mismatch: unexpected={unexpected}, missing={missing}")
    return [bundle / name for name in sorted(included) if name != "blind_bundle_audit.json"]


def run_case(base_url: str, bundle: Path, fps: float, max_frames: int, threshold: float) -> dict:
    audit = json.loads((bundle / "blind_bundle_audit.json").read_text(encoding="utf-8"))
    validate_label_isolation(audit)
    claim = (bundle / "content.txt").read_text(encoding="utf-8-sig").strip() if (bundle / "content.txt").exists() else ""
    customer_context = {}
    context_path = bundle / "customer_context.json"
    if context_path.exists():
        customer_context = json.loads(context_path.read_text(encoding="utf-8-sig"))
    window_manifests = [
        json.loads(path.read_text(encoding="utf-8-sig"))
        for path in bundle.glob("*.window.json")
    ]
    with ExitStack() as stack:
        files = []
        for path in submission_paths(bundle, audit):
            handle = stack.enter_context(path.open("rb"))
            files.append(("files", (path.name, handle, mimetypes.guess_type(path.name)[0] or "application/octet-stream")))
        data = {
            "scenario": "product_damage",
            "business_scenario": "product_damage",
            "ticket_id": bundle.name,
            "customer_claim": claim,
            "conversation_history": json.dumps(customer_context, ensure_ascii=False) if customer_context else "",
            "asset_manifest": json.dumps({"video_windows": window_manifests}, ensure_ascii=False) if window_manifests else "",
            "sampling_mode": "dense",
            "fps": str(fps),
            "max_frames": str(max_frames),
            "api_frame_limit": "24",
            "probe_seconds": "12",
            "continuity_policy": json.dumps(
                {
                    "out_of_frame_warning_seconds": threshold,
                    "force_dense_scan": True,
                    "scan_fps": fps,
                    "require_identity_reestablishment": True,
                },
                ensure_ascii=False,
            ),
            "damage_causality_policy": json.dumps(
                {
                    "force_action_scan": True,
                    "dedicated_chunk_frames": 20,
                    "context_frames": 6,
                },
                ensure_ascii=False,
            ),
        }
        with httpx.Client(
            timeout=httpx.Timeout(3600, connect=10, write=3600, read=3600),
            trust_env=False,
        ) as client:
            response = client.post(base_url.rstrip("/") + "/api/review-folder", data=data, files=files)
        if response.is_error:
            raise RuntimeError(f"visual_workbench_http_{response.status_code}: {response.text[:2000]}")
        response.raise_for_status()
        return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="执行商品有伤盲测回归")
    parser.add_argument("bundles", nargs="+", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:7864")
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=1200)
    parser.add_argument("--out-of-frame-threshold", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=Path("tests/reports/blind_damage_regression_latest.json"))
    args = parser.parse_args()
    results = []
    for bundle in args.bundles:
        payload = run_case(args.base_url, bundle, args.fps, args.max_frames, args.out_of_frame_threshold)
        parsed = (((payload.get("review") or {}).get("agent_report") or {}).get("parsed") or {})
        results.append(
            {
                "case_id": bundle.name,
                "ok": payload.get("ok"),
                "predicted_label": parsed.get("predicted_label"),
                "confidence": parsed.get("confidence"),
                "damage_causality_assessment": parsed.get("damage_causality_assessment"),
                "object_continuity_assessment": parsed.get("object_continuity_assessment"),
                "continuity_guard_reason": parsed.get("continuity_guard_reason"),
                "causality_guard_reason": parsed.get("causality_guard_reason"),
                "pass_integrity_status": parsed.get("pass_integrity_status"),
                "specialized_pass_guard_reason": parsed.get("specialized_pass_guard_reason"),
                "decision_policy_audit": parsed.get("decision_policy_audit")
                or (payload.get("review") or {}).get("decision_policy_audit"),
                "report": (payload.get("review") or {}).get("report"),
                "diagnostics": payload.get("diagnostics") or (payload.get("review") or {}).get("diagnostics"),
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False, indent=2))
    report = {
        "label_isolation": "推理阶段不读取 annotation、reply 原文件、管理员消息或人工标签；只使用盲测包内清洗后的用户本人消息，本文件不计算命中率。",
        "base_url": args.base_url,
        "fps": args.fps,
        "out_of_frame_threshold_seconds": args.out_of_frame_threshold,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
