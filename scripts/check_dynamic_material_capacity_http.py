# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "tests" / "reports" / "dynamic_material_capacity_http_latest.json"


def git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="真实 HTTP 单案动态资料容量回归")
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--count", type=int, default=62)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--image",
        type=Path,
        default=ROOT / "docs" / "三大审核场景的小量样本" / "sample_004" / "frame_001.jpg",
    )
    return parser.parse_args()


def main() -> int:
    options = args()
    if not options.image.is_file():
        candidates = sorted((options.image.parent).glob("*.*"))
        options.image = next(
            (path for path in candidates if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}),
            options.image,
        )
    if not options.image.is_file():
        raise FileNotFoundError(f"缺少回归图片：{options.image}")
    if options.count < 1:
        raise ValueError("count 必须大于 0")

    base_url = options.base_url.rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(180, connect=30, write=180, read=180)) as client:
        login = client.post(
            f"{base_url}/api/v1/auth/login",
            json={
                "username": os.getenv("E2E_ADMIN_USERNAME", "admin"),
                "password": os.getenv("E2E_ADMIN_PASSWORD", "admin123"),
                "tenant_id": os.getenv("E2E_TENANT_ID", "mitako"),
            },
        )
        login.raise_for_status()
        headers = {
            "Authorization": f"Bearer {login.json()['token']}",
            "Idempotency-Key": f"dynamic-material-{options.count}-{int(time.time())}",
        }
        metadata = {
            "client_case_id": f"dynamic-material-{options.count}-{int(time.time())}",
            "scenario": "minor_refund",
            "source": "dynamic_material_capacity_http_e2e",
            "customer_claim": "未成年人退款资料审核",
            "output_options": {"include_html_report": False},
            "claim_scope": {
                "split_status": "resolved",
                "stage": "combined",
                "active_claim_ids": ["CLM-MATERIAL"],
                "claims": [{"claim_id": "CLM-MATERIAL", "issue_type": "material_completeness"}],
            },
            "sop_context": {"policy_ref": "minor_refund_2_0"},
        }
        with ExitStack() as stack:
            files = [
                (
                    "files",
                    (
                        f"material_{index:03d}{options.image.suffix.lower()}",
                        stack.enter_context(options.image.open("rb")),
                        mimetypes.guess_type(options.image.name)[0] or "image/jpeg",
                    ),
                )
                for index in range(1, options.count + 1)
            ]
            submitted = client.post(
                f"{base_url}/api/v1/review/jobs",
                headers=headers,
                data={"metadata": json.dumps(metadata, ensure_ascii=False)},
                files=files,
            )
        submitted.raise_for_status()
        job = submitted.json()["job"]
        job_id = job["job_id"]
        deadline = time.time() + options.timeout
        while time.time() < deadline:
            response = client.get(
                f"{base_url}/api/v1/review/jobs/{job_id}",
                headers={"Authorization": headers["Authorization"]},
            )
            response.raise_for_status()
            job = response.json()["job"]
            if job["status"] in {"SUCCEEDED", "FAILED"}:
                break
            time.sleep(2)

    ingestion = job.get("metadata", {}).get("ingestion", {})
    assessment = (
        job.get("result", {})
        .get("review", {})
        .get("agent_report", {})
        .get("parsed", {})
        .get("minor_material_assessment", {})
    )
    checks = {
        "job_succeeded": job.get("status") == "SUCCEEDED",
        "all_assets_saved": len(job.get("assets") or []) == options.count,
        "expanded_capacity": ingestion.get("capacity_mode") == ("expanded" if options.count > 40 else "standard"),
        "all_images_accepted": assessment.get("accepted_image_count") == options.count,
        "all_images_processed": assessment.get("processed_image_count") == options.count,
        "coverage_complete": assessment.get("coverage_complete") is True,
    }
    report = {
        "ok": all(checks.values()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "job_id": job_id,
        "status": job.get("status"),
        "requested_count": options.count,
        "ingestion": ingestion,
        "assessment": {
            key: assessment.get(key)
            for key in (
                "declared_image_count",
                "accepted_image_count",
                "processed_image_count",
                "coverage_ratio",
                "coverage_complete",
                "processing_status",
                "system_action",
            )
        },
        "checks": checks,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
