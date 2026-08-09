# -*- coding: utf-8 -*-
"""复跑最终商业验收样本，并生成可追溯的 JSON/HTML 证据。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import mimetypes
import os
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review_service import service, store


REPORT_DIR = ROOT / "tests" / "reports"
CHINA_TZ = timezone(timedelta(hours=8))
CASES = (
    {
        "case_id": "598089",
        "source_job": "RJ-929FD4BDE02D46CF",
        "runs": 2,
        "json_names": (
            "review_0809_native_optimized_pd_latest.json",
            "review_0809_native_optimized_pd_stability_2.json",
        ),
        "html_names": (
            "review_0809_native_optimized_pd_latest.html",
            "review_0809_native_optimized_pd_stability_2.html",
        ),
        "manual_baseline": "开箱视频不合格：偏离过久、商品未完整展示",
    },
    {
        "case_id": "606669",
        "source_job": "RJ-4856B4E78D474CFD",
        "runs": 1,
        "json_names": ("review_0809_pd_r04_final_latest.json",),
        "html_names": ("review_0809_pd_r04_final_latest.html",),
        "manual_baseline": "开箱关键条件不完整，不支持直接认定商品有伤诉求",
    },
    {
        "case_id": "568689",
        "source_job": "RJ-71989F427E524F15",
        "runs": 1,
        "json_names": ("review_0809_missing_568689_final_latest.json",),
        "html_names": ("review_0809_missing_568689_final_latest.html",),
        "manual_baseline": "仓库终核确认实收摆件与订单商品一致，确定未漏发",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://127.0.0.1:8015"))
    parser.add_argument("--timeout", type=int, default=2400)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def login(client: httpx.Client, base_url: str) -> str:
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


def source_case(source_job: str) -> tuple[Dict[str, Any], List[Path], List[Dict[str, Any]]]:
    source = store.get_job(source_job)
    if not source:
        raise RuntimeError(f"找不到源工单：{source_job}")
    metadata = copy.deepcopy(source["metadata"])
    metadata.pop("ingestion", None)
    metadata["idempotency_key"] = ""
    paths = []
    manifest = []
    for index, asset in enumerate(source["assets"], start=1):
        path = service.upload_root() / source_job / asset["stored_name"]
        if not path.is_file() or path.stat().st_size != int(asset["size"]):
            raise RuntimeError(f"源媒体缺失或大小变化：{path}")
        digest = sha256(path)
        if digest != asset["sha256"]:
            raise RuntimeError(f"源媒体哈希变化：{path}")
        suffix = Path(asset["original_name"]).suffix.lower()
        neutral_name = f"asset_{index:03d}{suffix}"
        paths.append(path)
        manifest.append({"neutral_name": neutral_name, "bytes": path.stat().st_size, "sha256": digest})
    return metadata, paths, manifest


def submit(
    client: httpx.Client,
    base_url: str,
    token: str,
    case: Dict[str, Any],
    run_number: int,
) -> Dict[str, Any]:
    metadata, paths, manifest = source_case(case["source_job"])
    run_id = f"{int(time.time())}-{run_number}"
    metadata.update({
        "client_case_id": f"{case['case_id']}-final-acceptance-{run_id}",
        "source": "final_commercial_acceptance_20260809",
        "batch_id": f"final-commercial-20260809-{run_id}",
    })
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
            for item, path in zip(manifest, paths)
        ]
        response = client.post(
            f"{base_url}/api/v1/review/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": f"final-commercial-{case['case_id']}-{run_id}",
            },
            data={"metadata": json.dumps(metadata, ensure_ascii=False)},
            files=files,
        )
    if response.status_code != 202:
        raise RuntimeError(f"{case['case_id']} 发单失败：HTTP {response.status_code} {response.text[:1000]}")
    job = response.json()["job"]
    print(f"已提交 {case['case_id']} 第 {run_number} 次：{job['job_id']}", flush=True)
    return {
        "case": case,
        "run_number": run_number,
        "job_id": job["job_id"],
        "manifest": manifest,
    }


def wait_all(client: httpx.Client, base_url: str, token: str, rows: List[Dict[str, Any]], timeout: int) -> None:
    deadline = time.time() + timeout
    pending = {row["job_id"]: row for row in rows}
    observed: Dict[str, str] = {}
    headers = {"Authorization": f"Bearer {token}"}
    while pending and time.time() < deadline:
        for job_id, row in list(pending.items()):
            response = client.get(f"{base_url}/api/v1/review/jobs/{job_id}", headers=headers)
            response.raise_for_status()
            job = response.json()["job"]
            status = job["status"]
            if observed.get(job_id) != status:
                print(f"{row['case']['case_id']} / {job_id}：{status}", flush=True)
                observed[job_id] = status
            if status in {"SUCCEEDED", "FAILED"}:
                row["job"] = job
                pending.pop(job_id)
        if pending:
            time.sleep(3)
    if pending:
        raise TimeoutError(f"真实验收任务超时：{', '.join(pending)}")


def parsed(job: Dict[str, Any]) -> Dict[str, Any]:
    return (((job.get("result") or {}).get("review") or {}).get("agent_report") or {}).get("parsed") or {}


def case_summary(row: Dict[str, Any], json_name: str, html_name: str) -> Dict[str, Any]:
    job = row["job"]
    result = job.get("result") or {}
    review = result.get("review") or {}
    summary = review.get("summary") or {}
    advisory = result.get("advisory_assessment") or review.get("advisory_assessment") or {}
    assessment = parsed(job)
    opening = ((assessment.get("video_audit_conclusion") or {}).get("opening_video_compliance") or {})
    damage = assessment.get("damage_causality_assessment") or {}
    primary_video = ((damage.get("evidence_source_summary") or {}).get("primary_video") or {})
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "manual_baseline": row["case"]["manual_baseline"],
        "predicted_label": summary.get("predicted_label") or assessment.get("predicted_label"),
        "confidence": summary.get("confidence") or assessment.get("confidence"),
        "human_review": (advisory.get("human_review") or {}).get("level") or summary.get("human_review_level"),
        "material_gaps": assessment.get("material_gaps") or [],
        "opening_result": opening.get("result"),
        "issue_visible_in_continuous_opening": opening.get("issue_visible_in_continuous_opening"),
        "business_follow_up_reason": assessment.get("business_follow_up_reason") or "",
        "primary_claim_support": primary_video.get("claim_support"),
        "overall_conclusion": (assessment.get("overall_audit") or {}).get("conclusion") or "",
        "report_json": f"tests/reports/{json_name}",
        "report_html": f"tests/reports/{html_name}",
    }


def damage_follow_up_consistent(item: Dict[str, Any]) -> bool:
    reason = str(item.get("business_follow_up_reason") or "").lower()
    contradictory = (
        "without needing human",
        "no human intervention required",
        "证据完整有效",
        "直接支持用户诉求",
    )
    return item.get("primary_claim_support") == "insufficient" and not any(
        phrase in reason for phrase in contradictory
    )


def export(client: httpx.Client, base_url: str, token: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        case = row["case"]
        index = row["run_number"] - 1
        json_name = case["json_names"][index]
        html_name = case["html_names"][index]
        evidence = {
            "generated_at": datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S %z"),
            "evidence_type": "real_api_review",
            "manual_evaluation_baseline": case["manual_baseline"],
            "submitted_assets": row["manifest"],
            "job": row["job"],
        }
        (REPORT_DIR / json_name).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        report = client.get(f"{base_url}/api/v1/review/jobs/{row['job_id']}/report", headers=headers)
        report.raise_for_status()
        (REPORT_DIR / html_name).write_text(report.text, encoding="utf-8")
        grouped.setdefault(case["case_id"], []).append(case_summary(row, json_name, html_name))

    checks = {
        "all_jobs_succeeded": all(item["status"] == "SUCCEEDED" for items in grouped.values() for item in items),
        "598089_stable_manual_alignment": len(grouped["598089"]) == 2
        and all(
            item["predicted_label"] in {"negative", "review"}
            and item["opening_result"] == "noncompliant"
            and item["issue_visible_in_continuous_opening"] is False
            and damage_follow_up_consistent(item)
            and not item["material_gaps"]
            for item in grouped["598089"]
        ),
        "606669_negative_without_material_gap": grouped["606669"][0]["predicted_label"] == "negative"
        and grouped["606669"][0]["opening_result"] == "noncompliant"
        and damage_follow_up_consistent(grouped["606669"][0])
        and not grouped["606669"][0]["material_gaps"],
        "568689_warehouse_closed_without_human": grouped["568689"][0]["predicted_label"] == "negative"
        and grouped["568689"][0]["human_review"] == "not_required"
        and "确定未漏发" in grouped["568689"][0]["overall_conclusion"]
        and not grouped["568689"][0]["material_gaps"],
    }
    commercial = {
        "generated_at": datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S %z"),
        "generator": "scripts/run_final_commercial_acceptance.py",
        "commercial_boundary": "受控试点证据，不代表全量生产准确率",
        "checks": checks,
        "cases": grouped,
    }
    (REPORT_DIR / "review_0809_commercial_acceptance_latest.json").write_text(
        json.dumps(commercial, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not all(checks.values()):
        raise RuntimeError(f"商业验收未通过：{json.dumps(checks, ensure_ascii=False)}")
    return commercial


def main() -> int:
    args = parse_args()
    timeout = httpx.Timeout(args.timeout, connect=30, write=args.timeout, read=60)
    with httpx.Client(timeout=timeout) as client:
        token = login(client, args.base_url)
        rows = [
            submit(client, args.base_url, token, case, run_number)
            for case in CASES
            for run_number in range(1, case["runs"] + 1)
        ]
        wait_all(client, args.base_url, token, rows, args.timeout)
        commercial = export(client, args.base_url, token, rows)
    print(json.dumps(commercial["checks"], ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
