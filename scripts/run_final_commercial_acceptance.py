# -*- coding: utf-8 -*-
"""执行当前四场景密封盲测，并生成可追溯的 JSON/HTML 证据。"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
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

from poc.visual_review_poc.order_info_adapter import build_order_info_context, read_safe_ticket_manifest
from review_public_safety import redact_public_review_data
from review_input_safety import read_user_conversation_history
from review_service import store
from review_service.schemas import ReviewMaterialReadiness


REPORT_DIR = ROOT / "tests" / "reports"
CHINA_TZ = timezone(timedelta(hours=8))
SCENARIOS = {"product_damage", "wrong_item", "missing_item", "minor_refund"}
REQUIRED_CASES_PER_SCENE = 2
CONTRACT_VERSION = "MITAKO-FOUR-SCENE@20260814.1"
CURRENT_ARTIFACT_TAG = "0816"
BLIND_MANIFEST_PATH = ROOT / "tests" / "acceptance" / "four_scene_blind_manifest_20260816.json"
DEFAULT_SAMPLE_ROOT = Path(r"E:\AIGC\0 Mitako样本")
DEFAULT_CHECKPOINT_PATH = REPORT_DIR / "review_0816_formally_unrun_blind_checkpoint.json"
DEFAULT_EXECUTION_ID = "20260816.1"
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm", ".mkv"}
FORBIDDEN_INPUT_NAMES = {"reply.json", "annotation.json", "manifest.json", "sample_labels.json"}
DEFAULT_MODEL_PROFILE = "baidu-gemini-3.5-flash-lite-high-high-fps1-when-video-provider-default-output"
UNSEEN_AUDIT_VERSION = "strict-unseen-v1"
UNSEEN_AUDIT_SCOPES = {
    "active_conversation",
    "project_worktree",
    "git_history",
    "prior_blind_manifests",
}
FORMALLY_UNRUN_AUDIT_VERSION = "formally-unrun-v1"
FORMALLY_UNRUN_AUDIT_SCOPES = {
    "review_service_jobs",
    "report_artifacts",
    "submission_checkpoints",
    "prior_blind_runs",
}
DETECTED_MEDIA_TYPES = (
    (".jpg", "image/jpeg", lambda head: head.startswith(b"\xff\xd8\xff")),
    (".png", "image/png", lambda head: head.startswith(b"\x89PNG\r\n\x1a\n")),
    (".webp", "image/webp", lambda head: head.startswith(b"RIFF") and head[8:12] == b"WEBP"),
    (".mp4", "video/mp4", lambda head: b"ftyp" in head[:32]),
    (".webm", "video/webm", lambda head: head.startswith(b"\x1aE\xdf\xa3")),
)


def case_ids_sha256(case_ids: List[str]) -> str:
    normalized = "\n".join(sorted(str(case_id).strip() for case_id in case_ids))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _blind_audit_valid(payload: Dict[str, Any]) -> bool:
    cases = payload.get("cases") if isinstance(payload, dict) else None
    audit = payload.get("unseen_audit") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not isinstance(audit, dict):
        return False
    case_ids = [str(item.get("case_id") or "") for item in cases if isinstance(item, dict)]
    checked_scopes = audit.get("checked_scopes")
    if not isinstance(checked_scopes, list) or not all(isinstance(item, str) for item in checked_scopes):
        return False
    expected_scopes = {
        UNSEEN_AUDIT_VERSION: UNSEEN_AUDIT_SCOPES,
        FORMALLY_UNRUN_AUDIT_VERSION: FORMALLY_UNRUN_AUDIT_SCOPES,
    }.get(audit.get("version"))
    return (
        expected_scopes is not None
        and audit.get("status") == "verified_before_freeze"
        and bool(str(audit.get("audited_at") or "").strip())
        and set(checked_scopes) == expected_scopes
        and audit.get("case_ids_sha256") == case_ids_sha256(case_ids)
        and audit.get("matches") == []
    )


def load_blind_manifest(path: Path = BLIND_MANIFEST_PATH) -> Dict[str, Any]:
    """读取不含人工答案的冻结样本清单。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"盲测清单不可读：{path}") from exc
    if payload.get("label_state") != "sealed":
        raise RuntimeError("模型执行前的盲测清单必须保持 sealed")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise RuntimeError("盲测清单缺少 cases")
    forbidden = {"expected_label", "manual_baseline", "manual_source", "sample_dir"}
    counts = {scenario: 0 for scenario in SCENARIOS}
    case_ids = set()
    for case in cases:
        if not isinstance(case, dict) or forbidden.intersection(case):
            raise RuntimeError("盲测清单包含人工答案或本地标签路径")
        scenario = str(case.get("scenario") or "")
        case_id = str(case.get("case_id") or "")
        if scenario not in SCENARIOS or not case_id.isdigit() or case_id in case_ids:
            raise RuntimeError(f"盲测 Case 无效或重复：{case_id or '-'}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(case.get("input_bundle_sha256") or "")):
            raise RuntimeError(f"盲测 Case 缺少输入哈希：{case_id}")
        counts[scenario] += 1
        case_ids.add(case_id)
    if any(count != REQUIRED_CASES_PER_SCENE for count in counts.values()):
        raise RuntimeError("盲测必须为四场景各 2 个随机 Case")
    if not _blind_audit_valid(payload):
        raise RuntimeError("盲测清单缺少有效的盲验输入审计")
    return payload


def resolve_blind_cases(
    payload: Dict[str, Any],
    *,
    sample_root: Path = DEFAULT_SAMPLE_ROOT,
) -> List[Dict[str, Any]]:
    """只按匿名 Case ID 定位唯一目录；目录及其标签永不进入模型请求。"""
    if not sample_root.is_dir():
        raise RuntimeError(f"样本根目录不存在：{sample_root}")
    wanted = {str(item["case_id"]) for item in payload["cases"]}
    matches: Dict[str, List[Path]] = {case_id: [] for case_id in wanted}
    for path in sample_root.rglob("*"):
        if (
            path.is_dir()
            and path.name in matches
            and case_input_names([item.name for item in path.iterdir() if item.is_file()])
        ):
            matches[path.name].append(path)
    resolved = []
    for frozen in payload["cases"]:
        case_id = str(frozen["case_id"])
        paths = matches[case_id]
        if len(paths) != 1:
            raise RuntimeError(f"盲测样本目录数量不是 1：{case_id} / {len(paths)}")
        actual_hash = compute_case_input_bundle_sha256(paths[0])
        if actual_hash != frozen["input_bundle_sha256"]:
            raise RuntimeError(f"盲测输入已变化，拒绝执行：{case_id}")
        resolved.append({
            **frozen,
            "sample_dir": paths[0],
            "report_slug": f"review_{CURRENT_ARTIFACT_TAG}_blind_{frozen['scenario']}_{case_id}",
        })
    return resolved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://127.0.0.1:8015"))
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--manifest", type=Path, default=BLIND_MANIFEST_PATH)
    parser.add_argument("--sample-root", type=Path, default=DEFAULT_SAMPLE_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT_PATH)
    parser.add_argument("--execution-id", default=DEFAULT_EXECUTION_ID)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def compute_case_input_bundle_sha256(sample_dir: Path) -> str:
    """冻结真实请求输入；只纳入脱敏用户原话，不纳入客服结论。"""
    safe_names = set(case_input_names([
        item.name for item in sample_dir.iterdir() if item.is_file()
    ]))
    safe_names.update(
        name
        for name in ("content.txt", "manifest.json", "order_info_snapshot.json")
        if (sample_dir / name).is_file()
    )
    digest = hashlib.sha256()
    for name in sorted(safe_names):
        digest.update(f"{name}\0{sha256(sample_dir / name)}\n".encode("utf-8"))
    conversation = read_user_conversation_history(sample_dir)
    if conversation:
        canonical = json.dumps(conversation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest.update(f"conversation_history\0{canonical}\n".encode("utf-8"))
    return digest.hexdigest()


def save_submission_checkpoint(path: Path, rows: List[Dict[str, Any]]) -> None:
    """原子记录已取得的真实工单，避免中断后重复调用模型。"""
    payload = []
    for row in rows:
        case = row.get("case") or {}
        item = {
            "case_id": str(case.get("case_id") or ""),
            "scenario": str(case.get("scenario") or ""),
            "run_number": int(row.get("run_number") or 1),
            "job_id": str(row.get("job_id") or ""),
            "manifest": row.get("manifest") or [],
        }
        if case.get("input_bundle_sha256"):
            item["input_bundle_sha256"] = case["input_bundle_sha256"]
        payload.append(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_submission_checkpoint(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"盲测断点不可读：{path}") from exc
    if not isinstance(payload, list):
        raise RuntimeError("盲测断点格式无效")
    for item in payload:
        if not isinstance(item, dict) or not item.get("job_id") or not item.get("case_id"):
            raise RuntimeError("盲测断点包含无效工单")
    return payload


def detected_media_identity(path: Path) -> tuple[str, str]:
    with path.open("rb") as stream:
        head = stream.read(32)
    for suffix, mime_type, matches in DETECTED_MEDIA_TYPES:
        if matches(head):
            if suffix == ".mp4" and path.suffix.lower() in {".mov", ".m4v"}:
                return path.suffix.lower(), mimetypes.guess_type(path.name)[0] or "video/quicktime"
            return suffix, mime_type
    raise RuntimeError(f"媒体内容无法识别或已损坏：{path.name}")


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


def case_input_names(names: List[str]) -> List[str]:
    """只返回真实媒体；文件名及目录标签不得作为模型答案来源。"""
    return sorted(
        name
        for name in names
        if Path(name).suffix.lower() in MEDIA_SUFFIXES
        and Path(name).name.lower() not in FORBIDDEN_INPUT_NAMES
    )


def anonymous_case_id(case: Dict[str, Any]) -> str:
    frozen_hash = str(case.get("input_bundle_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", frozen_hash):
        frozen_hash = hashlib.sha256(str(case.get("case_id") or "").encode("utf-8")).hexdigest()
    return f"BLIND-{frozen_hash[:16].upper()}"


def source_case(case: Dict[str, Any]) -> tuple[Dict[str, Any], List[Path], List[Dict[str, Any]]]:
    sample_dir = Path(case["sample_dir"])
    if not sample_dir.is_dir():
        raise RuntimeError(f"样本目录不存在：{sample_dir}")
    names = case_input_names([item.name for item in sample_dir.iterdir() if item.is_file()])
    paths = [sample_dir / name for name in names]
    if not paths:
        raise RuntimeError(f"样本没有可审核媒体：{case['case_id']}")
    claim_path = sample_dir / "content.txt"
    claim = claim_path.read_text(encoding="utf-8-sig").strip() if claim_path.is_file() else ""
    claim = str(redact_public_review_data(claim))
    safe_ticket = read_safe_ticket_manifest(sample_dir / "manifest.json")
    blind_case_id = anonymous_case_id(case)
    claim_id = f"CLAIM-{blind_case_id}"
    metadata: Dict[str, Any] = {
        "client_case_id": f"{blind_case_id}-pending",
        "scenario": case["scenario"],
        "source": "four_scene_blind_acceptance_20260816",
        "priority": "high",
        "ticket_id": blind_case_id,
        "order_no": safe_ticket.get("order_reference") or "",
        "customer_claim": claim,
        "conversation_history": read_user_conversation_history(sample_dir),
        "claim_scope": {
            "claim_id": claim_id,
            "scope_version": "1",
            "split_status": "resolved",
            "stage": "initial",
            "claim_text": claim,
            "issue_types": [case["scenario"]],
            "active_claim_ids": [claim_id],
            "claims": [{
                "claim_id": claim_id,
                "role": "primary",
                "issue_type": case["scenario"],
            }],
        },
        "sampling_policy": {
            "preset": "adaptive",
            "fps": 1.0,
            "auto_escalate": False,
            "forensic_checks": True,
        },
        "output_options": {"include_html_report": True},
    }
    order_path = sample_dir / "order_info_snapshot.json"
    if order_path.is_file():
        metadata.update(build_order_info_context(
            order_path,
            order_reference=safe_ticket.get("order_reference", ""),
        ))
    composition = case.get("trusted_product_composition_resolution")
    if composition:
        baseline = dict(metadata.get("fulfillment_baseline") or {})
        if not baseline.get("expected_items"):
            raise RuntimeError(f"商品构成核验缺少订单基线：{case['case_id']}")
        refs_by_sku: Dict[str, List[str]] = {}
        for item in baseline.get("expected_items") or []:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("sku") or "").strip()
            item_ref = str(item.get("item_ref") or "").strip()
            if sku and item_ref:
                refs_by_sku.setdefault(sku, []).append(item_ref)
        required_skus = [
            str(sku).strip()
            for sku in composition.get("required_received_skus") or []
            if str(sku).strip()
        ]
        unknown_skus = [sku for sku in required_skus if len(refs_by_sku.get(sku) or []) != 1]
        if not required_skus or unknown_skus:
            raise RuntimeError(
                f"商品构成核验引用了订单中不存在的 SKU：{', '.join(unknown_skus) or '未提供'}"
            )
        baseline["claim_expected_item_resolution"] = {
            "claimed_item": str(composition.get("claimed_item") or "").strip(),
            "is_expected": False,
            "baseline_version": str(baseline.get("baseline_version") or ""),
            "source": str(composition.get("source") or "").strip(),
            "resolution_ref": str(composition.get("resolution_ref") or "").strip(),
            "reason": str(composition.get("reason") or "").strip(),
            "required_received_item_refs": [refs_by_sku[sku][0] for sku in required_skus],
        }
        metadata["fulfillment_baseline"] = baseline
    manifest = []
    for index, path in enumerate(paths, start=1):
        suffix, mime_type = detected_media_identity(path)
        manifest.append({
            "neutral_name": f"asset_{index:03d}{suffix}",
            "mime_type": mime_type,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    return metadata, paths, manifest


def submit(
    client: httpx.Client,
    base_url: str,
    token: str,
    case: Dict[str, Any],
    run_number: int,
    execution_id: str,
) -> Dict[str, Any]:
    metadata, paths, manifest = source_case(case)
    frozen_hash = str(case.get("input_bundle_sha256") or "")
    run_id = frozen_hash[:16]
    blind_case_id = anonymous_case_id(case)
    metadata.update({
        "client_case_id": f"{blind_case_id}-{run_id}",
        "source": "four_scene_blind_acceptance_20260816",
        "batch_id": f"blind-{execution_id}-{run_id}",
    })
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
        response = client.post(
            f"{base_url}/api/v1/review/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": f"blind-{execution_id}-{blind_case_id}-{run_id}",
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
    consecutive_transport_failures: Dict[str, int] = {}
    headers = {"Authorization": f"Bearer {token}"}
    while pending and time.time() < deadline:
        for job_id, row in list(pending.items()):
            try:
                response = client.get(f"{base_url}/api/v1/review/jobs/{job_id}", headers=headers)
            except httpx.TransportError as exc:
                failures = consecutive_transport_failures.get(job_id, 0) + 1
                consecutive_transport_failures[job_id] = failures
                if failures >= 5:
                    raise RuntimeError(
                        f"{row['case']['case_id']} 工单轮询连续 {failures} 次连接失败；"
                        f"工单 {job_id} 已保留，可从断点继续：{exc}"
                    ) from exc
                print(
                    f"{row['case']['case_id']} / {job_id}：轮询连接短暂中断，"
                    f"保留原工单后重试（{failures}/5）",
                    flush=True,
                )
                continue
            if int(getattr(response, "status_code", 200)) >= 500:
                failures = consecutive_transport_failures.get(job_id, 0) + 1
                consecutive_transport_failures[job_id] = failures
                if failures >= 5:
                    raise RuntimeError(
                        f"{row['case']['case_id']} 工单轮询连续 {failures} 次服务端异常；"
                        f"工单 {job_id} 已保留，可从断点继续。"
                    )
                print(
                    f"{row['case']['case_id']} / {job_id}：轮询服务端短暂异常，"
                    f"保留原工单后重试（{failures}/5）",
                    flush=True,
                )
                continue
            consecutive_transport_failures.pop(job_id, None)
            response.raise_for_status()
            job = response.json()["job"]
            status = job["status"]
            if observed.get(job_id) != status:
                print(f"{row['case']['case_id']} / {job_id}：{status}", flush=True)
                observed[job_id] = status
            if status in {"SUCCEEDED", "FAILED"}:
                row["job"] = job
                row["internal_job"] = store.get_job(job_id) or {}
                pending.pop(job_id)
        if pending:
            time.sleep(3)
    if pending:
        raise TimeoutError(f"真实验收任务超时：{', '.join(pending)}")


def parsed(job: Dict[str, Any]) -> Dict[str, Any]:
    return (((job.get("result") or {}).get("review") or {}).get("agent_report") or {}).get("parsed") or {}


def _all_evidence_refs(value: Any) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "evidence_refs" and isinstance(child, list):
                refs.extend(item for item in child if isinstance(item, dict))
            else:
                refs.extend(_all_evidence_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_all_evidence_refs(child))
    return refs


def _scene_facts_present(scenario: str, assessment: Dict[str, Any]) -> bool:
    return _scene_contract_valid({
        "scenario": scenario,
        "predicted_label": assessment.get("predicted_label"),
        "material_readiness": assessment.get("material_readiness") or {},
        "scene_contract": _scene_contract(scenario, assessment, {}),
    })


def _scene_contract(
    scenario: str,
    assessment: Dict[str, Any],
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    if scenario == "product_damage":
        damage = assessment.get("damage_causality_assessment") or {}
        severity = damage.get("severity_assessment") or {}
        audit = assessment.get("decision_policy_audit") or {}
        return {
            "opening_video_evidence": assessment.get("opening_video_evidence") or {},
            "damage_presence": damage.get("damage_presence"),
            "damage_timing": damage.get("damage_timing"),
            "claim_support": damage.get("claim_support"),
            "severity": {
                "level": severity.get("level"),
                "confidence": severity.get("confidence"),
                "structural_failure": severity.get("structural_failure"),
            },
            "severe_alert_eligible": bool(
                summary.get("severe_alert_eligible")
                or audit.get("severe_alert_eligible")
            ),
        }
    if scenario == "wrong_item":
        reconciliation = assessment.get("fulfillment_reconciliation") or {}
        observed = reconciliation.get("observed_items")
        packages = reconciliation.get("package_observations")
        identity_fields = {"item_role", "series", "edition", "physical_form", "included_parts"}
        return {
            "evidence_sufficiency": reconciliation.get("evidence_sufficiency"),
            "observed_items_present": isinstance(observed, list) and bool(observed),
            "package_observations_present": isinstance(packages, list) and bool(packages),
            "identity_definition_fields_present": isinstance(observed, list) and bool(observed) and all(
                isinstance(item, dict) and identity_fields.issubset(item)
                for item in observed
            ),
            "same_package_evidence_present": isinstance(packages, list) and any(
                isinstance(item, dict)
                and bool(str(item.get("package_ref") or "").strip())
                and bool(item.get("evidence_refs"))
                for item in packages
            ),
        }
    if scenario == "missing_item":
        reconciliation = assessment.get("fulfillment_reconciliation") or {}
        return {
            "evidence_route": reconciliation.get("evidence_route"),
            "resolution_basis": reconciliation.get("resolution_basis"),
            "warehouse_check": reconciliation.get("warehouse_check") or (
                {"state": "verified", "outcome": (reconciliation.get("warehouse_verification") or {}).get("status")}
                if reconciliation.get("warehouse_verification")
                else {"state": "not_available", "outcome": None}
            ),
            "user_materials_complete": reconciliation.get("user_materials_complete"),
        }
    if scenario == "minor_refund":
        minor = assessment.get("minor_material_assessment") or {}
        checklist = minor.get("checklist")
        required_ids = {"identity", "relationship", "commitment", "payment", "mobile_realname"}
        return {
            "five_material_checklist_present": isinstance(checklist, list) and required_ids.issubset({
                str(item.get("requirement_id") or "")
                for item in checklist
                if isinstance(item, dict)
            }),
            "payment_capability_risk": minor.get("payment_capability_risk") or {},
        }
    return {}


def _scene_contract_valid(item: Dict[str, Any]) -> bool:
    scenario = str(item.get("scenario") or "")
    contract = item.get("scene_contract") or {}
    predicted_label = str(item.get("predicted_label") or "")
    readiness = item.get("material_readiness") or {}
    if scenario == "product_damage":
        opening = contract.get("opening_video_evidence") or {}
        severity = contract.get("severity") or {}
        severe = contract.get("severe_alert_eligible") is True
        required = (
            isinstance(opening, dict)
            and (
                severe
                or (
                    isinstance(opening.get("present"), bool)
                    and isinstance(opening.get("sop_compliant"), bool)
                )
            )
            and contract.get("damage_presence") in {"confirmed", "not_visible", "uncertain"}
            and contract.get("claim_support") in {"supported", "not_supported", "insufficient"}
            and severity.get("level") in {"none", "minor", "moderate", "severe", "extreme", "unknown"}
            and isinstance(severity.get("structural_failure"), bool)
        )
        severe_valid = not severe or (
            contract.get("damage_presence") == "confirmed"
            and severity.get("level") in {"severe", "extreme"}
            and severity.get("structural_failure") is True
            and float(severity.get("confidence") or 0) >= 0.8
            and predicted_label == "positive"
        )
        missing_opening = opening.get("present") is not True
        no_ordinary_negative = not (
            missing_opening and predicted_label == "negative" and not severe
        )
        readiness_consistent = not (
            missing_opening and readiness.get("status") == "complete" and not severe
        )
        return bool(required and severe_valid and no_ordinary_negative and readiness_consistent)
    if scenario == "wrong_item":
        if contract.get("package_observations_present") is not True:
            return False
        if contract.get("evidence_sufficiency") == "insufficient":
            return predicted_label == "review"
        return all(contract.get(key) is True for key in (
            "observed_items_present", "identity_definition_fields_present", "same_package_evidence_present",
        ))
    if scenario == "missing_item":
        route = contract.get("evidence_route")
        basis = contract.get("resolution_basis")
        warehouse = contract.get("warehouse_check") or {}
        if route not in {"compliant_opening_video", "static_three_images", "insufficient", "not_required"}:
            return False
        if basis not in {"visual_reconciliation", "warehouse_verification", "trusted_expected_item_resolution", "none"}:
            return False
        if warehouse.get("state") not in {"not_available", "pending", "verified"}:
            return False
        if route == "static_three_images":
            return bool(
                contract.get("user_materials_complete") is True
                and basis == "none"
                and warehouse.get("state") == "pending"
                and predicted_label == "review"
            )
        return isinstance(contract.get("user_materials_complete"), bool)
    if scenario == "minor_refund":
        risk = contract.get("payment_capability_risk") or {}
        if contract.get("five_material_checklist_present") is not True:
            return False
        required_risk_fields = {
            "low_age", "under_nine", "age_confidence", "process_evidence_status",
            "requires_more_material", "requires_review",
        }
        if not required_risk_fields.issubset(risk):
            return False
        process_gap = risk.get("low_age") is True and risk.get("process_evidence_status") != "matched"
        if process_gap and (
            risk.get("requires_more_material") is not True or predicted_label != "review"
        ):
            return False
        under_nine_high = risk.get("under_nine") is True and risk.get("age_confidence") == "high"
        return not under_nine_high or risk.get("requires_review") is True
    return False


def _model_profile(review: Dict[str, Any]) -> str:
    agent_report = review.get("agent_report") or {}
    estimate = agent_report.get("inference_estimate") or {}
    profile = estimate.get("request_profile") or {}
    native_video_count = int(profile.get("native_video_count") or 0)
    execution = review.get("media_preflight_execution") or {}
    executed_video = execution.get("video") or {}
    frame_fallback = execution.get("frame_fallback") or {}
    fps = profile.get("sampling_fps")
    if fps is None and executed_video.get("native_review_status") == "completed":
        fps = executed_video.get("native_sampling_fps")
    base_matches = (
        profile.get("provider") == "gemini_native"
        and profile.get("model") == "gemini-3.5-flash-lite"
        and profile.get("thinking_level") == "high"
        and profile.get("media_resolution") == "high"
        and profile.get("max_output_tokens") == "provider_default"
    )
    native_video_executed = (
        native_video_count > 0
        or executed_video.get("native_review_status") == "completed"
    )
    video_sampling_matches = not native_video_executed or float(fps or 0) == 1.0
    if base_matches and video_sampling_matches and not bool(frame_fallback.get("used")):
        return DEFAULT_MODEL_PROFILE
    return "-".join(str(profile.get(key) or "unknown") for key in (
        "provider", "model", "thinking_level", "media_resolution", "max_output_tokens",
    )) + f"-native{native_video_count}-fps{fps if fps is not None else 'unknown'}"


def case_summary(row: Dict[str, Any], json_name: str, html_name: str) -> Dict[str, Any]:
    job = row["job"]
    result = job.get("result") or {}
    review = result.get("review") or {}
    summary = review.get("summary") or {}
    advisory = result.get("advisory_assessment") or review.get("advisory_assessment") or {}
    assessment = parsed(job)
    opening = ((assessment.get("video_audit_conclusion") or {}).get("opening_video_compliance") or {})
    continuity = assessment.get("object_continuity_assessment") or {}
    continuity_verdict = str(continuity.get("continuity_verdict") or "")
    has_offscreen = (
        True if continuity_verdict == "long_absence"
        else False if continuity_verdict in {"continuous", "brief_occlusion"}
        else None
    )
    damage = assessment.get("damage_causality_assessment") or {}
    primary_video = ((damage.get("evidence_source_summary") or {}).get("primary_video") or {})
    material_readiness = (
        result.get("material_readiness")
        or review.get("material_readiness")
        or assessment.get("material_readiness")
        or {}
    )
    internal_review = (((row.get("internal_job") or {}).get("result") or {}).get("review") or {})
    evidence_refs = _all_evidence_refs(assessment)
    video_evidence_present = any(
        str(item.get("asset_ref") or "").startswith(("native_video_", "video_"))
        and bool(str(item.get("timestamp") or "").strip())
        for item in evidence_refs
    )
    image_evidence_present = any(
        str(item.get("asset_ref") or "").startswith(("supplemental_image_", "official_product_reference_"))
        for item in evidence_refs
    )
    warehouse_evidence_present = (
        str((assessment.get("fulfillment_reconciliation") or {}).get("resolution_basis") or "")
        == "warehouse_verification"
    )
    return {
        "case_id": row["case"]["case_id"],
        "scenario": row["case"]["scenario"],
        "job_id": job["job_id"],
        "status": job["status"],
        "processing_status": assessment.get("processing_status"),
        "system_action": assessment.get("system_action"),
        "predicted_label": summary.get("predicted_label") or assessment.get("predicted_label"),
        "confidence": summary.get("confidence") or assessment.get("confidence"),
        "human_review": (advisory.get("human_review") or {}).get("level") or summary.get("human_review_level"),
        "material_gaps": assessment.get("material_gaps") or [],
        "opening_result": opening.get("result"),
        "issue_visible_in_continuous_opening": opening.get("issue_visible_in_continuous_opening"),
        "has_offscreen": has_offscreen,
        "business_follow_up_reason": assessment.get("business_follow_up_reason") or "",
        "primary_claim_support": primary_video.get("claim_support"),
        "overall_conclusion": (assessment.get("overall_audit") or {}).get("conclusion") or "",
        "material_readiness": material_readiness,
        "scene_facts_present": _scene_facts_present(row["case"]["scenario"], assessment),
        "scene_contract": _scene_contract(row["case"]["scenario"], assessment, summary),
        "evidence_ref_count": len(evidence_refs),
        "evidence_preview": {
            "video": video_evidence_present,
            "image": image_evidence_present,
            "warehouse": warehouse_evidence_present,
        },
        "report_json": f"tests/reports/{json_name}",
        "report_html": f"tests/reports/{html_name}",
        "report_same_job": row.get("report_requested_job_id") == job.get("job_id"),
        "model_profile": _model_profile(internal_review),
    }


def build_blind_review_checks(rows: List[Dict[str, Any]]) -> Dict[str, bool]:
    counts = {
        scenario: sum(1 for item in rows if item.get("scenario") == scenario)
        for scenario in SCENARIOS
    }
    def readiness_valid(item: Dict[str, Any]) -> bool:
        readiness = item.get("material_readiness") or {}
        try:
            validated = ReviewMaterialReadiness.model_validate(readiness)
        except Exception:
            return False
        return validated.scenario == item.get("scenario")

    def traceable_evidence_valid(item: Dict[str, Any]) -> bool:
        if int(item.get("evidence_ref_count") or 0) > 0:
            return True
        contract = item.get("scene_contract") or {}
        readiness = item.get("material_readiness") or {}
        return bool(
            item.get("scenario") == "wrong_item"
            and item.get("predicted_label") == "review"
            and readiness.get("status") == "incomplete"
            and contract.get("evidence_sufficiency") == "insufficient"
            and contract.get("observed_items_present") is False
            and contract.get("same_package_evidence_present") is False
        )

    return {
        "all_required_random_cases_present": len(rows) == len(SCENARIOS) * REQUIRED_CASES_PER_SCENE
        and all(count == REQUIRED_CASES_PER_SCENE for count in counts.values()),
        "all_jobs_succeeded": len(rows) == len(SCENARIOS) * REQUIRED_CASES_PER_SCENE
        and all(
            item.get("status") == "SUCCEEDED"
            and item.get("processing_status") != "technical_processing_incomplete"
            and item.get("system_action") != "system_retry"
            for item in rows
        ),
        "all_material_readiness_contracts_valid": all(readiness_valid(item) for item in rows),
        "all_scene_facts_present": all(item.get("scene_facts_present") is True for item in rows),
        "all_current_business_contracts_valid": all(_scene_contract_valid(item) for item in rows),
        "all_required_facts_have_traceable_evidence": all(
            traceable_evidence_valid(item) for item in rows
        ),
        "api_html_same_job": all(item.get("report_same_job") is True for item in rows),
        "current_artifacts_only": all(
            f"review_{CURRENT_ARTIFACT_TAG}_blind_" in str(item.get("report_json") or "")
            and f"review_{CURRENT_ARTIFACT_TAG}_blind_" in str(item.get("report_html") or "")
            for item in rows
        ),
        "default_model_profile_consistent": all(
            item.get("model_profile") == DEFAULT_MODEL_PROFILE for item in rows
        ),
    }


def export(
    client: httpx.Client,
    base_url: str,
    token: str,
    rows: List[Dict[str, Any]],
    *,
    unseen_audit: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    failed = []
    for row in rows:
        job = row.get("job") or {}
        assessment = parsed(job)
        if (
            job.get("status") != "SUCCEEDED"
            or assessment.get("processing_status") == "technical_processing_incomplete"
            or assessment.get("system_action") == "system_retry"
        ):
            failed.append(
                f"{(row.get('case') or {}).get('case_id')}:{job.get('status')}/"
                f"{assessment.get('processing_status') or assessment.get('system_action') or 'review_failed'}"
            )
    if failed:
        raise RuntimeError("密封盲测存在未成功工单，停止导出报告：" + ", ".join(failed))
    audit_payload = {
        "cases": [row.get("case") or {} for row in rows],
        "unseen_audit": unseen_audit,
    }
    if not _blind_audit_valid(audit_payload):
        raise RuntimeError("密封盲测缺少有效的盲验输入审计")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    summaries: List[Dict[str, Any]] = []
    for row in rows:
        case = row["case"]
        json_name = f"{case['report_slug']}.json"
        html_name = f"{case['report_slug']}.html"
        evidence = {
            "generated_at": datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S %z"),
            "evidence_type": "sealed_blind_real_api_review",
            "label_state": "sealed",
            "selection_rank_sha256": case["selection_rank_sha256"],
            "input_bundle_sha256": case["input_bundle_sha256"],
            "submitted_assets": row["manifest"],
            "job": row["job"],
        }
        (REPORT_DIR / json_name).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        report = client.get(f"{base_url}/api/v1/review/jobs/{row['job_id']}/report", headers=headers)
        report.raise_for_status()
        row["report_requested_job_id"] = row["job_id"]
        (REPORT_DIR / html_name).write_text(report.text, encoding="utf-8")
        summary = case_summary(row, json_name, html_name)
        summary["report_json_sha256"] = sha256(REPORT_DIR / json_name)
        summary["report_html_sha256"] = sha256(REPORT_DIR / html_name)
        summaries.append(summary)

    checks = build_blind_review_checks(summaries)
    checks["blind_input_audit_valid"] = True
    commercial = {
        "generated_at": datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S %z"),
        "generator": "scripts/run_final_commercial_acceptance.py",
        "contract_version": CONTRACT_VERSION,
        "label_state": "sealed",
        "unseen_audit": unseen_audit,
        "commercial_boundary": "四场景随机盲测的模型输出阶段；人工标签尚未解封，不宣称准确率",
        "checks": checks,
        "cases": summaries,
    }
    (REPORT_DIR / f"review_{CURRENT_ARTIFACT_TAG}_four_scenario_blind_results_latest.json").write_text(
        json.dumps(commercial, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not all(checks.values()):
        raise RuntimeError(f"商业验收未通过：{json.dumps(checks, ensure_ascii=False)}")
    return commercial


def main() -> int:
    args = parse_args()
    frozen = load_blind_manifest(args.manifest)
    cases = resolve_blind_cases(frozen, sample_root=args.sample_root)
    timeout = httpx.Timeout(args.timeout, connect=30, write=args.timeout, read=60)
    with httpx.Client(timeout=timeout) as client:
        token = login(client, args.base_url)
        cases_by_id = {case["case_id"]: case for case in cases}
        rows = []
        for saved in load_submission_checkpoint(args.checkpoint):
            case = cases_by_id.get(str(saved.get("case_id") or ""))
            if case is None or saved.get("input_bundle_sha256") not in (None, case["input_bundle_sha256"]):
                raise RuntimeError(f"盲测断点与冻结清单不一致：{saved.get('case_id') or '-'}")
            rows.append({**saved, "case": case})
        submitted = {row["case"]["case_id"] for row in rows}
        for case in cases:
            if case["case_id"] in submitted:
                continue
            rows.append(submit(client, args.base_url, token, case, 1, args.execution_id))
            save_submission_checkpoint(args.checkpoint, rows)
        wait_all(client, args.base_url, token, rows, args.timeout)
        commercial = export(
            client,
            args.base_url,
            token,
            rows,
            unseen_audit=frozen["unseen_audit"],
        )
    print(json.dumps(commercial["checks"], ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
