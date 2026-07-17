# -*- coding: utf-8 -*-
"""未成年人退款资料全覆盖审核与确定性聚合。"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Sequence, Tuple


ALLOWED_DOCUMENT_TYPES = {
    "identity_card",
    "household_register",
    "birth_certificate",
    "signed_commitment",
    "order_payment_proof",
    "mobile_realname_proof",
    "carrier_invoice",
    "other",
}
ALLOWED_ROLES = {"guardian", "minor", "unknown", "not_applicable"}
ALLOWED_SIDES = {"front", "back", "page", "multiple", "unknown"}
ALLOWED_READABILITY = {"clear", "partial", "unreadable"}
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
    return {
        **second,
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
            role = str(raw.get("subject_role") or "unknown")
            side = str(raw.get("document_side") or "unknown")
            readability = str(raw.get("readability") or "unreadable")
            quality_issues = [
                str(value)
                for value in raw.get("quality_issues") or []
                if str(value) in ALLOWED_QUALITY_ISSUES
            ]
            by_index[image_index] = {
                "image_index": image_index,
                "asset_ref": f"supplemental_image_{image_index}",
                "document_types": document_types or ["other"],
                "subject_role": role if role in ALLOWED_ROLES else "unknown",
                "document_side": side if side in ALLOWED_SIDES else "unknown",
                "readability": readability if readability in ALLOWED_READABILITY else "unreadable",
                "quality_issues": quality_issues,
            }
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

    def status(present: bool, observed: bool) -> str:
        if present:
            return "present"
        if observed:
            return "needs_manual_confirmation"
        return "not_observed_after_full_scan" if coverage_complete else "not_assessed"

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
            "status": status(present, observed),
            "evidence_refs": [item["asset_ref"] for item in evidence],
            "evidence_image_indices": [item["image_index"] for item in evidence],
            "rule_note": note,
            "validation_status": validation_status if present else "not_validated",
        }
        for requirement_id, label, present, observed, evidence, note, validation_status in rows
    ]


def aggregate_minor_material_results(
    case: Dict[str, Any],
    image_rows: List[Tuple[List[int], Dict[str, Any]]],
    image_failures: List[Dict[str, Any]],
    video_results: List[Dict[str, Any]],
    video_failures: List[Dict[str, Any]],
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
    coverage_complete = (
        not image_failures
        and not unclassified
        and processed_indices == expected_indices
        and ingestion_complete
    )
    coverage_ratio = round(len(processed_indices) / max(declared_image_count, 1), 4)
    checklist = _checklist(observations, coverage_complete)
    present_count = sum(1 for item in checklist if item["status"] == "present")
    uncertain_count = sum(1 for item in checklist if item["status"] == "needs_manual_confirmation")
    not_observed = [item for item in checklist if item["status"] == "not_observed_after_full_scan"]

    if coverage_complete and present_count == len(checklist):
        predicted_label = "positive"
        decision = "pass"
        system_yes_no = "YES"
        confidence = round(min(0.95, 0.78 + 0.03 * present_count), 2)
        readiness = "ready_for_human_first_review"
        conclusion = "五类材料均已在全量图片中识别到，可进入VIP客服人工一审；这不代表自动退款或终审通过。"
    elif not_observed:
        predicted_label = "review"
        decision = "request_more_material"
        system_yes_no = "REVIEW"
        confidence = 0.66
        readiness = "needs_human_gap_confirmation"
        conclusion = "全量图片已处理，但部分材料类别尚未被可靠确认；应先由VIP客服回看对应图片，再决定是否要求补充。"
    else:
        predicted_label = "review"
        decision = "manual_review"
        system_yes_no = "REVIEW"
        confidence = round(min(0.69, 0.45 + 0.04 * present_count + 0.02 * uncertain_count), 2)
        readiness = "incomplete_processing" if not coverage_complete else "manual_consistency_review"
        conclusion = "材料包未完成全量可靠识别或仍有角色/清晰度待确认，不能据此声称用户缺少材料。"

    material_gaps = [
        f"全量图片中尚未确认到“{item['label']}”；不得据此断言用户未提交，请VIP客服先回看未分类或低清图片。"
        for item in not_observed
    ]
    if not coverage_complete:
        material_gaps.insert(0, "本轮未完成全部图片的可靠识别，缺件结论已被门禁阻断。")

    supporting_evidence = [
        {
            "source_type": "supplementary_image",
            "image_index": image_index,
            "asset_ref": f"supplemental_image_{image_index}",
            "description": f"该图片被识别为“{item['label']}”的候选证据，具体身份字段由VIP客服核对。",
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
    assessment = {
        "sop_version": "minor_refund_2_0",
        "readiness": readiness,
        "declared_image_count": declared_image_count,
        "accepted_image_count": accepted_image_count,
        "processed_image_count": len(processed_indices),
        "processed_image_indices": processed_indices,
        "unclassified_image_indices": unclassified,
        "coverage_ratio": coverage_ratio,
        "coverage_complete": coverage_complete,
        "ingestion_complete": ingestion_complete,
        "image_batch_failures": image_failures,
        "video_batch_failures": video_failures,
        "material_inventory": observations,
        "checklist": checklist,
        "process_evidence": process_observations,
        "privacy_boundary": "报告只保留材料类型、图片编号、清晰度和一致性待核点，不输出姓名、手机号、证件号、住址或OCR原文。",
        "business_boundary": "资料齐全只表示可进入人工一审、二审和终审；Agent不得自动退款、自动通过或自动拒绝。",
    }
    return {
        "decision": decision,
        "predicted_label": predicted_label,
        "system_yes_no": system_yes_no,
        "confidence": confidence,
        "overall_audit": {
            "conclusion": conclusion,
            "confidence": confidence,
            "core_reason": f"已处理 {len(processed_indices)}/{declared_image_count} 张申报图片，五类材料确认 {present_count}/{len(checklist)} 项。",
            "business_follow_up_suggestion": "请VIP客服按图片编号核对身份关系、发票备注、金额与签字，再按SOP进入人工一审或补件流程。",
        },
        "visual_evidence_verdict": conclusion,
        "visual_qc_conclusion": {"verdict": predicted_label, "confidence": confidence, "core_reason": conclusion},
        "confidence_reason": f"图片覆盖率 {coverage_ratio}，已确认材料类别 {present_count}/{len(checklist)}；该分数是未校准的证据完整性参考。",
        "minor_material_assessment": assessment,
        "supporting_evidence": supporting_evidence,
        "adopted_evidence": supporting_evidence,
        "challenging_evidence": [],
        "material_gaps": material_gaps,
        "audit_methods": ["全图片分批识别", "图片编号覆盖校验", "SOP五类材料确定性聚合", "过程视频独立识别", "缺件结论门禁"],
        "business_action_allowed": False,
        "human_required": True,
        "business_follow_up_reason": "未成年人退款涉及身份、监护关系、账号归属与资金处置，必须由授权人员终审。",
        "next_step": "请VIP客服按材料清单和图片编号核对；材料类别齐全时进入人工一审，未确认项先回看原图再决定是否补件。",
        "model_limitations": ["材料类型识别不等同于身份真实性验证", "姓名、号码、金额和主体一致性不在公开报告中展示", "退款结果由甲方业务系统和授权人员决定"],
        "confidence_components": {
            "material_image_coverage": coverage_ratio,
            "required_category_completeness": round(present_count / max(len(checklist), 1), 4),
            "final_decision": confidence,
            "calibration_status": "uncalibrated_model_score",
            "interpretation": "覆盖率表示图片是否全部处理，类别完整度表示五类材料是否被识别；均不等同于退款审核正确率。",
        },
    }


def run_minor_material_pipeline(
    case: Dict[str, Any],
    invoke: Callable[[Dict[str, Any]], Dict[str, Any]],
    workers: int,
) -> Dict[str, Any]:
    wall_started = time.time()
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
        if kind == "image" and result.get("status") == "success":
            schema_retries = max(0, min(int(os.getenv("REVIEW_MINOR_SCHEMA_RETRIES", "1") or 1), 2))
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
                result = _merge_semantic_attempts(result, invoke(retry_case))
        result.setdefault("_model_calls", 1)
        return kind, index, indices, result

    if jobs:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 4, len(jobs)))) as pool:
            futures = {pool.submit(review_job, *job): job for job in jobs}
            completed = []
            for future in as_completed(futures):
                kind, index, _ = futures[future]
                try:
                    completed.append(future.result())
                except Exception as exc:
                    completed.append((kind, index, [], {"status": "failed", "error": str(exc)[:500]}))
        for kind, index, indices, result in sorted(completed, key=lambda item: (item[0], item[1])):
            if result.get("status") != "success":
                failure = {"batch_index": index + 1, "error": result.get("error") or result.get("status")}
                (image_failures if kind == "image" else video_failures).append(failure)
            elif kind == "image":
                image_rows.append((indices, result))
            else:
                video_results.append(result)

    parsed = aggregate_minor_material_results(case, image_rows, image_failures, video_results, video_failures)
    billed_results = [result for _, result in image_rows] + video_results
    usage = {
        key: sum(int((item.get("usage") or {}).get(key) or 0) for item in billed_results)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    cost = round(sum(float((item.get("cost") or {}).get("estimated_usd") or 0) for item in billed_results), 6)
    return {
        "status": "success" if image_rows or not images else "failed",
        "error": "minor_material_all_image_batches_failed" if images and not image_rows else "",
        "latency_seconds": round(time.time() - wall_started, 2),
        "model_latency_seconds_sum": round(sum(float(item.get("latency_seconds") or 0) for item in billed_results), 2),
        "usage": usage,
        "cost": {"estimated_usd": cost},
        "parsed": parsed,
        "chunking": {
            "segment_count": len(image_batches) + len(frame_batches),
            "frames_per_segment": frame_batch_size,
            "total_frames": len(frames),
            "total_model_calls": len(billed_results),
            "channels": {
                "minor_material_inventory": _metric_summary([result for _, result in image_rows]),
                "minor_process_video": _metric_summary(video_results),
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
        },
    }
