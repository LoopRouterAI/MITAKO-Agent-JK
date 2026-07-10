# -*- coding: utf-8 -*-
"""甲方样本批量审核 API 验收：多案件并发提交、轮询与结果校验。"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List

import httpx


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = ROOT / "docs" / "三大审核场景的小量样本"
REPORT_DIR = ROOT / "tests" / "reports"
SCENARIOS = {
    "sample_001": "wrong_item",
    "sample_002": "wrong_item",
    "sample_003": "product_damage",
    "sample_004": "minor_refund",
}
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".txt", ".json"}
PRIVATE_RESULT_KEYS = {"api_key", "system_prompt", "user_prompt", "raw_response", "raw_text", "provider", "model", "display_model"}


def has_private_result_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() in PRIVATE_RESULT_KEYS or has_private_result_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(has_private_result_key(item) for item in value)
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://127.0.0.1:8015"))
    parser.add_argument("--samples", default=os.getenv("E2E_REVIEW_SAMPLES", "sample_002,sample_004"))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("E2E_REVIEW_TIMEOUT_SECONDS", "1200")))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--sampling-preset", choices=["adaptive", "strict", "forensic"], default="adaptive")
    return parser.parse_args()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def metadata_for(sample_id: str, batch_id: str = "", sampling_preset: str = "adaptive") -> Dict[str, Any]:
    sample_dir = SAMPLE_ROOT / sample_id
    manifest = read_json(sample_dir / "manifest.json", {})
    resources = manifest.get("resources") or []
    asset_fields = {
        str(item.get("local_file") or ""): list(item.get("fields") or [])
        for item in resources
        if item.get("local_file")
    }
    return {
        "client_case_id": str(manifest.get("id") or sample_id),
        "scenario": SCENARIOS[sample_id],
        "source": "customer_sample_batch_e2e",
        "batch_id": batch_id,
        "priority": "high",
        "ticket_id": str(manifest.get("id") or sample_id),
        "order_no": str(manifest.get("order_no") or ""),
        "customer_claim": (sample_dir / "content.txt").read_text(encoding="utf-8").strip(),
        "complaint_stage": str(manifest.get("admin_status") or manifest.get("status") or ""),
        "order_items": read_json(sample_dir / "order_items.json", manifest.get("order_items") or []),
        "product_master_data": read_json(sample_dir / "product_master.json", manifest.get("product_master_data") or {}),
        "warehouse_master_data": read_json(sample_dir / "warehouse_master.json", manifest.get("warehouse_master_data") or {}),
        "conversation_history": read_json(sample_dir / "reply.json", []),
        "sop_context": {
            "summary": {
                "product_damage": "核验开箱连续性、未拆封包装/面单、瑕疵位置与严重程度；只输出证据建议，业务动作由人工执行。",
                "wrong_item": "比对订单商品与实物角色、款式、规格、SKU；排除光栅、隐藏款和包装尺寸口径差异。",
                "minor_refund": "核验五类必需材料及人、号、订单、付款关系；必须进入人工一审、二审和终审。",
            }.get(SCENARIOS[sample_id], "")
        },
        "asset_fields": asset_fields,
        "source_record": manifest,
        "sampling_policy": {
            "preset": sampling_preset,
            "fps": 2.0 if sampling_preset == "forensic" else 1.0,
            "max_frames_per_video": 1800 if sampling_preset == "forensic" else 1200,
            "frames_per_model_call": 24,
        },
    }


def files_for(sample_id: str) -> List[Path]:
    sample_dir = SAMPLE_ROOT / sample_id
    return [
        path
        for path in sorted(sample_dir.iterdir())
        if path.is_file()
        and path.suffix.lower() in ALLOWED_SUFFIXES
        and path.name not in {"reply.json", "sample_labels.json"}
    ]


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
        raise RuntimeError("未获取到管理员 Token")
    return token


def submit(base_url: str, token: str, sample_id: str, timeout: int, run_id: str, batch_id: str, sampling_preset: str) -> Dict[str, Any]:
    metadata = metadata_for(sample_id, batch_id, sampling_preset)
    paths = files_for(sample_id)
    with ExitStack() as stack:
        files = [
            (
                "files",
                (
                    path.name,
                    stack.enter_context(path.open("rb")),
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                ),
            )
            for path in paths
        ]
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=15, write=timeout, read=timeout)) as client:
            response = client.post(
                f"{base_url}/api/v1/review/jobs",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": f"sample-review-{sample_id}-{metadata['client_case_id']}-{sampling_preset}{('-' + run_id) if run_id else ''}",
                },
                data={"metadata": json.dumps(metadata, ensure_ascii=False)},
                files=files,
            )
    if response.is_error:
        raise RuntimeError(f"提交 {sample_id} 失败：HTTP {response.status_code} {response.text[:2000]}")
    body = response.json()
    return {
        "sample_id": sample_id,
        "file_count": len(paths),
        "bytes": sum(path.stat().st_size for path in paths),
        "created": body.get("created"),
        "job_id": (body.get("job") or {}).get("job_id"),
        "initial_status": (body.get("job") or {}).get("status"),
    }


def wait_job(base_url: str, token: str, job_id: str, timeout: int) -> Dict[str, Any]:
    deadline = time.time() + timeout
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30) as client:
        while time.time() < deadline:
            response = client.get(f"{base_url}/api/v1/review/jobs/{job_id}", headers=headers)
            response.raise_for_status()
            job = response.json().get("job") or {}
            if job.get("status") in {"SUCCEEDED", "FAILED"}:
                return job
            time.sleep(2)
    raise TimeoutError(f"审核任务等待超时：{job_id}")


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    sample_ids = [item.strip() for item in args.samples.split(",") if item.strip()]
    batch_id = f"sample-review-batch-{args.sampling_preset}-{args.run_id or int(time.time())}"
    unknown = [item for item in sample_ids if item not in SCENARIOS]
    if unknown:
        raise SystemExit(f"未知样本：{unknown}")
    missing = [item for item in sample_ids if not (SAMPLE_ROOT / item).exists()]
    if missing:
        raise SystemExit(f"样本目录不存在：{missing}")

    with httpx.Client(timeout=30) as client:
        token = login(client, base_url)
        contract_response = client.get(
            f"{base_url}/api/v1/review/contracts",
            headers={"Authorization": f"Bearer {token}"},
        )
        contract_response.raise_for_status()
        supported = set((contract_response.json().get("contract") or {}).get("supported_scenarios") or [])
        if not {"product_damage", "wrong_item", "missing_item", "minor_refund"}.issubset(supported):
            raise RuntimeError(f"审核场景契约不完整：{sorted(supported)}")

    submitted: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(4, len(sample_ids))) as pool:
        futures = {
            pool.submit(submit, base_url, token, sample_id, args.timeout, args.run_id, batch_id, args.sampling_preset): sample_id
            for sample_id in sample_ids
        }
        for future in as_completed(futures):
            submitted.append(future.result())

    results = []
    for item in submitted:
        job = wait_job(base_url, token, str(item["job_id"]), args.timeout)
        review = (job.get("result") or {}).get("review") or {}
        brief = review.get("agent_brief") or {}
        report = review.get("agent_report") or {}
        inference = report.get("inference_estimate") or {}
        videos = (report.get("evidence_package") or {}).get("videos") or []
        gallery_frames = (report.get("media_gallery") or {}).get("frames") or []
        all_videos_represented = not videos or {
            int(item.get("video_index")) for item in videos if item.get("video_index") is not None
        }.issubset({int(item.get("video_index")) for item in gallery_frames if item.get("video_index") is not None})
        expected_strategy = "full_timeline_adaptive" if args.sampling_preset == "adaptive" else "full_timeline_dense"
        timeline_ok = all(item.get("sampling_strategy") == expected_strategy for item in videos)
        source_fields_ok = (job.get("metadata") or {}).get("source_record") == read_json(SAMPLE_ROOT / item["sample_id"] / "manifest.json", {})
        report_url = (review.get("report") or {}).get("html_url") or ""
        with httpx.Client(timeout=30) as client:
            html_response = client.get(base_url + report_url, headers={"Authorization": f"Bearer {token}"}) if report_url else None
        html_ok = bool(html_response and html_response.status_code == 200 and "Agent 报告" in html_response.text)
        safe_result = not has_private_result_key(report) and not any(
            marker in (html_response.text.lower() if html_response else "")
            for marker in ("api_key", "system_prompt", "user_prompt", "raw_response", "raw_text")
        )
        ok = (
            job.get("status") == "SUCCEEDED"
            and bool(brief)
            and bool(report)
            and bool(inference)
            and timeline_ok
            and html_ok
            and safe_result
            and source_fields_ok
            and all_videos_represented
        )
        results.append(
            {
                **item,
                "status": job.get("status"),
                "ok": ok,
                "confidence": brief.get("confidence"),
                "conclusion": brief.get("conclusion"),
                "inference_estimate": inference,
                "full_timeline_sampling": timeline_ok,
                "html_report": html_ok,
                "public_result_safe": safe_result,
                "source_manifest_preserved": source_fields_ok,
                "all_videos_represented": all_videos_represented,
                "diagnostics": job.get("diagnostics") or {},
            }
        )

    with httpx.Client(timeout=30) as client:
        batch_response = client.get(
            f"{base_url}/api/v1/review/batches/{batch_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        paged_response = client.get(
            f"{base_url}/api/v1/review/batches/{batch_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 1, "offset": 1 if len(sample_ids) > 1 else 0},
        )
    batch_summary = (batch_response.json().get("summary") or {}) if batch_response.status_code == 200 else {}
    paged_body = paged_response.json() if paged_response.status_code == 200 else {}
    paged_summary = paged_body.get("summary") or {}
    batch_ok = (
        batch_response.status_code == 200
        and paged_response.status_code == 200
        and batch_summary.get("total") == len(sample_ids)
        and batch_summary.get("complete") is True
        and paged_summary.get("total") == len(sample_ids)
        and paged_summary.get("returned") == 1
        and len(paged_body.get("jobs") or []) == 1
    )
    report = {
        "ok": all(item["ok"] for item in results) and batch_ok,
        "base_url": base_url,
        "batch_id": batch_id,
        "batch_summary": batch_summary,
        "samples": sample_ids,
        "run_id": args.run_id,
        "sampling_preset": args.sampling_preset,
        "results": sorted(results, key=lambda item: item["sample_id"]),
        "note": "当前资料没有真实漏发货样本；missing_item 已验证 OpenAPI 契约与 SOP 规则覆盖，准确率需甲方补样本后验收。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORT_DIR / "review_service_batch_latest.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
