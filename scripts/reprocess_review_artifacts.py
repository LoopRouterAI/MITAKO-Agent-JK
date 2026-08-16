# -*- coding: utf-8 -*-
"""对已有成功工单重跑确定性业务规则并生成独立报告，不再次调用模型。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review_service import store
from review_service.service import (
    _sync_final_advisory_brief,
    postprocess_review,
    render_job_report,
)


REPORT_DIR = ROOT / "tests" / "reports"
DEFAULT_CHECKPOINT = REPORT_DIR / "review_0814_four_scene_blind_checkpoint_fresh.json"
CHINA_TZ = timezone(timedelta(hours=8))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot(review: Dict[str, Any]) -> Dict[str, Any]:
    advisory = review.get("advisory_assessment") or {}
    assessment = advisory.get("assessment") or {}
    human = advisory.get("human_review") or {}
    material = review.get("material_readiness") or {}
    summary = review.get("summary") or {}
    return {
        "predicted_label": summary.get("predicted_label"),
        "confidence": summary.get("confidence"),
        "material_status": material.get("status"),
        "workflow": advisory.get("workflow_recommendation"),
        "human_review": human.get("level"),
        "reason_codes": human.get("reason_codes") or [],
        "conclusion": assessment.get("conclusion"),
        "next_step": human.get("recommendation"),
    }


def reprocess_job(job: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """返回派生工单和可审计差异；输入工单及数据库保持不变。"""
    if job.get("status") != "SUCCEEDED":
        raise ValueError("only_succeeded_jobs_can_be_reprocessed")
    source_result = deepcopy(job.get("result") or {})
    source_review = deepcopy(source_result.get("review") or {})
    derived_review = postprocess_review(
        job,
        source_review,
        readiness=source_result.get("input_readiness") or {},
        media_forensics=source_result.get("media_forensics") or {},
        succeeded=True,
    )
    derived_review = _sync_final_advisory_brief(derived_review)
    derived_result = deepcopy(source_result)
    derived_result["review"] = derived_review
    derived_result["material_readiness"] = derived_review.get("material_readiness") or {}
    derived_job = deepcopy(job)
    derived_job["result"] = derived_result
    before = _snapshot(source_review)
    after = _snapshot(derived_review)
    return derived_job, {
        "before": before,
        "after": after,
        "changed_fields": [key for key in after if before.get(key) != after.get(key)],
    }


def _checkpoint_rows(path: Path) -> Iterable[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise RuntimeError("重处理断点必须是工单列表")
    for row in payload:
        if not isinstance(row, dict) or not row.get("job_id") or not row.get("case_id"):
            raise RuntimeError("重处理断点含无效工单")
        yield row


def export(checkpoint: Path, suffix: str) -> Dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    cases = []
    for row in _checkpoint_rows(checkpoint):
        job = store.get_job(str(row["job_id"]))
        if not job:
            raise RuntimeError(f"工单不存在：{row['job_id']}")
        derived_job, changes = reprocess_job(job)
        stem = f"review_0815_blind_{row['scenario']}_{row['case_id']}_{suffix}"
        json_path = REPORT_DIR / f"{stem}.json"
        html_path = REPORT_DIR / f"{stem}.html"
        evidence = {
            "generated_at": datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S %z"),
            "evidence_type": "deterministic_rule_reprocess_without_model_call",
            "formal_api_job": False,
            "source_job_id": job["job_id"],
            "source_status": job["status"],
            "scenario": row["scenario"],
            "client_case_id": row["case_id"],
            "changes": changes,
            "job": derived_job,
        }
        json_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        html_path.write_text(render_job_report(derived_job), encoding="utf-8")
        cases.append({
            "case_id": str(row["case_id"]),
            "scenario": str(row["scenario"]),
            "source_job_id": str(job["job_id"]),
            "changed_fields": changes["changed_fields"],
            "report_json": json_path.relative_to(ROOT).as_posix(),
            "report_html": html_path.relative_to(ROOT).as_posix(),
            "report_json_sha256": _sha256(json_path),
            "report_html_sha256": _sha256(html_path),
        })
    manifest = {
        "generated_at": datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S %z"),
        "evidence_type": "deterministic_rule_reprocess_without_model_call",
        "acceptance_boundary": "仅验证最新确定性规则与报告渲染；不能替代正式 API 新工单或模型效果验收。",
        "checkpoint": checkpoint.relative_to(ROOT).as_posix(),
        "cases": cases,
    }
    manifest_path = REPORT_DIR / f"review_0813_four_scenario_{suffix}_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--suffix", default="postprocessed_0814")
    args = parser.parse_args()
    manifest = export(args.checkpoint.resolve(), str(args.suffix).strip())
    print(json.dumps({"cases": len(manifest["cases"]), "changes": {
        item["case_id"]: item["changed_fields"] for item in manifest["cases"]
    }}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
