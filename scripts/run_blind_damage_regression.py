# -*- coding: utf-8 -*-
"""通过公开工作台接口执行视觉审核盲测包，不读取人工标签。"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from contextlib import ExitStack
from pathlib import Path

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)


ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".txt", ".json"}
FORBIDDEN_ANSWER_FILES = {"annotation.json", "reply.json"}
BUSINESS_TO_TECHNICAL = {
    "product_damage": "product_damage",
    "wrong_item": "video_unboxing",
    "missing_item": "video_unboxing",
    "minor_refund": "minor_material",
    "minor_material": "minor_material",
}


def technical_scenario(scenario: str) -> str:
    try:
        return BUSINESS_TO_TECHNICAL[scenario]
    except KeyError as exc:
        raise ValueError("unsupported_business_scenario") from exc


def internal_metrics_headers(request_id: str = "") -> dict[str, str]:
    token = os.getenv("VISUAL_REPORT_SIGNING_SECRET", "").strip()
    headers = {
        "X-MITAKO-Internal-Metrics": "1",
        "X-MITAKO-Internal-Token": token,
    } if token else {}
    if headers and request_id:
        headers["X-Request-ID"] = request_id
    return headers


def internal_metrics_fields() -> dict[str, str]:
    return {"rule_tenant_id": "mitako"} if os.getenv("VISUAL_REPORT_SIGNING_SECRET", "").strip() else {}


def blind_case_id(bundle: Path) -> str:
    digest = hashlib.sha256(str(bundle.resolve()).encode("utf-8")).hexdigest()[:12].upper()
    return f"CASE-{digest}"


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


def run_case(
    base_url: str,
    bundle: Path,
    scenario: str,
    fps: float,
    max_frames: int,
) -> dict:
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
        business_scenario = "minor_refund" if scenario == "minor_material" else scenario
        data = {
            "scenario": technical_scenario(scenario),
            "business_scenario": business_scenario,
            "ticket_id": blind_case_id(bundle),
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
        data.update(internal_metrics_fields())
        with httpx.Client(
            timeout=httpx.Timeout(3600, connect=10, write=3600, read=3600),
            trust_env=False,
        ) as client:
            response = client.post(
                base_url.rstrip("/") + "/api/review-folder",
                headers=internal_metrics_headers(f"{blind_case_id(bundle)}-workbench"),
                data=data,
                files=files,
            )
        if response.is_error:
            raise RuntimeError(f"visual_workbench_http_{response.status_code}: {response.text[:2000]}")
        response.raise_for_status()
        return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="执行视觉审核盲测回归")
    parser.add_argument("bundles", nargs="+", type=Path)
    parser.add_argument(
        "--scenario",
        choices=("product_damage", "wrong_item", "missing_item", "minor_refund", "minor_material"),
        default="product_damage",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:7864")
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=1200)
    parser.add_argument("--output", type=Path, default=Path("tests/reports/blind_damage_regression_latest.json"))
    args = parser.parse_args()
    results = []
    for bundle in args.bundles:
        payload = run_case(
            args.base_url,
            bundle,
            args.scenario,
            args.fps,
            args.max_frames,
        )
        parsed = (((payload.get("review") or {}).get("agent_report") or {}).get("parsed") or {})
        advisory = (
            parsed.get("advisory_assessment")
            or ((payload.get("review") or {}).get("agent_report") or {}).get("advisory_assessment")
            or (payload.get("review") or {}).get("advisory_assessment")
            or {}
        )
        minor = parsed.get("minor_material_assessment") or {}
        results.append(
            {
                "case_id": blind_case_id(bundle),
                "ok": payload.get("ok"),
                "predicted_label": parsed.get("predicted_label"),
                "confidence": parsed.get("confidence"),
                "conclusion": (parsed.get("overall_audit") or {}).get("conclusion"),
                "workflow_recommendation": advisory.get("workflow_recommendation"),
                "human_review": advisory.get("human_review"),
                "minor_material_assessment": {
                    "readiness": minor.get("readiness"),
                    "visual_precheck_status": minor.get("visual_precheck_status"),
                    "declared_image_count": minor.get("declared_image_count"),
                    "accepted_image_count": minor.get("accepted_image_count"),
                    "processed_image_count": minor.get("processed_image_count"),
                    "checklist": minor.get("checklist"),
                    "field_consistency": minor.get("field_consistency"),
                    "required_materials": minor.get("required_materials"),
                    "payment_capability_risk": minor.get("payment_capability_risk"),
                    "authenticity_assessment": minor.get("authenticity_assessment"),
                }
                if minor
                else None,
                "material_gaps": parsed.get("material_gaps"),
                "damage_causality_assessment": parsed.get("damage_causality_assessment"),
                "object_continuity_assessment": parsed.get("object_continuity_assessment"),
                "continuity_guard_reason": parsed.get("continuity_guard_reason"),
                "causality_guard_reason": parsed.get("causality_guard_reason"),
                "pass_integrity_status": parsed.get("pass_integrity_status"),
                "specialized_pass_guard_reason": parsed.get("specialized_pass_guard_reason"),
                "video_audit_conclusion": parsed.get("video_audit_conclusion"),
                "decision_policy_audit": parsed.get("decision_policy_audit")
                or (payload.get("review") or {}).get("decision_policy_audit"),
                "inference_estimate": ((payload.get("review") or {}).get("agent_report") or {}).get("inference_estimate"),
                "report": (payload.get("review") or {}).get("report"),
                "diagnostics": payload.get("diagnostics") or (payload.get("review") or {}).get("diagnostics"),
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False, indent=2))
    report = {
        "label_isolation": "推理阶段不读取 annotation、reply 原文件、管理员消息或人工标签；只使用盲测包内清洗后的用户本人消息，本文件不计算命中率。",
        "base_url": args.base_url,
        "scenario": args.scenario,
        "fps": args.fps,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
