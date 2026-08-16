# -*- coding: utf-8 -*-
"""审核服务单件、文件夹与批量案件的真实请求回归。"""
from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "tests" / "reports"
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm", ".mkv"}
SAFE_CONTEXT_FILES = {
    "content.txt",
    "order_items.json",
    "order_info_snapshot.json",
    "product_master.json",
    "warehouse_master.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审核提交模式真实 E2E")
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://127.0.0.1:8015"))
    parser.add_argument("--visual-url", default=os.getenv("VISUAL_WORKBENCH_BASE_URL", "http://127.0.0.1:7861"))
    parser.add_argument(
        "--sample-dir",
        type=Path,
        default=ROOT / "docs" / "三大审核场景的小量样本" / "sample_004",
    )
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    return parser.parse_args()


def login(base_url: str) -> str:
    response = httpx.post(
        f"{base_url}/api/v1/auth/login",
        json={
            "username": os.getenv("E2E_ADMIN_USERNAME", "admin"),
            "password": os.getenv("E2E_ADMIN_PASSWORD", "admin123"),
            "tenant_id": os.getenv("E2E_TENANT_ID", "mitako"),
        },
        timeout=30,
    )
    response.raise_for_status()
    token = str(response.json().get("token") or "")
    if not token:
        raise RuntimeError("登录成功但未返回 Token")
    return token


def sample_assets(sample_dir: Path) -> tuple[Path, Path, list[Path]]:
    if not sample_dir.is_dir():
        raise RuntimeError(f"样本目录不存在：{sample_dir}")
    media = [path for path in sorted(sample_dir.iterdir()) if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES]
    videos = [path for path in media if path.suffix.lower() in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}]
    images = [path for path in media if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    if not videos or not images:
        raise RuntimeError("提交模式回归要求样本同时包含视频和图片")
    folder_files = media + [sample_dir / name for name in sorted(SAFE_CONTEXT_FILES) if (sample_dir / name).is_file()]
    return videos[0], images[0], folder_files


def submit_api_job(
    base_url: str,
    token: str,
    paths: list[Path],
    *,
    client_case_id: str,
    batch_id: str,
    run_id: str,
) -> str:
    metadata = {
        "client_case_id": client_case_id,
        "scenario": "minor_refund",
        "batch_id": batch_id,
        "priority": "normal",
        "source": "submission_modes_e2e",
        "customer_claim": "未成年人退款资料完整性审核",
        "claim_scope": {
            "split_status": "resolved",
            "stage": "combined",
            "active_claim_ids": ["CLM-MATERIAL"],
            "claims": [{"claim_id": "CLM-MATERIAL", "issue_type": "material_completeness"}],
        },
        "sampling_policy": {"preset": "adaptive", "frames_per_model_call": 24, "forensic_checks": True},
        "sop_context": {"policy_ref": "minor_refund_2_0", "business_boundary": "只生成审核建议，不执行退款"},
    }
    with ExitStack() as stack:
        files = [
            (
                "files",
                (
                    f"asset_{index:03d}{path.suffix.lower()}",
                    stack.enter_context(path.open("rb")),
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                ),
            )
            for index, path in enumerate(paths, start=1)
        ]
        with httpx.Client(timeout=httpx.Timeout(120, connect=30, write=120, read=120)) as client:
            response = client.post(
                f"{base_url}/api/v1/review/jobs",
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"{run_id}-{client_case_id}"},
                data={"metadata": json.dumps(metadata, ensure_ascii=False)},
                files=files,
            )
    if response.status_code != 202:
        raise RuntimeError(f"正式 API 提交失败：HTTP {response.status_code} {response.text[:800]}")
    job_id = str((response.json().get("job") or {}).get("job_id") or "")
    if not job_id:
        raise RuntimeError("正式 API 未返回 job_id")
    return job_id


def wait_jobs(base_url: str, token: str, job_ids: list[str], timeout: int) -> dict[str, str]:
    pending = set(job_ids)
    statuses: dict[str, str] = {}
    deadline = time.time() + timeout
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=60) as client:
        while pending and time.time() < deadline:
            for job_id in list(pending):
                response = client.get(f"{base_url}/api/v1/review/jobs/{job_id}", headers=headers)
                response.raise_for_status()
                status = str((response.json().get("job") or {}).get("status") or "")
                statuses[job_id] = status
                if status in {"SUCCEEDED", "FAILED"}:
                    pending.remove(job_id)
            if pending:
                time.sleep(2)
    if pending:
        raise TimeoutError(f"正式审核任务超时：{sorted(pending)}")
    return statuses


def run_workbench_single(visual_url: str, video: Path, timeout: int) -> dict[str, Any]:
    with video.open("rb") as stream:
        response = httpx.post(
            f"{visual_url}/api/review",
            data={
                "source_type": "upload",
                "scenario": "minor_material",
                "customer_claim": "未成年人退款资料完整性审核",
                "fps": "1",
                "max_frames": "24",
                "api_frame_limit": "24",
            },
            files={"file": ("evidence.mp4", stream, "video/mp4")},
            timeout=timeout,
        )
    response.raise_for_status()
    payload = response.json()
    return {
        "http_status": response.status_code,
        "ok": payload.get("ok") is True,
        "source_status": payload.get("source_status"),
        "review_status": (((payload.get("review") or {}).get("summary") or {}).get("review_status")),
    }


def run_workbench_folder(visual_url: str, paths: list[Path], timeout: int) -> dict[str, Any]:
    with ExitStack() as stack:
        files = [
            (
                "files",
                (
                    f"case/{path.name}",
                    stack.enter_context(path.open("rb")),
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                ),
            )
            for path in paths
        ]
        response = httpx.post(
            f"{visual_url}/api/review-folder",
            data={
                "scenario": "minor_material",
                "customer_claim": "未成年人退款资料完整性审核",
                "sampling_mode": "adaptive",
                "fps": "1",
                "max_frames": "24",
                "api_frame_limit": "24",
            },
            files=files,
            timeout=timeout,
        )
    response.raise_for_status()
    payload = response.json()
    ingestion = payload.get("ingestion") or {}
    return {
        "http_status": response.status_code,
        "ok": payload.get("ok") is True,
        "source_status": payload.get("source_status"),
        "review_status": (((payload.get("review") or {}).get("summary") or {}).get("review_status")),
        "accepted_count": ingestion.get("accepted_count"),
        "rejected_count": ingestion.get("rejected_count"),
    }


def run_workbench_batch(visual_url: str, video: Path, image: Path, timeout: int) -> dict[str, Any]:
    with ExitStack() as stack:
        files = []
        for case_id in ("case-a", "case-b"):
            for path, neutral_name in ((video, "evidence.mp4"), (image, "material.png")):
                files.append((
                    "files",
                    (
                        f"batch/{case_id}/{neutral_name}",
                        stack.enter_context(path.open("rb")),
                        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    ),
                ))
        response = httpx.post(
            f"{visual_url}/api/review-folders-batch",
            data={
                "scenario": "minor_material",
                "customer_claim": "未成年人退款资料完整性审核",
                "sampling_mode": "adaptive",
                "fps": "1",
                "max_frames": "24",
                "api_frame_limit": "24",
            },
            files=files,
            timeout=timeout,
        )
    response.raise_for_status()
    payload = response.json()
    summary = payload.get("summary") or {}
    return {
        "http_status": response.status_code,
        "ok": payload.get("ok") is True,
        "source_status": payload.get("source_status"),
        "total": summary.get("total"),
        "success": summary.get("success"),
        "report_count": len(payload.get("reports") or []),
        "case_ids": [item.get("case_id") for item in payload.get("cases") or []],
    }


def render_html(report: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(item['name'])}</td><td class={'ok' if item['ok'] else 'bad'}>{'PASS' if item['ok'] else 'FAIL'}</td><td>{html.escape(item['detail'])}</td></tr>"
        for item in report["checks"]
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>审核提交模式验收</title><style>body{{margin:0;background:#f4f6f4;color:#1d2721;font:15px/1.7 "Microsoft YaHei",sans-serif}}main{{max-width:1080px;margin:auto;padding:28px 16px}}section{{background:#fff;border:1px solid #dce4de;border-radius:8px;padding:20px;margin:12px 0}}h1{{margin:0 0 8px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #e2e8e3;vertical-align:top}}th{{background:#eef3ef}}.ok{{color:#176b43;font-weight:700}}.bad{{color:#a33830;font-weight:700}}code{{background:#eef2ef;padding:2px 5px;border-radius:4px}}</style></head><body><main><section><h1>审核提交模式验收</h1><p>正式 API 与网页工作台真实请求；未读取或发送人工标签、reply.json 或标准答案。</p></section><section><p>批次：<code>{html.escape(report['batch_id'])}</code> · 总结果：<b class={'ok' if report['ok'] else 'bad'}>{'PASS' if report['ok'] else 'FAIL'}</b></p><table><thead><tr><th>检查项</th><th>结果</th><th>证据</th></tr></thead><tbody>{rows}</tbody></table></section></main></body></html>"""


def main() -> int:
    args = parse_args()
    sample_dir = args.sample_dir.resolve()
    video, image, folder_files = sample_assets(sample_dir)
    token = login(args.base_url.rstrip("/"))
    batch_id = f"submission-modes-{args.run_id}"
    api_single = submit_api_job(
        args.base_url.rstrip("/"), token, [video],
        client_case_id=f"single-{args.run_id}", batch_id=batch_id, run_id=args.run_id,
    )
    api_folder = submit_api_job(
        args.base_url.rstrip("/"), token, [video, image],
        client_case_id=f"folder-{args.run_id}", batch_id=batch_id, run_id=args.run_id,
    )
    statuses = wait_jobs(args.base_url.rstrip("/"), token, [api_single, api_folder], args.timeout)
    headers = {"Authorization": f"Bearer {token}"}
    batch_response = httpx.get(
        f"{args.base_url.rstrip('/')}/api/v1/review/batches/{batch_id}", headers=headers, timeout=60,
    )
    batch_response.raise_for_status()
    batch = batch_response.json()
    web_single = run_workbench_single(args.visual_url.rstrip("/"), video, args.timeout)
    web_folder = run_workbench_folder(args.visual_url.rstrip("/"), folder_files, args.timeout)
    web_batch = run_workbench_batch(args.visual_url.rstrip("/"), video, image, args.timeout)
    workbench_html = httpx.get(f"{args.visual_url.rstrip('/')}/", timeout=30).text

    summary = batch.get("summary") or {}
    checks = [
        {"name": "API-single-asset", "ok": statuses.get(api_single) == "SUCCEEDED", "detail": f"job={api_single} status={statuses.get(api_single)}"},
        {"name": "API-folder-multi-asset", "ok": statuses.get(api_folder) == "SUCCEEDED", "detail": f"job={api_folder} status={statuses.get(api_folder)} assets=2"},
        {"name": "API-batch-query", "ok": summary.get("total") == 2 and summary.get("complete") is True, "detail": f"batch={batch_id} total={summary.get('total')} complete={summary.get('complete')}"},
        {"name": "Web-single-file", "ok": web_single.get("ok") is True and web_single.get("review_status") == "completed", "detail": json.dumps(web_single, ensure_ascii=False)},
        {"name": "Web-folder", "ok": web_folder.get("ok") is True and web_folder.get("review_status") == "completed" and int(web_folder.get("accepted_count") or 0) >= 2, "detail": json.dumps(web_folder, ensure_ascii=False)},
        {"name": "Web-folder-batch", "ok": web_batch.get("ok") is True and web_batch.get("total") == 2 and web_batch.get("success") == 2 and web_batch.get("report_count") == 2, "detail": json.dumps(web_batch, ensure_ascii=False)},
        {"name": "Web-UI-binding", "ok": "webkitdirectory" in workbench_html and "'/api/review-folder'" in workbench_html and "'/api/review-folders-batch'" in workbench_html and "'/api/review'" in workbench_html, "detail": "单文件、单工单文件夹和批量工单控件及请求路由均存在"},
    ]
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "blind_input_boundary": "未读取或上传 reply.json、人工标签和标准答案",
        "batch_id": batch_id,
        "api_jobs": {"single": api_single, "folder": api_folder},
        "api_statuses": statuses,
        "batch_summary": summary,
        "web_single": web_single,
        "web_folder": web_folder,
        "web_batch": web_batch,
        "checks": checks,
        "ok": all(item["ok"] for item in checks),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "review_submission_modes_20260717-final.json"
    html_path = REPORT_DIR / "review_submission_modes_20260717-final.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "checks": checks, "json": str(json_path), "html": str(html_path)}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
