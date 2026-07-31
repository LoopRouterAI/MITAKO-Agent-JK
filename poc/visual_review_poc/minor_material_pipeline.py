# -*- coding: utf-8 -*-
"""未成年人退款资料全覆盖审核与确定性聚合。"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Sequence, Tuple

from poc.visual_review_poc.model_catalog import summarize_cost_observability
from review_service.schemas import ReviewMinorMaterialObservation


ALLOWED_DOCUMENT_TYPES = {
    "identity_card",
    "passport",
    "household_register",
    "birth_certificate",
    "signed_commitment",
    "order_payment_proof",
    "mobile_realname_proof",
    "carrier_invoice",
    "other",
    "unknown",
}
ALLOWED_ROLES = {"guardian", "minor", "unknown", "not_applicable"}
ALLOWED_SIDES = {"front", "back", "page", "multiple", "unknown"}
ALLOWED_READABILITY = {"clear", "partial", "unknown"}
ALLOWED_QUALITY_ISSUES = {
    "blur",
    "glare",
    "occlusion",
    "excessive_redaction",
    "incomplete_page",
    "suspected_editing",
    "other",
}
PROCESS_TYPES = {"invoice_generation", "document_capture", "payment_record", "other", "uncertain"}
PROCESS_QUALITY = {"clear", "partial", "unreadable"}
CONSISTENCY_FIELDS = {
    "identity_age": ("guardian_identity", "minor_identity", "age_eligibility"),
    "guardian_relationship": ("guardian_identity", "minor_identity", "relationship_link"),
    "commitment_signatures": ("guardian_signer", "minor_signer", "signature_presence"),
    "order_payment": ("order_reference", "payer_identity", "amount", "transaction_scope"),
    "mobile_realname": ("subscriber_identity", "account_mobile", "invoice_identity"),
}
CONSISTENCY_STATUS = {"matched", "mismatched", "uncertain", "not_assessed"}
FIELD_VISIBILITY = {"complete", "partial", "masked", "unreadable"}
TAMPER_RISK = {"low", "medium", "high", "uncertain"}
RISK_REASON_CODES = {
    "no_obvious_risk",
    "suspected_editing",
    "unreadable_fields",
    "incomplete_document",
    "conflicting_fields",
    "evidence_gap",
}
CONSISTENCY_MESSAGES = {
    "matched": "所提供图片中的可见字段未发现明显矛盾；这不代表资料已通过权威真伪验证。",
    "mismatched": "所提供图片中的可见字段存在冲突，需授权人员回看对应证据。",
    "uncertain": "部分字段不可读、证据不足或存在可疑风险，无法完成视觉一致性确认。",
    "not_assessed": "本项尚未完成视觉字段一致性初审。",
}


def _chunks(items: Sequence[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
    return [list(items[index:index + size]) for index in range(0, len(items), size)]


def _metric_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "model_calls": sum(int(item.get("_model_calls") or 1) for item in items),
        "model_latency_seconds_sum": round(sum(float(item.get("latency_seconds") or 0) for item in items), 2),
        "input_tokens": sum(int((item.get("usage") or {}).get("input_tokens") or 0) for item in items),
        "output_tokens": sum(int((item.get("usage") or {}).get("output_tokens") or 0) for item in items),
        "total_tokens": sum(int((item.get("usage") or {}).get("total_tokens") or 0) for item in items),
        "estimated_usd": round(sum(float((item.get("cost") or {}).get("estimated_usd") or 0) for item in items), 6),
    }


def _result_observed_indices(result: Dict[str, Any]) -> set[int]:
    indices = set()
    for item in (result.get("parsed") or {}).get("material_observations") or []:
        if not isinstance(item, dict):
            continue
        try:
            indices.add(int(item.get("image_index")))
        except (TypeError, ValueError):
            continue
    return indices


def _merge_semantic_attempts(first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
    observations: Dict[int, Dict[str, Any]] = {}
    for result in (first, second):
        for item in (result.get("parsed") or {}).get("material_observations") or []:
            if not isinstance(item, dict):
                continue
            try:
                observations[int(item.get("image_index"))] = item
            except (TypeError, ValueError):
                continue
    usage = {
        key: sum(int((item.get("usage") or {}).get(key) or 0) for item in (first, second))
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    cost_observability = summarize_cost_observability([first, second])
    return {
        **second,
        **cost_observability,
        "status": "success" if first.get("status") == "success" or second.get("status") == "success" else "failed",
        "parsed": {
            **(second.get("parsed") or {}),
            "material_observations": [observations[index] for index in sorted(observations)],
        },
        "usage": usage,
        "cost": {
            "estimated_usd": round(
                sum(float((item.get("cost") or {}).get("estimated_usd") or 0) for item in (first, second)),
                6,
            )
        },
        "latency_seconds": round(sum(float(item.get("latency_seconds") or 0) for item in (first, second)), 2),
        "_model_calls": int(first.get("_model_calls") or 1) + int(second.get("_model_calls") or 1),
    }


def _declared_image_count(case: Dict[str, Any]) -> int:
    structured = case.get("structured_business_context") or {}
    frontdesk = structured.get("frontdesk_evidence_package") or {}
    asset_manifest = frontdesk.get("asset_manifest") or {}
    assets = asset_manifest.get("assets") if isinstance(asset_manifest, dict) else []
    declared = sum(1 for item in (assets or []) if str(item.get("mime_type") or "").lower().startswith("image/"))
    if declared:
        return declared
    evidence_assets = case.get("evidence_assets") or []
    image_suffixes = (".jpg", ".jpeg", ".png", ".webp")
    declared = sum(1 for item in evidence_assets if str(item.get("file") or "").lower().endswith(image_suffixes))
    return max(declared, len(case.get("supplemental_images") or []))


def _minor_refund_policy(case: Dict[str, Any]) -> Dict[str, str]:
    raw = (case.get("structured_business_context") or {}).get("minor_refund_policy") or {}
    review_mode = str(raw.get("review_mode") or "standard")
    authoritative = str(raw.get("authoritative_verification") or "disabled")
    return {
        "review_mode": review_mode if review_mode in {"standard", "strict"} else "standard",
        "authoritative_verification": (
            authoritative if authoritative in {"disabled", "advisory", "required"} else "disabled"
        ),
    }


def _authenticity_assessment(
    case: Dict[str, Any],
    observations: List[Dict[str, Any]],
    field_consistency: Dict[str, Any],
) -> Dict[str, Any]:
    image_by_index = {
        int(item["image_index"]): item
        for item in case.get("supplemental_images") or []
        if item.get("image_index") is not None
    }
    missing_exif = sorted(index for index, item in image_by_index.items() if item.get("has_exif") is False)
    unknown_exif = sorted(index for index, item in image_by_index.items() if item.get("has_exif") is None)
    suspected_editing = {
        int(item["image_index"])
        for item in observations
        if "suspected_editing" in (item.get("quality_issues") or [])
    }
    corroborated_editing: set[int] = set()
    for check in field_consistency.get("checks") or []:
        if str(check.get("tamper_risk") or "").lower() == "high":
            corroborated_editing.update(int(index) for index in check.get("evidence_image_indices") or [])
    suspected_editing.update(corroborated_editing)
    evidence_indices = sorted(suspected_editing)
    if corroborated_editing or len(evidence_indices) >= 2:
        severity = "critical"
        risk_score = min(0.94, 0.78 + 0.04 * len(evidence_indices))
        conclusion = "发现较强的疑似编辑或修改线索，请优先回看标红图片。"
    elif evidence_indices:
        severity = "warning"
        risk_score = 0.48
        conclusion = "单张图片出现疑似编辑提示，但缺少交叉证据；已标黄供抽检，不单独阻断初审。"
    elif missing_exif or unknown_exif:
        severity = "warning"
        risk_score = 0.25
        conclusion = "部分图片没有可用拍摄信息；压缩、转发或格式转换都可能造成该情况，本身不能证明图片造假。"
    else:
        severity = "clear"
        risk_score = 0.08
        conclusion = "图片保留拍摄信息，视觉检查也未发现明显编辑线索。"
    return {
        "severity": severity,
        "risk_score": risk_score,
        "risk_percent": int(round(risk_score * 100)),
        "blocks_visual_precheck": severity == "critical",
        "evidence_image_indices": evidence_indices,
        "missing_exif_image_indices": missing_exif,
        "unknown_exif_image_indices": unknown_exif,
        "conclusion": conclusion,
        "boundary": "该分数是未校准的图片风险提示，不是图片真实或伪造的客观概率。",
    }


def _normalize_observations(
    rows: List[Tuple[List[int], Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], List[int]]:
    by_index: Dict[int, Dict[str, Any]] = {}
    expected: set[int] = set()
    for batch_indices, result in rows:
        expected.update(batch_indices)
        parsed = result.get("parsed") or {}
        for raw in parsed.get("material_observations") or []:
            if not isinstance(raw, dict):
                continue
            try:
                image_index = int(raw.get("image_index"))
            except (TypeError, ValueError):
                continue
            if image_index not in batch_indices:
                continue
            document_types = [
                str(value)
                for value in raw.get("document_types") or []
                if str(value) in ALLOWED_DOCUMENT_TYPES
            ]
            document_type = str(raw.get("document_type") or "")
            if document_type not in ALLOWED_DOCUMENT_TYPES:
                document_type = document_types[0] if document_types else "unknown"
            document_types = list(dict.fromkeys([document_type, *document_types]))[:4]
            role = str(raw.get("subject_role") or "unknown")
            side = str(raw.get("document_side") or "unknown")
            readability = str(raw.get("readability") or "unknown")
            if readability == "unreadable" or readability not in ALLOWED_READABILITY:
                readability = "unknown"
            quality_issues = [
                str(value)
                for value in raw.get("quality_issues") or []
                if str(value) in ALLOWED_QUALITY_ISSUES
            ][:8]
            observation = ReviewMinorMaterialObservation.model_validate({
                "image_index": image_index,
                "asset_ref": f"supplemental_image_{image_index}",
                "document_type": document_type,
                "document_types": document_types,
                "subject_role": role if role in ALLOWED_ROLES else "unknown",
                "document_side": side if side in ALLOWED_SIDES else "unknown",
                "issuing_country_or_region": raw.get("issuing_country_or_region") or "unknown",
                "readability": readability,
                "quality_issues": quality_issues,
            }).model_dump(mode="json")
            by_index[image_index] = observation
    observations = [by_index[index] for index in sorted(by_index)]
    unclassified = sorted(expected - set(by_index))
    return observations, unclassified


def _normalize_process_observations(results: List[Dict[str, Any]], valid_frames: set[Tuple[int, int]]) -> List[Dict[str, Any]]:
    output = []
    seen = set()
    for result in results:
        for raw in (result.get("parsed") or {}).get("process_observations") or []:
            if not isinstance(raw, dict):
                continue
            try:
                video_index = int(raw.get("video_index"))
                frame_index = int(raw.get("global_frame_index"))
            except (TypeError, ValueError):
                continue
            key = (video_index, frame_index)
            if key not in valid_frames or key in seen:
                continue
            seen.add(key)
            process_type = str(raw.get("process_type") or "uncertain")
            quality = str(raw.get("evidence_quality") or "unreadable")
            output.append({
                "video_index": video_index,
                "global_frame_index": frame_index,
                "timestamp": str(raw.get("timestamp") or ""),
                "asset_ref": f"video_{video_index}_frame_{frame_index}",
                "process_type": process_type if process_type in PROCESS_TYPES else "uncertain",
                "evidence_quality": quality if quality in PROCESS_QUALITY else "unreadable",
            })
    return sorted(output, key=lambda item: (item["video_index"], item["global_frame_index"]))


def _usable(observation: Dict[str, Any]) -> bool:
    return observation.get("readability") == "clear" and not {
        "excessive_redaction",
        "incomplete_page",
    }.intersection(observation.get("quality_issues") or [])


def _checklist(observations: List[Dict[str, Any]], coverage_complete: bool) -> List[Dict[str, Any]]:
    def candidates(*types: str) -> List[Dict[str, Any]]:
        selected = []
        wanted = set(types)
        for item in observations:
            if wanted.intersection(item.get("document_types") or []):
                selected.append(item)
        return selected

    identity = candidates("identity_card")
    guardian_identity = [item for item in identity if item.get("subject_role") == "guardian"]
    minor_identity = [item for item in identity if item.get("subject_role") == "minor"]
    relationship = candidates("household_register", "birth_certificate")
    commitment = candidates("signed_commitment")
    payment = candidates("order_payment_proof")
    mobile_verified = candidates("mobile_realname_proof")
    mobile = candidates("mobile_realname_proof", "carrier_invoice")

    def status(observed: bool) -> str:
        if observed:
            return "present"
        return "not_observed_after_full_scan" if coverage_complete else "not_assessed"

    def quality_status(usable: bool, observed: bool) -> str:
        if usable:
            return "usable"
        if observed:
            return "needs_manual_confirmation"
        return "not_observed" if coverage_complete else "not_assessed"

    identity_present = bool(any(_usable(item) for item in guardian_identity)) and bool(
        any(_usable(item) for item in minor_identity) or any(_usable(item) for item in relationship)
    )
    rows = [
        (
            "identity",
            "未成年人及监护人身份证明",
            identity_present,
            bool(identity),
            identity,
            "未成年人无身份证时可由户口本信息页或出生证明替代；角色和正反面仍需人工核对。",
            "needs_manual_consistency_check",
        ),
        (
            "relationship",
            "监护关系证明",
            any(_usable(item) for item in relationship),
            bool(relationship),
            relationship,
            "户口本相关页或出生证明二选一。",
            "needs_manual_consistency_check",
        ),
        (
            "commitment",
            "双方签字退款申请承诺书",
            any(_usable(item) for item in commitment),
            bool(commitment),
            commitment,
            "签字真实性由人工终审确认。",
            "needs_manual_consistency_check",
        ),
        (
            "payment",
            "订单或支付凭证",
            any(_usable(item) for item in payment),
            bool(payment),
            payment,
            "金额、订单范围和付款主体由业务系统复核。",
            "needs_business_system_check",
        ),
        (
            "mobile_realname",
            "绑定手机号实名归属证明",
            any(_usable(item) for item in mobile),
            bool(mobile),
            mobile,
            "运营商话费账单或电子发票视为已提交候选证明；实名主体、购物手机号和备注信息仍需人工核对。",
            "confirmed_by_visual_category" if any(_usable(item) for item in mobile_verified) else "needs_manual_consistency_check",
        ),
    ]
    return [
        {
            "requirement_id": requirement_id,
            "label": label,
            "status": status(observed),
            "quality_status": quality_status(present, observed),
            "evidence_refs": [item["asset_ref"] for item in evidence],
            "evidence_image_indices": [item["image_index"] for item in evidence],
            "rule_note": note,
            "validation_status": (
                validation_status if present
                else "needs_manual_quality_check" if observed
                else "not_validated"
            ),
        }
        for requirement_id, label, present, observed, evidence, note, validation_status in rows
    ]


def _consistency_image_jobs(
    observations: List[Dict[str, Any]],
    images: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_index = {int(item["image_index"]): item for item in images if item.get("image_index") is not None}

    def indices(*document_types: str, role: str | None = None, usable_only: bool = False) -> List[int]:
        wanted = set(document_types)
        return [
            int(item["image_index"])
            for item in observations
            if wanted.intersection(item.get("document_types") or [])
            and (role is None or item.get("subject_role") == role)
            and (not usable_only or _usable(item))
        ]

    guardian = indices("identity_card", role="guardian")
    minor = indices("identity_card", role="minor")
    guardian_passport = indices("passport", role="guardian")
    minor_passport = indices("passport", role="minor")
    relationship = indices("household_register", "birth_certificate")
    commitment = indices("signed_commitment")
    payment = indices("order_payment_proof")
    mobile = indices("mobile_realname_proof", "carrier_invoice")
    plans = {
        "identity_age": guardian + guardian_passport + minor + minor_passport + relationship,
        "guardian_relationship": guardian + guardian_passport + minor + minor_passport + relationship,
        "commitment_signatures": guardian + minor + relationship + commitment,
        "order_payment": guardian + payment,
        "mobile_realname": guardian + mobile + payment,
    }
    clear_guardian = indices("identity_card", role="guardian", usable_only=True)
    clear_minor = indices("identity_card", role="minor", usable_only=True)
    clear_guardian_passport = indices("passport", role="guardian", usable_only=True)
    clear_minor_passport = indices("passport", role="minor", usable_only=True)
    clear_relationship = indices("household_register", "birth_certificate", usable_only=True)
    clear_commitment = indices("signed_commitment", usable_only=True)
    clear_payment = indices("order_payment_proof", usable_only=True)
    clear_mobile = indices("mobile_realname_proof", "carrier_invoice", usable_only=True)
    anchors = {
        "identity_age": (
            (clear_guardian or guardian)[:1]
            + (clear_guardian_passport or guardian_passport)[:1]
            + (clear_minor or minor)[:1]
            + (clear_minor_passport or minor_passport)[:1]
            + (clear_relationship or relationship)[:1]
        ),
        "guardian_relationship": (
            (clear_guardian or guardian)[:1]
            + (clear_guardian_passport or guardian_passport)[:1]
            + (clear_minor or minor)[:1]
            + (clear_minor_passport or minor_passport)[:1]
            + (clear_relationship or relationship)[:1]
        ),
        "commitment_signatures": (clear_guardian or guardian)[:1] + ((clear_minor or minor)[:1] or (clear_relationship or relationship)[:1]) + (clear_commitment or commitment)[:1],
        "order_payment": (clear_guardian or guardian)[:1] + (clear_payment or payment)[:1],
        "mobile_realname": (clear_guardian or guardian)[:1] + (clear_mobile or mobile)[:1] + (clear_payment or payment)[:1],
    }
    limit = max(4, min(int(os.getenv("REVIEW_MINOR_CONSISTENCY_IMAGE_LIMIT", "8") or 8), 12))
    jobs = []
    for check_id in CONSISTENCY_FIELDS:
        required_indices = list(dict.fromkeys(
            image_index for image_index in plans[check_id] if image_index in by_index
        ))
        if not required_indices:
            continue
        anchor_indices = list(dict.fromkeys(
            image_index for image_index in anchors[check_id] if image_index in by_index
        ))[: max(1, limit - 1)]
        remaining = [image_index for image_index in required_indices if image_index not in anchor_indices]
        segment_indices = [required_indices]
        if len(required_indices) > limit:
            segment_indices = [
                anchor_indices + [int(item["image_index"]) for item in chunk]
                for chunk in _chunks(
                    [{"image_index": image_index} for image_index in remaining],
                    max(1, limit - len(anchor_indices)),
                )
            ]
        for segment_index, selected_indices in enumerate(segment_indices, start=1):
            jobs.append({
                "check_id": check_id,
                "segment_index": segment_index,
                "segment_total": len(segment_indices),
                "selected": [by_index[image_index] for image_index in selected_indices],
                "required_image_indices": required_indices,
                "quality_uncertain_indices": [
                    image_index
                    for image_index in required_indices
                    if not _usable(next(item for item in observations if int(item["image_index"]) == image_index))
                ],
            })
    return jobs


def _normalize_consistency_checks(
    results: List[Dict[str, Any]] | None,
    failures: List[Dict[str, Any]] | None,
) -> Dict[str, Any]:
    normalized: Dict[str, Dict[str, Any]] = {}
    grouped: Dict[str, List[Dict[str, Any]]] = {check_id: [] for check_id in CONSISTENCY_FIELDS}
    for result in results or []:
        parsed = result.get("parsed") or {}
        raw = parsed.get("consistency_check") or {}
        check_id = str(result.get("_expected_check_id") or raw.get("check_id") or "")
        if check_id in grouped:
            grouped[check_id].append(result)

    failed_ids = {
        str(item.get("check_id") or "")
        for item in failures or []
        if str(item.get("check_id") or "") in CONSISTENCY_FIELDS
    }
    for check_id, check_results in grouped.items():
        if not check_results:
            continue
        required_indices: set[int] = set()
        expected_union: set[int] = set()
        segment_coverage_ok = True
        quality_uncertain_indices: set[int] = set()
        field_candidates: Dict[str, List[Dict[str, Any]]] = {
            field_name: [] for field_name in CONSISTENCY_FIELDS[check_id]
        }
        tamper_risks = []
        risk_reason_codes = set()
        for result in check_results:
            parsed = result.get("parsed") or {}
            raw = parsed.get("consistency_check") or {}
            expected_indices = {
                int(value)
                for value in (result.get("_expected_image_indices") or (parsed.get("coverage_ack") or {}).get("expected_image_indices") or [])
                if str(value).isdigit()
            }
            observed_indices = {
                int(value)
                for value in (parsed.get("coverage_ack") or {}).get("observed_image_indices") or []
                if str(value).isdigit()
            }
            required_indices.update(
                int(value) for value in (result.get("_required_image_indices") or expected_indices)
                if str(value).isdigit()
            )
            quality_uncertain_indices.update(
                int(value) for value in result.get("_quality_uncertain_indices") or []
                if str(value).isdigit()
            )
            expected_union.update(expected_indices)
            segment_coverage_ok = segment_coverage_ok and bool(expected_indices) and expected_indices == observed_indices
            for item in raw.get("field_results") or []:
                if not isinstance(item, dict):
                    continue
                field_name = str(item.get("field_name") or "")
                status = str(item.get("status") or "uncertain")
                if field_name not in field_candidates or status not in CONSISTENCY_STATUS:
                    continue
                visibility = str(item.get("visibility") or "unreadable")
                if visibility not in FIELD_VISIBILITY:
                    visibility = "unreadable"
                evidence_indices = sorted({
                    int(value)
                    for value in item.get("evidence_image_indices") or []
                    if str(value).isdigit() and int(value) in expected_indices
                })
                if status == "mismatched" and (visibility != "complete" or len(evidence_indices) < 2):
                    status = "uncertain"
                if status == "matched" and (
                    visibility not in {"complete", "partial"} or not evidence_indices
                ):
                    status = "uncertain"
                field_candidates[field_name].append({
                    "status": status,
                    "visibility": visibility,
                    "evidence_image_indices": evidence_indices,
                })
            tamper_risk = str(raw.get("tamper_risk") or "uncertain")
            tamper_risks.append(tamper_risk if tamper_risk in TAMPER_RISK else "uncertain")
            risk_reason_codes.update(
                str(value) for value in raw.get("risk_reason_codes") or []
                if str(value) in RISK_REASON_CODES
            )

        field_rows = []
        for field_name, candidates in field_candidates.items():
            statuses = {item["status"] for item in candidates}
            if "mismatched" in statuses:
                status = "mismatched"
            elif len(candidates) == len(check_results) and statuses == {"matched"}:
                status = "matched"
            else:
                status = "uncertain"
            field_rows.append({
                "field_name": field_name,
                "status": status,
                "visibility": (
                    "complete" if status == "mismatched"
                    else "partial" if any(item["visibility"] == "partial" for item in candidates)
                    else "complete" if candidates and all(item["visibility"] == "complete" for item in candidates)
                    else "unreadable"
                ),
                "evidence_image_indices": sorted({
                    image_index for item in candidates for image_index in item["evidence_image_indices"]
                }),
            })
        field_statuses = {item["status"] for item in field_rows}
        tamper_risk = next(
            (value for value in ("high", "medium", "uncertain", "low") if value in tamper_risks),
            "uncertain",
        )
        coverage_ok = (
            bool(required_indices)
            and expected_union == required_indices
            and segment_coverage_ok
            and check_id not in failed_ids
        )
        if "mismatched" in field_statuses:
            status = "mismatched"
        elif field_statuses == {"matched"} and tamper_risk == "low" and coverage_ok and not quality_uncertain_indices:
            status = "matched"
        else:
            status = "uncertain"
        normalized[check_id] = {
            "check_id": check_id,
            "status": status,
            "message": CONSISTENCY_MESSAGES[status],
            "field_results": field_rows,
            "tamper_risk": tamper_risk,
            "risk_reason_codes": sorted(risk_reason_codes),
            "evidence_image_indices": sorted(required_indices),
            "coverage_complete": coverage_ok,
            "segment_count": len(check_results),
        }
    checks = []
    for check_id in CONSISTENCY_FIELDS:
        checks.append(normalized.get(check_id, {
            "check_id": check_id,
            "status": "not_assessed",
            "message": CONSISTENCY_MESSAGES["not_assessed"],
            "field_results": [],
            "tamper_risk": "uncertain",
            "risk_reason_codes": ["evidence_gap"] if check_id in failed_ids else [],
            "evidence_image_indices": [],
        }))
    statuses = {item["status"] for item in checks}
    if statuses == {"matched"} and not failures:
        verdict = "matched"
        status = "completed"
    elif "mismatched" in statuses:
        verdict = "mismatched"
        status = "completed"
    elif results or failures:
        verdict = "uncertain"
        status = "degraded" if failures else "completed"
    else:
        verdict = "not_assessed"
        status = "not_completed"
    return {
        "schema_version": "minor_consistency_v1",
        "status": status,
        "verdict": verdict,
        "message": CONSISTENCY_MESSAGES.get(verdict, CONSISTENCY_MESSAGES["not_assessed"]),
        "checks": checks,
        "failures": failures or [],
    }
def aggregate_minor_material_results(
    case: Dict[str, Any],
    image_rows: List[Tuple[List[int], Dict[str, Any]]],
    image_failures: List[Dict[str, Any]],
    video_results: List[Dict[str, Any]],
    video_failures: List[Dict[str, Any]],
    consistency_results: List[Dict[str, Any]] | None = None,
    consistency_failures: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    observations, unclassified = _normalize_observations(image_rows)
    expected_indices = sorted(
        int(item.get("image_index"))
        for item in case.get("supplemental_images") or []
        if item.get("image_index") is not None
    )
    declared_image_count = _declared_image_count(case)
    accepted_image_count = len(expected_indices)
    processed_indices = [item["image_index"] for item in observations]
    ingestion_complete = declared_image_count <= accepted_image_count
    technical_processing_incomplete = (
        not ingestion_complete
        or bool(image_failures)
        or len(processed_indices) < accepted_image_count
    )
    coverage_complete = (
        not image_failures
        and not unclassified
        and processed_indices == expected_indices
        and ingestion_complete
    )
    coverage_ratio = round(len(processed_indices) / max(declared_image_count, 1), 4)
    checklist = _checklist(observations, coverage_complete)
    present_count = sum(1 for item in checklist if item["status"] == "present")
    uncertain_count = sum(1 for item in checklist if item.get("quality_status") == "needs_manual_confirmation")
    not_observed = [item for item in checklist if item["status"] == "not_observed_after_full_scan"]
    field_consistency = _normalize_consistency_checks(consistency_results, consistency_failures)
    consistency_by_id = {item["check_id"]: item for item in field_consistency["checks"]}
    consistency_status_labels = {
        "matched": "未发现明显矛盾",
        "mismatched": "存在明确冲突",
        "uncertain": "仍待确认",
        "not_assessed": "尚未完成",
    }
    requirement_checks = {
        "identity": "identity_age",
        "relationship": "guardian_relationship",
        "commitment": "commitment_signatures",
        "payment": "order_payment",
        "mobile_realname": "mobile_realname",
    }
    for item in checklist:
        check = consistency_by_id.get(requirement_checks[item["requirement_id"]]) or {}
        item["validation_status"] = {
            "matched": "visual_consistency_matched",
            "mismatched": "visual_consistency_mismatched",
            "uncertain": "visual_consistency_uncertain",
        }.get(check.get("status"), item["validation_status"])

    policy = _minor_refund_policy(case)
    authoritative_required = policy["authoritative_verification"] == "required"
    authenticity = _authenticity_assessment(case, observations, field_consistency)
    authenticity_blocked = bool(authenticity["blocks_visual_precheck"])

    if (
        coverage_complete
        and present_count == len(checklist)
        and field_consistency["verdict"] == "matched"
        and not authenticity_blocked
        and not authoritative_required
    ):
        predicted_label = "positive"
        decision = "visual_precheck_passed"
        system_yes_no = "YES"
        confidence = 0.88
        readiness = "ready_for_customer_policy"
        visual_precheck_status = "passed"
        conclusion = "五类必交材料已齐全，视觉字段未发现明显矛盾，可以按甲方现行流程继续审核。"
    elif coverage_complete and present_count == len(checklist) and field_consistency["verdict"] == "mismatched":
        predicted_label = "negative"
        decision = "visual_precheck_not_passed"
        system_yes_no = "NO"
        confidence = 0.84
        readiness = "visual_conflict_requires_review"
        visual_precheck_status = "failed"
        conclusion = "材料虽然齐全，但可见字段存在明确冲突，当前资料不支持继续通过初审；请回看标红图片。"
    elif coverage_complete and present_count == len(checklist) and authenticity_blocked:
        predicted_label = "review"
        decision = "manual_review"
        system_yes_no = "REVIEW"
        confidence = 0.74
        readiness = "suspected_editing_requires_review"
        visual_precheck_status = "needs_review"
        conclusion = "五类材料已齐全，但部分图片存在较强的疑似编辑线索，请重点复核标红证据。"
    elif coverage_complete and present_count == len(checklist) and authoritative_required:
        predicted_label = "review"
        decision = "manual_review"
        system_yes_no = "REVIEW"
        confidence = 0.88 if field_consistency["verdict"] == "matched" else 0.69
        readiness = "ready_for_authoritative_verification"
        visual_precheck_status = "needs_review"
        conclusion = "视觉初审已完成；当前工单启用了严格验真策略，仍需完成甲方配置的权威核验。"
    elif (
        coverage_complete
        and present_count == len(checklist)
        and field_consistency["status"] in {"degraded", "not_completed"}
    ):
        predicted_label = "review"
        decision = "manual_consistency_review"
        system_yes_no = "REVIEW"
        confidence = 0.69
        readiness = "needs_field_consistency_review"
        visual_precheck_status = "needs_review"
        conclusion = "五类材料已齐全，但字段仍不清楚或未完成比对；请回看标黄图片或受控重试，不能直接按本轮结果处理。"
    elif coverage_complete and present_count == len(checklist):
        predicted_label = "review"
        decision = "continue_by_customer_policy"
        system_yes_no = "REVIEW"
        confidence = 0.69
        readiness = "ready_with_visual_warnings"
        visual_precheck_status = "needs_review"
        conclusion = "五类材料已齐全，部分可见字段仍不清楚或无法比较；可按甲方现行流程继续，标黄图片建议抽检。"
    elif not_observed:
        predicted_label = "review"
        decision = "request_more_material"
        system_yes_no = "REVIEW"
        confidence = 0.66
        readiness = "needs_human_gap_confirmation"
        visual_precheck_status = "incomplete"
        conclusion = "全量图片已处理，但部分材料类别尚未被可靠确认；应先由VIP客服回看对应图片，再决定是否要求补充。"
    else:
        predicted_label = "review"
        decision = "manual_review"
        system_yes_no = "REVIEW"
        confidence = round(min(0.69, 0.45 + 0.04 * present_count + 0.02 * uncertain_count), 2)
        readiness = "incomplete_processing" if not coverage_complete else "manual_consistency_review"
        visual_precheck_status = "incomplete"
        conclusion = "材料包未完成全量可靠识别或仍有角色/清晰度待确认，不能据此声称用户缺少材料。"

    material_gaps = [
        f"全量图片中尚未确认到“{item['label']}”；不得据此断言用户未提交，请VIP客服先回看未分类或低清图片。"
        for item in not_observed
    ]
    if not coverage_complete and not technical_processing_incomplete:
        material_gaps.insert(0, "本轮未完成全部图片的可靠识别，缺件结论已被门禁阻断。")
    if technical_processing_incomplete:
        material_gaps = []
        confidence = None
        decision = "system_retry"
        readiness = "technical_processing_incomplete"
        visual_precheck_status = "processing_incomplete"
        conclusion = "系统尚未完成全部已接收图片的技术处理，本轮不形成材料缺失或真实性结论。"

    human_required = bool(
        not technical_processing_incomplete
        and (
            field_consistency["verdict"] == "mismatched"
            or field_consistency["status"] in {"degraded", "not_completed"}
            or authenticity_blocked
            or authoritative_required
        )
    )
    business_follow_up_reason = (
        "当前请求已完成结构修复和逐张恢复；仍未覆盖时可受控重跑整案，可能重复模型成本，且不要求用户补件。"
        if technical_processing_incomplete
        else "Agent只给资料初审建议，不执行退款或拒绝；甲方可按当前流程继续、抽检或要求用户补充指定材料。"
    )
    if technical_processing_incomplete:
        next_step = "请受控重跑整案；全部资料处理完成后再生成审核建议，达到重试上限后再转授权人员。"
    elif predicted_label == "positive":
        next_step = "五类材料和可见字段均已通过初审，可按甲方现行一审流程继续；本服务不直接执行退款。"
    elif predicted_label == "negative":
        next_step = "请先回看报告中标红的冲突图片；确认无误后，按 SOP 告知用户补交或更正对应材料。"
    elif authenticity_blocked:
        next_step = "请优先打开报告中标红的疑似编辑图片；确认原图无误后可重新送审。"
    elif authoritative_required:
        next_step = "当前工单显式启用了严格验真，请完成甲方配置的核验步骤；没有可用接口时请改回默认策略。"
    else:
        next_step = "请回看报告中标黄的字段或图片；能确认一致时按现行流程继续，不能确认时只补对应材料。"

    supporting_evidence = [
        {
            "source_type": "supplementary_image",
            "image_index": image_index,
            "asset_ref": f"supplemental_image_{image_index}",
            "description": (
                f"该图片支持“{item['label']}”材料存在；视觉字段一致性状态为"
                f"{consistency_status_labels.get(consistency_by_id.get(requirement_checks[item['requirement_id']], {}).get('status', 'not_assessed'), '尚未完成')}。"
            ),
            "confidence": 0.82,
        }
        for item in checklist
        if item["status"] == "present"
        for image_index in item["evidence_image_indices"][:2]
    ]
    valid_frames = {
        (int(item.get("video_index") or 0), int(item.get("global_frame_index") or 0))
        for item in case.get("frames") or []
    }
    process_observations = _normalize_process_observations(video_results, valid_frames)
    evidence_conflicts = [
        {
            "check_id": item.get("check_id"),
            "evidence_image_indices": item.get("evidence_image_indices") or [],
            "message": "可见字段存在冲突，请回看对应图片。",
        }
        for item in field_consistency.get("checks") or []
        if item.get("status") == "mismatched"
    ]
    challenging_evidence = [
        {
            "source_type": "supplementary_image",
            "image_index": image_index,
            "asset_ref": f"supplemental_image_{image_index}",
            "description": "该图片存在较强的疑似编辑线索，需要优先人工回看原图。",
            "confidence": authenticity["risk_score"],
        }
        for image_index in authenticity["evidence_image_indices"]
    ]
    assessment = {
        "sop_version": "minor_refund_2_0",
        "readiness": readiness,
        "visual_precheck_status": visual_precheck_status,
        "declared_image_count": declared_image_count,
        "accepted_image_count": accepted_image_count,
        "processed_image_count": len(processed_indices),
        "processed_image_indices": processed_indices,
        "unclassified_image_indices": unclassified,
        "coverage_ratio": coverage_ratio,
        "coverage_complete": coverage_complete,
        "ingestion_complete": ingestion_complete,
        "processing_status": "technical_processing_incomplete" if technical_processing_incomplete else "completed",
        "system_action": "system_retry" if technical_processing_incomplete else "none",
        "image_batch_failures": image_failures,
        "video_batch_failures": video_failures,
        "material_inventory": observations,
        "checklist": checklist,
        "field_consistency": field_consistency,
        "authenticity_assessment": authenticity,
        "policy": policy,
        "authoritative_verification": {
            "status": (
                "customer_integration_required"
                if authoritative_required
                else "not_configured_advisory"
                if policy["authoritative_verification"] == "advisory"
                else "not_configured_optional"
            ),
            "checks": [
                {
                    "verification_id": verification_id,
                    "integration_status": "customer_integration_required" if authoritative_required else "not_configured",
                }
                for verification_id in ("identity_registry", "carrier_realname", "order_payment_system")
            ],
            "pending_checks": (
                ["identity_registry", "carrier_realname", "order_payment_system"]
                if authoritative_required
                else []
            ),
            "boundary": (
                "当前策略要求完成甲方权威验真后再继续。"
                if authoritative_required
                else "当前默认不依赖外部验真接口；视觉一致性仍不等于法定真实性，报告不会宣称证件已权威验真。"
            ),
        },
        "process_evidence": process_observations,
        "privacy_boundary": "报告只保留材料类型、护照签发国家/地区、图片编号、清晰度和一致性待核点，不输出姓名、手机号、证件号、住址或OCR原文。",
        "business_boundary": "Agent输出资料初审建议，不自动退款、自动通过、自动拒绝或注销账号；最终业务动作仍由甲方规则执行。",
    }
    return {
        "decision": decision,
        "predicted_label": predicted_label,
        "system_yes_no": system_yes_no,
        "confidence": confidence,
        "overall_audit": {
            "conclusion": conclusion,
            "confidence": confidence,
            "core_reason": f"已处理 {len(processed_indices)}/{declared_image_count} 张申报图片，五类材料确认 {present_count}/{len(checklist)} 项；字段一致性{consistency_status_labels.get(field_consistency['verdict'], '尚未完成')}。",
            "business_follow_up_suggestion": next_step,
        },
        "visual_evidence_verdict": conclusion,
        "visual_qc_conclusion": {"verdict": predicted_label, "confidence": confidence, "core_reason": conclusion},
        "confidence_reason": (
            "技术处理未完成，本轮不输出证据分。"
            if technical_processing_incomplete
            else f"图片覆盖率 {coverage_ratio}，已确认材料类别 {present_count}/{len(checklist)}；该分数是未校准的证据完整性参考。"
        ),
        "minor_material_assessment": assessment,
        "authoritative_verification": assessment["authoritative_verification"],
        "authenticity_assessment": authenticity,
        "supporting_evidence": supporting_evidence,
        "adopted_evidence": supporting_evidence,
        "challenging_evidence": challenging_evidence,
        "evidence_conflicts": evidence_conflicts,
        "material_gaps": material_gaps,
        "processing_status": "technical_processing_incomplete" if technical_processing_incomplete else "completed",
        "system_action": "system_retry" if technical_processing_incomplete else "none",
        "audit_methods": ["全图片分批识别", "图片编号覆盖校验", "SOP五类材料确定性聚合", "跨材料视觉字段一致性", "过程视频独立识别", "缺件与一致性门禁"],
        "business_action_allowed": False,
        "human_required": human_required,
        "business_follow_up_reason": business_follow_up_reason,
        "next_step": next_step,
        "model_limitations": [
            "视觉字段一致不等同于法定真实性",
            "缺少 EXIF 不等于图片造假，疑似编辑分数也不是客观真伪概率",
            "公开结果不展示姓名、号码、金额或OCR原文",
            "退款结果由甲方业务系统和授权人员决定",
        ],
        "confidence_components": {
            "material_image_coverage": coverage_ratio,
            "required_category_completeness": round(present_count / max(len(checklist), 1), 4),
            "final_decision": confidence,
            "calibration_status": (
                "not_applicable_technical_processing_incomplete"
                if technical_processing_incomplete
                else "uncalibrated_model_score"
            ),
            "interpretation": "覆盖率表示图片是否全部处理，类别完整度表示五类材料是否被识别；均不等同于退款审核正确率。",
        },
    }


def run_minor_material_pipeline(
    case: Dict[str, Any],
    invoke: Callable[[Dict[str, Any]], Dict[str, Any]],
    workers: int,
) -> Dict[str, Any]:
    wall_started = time.time()
    effective_workers = max(1, min(int(workers or 1), 8))
    images = list(case.get("supplemental_images") or [])
    frames = list(case.get("frames") or [])
    image_batch_size = max(1, min(int(os.getenv("REVIEW_MINOR_IMAGE_BATCH_SIZE", "4") or 4), 6))
    frame_batch_size = max(1, min(int(case.get("model_frames_per_call") or 24), 24))
    image_batches = _chunks(images, image_batch_size)
    frame_batches = _chunks(frames, frame_batch_size)
    jobs: List[Tuple[str, int, List[Dict[str, Any]]]] = [
        ("image", index, batch) for index, batch in enumerate(image_batches)
    ] + [("video", index, batch) for index, batch in enumerate(frame_batches)]
    image_rows: List[Tuple[List[int], Dict[str, Any]]] = []
    video_results: List[Dict[str, Any]] = []
    image_failures: List[Dict[str, Any]] = []
    video_failures: List[Dict[str, Any]] = []
    consistency_results: List[Dict[str, Any]] = []
    consistency_failures: List[Dict[str, Any]] = []
    consistency_jobs: List[Dict[str, Any]] = []
    image_metric_results: List[Dict[str, Any]] = []
    video_metric_results: List[Dict[str, Any]] = []
    consistency_metric_results: List[Dict[str, Any]] = []

    def review_job(kind: str, index: int, batch: List[Dict[str, Any]]) -> Tuple[str, int, List[int], Dict[str, Any]]:
        batch_case = dict(case)
        structured = dict(case.get("structured_business_context") or {})
        if kind == "image":
            indices = [int(item["image_index"]) for item in batch]
            batch_case["frames"] = []
            batch_case["videos"] = []
            batch_case["supplemental_images"] = batch
            structured["analysis_mode"] = "minor_material_inventory"
            structured["minor_material_batch"] = {
                "index": index + 1,
                "total": len(image_batches),
                "expected_image_indices": indices,
                "global_image_count": len(images),
                "instruction": "本批只识别所见材料，不判断其他批次是否缺件。",
            }
        else:
            indices = [int(item["global_frame_index"]) for item in batch]
            batch_case["frames"] = batch
            batch_case["supplemental_images"] = []
            structured["analysis_mode"] = "minor_material_process_video"
            structured["minor_video_batch"] = {
                "index": index + 1,
                "total": len(frame_batches),
                "expected_global_frame_indices": indices,
                "global_frame_count": len(frames),
                "instruction": "视频只用于识别开票或材料展示过程，不判断图片材料缺失。",
            }
        batch_case["structured_business_context"] = structured
        result = invoke(batch_case)

        def invoke_repair(retry_case: Dict[str, Any]) -> Dict[str, Any]:
            try:
                return invoke(retry_case)
            except Exception as exc:
                return {
                    "status": "failed",
                    "error": str(exc)[:500],
                    "_model_calls": 1,
                }

        if kind == "image" and result.get("status") == "success":
            schema_retries = max(0, min(int(os.getenv("REVIEW_MINOR_SCHEMA_RETRIES", "2") or 2), 2))
            for retry_index in range(schema_retries):
                missing = sorted(set(indices) - _result_observed_indices(result))
                if not missing:
                    break
                retry_case = dict(batch_case)
                retry_structured = dict(structured)
                retry_structured["minor_material_batch"] = {
                    **(structured.get("minor_material_batch") or {}),
                    "schema_retry": retry_index + 1,
                    "missing_image_indices_from_previous_response": missing,
                    "instruction": "上次响应遗漏了图片编号；本次必须逐张返回全部 expected_image_indices，仍不得输出任何个人信息。",
                }
                retry_case["structured_business_context"] = retry_structured
                result = _merge_semantic_attempts(result, invoke_repair(retry_case))
            missing = sorted(set(indices) - _result_observed_indices(result))
            images_by_index = {int(item["image_index"]): item for item in batch}
            for image_index in missing:
                for recovery_index in range(schema_retries + 1):
                    retry_case = dict(batch_case)
                    retry_case["supplemental_images"] = [images_by_index[image_index]]
                    retry_structured = dict(structured)
                    retry_structured["minor_material_batch"] = {
                        **(structured.get("minor_material_batch") or {}),
                        "single_image_recovery": True,
                        "single_image_recovery_attempt": recovery_index + 1,
                        "expected_image_indices": [image_index],
                        "instruction": "批量响应持续遗漏该图片；本次只审核这一张，并必须返回该图片编号的受控分类结果。",
                    }
                    retry_case["structured_business_context"] = retry_structured
                    result = _merge_semantic_attempts(result, invoke_repair(retry_case))
                    if image_index in _result_observed_indices(result):
                        break
        result.setdefault("_model_calls", 1)
        return kind, index, indices, result

    if jobs:
        with ThreadPoolExecutor(max_workers=max(1, min(effective_workers, len(jobs)))) as pool:
            futures = {pool.submit(review_job, *job): job for job in jobs}
            completed = []
            for future in as_completed(futures):
                kind, index, _ = futures[future]
                try:
                    completed.append(future.result())
                except Exception as exc:
                    completed.append((kind, index, [], {"status": "failed", "error": str(exc)[:500], "_model_calls": 1}))
        for kind, index, indices, result in sorted(completed, key=lambda item: (item[0], item[1])):
            (image_metric_results if kind == "image" else video_metric_results).append(result)
            if result.get("status") != "success":
                failure = {"batch_index": index + 1, "error": result.get("error") or result.get("status")}
                (image_failures if kind == "image" else video_failures).append(failure)
            elif kind == "image":
                image_rows.append((indices, result))
            else:
                video_results.append(result)

    preliminary = aggregate_minor_material_results(case, image_rows, image_failures, video_results, video_failures)
    preliminary_assessment = preliminary["minor_material_assessment"]
    if preliminary_assessment["coverage_complete"] and all(
        item["status"] == "present" for item in preliminary_assessment["checklist"]
    ):
        consistency_jobs = _consistency_image_jobs(preliminary_assessment["material_inventory"], images)

        def review_consistency(job: Dict[str, Any]) -> Dict[str, Any]:
            check_id = str(job["check_id"])
            selected = list(job["selected"])
            check_case = dict(case)
            structured = dict(case.get("structured_business_context") or {})
            expected_indices = [int(item["image_index"]) for item in selected]
            structured["analysis_mode"] = "minor_material_consistency"
            structured["minor_consistency_check"] = {
                "check_id": check_id,
                "segment_index": job["segment_index"],
                "segment_total": job["segment_total"],
                "expected_image_indices": expected_indices,
                "instruction": "只返回受控枚举、证据图片编号和风险码，不得返回任何字段原值。",
            }
            check_case["structured_business_context"] = structured
            check_case["frames"] = []
            check_case["videos"] = []
            check_case["supplemental_images"] = selected
            result = invoke(check_case)
            result["_expected_check_id"] = check_id
            result["_expected_image_indices"] = expected_indices
            result["_required_image_indices"] = job["required_image_indices"]
            result["_quality_uncertain_indices"] = job["quality_uncertain_indices"]
            result["_segment_index"] = job["segment_index"]
            result["_segment_total"] = job["segment_total"]
            result.setdefault("_model_calls", 1)
            return result

        with ThreadPoolExecutor(max_workers=max(1, min(effective_workers, len(consistency_jobs)))) as pool:
            futures = {
                pool.submit(review_consistency, job): job
                for job in consistency_jobs
            }
            for future in as_completed(futures):
                job = futures[future]
                check_id = str(job["check_id"])
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"status": "failed", "error": str(exc)[:500], "_model_calls": 1}
                    consistency_metric_results.append(result)
                    consistency_failures.append({
                        "check_id": check_id,
                        "segment_index": job["segment_index"],
                        "error": str(exc)[:500],
                    })
                    continue
                consistency_metric_results.append(result)
                if result.get("status") == "success":
                    consistency_results.append(result)
                else:
                    consistency_failures.append({
                        "check_id": check_id,
                        "segment_index": job["segment_index"],
                        "error": result.get("error") or result.get("status"),
                    })

    parsed = aggregate_minor_material_results(
        case,
        image_rows,
        image_failures,
        video_results,
        video_failures,
        consistency_results=consistency_results,
        consistency_failures=consistency_failures,
    )
    billed_results = image_metric_results + video_metric_results + consistency_metric_results
    usage = {
        key: sum(int((item.get("usage") or {}).get(key) or 0) for item in billed_results)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    cost = round(sum(float((item.get("cost") or {}).get("estimated_usd") or 0) for item in billed_results), 6)
    cost_observability = summarize_cost_observability(billed_results)
    return {
        "status": "success" if image_rows or not images else "failed",
        "error": "minor_material_all_image_batches_failed" if images and not image_rows else "",
        "latency_seconds": round(time.time() - wall_started, 2),
        "model_latency_seconds_sum": round(sum(float(item.get("latency_seconds") or 0) for item in billed_results), 2),
        "usage": usage,
        "cost": {"estimated_usd": cost},
        **cost_observability,
        "parsed": parsed,
        "chunking": {
            "effective_workers": effective_workers,
            "segment_count": len(image_batches) + len(frame_batches) + len(consistency_jobs),
            "frames_per_segment": frame_batch_size,
            "total_frames": len(frames),
            "total_model_calls": sum(int(item.get("_model_calls") or 1) for item in billed_results),
            "channels": {
                "minor_material_inventory": _metric_summary(image_metric_results),
                "minor_process_video": _metric_summary(video_metric_results),
                "minor_field_consistency": _metric_summary(consistency_metric_results),
            },
            "image_batches": {
                "planned": len(image_batches),
                "completed": len(image_rows),
                "failures": image_failures,
            },
            "video_batches": {
                "planned": len(frame_batches),
                "completed": len(video_results),
                "failures": video_failures,
            },
            "consistency_checks": {
                "planned": len(consistency_results) + len(consistency_failures),
                "completed": len(consistency_results),
                "failures": consistency_failures,
            },
        },
    }
