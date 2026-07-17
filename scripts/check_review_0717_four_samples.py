# -*- coding: utf-8 -*-
"""0717 四样本正式审核 API 盲测，不读取或上传人工标签与客服结论。"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "tests" / "reports"
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm", ".mkv"}
CASES = ("617341", "614176", "618205", "617911")
FORBIDDEN_FILES = {"annotation.json", "reply.json", "manifest.json"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://127.0.0.1:8015"))
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--submit-workers", type=int, default=2)
    parser.add_argument("--resume-report", type=Path)
    parser.add_argument("--replacement-report", type=Path)
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--skip-strong-618205", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def case_dir(root: Path, case_id: str) -> Path:
    matches = [path for path in root.rglob(case_id) if path.is_dir() and path.name == case_id]
    if len(matches) != 1:
        raise RuntimeError(f"样本 {case_id} 目录数量不是 1：{len(matches)}")
    return matches[0]


def case_inputs(root: Path, case_id: str) -> Tuple[str, List[Path]]:
    folder = case_dir(root, case_id)
    claim_path = folder / "content.txt"
    if not claim_path.is_file():
        raise RuntimeError(f"样本 {case_id} 缺少 content.txt")
    claim = claim_path.read_text(encoding="utf-8-sig").strip()
    assets = [path for path in sorted(folder.iterdir()) if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES]
    if not assets:
        raise RuntimeError(f"样本 {case_id} 没有媒体文件")
    if any(path.name in FORBIDDEN_FILES for path in assets):
        raise RuntimeError("盲测输入包含禁止文件")
    return claim, assets


def metadata(case_id: str, claim: str, preset: str, run_id: str) -> Dict[str, Any]:
    policy: Dict[str, Any] = {"mode": "conservative_review"}
    if case_id == "617341":
        policy = {
            "mode": "classification_recommendation",
            "policy_ref": "MITAKO-PD-MISSING-OPENING@20260717.1",
            "opening_video_required": True,
            "missing_required_opening_video": "negative",
        }
    return {
        "client_case_id": f"blind-{case_id}-{preset}-{run_id}",
        "scenario": "product_damage",
        "source": "customer_media_blind_e2e",
        "batch_id": f"blind-0717-{run_id}",
        "priority": "high",
        "customer_claim": claim,
        "claim_scope": {
            "scope_version": "1",
            "split_status": "resolved",
            "stage": "initial",
            "claim_text": claim,
            "active_claim_ids": [f"CLM-{case_id}-INITIAL"],
            "claims": [
                {
                    "claim_id": f"CLM-{case_id}-INITIAL",
                    "role": "primary",
                    "subject_ref": "claimed_item",
                    "issue_type": "product_damage",
                    "location": "以本次用户原始诉求为准",
                }
            ],
            "excluded_issue_types": ["later_supplemental_claims"] if case_id == "614176" else [],
        },
        "decision_policy": policy,
        "sampling_policy": {
            "preset": preset,
            "frames_per_model_call": 24,
            "forensic_checks": True,
        },
        "continuity_policy": {
            "out_of_frame_warning_seconds": 2.0,
            "require_identity_reestablishment": True,
        },
        "damage_causality_policy": {"dedicated_chunk_frames": 20, "context_frames": 6},
    }


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


def submit_job(base_url: str, token: str, root: Path, case_id: str, preset: str, run_id: str, timeout: int) -> Dict[str, Any]:
    claim, paths = case_inputs(root, case_id)
    body = metadata(case_id, claim, preset, run_id)
    asset_manifest = [
        {
            "neutral_name": f"asset_{index:03d}{path.suffix.lower()}",
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
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
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                ),
            )
            for item, path in zip(asset_manifest, paths)
        ]
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=30, write=timeout, read=timeout)) as client:
            response = client.post(
                f"{base_url}/api/v1/review/jobs",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": f"blind-{run_id}-{case_id}-{preset}",
                },
                data={"metadata": json.dumps(body, ensure_ascii=False)},
                files=files,
            )
    if response.status_code != 202:
        raise RuntimeError(f"{case_id}/{preset} 提交失败：HTTP {response.status_code} {response.text[:800]}")
    job = response.json().get("job") or {}
    return {
        "case_id": case_id,
        "preset": preset,
        "job_id": job.get("job_id"),
        "request_metadata_sha256": hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "assets": asset_manifest,
        "total_bytes": sum(item["bytes"] for item in asset_manifest),
    }


def wait_job(base_url: str, token: str, item: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    deadline = time.time() + timeout
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=60) as client:
        while time.time() < deadline:
            response = client.get(f"{base_url}/api/v1/review/jobs/{item['job_id']}", headers=headers)
            response.raise_for_status()
            job = response.json().get("job") or {}
            if job.get("status") in {"SUCCEEDED", "FAILED"}:
                result = job.get("result") or {}
                review = result.get("review") or {}
                parsed = ((review.get("agent_report") or {}).get("parsed") or {})
                summary = review.get("summary") or {}
                forensics = result.get("media_forensics") or {}
                return {
                    **item,
                    "status": job.get("status"),
                    "predicted_label": summary.get("predicted_label") or parsed.get("predicted_label"),
                    "confidence": summary.get("confidence") or parsed.get("confidence"),
                    "media_forensics_status": forensics.get("status"),
                    "continuity": parsed.get("object_continuity_assessment") or {},
                    "global_review_summary": parsed.get("global_review_summary") or {},
                    "aggregation_warnings": parsed.get("aggregation_warnings") or [],
                    "decision_policy_audit": review.get("decision_policy_audit") or parsed.get("decision_policy_audit") or {},
                    "damage_observability": parsed.get("damage_observability") or {},
                    "overall_conclusion": ((parsed.get("overall_audit") or {}).get("conclusion") or "")[:1500],
                    "inference_estimate": (review.get("agent_report") or {}).get("inference_estimate") or {},
                    "workbench_transport": result.get("workbench_transport") or {},
                    "diagnostics": job.get("diagnostics") or {},
                }
            time.sleep(2)
    raise TimeoutError(f"任务超时：{item['job_id']}")


def evaluate(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    by_key = {(row["case_id"], row["preset"]): row for row in rows}
    checks.append({"name": "all_jobs_succeeded", "ok": all(row["status"] == "SUCCEEDED" for row in rows)})
    checks.append({
        "name": "all_video_forensics_completed",
        "ok": all(row["media_forensics_status"] == "completed" for row in rows if row["case_id"] != "617341"),
    })
    if ("617341", "adaptive") in by_key:
        row_617341 = by_key[("617341", "adaptive")]
        checks.append({
            "name": "617341_versioned_policy_negative",
            "ok": row_617341["predicted_label"] == "negative"
            and (row_617341["decision_policy_audit"] or {}).get("rule_id") == "PD-N-OPENING-VIDEO-REQUIRED",
        })
        checks.append({
            "name": "617341_policy_report_synchronized",
            "ok": "必须提交开箱视频" in row_617341["overall_conclusion"]
            and "建议人工客服予以支持" not in row_617341["overall_conclusion"],
        })
    if ("614176", "adaptive") in by_key:
        row_614176 = by_key[("614176", "adaptive")]
        checks.append({"name": "614176_initial_claim_only", "ok": "撕拉" not in row_614176["overall_conclusion"]})
        checks.append({"name": "614176_disputed_scope_stays_review", "ok": row_614176["predicted_label"] == "review"})
    if ("617911", "adaptive") in by_key:
        row_617911 = by_key[("617911", "adaptive")]
        checks.append({
            "name": "617911_no_unsafe_auto_negative",
            "ok": row_617911["predicted_label"] == "review"
            and (row_617911["decision_policy_audit"] or {}).get("applied") is not True,
        })
    for preset in ("adaptive", "strong"):
        if ("618205", preset) not in by_key:
            continue
        row = by_key[("618205", preset)]
        checks.append({"name": f"618205_{preset}_not_positive", "ok": row["predicted_label"] == "review"})
        checks.append({
            "name": f"618205_{preset}_global_timeline",
            "ok": bool(row["global_review_summary"])
            and row["global_review_summary"].get("chunk_narratives_excluded_from_public_conclusion") is True,
        })
    return checks


def render_html(report: Dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(row['case_id'])}</td><td>{html.escape(row['preset'])}</td>"
        f"<td>{html.escape(str(row['status']))}</td><td>{html.escape(str(row['predicted_label']))}</td>"
        f"<td>{html.escape(str(row['confidence']))}</td><td>{html.escape(str(row['media_forensics_status']))}</td>"
        f"<td>{html.escape(row['overall_conclusion'][:220])}</td></tr>"
        for row in report["results"]
    )
    checks = "".join(
        f"<li class=\"{'pass' if item['ok'] else 'fail'}\">{'通过' if item['ok'] else '失败'}：{html.escape(item['name'])}</li>"
        for item in report["checks"]
    )
    return f"""<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><title>0717 四样本盲测</title>
<style>body{{font:15px/1.65 Arial,sans-serif;margin:0;background:#f5f7f8;color:#172126}}main{{max-width:1180px;margin:auto;padding:36px}}section{{background:white;border:1px solid #dce3e6;border-radius:6px;padding:24px;margin:16px 0}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid #e4e9eb;text-align:left;vertical-align:top}}.pass{{color:#087a4b}}.fail{{color:#c02d2d}}</style>
<main><h1>0717 四样本正式 API 盲测</h1><p>运行编号：{html.escape(report['run_id'])}。模型输入不包含 annotation.json、reply.json、manifest.json、人工结论或目录分类。</p>
<section><h2>验收门槛</h2><ul>{checks}</ul></section><section><h2>任务结果</h2><table><thead><tr><th>样本</th><th>档位</th><th>状态</th><th>标签</th><th>置信度</th><th>ffprobe</th><th>全局结论</th></tr></thead><tbody>{rows}</tbody></table></section></main></html>"""


def main() -> int:
    args = parse_args()
    root = args.sample_root.expanduser().resolve()
    base_url = args.base_url.rstrip("/")
    token = login(base_url)
    selected_cases = tuple(item.strip() for item in args.cases.split(",") if item.strip())
    unknown_cases = set(selected_cases) - set(CASES)
    if unknown_cases:
        raise RuntimeError(f"未知样本：{sorted(unknown_cases)}")
    jobs = [(case_id, "adaptive") for case_id in selected_cases]
    if "618205" in selected_cases and not args.skip_strong_618205:
        jobs.append(("618205", "strong"))
    submitted: List[Dict[str, Any]] = []
    if args.resume_report:
        previous = json.loads(args.resume_report.expanduser().resolve().read_text(encoding="utf-8-sig"))
        submitted = [
            {
                key: row.get(key)
                for key in ("case_id", "preset", "job_id", "request_metadata_sha256", "assets", "total_bytes")
            }
            for row in previous.get("results") or []
        ]
        if {(item.get("case_id"), item.get("preset")) for item in submitted} != set(jobs):
            raise RuntimeError("续跑报告的任务集合与 0717 四样本验收矩阵不一致")
        if args.replacement_report:
            replacement = json.loads(args.replacement_report.expanduser().resolve().read_text(encoding="utf-8-sig"))
            replacement_rows = {
                (row.get("case_id"), row.get("preset")): row
                for row in replacement.get("results") or []
            }
            submitted = [replacement_rows.get((row.get("case_id"), row.get("preset")), row) for row in submitted]
    else:
        with ThreadPoolExecutor(max_workers=max(1, min(args.submit_workers, len(jobs)))) as pool:
            futures = {
                pool.submit(submit_job, base_url, token, root, case_id, preset, args.run_id, args.timeout): (case_id, preset)
                for case_id, preset in jobs
            }
            for future in as_completed(futures):
                submitted.append(future.result())
    results = [wait_job(base_url, token, item, args.timeout) for item in submitted]
    results.sort(key=lambda item: (CASES.index(item["case_id"]), item["preset"]))
    checks = evaluate(results)
    report = {
        "run_id": args.run_id,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "input_isolation": {
            "sent": ["中性文件名媒体", "content.txt 原始诉求文本", "本次 claim_scope", "采样与连续性策略"],
            "not_sent": sorted(FORBIDDEN_FILES | {"目录分类", "人工结论", "评测标签"}),
        },
        "checks": checks,
        "results": results,
        "ok": all(item["ok"] for item in checks),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / f"review_0717_four_samples_{args.run_id}.json"
    html_path = REPORT_DIR / f"review_0717_four_samples_{args.run_id}.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    latest = REPORT_DIR / "review_0717_four_samples_latest.json"
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "json": str(json_path), "html": str(html_path), "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
