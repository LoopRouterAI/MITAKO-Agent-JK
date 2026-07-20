# -*- coding: utf-8 -*-
"""144989 未成年人退款资料正式 API 盲测。"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
import re
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review_input_safety import redact_review_personal_data


REPORT_DIR = ROOT / "tests" / "reports"
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm", ".mkv"}
FORBIDDEN_FILES = {"annotation.json", "reply.json", "manifest.json"}
SENSITIVE_OUTPUT_PATTERNS = (
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),
    re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="144989 未成年人退款资料正式 API 盲测")
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://127.0.0.1:8015"))
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def find_case(root: Path) -> Path:
    matches = [path for path in root.rglob("144989") if path.is_dir() and path.name == "144989"]
    if len(matches) != 1:
        raise RuntimeError(f"样本 144989 目录数量不是 1：{len(matches)}")
    return matches[0]


def load_blind_inputs(root: Path) -> tuple[str, List[Path]]:
    folder = find_case(root)
    claim_path = folder / "content.txt"
    if not claim_path.is_file():
        raise RuntimeError("样本缺少 content.txt")
    claim = redact_review_personal_data(claim_path.read_text(encoding="utf-8-sig").strip())
    assets = [
        path for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES
    ]
    if any(path.name.lower() in FORBIDDEN_FILES for path in assets):
        raise RuntimeError("盲测输入包含禁止文件")
    if not assets:
        raise RuntimeError("样本没有可审核媒体")
    return claim, assets


def login(base_url: str) -> str:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{base_url}/api/v1/auth/login",
            json={
                "username": os.getenv("E2E_ADMIN_USERNAME", "admin"),
                "password": os.getenv("E2E_ADMIN_PASSWORD", "admin123"),
                "tenant_id": os.getenv("E2E_TENANT_ID", "mitako"),
            },
        )
    response.raise_for_status()
    token = str(response.json().get("token") or "")
    if not token:
        raise RuntimeError("登录成功但未返回 Token")
    return token


def submit(base_url: str, token: str, root: Path, run_id: str, timeout: int) -> Dict[str, Any]:
    claim, paths = load_blind_inputs(root)
    metadata = {
        "client_case_id": f"blind-minor-material-{run_id}",
        "scenario": "minor_refund",
        "source": "customer_media_blind_e2e",
        "batch_id": f"blind-minor-{run_id}",
        "priority": "high",
        "customer_claim": claim,
        "complaint_stage": "combined_material_review",
        "sop_context": {
            "policy_ref": "minor_refund_2_0",
            "required_material_groups": [
                "identity",
                "relationship_household_or_birth",
                "signed_commitment",
                "order_or_payment_proof",
                "mobile_realname_proof",
            ],
            "business_boundary": "材料完整后继续执行视觉字段一致性初审；权威真伪验证和退款动作由甲方系统及授权人员完成",
        },
        "claim_scope": {
            "scope_version": "1",
            "split_status": "resolved",
            "stage": "combined",
            "claim_text": "未成年人退款资料完整性与视觉字段一致性初审",
            "active_claim_ids": ["CLM-MINOR-MATERIAL"],
            "claims": [{
                "claim_id": "CLM-MINOR-MATERIAL",
                "role": "primary",
                "subject_ref": "minor_refund_application",
                "issue_type": "material_completeness_and_visual_consistency",
            }],
        },
        "decision_policy": {"mode": "conservative_review"},
        "sampling_policy": {
            "preset": "adaptive",
            "frames_per_model_call": 24,
            "forensic_checks": True,
        },
    }
    manifest = [
        {
            "neutral_name": f"asset_{index:03d}{path.suffix.lower()}",
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        }
        for index, path in enumerate(paths, start=1)
    ]
    with ExitStack() as stack:
        files = [
            (
                "files",
                (
                    item["neutral_name"],
                    stack.enter_context(path.open("rb")),
                    item["mime_type"],
                ),
            )
            for item, path in zip(manifest, paths)
        ]
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=30, write=timeout, read=timeout)) as client:
            response = client.post(
                f"{base_url}/api/v1/review/jobs",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": f"blind-minor-{run_id}",
                },
                data={"metadata": json.dumps(metadata, ensure_ascii=False)},
                files=files,
            )
    if response.status_code != 202:
        raise RuntimeError(f"提交失败：HTTP {response.status_code} {response.text[:1000]}")
    job = response.json().get("job") or {}
    return {
        "job_id": job.get("job_id"),
        "asset_manifest": manifest,
        "image_count": sum(1 for item in manifest if item["mime_type"].startswith("image/")),
        "video_count": sum(1 for item in manifest if item["mime_type"].startswith("video/")),
        "total_bytes": sum(item["bytes"] for item in manifest),
        "request_metadata_sha256": hashlib.sha256(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def wait_job(base_url: str, token: str, submission: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    deadline = time.time() + timeout
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=60) as client:
        while time.time() < deadline:
            response = client.get(f"{base_url}/api/v1/review/jobs/{submission['job_id']}", headers=headers)
            response.raise_for_status()
            job = response.json().get("job") or {}
            if job.get("status") in {"SUCCEEDED", "FAILED"}:
                report_response = client.get(
                    f"{base_url}/api/v1/review/jobs/{submission['job_id']}/report",
                    headers=headers,
                )
                result = job.get("result") or {}
                review = result.get("review") or {}
                parsed = ((review.get("agent_report") or {}).get("parsed") or {})
                return {
                    **submission,
                    "status": job.get("status"),
                    "predicted_label": (review.get("summary") or {}).get("predicted_label") or parsed.get("predicted_label"),
                    "decision": parsed.get("decision"),
                    "system_yes_no": parsed.get("system_yes_no"),
                    "confidence": (review.get("summary") or {}).get("confidence") or parsed.get("confidence"),
                    "conclusion": ((parsed.get("overall_audit") or {}).get("conclusion") or ""),
                    "material_gaps": parsed.get("material_gaps") or [],
                    "minor_material_assessment": parsed.get("minor_material_assessment") or {},
                    "business_action_allowed": parsed.get("business_action_allowed"),
                    "human_required": parsed.get("human_required"),
                    "media_forensics_status": (result.get("media_forensics") or {}).get("status"),
                    "workbench_transport": result.get("workbench_transport") or {},
                    "inference_estimate": (review.get("agent_report") or {}).get("inference_estimate") or {},
                    "report_status": report_response.status_code,
                    "report_contains_raw_sensitive_data": any(
                        pattern.search(report_response.text)
                        for pattern in SENSITIVE_OUTPUT_PATTERNS
                    ),
                    "diagnostics": job.get("diagnostics") or {},
                }
            time.sleep(2)
    raise TimeoutError(f"任务超时：{submission['job_id']}")


def evaluate(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    assessment = row.get("minor_material_assessment") or {}
    checklist = assessment.get("checklist") or []
    relationship = next((item for item in checklist if item.get("requirement_id") == "relationship"), {})
    field_consistency = assessment.get("field_consistency") or {}
    consistency_checks = field_consistency.get("checks") or []
    authoritative = assessment.get("authoritative_verification") or {}
    inference_channels = (row.get("inference_estimate") or {}).get("channels") or {}
    consistency_channel = inference_channels.get("minor_field_consistency") or {}
    safe_gate = (
        row.get("predicted_label") == "review"
        and row.get("decision") == "manual_review"
        and row.get("system_yes_no") == "REVIEW"
        and row.get("business_action_allowed") is False
        and (
            assessment.get("visual_precheck_status") == "passed"
            if field_consistency.get("verdict") == "matched"
            else assessment.get("visual_precheck_status") in {"needs_review", "incomplete"}
        )
    )
    serialized = json.dumps(row, ensure_ascii=False)
    return [
        {"name": "job_succeeded", "ok": row.get("status") == "SUCCEEDED"},
        {"name": "all_20_images_processed", "ok": assessment.get("declared_image_count") == 20 and assessment.get("processed_image_count") == 20},
        {"name": "coverage_complete", "ok": assessment.get("coverage_complete") is True and assessment.get("coverage_ratio") == 1.0},
        {"name": "five_material_groups_present", "ok": len(checklist) == 5 and all(item.get("status") == "present" for item in checklist)},
        {"name": "household_or_birth_rule", "ok": relationship.get("status") == "present" and "二选一" in str(relationship.get("rule_note") or "")},
        {"name": "no_false_missing_claim", "ok": not row.get("material_gaps") and "缺" not in str(row.get("conclusion") or "")},
        {
            "name": "five_visual_consistency_checks_executed",
            "ok": field_consistency.get("status") in {"completed", "degraded"}
            and len(consistency_checks) == 5
            and all(item.get("status") != "not_assessed" for item in consistency_checks),
        },
        {"name": "consistency_decision_gate", "ok": safe_gate},
        {
            "name": "authoritative_verification_boundary",
            "ok": authoritative.get("status") == "customer_integration_required",
        },
        {
            "name": "consistency_cost_accounted",
            "ok": int(consistency_channel.get("model_calls") or 0) >= 5,
        },
        {"name": "business_boundary_enforced", "ok": row.get("business_action_allowed") is False and row.get("human_required") is True},
        {"name": "video_forensics_completed", "ok": row.get("media_forensics_status") == "completed"},
        {"name": "report_available", "ok": row.get("report_status") == 200},
        {
            "name": "pii_not_returned",
            "ok": not row.get("report_contains_raw_sensitive_data")
            and not any(pattern.search(serialized) for pattern in SENSITIVE_OUTPUT_PATTERNS),
        },
    ]


def render_html(report: Dict[str, Any]) -> str:
    row = report["result"]
    assessment = row.get("minor_material_assessment") or {}
    checks = report["checks"]
    check_rows = "".join(
        f"<tr><td>{html.escape(item['name'])}</td><td class={'ok' if item['ok'] else 'bad'}>{'PASS' if item['ok'] else 'FAIL'}</td></tr>"
        for item in checks
    )
    material_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('label') or ''))}</td>"
        f"<td>{html.escape(str(item.get('status') or ''))}</td>"
        f"<td>{html.escape(', '.join(str(value) for value in item.get('evidence_image_indices') or []))}</td>"
        f"<td>{html.escape(str(item.get('rule_note') or ''))}</td>"
        "</tr>"
        for item in assessment.get("checklist") or []
    )
    field_consistency = assessment.get("field_consistency") or {}
    check_labels = {
        "identity_age": "身份与年龄",
        "guardian_relationship": "监护关系",
        "commitment_signatures": "承诺书签署主体",
        "order_payment": "订单与支付",
        "mobile_realname": "手机号实名归属",
    }
    consistency_rows = "".join(
        "<tr>"
        f"<td>{html.escape(check_labels.get(str(item.get('check_id')), str(item.get('check_id') or '')))}</td>"
        f"<td>{html.escape(str(item.get('status') or ''))}</td>"
        f"<td>{html.escape(', '.join(str(value) for value in item.get('evidence_image_indices') or []))}</td>"
        f"<td>{html.escape(', '.join(str(value) for value in item.get('risk_reason_codes') or []) or '无')}</td>"
        "</tr>"
        for item in field_consistency.get("checks") or []
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>144989 未成年人资料审核回归</title>
<style>
body{{margin:0;background:#f3f5f2;color:#202823;font-family:"Microsoft YaHei","Segoe UI",sans-serif}}main{{max-width:1080px;margin:auto;padding:28px 18px 60px}}section{{background:#fff;border:1px solid #dce3de;border-radius:8px;padding:20px;margin:14px 0}}h1{{margin:0 0 8px;font-size:28px}}h2{{font-size:19px}}p{{line-height:1.7}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #e3e8e4;vertical-align:top}}th{{background:#eef2ef}}.ok{{color:#176b43;font-weight:700}}.bad{{color:#a42d2d;font-weight:700}}.metric{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}}.metric div{{border:1px solid #dde5df;padding:12px;border-radius:6px}}small{{display:block;color:#66736b;margin-bottom:5px}}
</style></head><body><main>
<section><h1>144989 未成年人资料审核回归</h1><p>正式 API 盲测；未向模型发送正样本目录标签、reply.json 或人工退款结论。审核包含材料完整性与视觉字段一致性两阶段。</p></section>
<section class="metric"><div><small>任务状态</small><b>{html.escape(str(row.get('status')))}</b></div><div><small>证据标签</small><b>{html.escape(str(row.get('predicted_label')))}</b></div><div><small>图片覆盖</small><b>{assessment.get('processed_image_count', 0)}/{assessment.get('declared_image_count', 0)}</b></div><div><small>置信度</small><b>{html.escape(str(row.get('confidence')))}</b></div></section>
<section><h2>结论</h2><p>{html.escape(str(row.get('conclusion') or ''))}</p><p>边界：视觉字段一致不等于资料具有法定真实性；身份证、运营商实名、订单和支付仍需甲方权威接口或授权人员核验。</p></section>
<section><h2>SOP 五类材料</h2><table><thead><tr><th>材料</th><th>状态</th><th>图片编号</th><th>规则</th></tr></thead><tbody>{material_rows}</tbody></table></section>
<section><h2>视觉字段一致性初审</h2><p>总体：{html.escape(str(field_consistency.get('verdict') or 'not_assessed'))}</p><table><thead><tr><th>检查项</th><th>状态</th><th>图片编号</th><th>风险码</th></tr></thead><tbody>{consistency_rows}</tbody></table></section>
<section><h2>自动验收</h2><table><thead><tr><th>检查项</th><th>结果</th></tr></thead><tbody>{check_rows}</tbody></table></section>
</main></body></html>"""


def main() -> int:
    args = parse_args()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    token = login(args.base_url)
    submission = submit(args.base_url, token, args.sample_root.resolve(), args.run_id, args.timeout)
    row = wait_job(args.base_url, token, submission, args.timeout)
    checks = evaluate(row)
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": args.base_url,
        "blind_input_boundary": "未读取或上传 reply.json、manifest.json、人工标签和退款结论",
        "result": row,
        "checks": checks,
        "ok": all(item["ok"] for item in checks),
    }
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"minor_refund_144989_{stamp}.json"
    html_path = REPORT_DIR / f"minor_refund_144989_{stamp}.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    print(json.dumps({
        "ok": report["ok"],
        "job_id": row.get("job_id"),
        "passed": sum(1 for item in checks if item["ok"]),
        "total": len(checks),
        "json_report": str(json_path),
        "html_report": str(html_path),
        "checks": checks,
    }, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
