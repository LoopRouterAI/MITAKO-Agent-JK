# -*- coding: utf-8 -*-
"""未成年人退款资料全覆盖审核与确定性聚合。"""
from __future__ import annotations

import os
import math
import time
from pathlib import Path
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any, Callable, Dict, List, Sequence, Tuple

from configs.model_catalog import summarize_cost_observability
from poc.visual_review_poc.observability import sanitize_error_text
from poc.visual_review_poc.media_preflight import prepare_image_detail_crop
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
ALLOWED_DOCUMENT_STATES = {"filled", "blank_template", "example", "unknown"}
ALLOWED_SOP_ELIGIBILITY = {"valid", "supporting_only", "invalid", "unknown"}
ALLOWED_ORDER_PAYMENT_EVIDENCE_TYPES = {"order", "payment", "combined", "unknown"}
ALLOWED_APPLICATION_SCOPE_COVERAGE = {"complete", "partial", "unknown"}
ALLOWED_QUALITY_ISSUES = {
    "blur",
    "glare",
    "occlusion",
    "excessive_redaction",
    "incomplete_page",
    "suspected_editing",
    "other",
}
ALLOWED_EDITING_EVIDENCE_CODES = {
    "inconsistent_text_edge",
    "duplicated_region",
    "local_resampling_artifact",
    "impossible_geometry",
    "other_specific_anomaly",
}
PROCESS_TYPES = {"invoice_generation", "document_capture", "payment_record", "other", "uncertain"}
PROCESS_QUALITY = {"clear", "partial", "unreadable"}
CONSISTENCY_FIELDS = {
    "identity_age": (
        "guardian_identity", "minor_identity", "age_eligibility",
        "payment_password_access", "guardian_discovery_process",
    ),
    "guardian_relationship": (
        "guardian_identity", "minor_identity", "relationship_document_linkage",
        "explicit_relationship_entry", "relationship_link", "applicant_guardian_role",
    ),
    "commitment_signatures": (
        "guardian_signer", "minor_signer", "signature_presence", "signature_method", "field_alignment",
        "commitment_content", "refund_scope", "recipient_information", "signed_date",
        "account_bound_phone", "account_nickname", "consumption_time_range",
        "refund_amount", "refund_method", "payment_recipient",
    ),
    "order_payment": (
        "order_reference", "order_item_scope", "item_quantity", "order_status",
        "payer_identity", "payment_status", "transaction_time", "amount",
        "merchant_identity", "transaction_id", "merchant_order_id",
        "transaction_scope", "commitment_amount",
    ),
    "mobile_realname": (
        "subscriber_identity", "account_mobile", "invoice_identity", "invoice_phone",
        "number_status", "ownership_proof", "guardian_phone_holder",
    ),
}
CONSISTENCY_STATUS = {"matched", "mismatched", "uncertain", "not_assessed"}
PAYMENT_CAPABILITY_RISKS = {"none", "high", "unknown"}
AGE_CONFIDENCE = {"high", "low", "unknown"}
RELATIONSHIP_EVIDENCE_TYPES = {
    "same_household_direct_link",
    "birth_certificate",
    "legal_guardianship_proof",
    "separate_household_books_without_bridge",
    "uncertain",
    "not_applicable",
}
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
CONSISTENCY_CHECK_LABELS = {
    "identity_age": "身份与年龄材料",
    "guardian_relationship": "监护关系材料",
    "commitment_signatures": "退款承诺书",
    "order_payment": "订单与支付材料",
    "mobile_realname": "手机号实名归属材料",
}
CONSISTENCY_FIELD_LABELS = {
    "guardian_identity": "监护人身份",
    "minor_identity": "未成年人身份",
    "age_eligibility": "未成年人年龄条件",
    "payment_password_access": "支付密码获取方式",
    "guardian_discovery_process": "监护人发现消费的过程",
    "relationship_link": "监护关系",
    "relationship_document_linkage": "关系材料主体链接",
    "explicit_relationship_entry": "明确亲子或合法监护记载",
    "applicant_guardian_role": "申请人监护资格",
    "guardian_signer": "监护人签字",
    "minor_signer": "未成年人签字",
    "signature_presence": "双方签字是否齐全",
    "signature_method": "签字方式",
    "field_alignment": "承诺书字段位置",
    "commitment_content": "完整承诺内容",
    "refund_scope": "退款范围",
    "recipient_information": "收款信息",
    "signed_date": "签署日期",
    "account_bound_phone": "账号绑定手机号",
    "account_nickname": "账号昵称",
    "consumption_time_range": "消费时间范围",
    "refund_amount": "退款金额",
    "refund_method": "退款方式",
    "payment_recipient": "收款对象",
    "order_reference": "订单编号",
    "order_item_scope": "订单商品范围",
    "item_quantity": "商品数量",
    "order_status": "订单状态",
    "payer_identity": "付款人身份",
    "payment_status": "支付状态",
    "transaction_time": "交易时间",
    "amount": "订单金额",
    "merchant_identity": "商户主体",
    "transaction_id": "交易流水号",
    "merchant_order_id": "商户订单号",
    "transaction_scope": "交易范围",
    "commitment_amount": "承诺书金额",
    "subscriber_identity": "实名主体",
    "account_mobile": "手机号",
    "invoice_identity": "发票实名主体",
    "invoice_phone": "发票业务手机号",
    "number_status": "手机号状态",
    "ownership_proof": "手机号归属证明",
    "guardian_phone_holder": "申请监护人手机号归属",
}
CONSISTENCY_FIELD_REQUIRED_MATERIALS = {
    "guardian_identity": "请重新提交监护人清晰、完整且关键身份字段可读的身份证明。",
    "minor_identity": "请重新提交未成年人清晰、完整且关键身份字段可读的身份证明。",
    "payment_password_access": "请补充说明未成年人如何获得或得知支付密码。",
    "guardian_discovery_process": "请补充说明监护人如何、何时发现消费。",
    "relationship_link": "请补同一本户口本直接关系页、出生证明或法定监护证明。",
    "relationship_document_linkage": "请补同一本户口本直接关系页、出生证明或法定监护证明。",
    "explicit_relationship_entry": "请补明确记载亲子或合法监护关系的证明。",
    "applicant_guardian_role": "如申请人为兄弟姐妹等非法定监护人，不能直接代办；请补父母关系或合法监护证明。",
    "signature_presence": "请重新提交包含双方亲笔签名的退款承诺书。",
    "signature_method": "请重新提交包含双方亲笔签名的退款承诺书，电脑录入姓名不能替代签名。",
    "field_alignment": "请重新提交字段填写位置正确且未涂改的退款承诺书。",
    "commitment_content": "请重新提交包含完整承诺内容的退款承诺书。",
    "refund_scope": "请重新提交明确退款范围的完整退款承诺书。",
    "recipient_information": "请重新提交收款信息完整的退款承诺书。",
    "signed_date": "请重新提交填写签署日期的完整退款承诺书。",
    "account_bound_phone": "请重新提交填写账号绑定手机号的完整退款承诺书。",
    "account_nickname": "请重新提交填写账号昵称的完整退款承诺书。",
    "consumption_time_range": "请重新提交填写消费时间范围的完整退款承诺书。",
    "refund_amount": "请重新提交填写退款金额的完整退款承诺书。",
    "refund_method": "请重新提交填写退款方式的完整退款承诺书。",
    "payment_recipient": "请重新提交填写收款对象的完整退款承诺书。",
    "order_reference": "请补充可读的订单编号或订单引用。",
    "order_item_scope": "请补充可读的订单商品范围。",
    "item_quantity": "请补充可读的商品数量。",
    "order_status": "请补充可读的订单状态。",
    "payer_identity": "请补充可与申请材料比对的付款主体信息。",
    "payment_status": "请补充可读的支付状态。",
    "transaction_time": "请补充可读的交易时间。",
    "amount": "请补充可读的订单或支付金额。",
    "merchant_identity": "请补充可读的收款商户主体。",
    "transaction_id": "请补充可读的交易流水号。",
    "merchant_order_id": "请补充可读的商户订单号。",
    "transaction_scope": "请补充可读的交易商品或服务范围。",
    "commitment_amount": "请重新提交金额与订单可退款范围一致且未涂改的退款承诺书。",
    "invoice_phone": "请补充显示平台绑定业务手机号的运营商发票或完整开票视频。",
    "number_status": "请补充能够核验号码当前状态的运营商材料；如已注销，请补销户或原号码归属证明。",
    "ownership_proof": "请补充手机号实名归属材料；如已注销，请补销户或原号码归属证明；支付截图不能替代手机号实名归属材料。",
    "guardian_phone_holder": "手机号实名归属主体必须是本案申请监护人；请补充申请监护人的号码归属材料。",
}
CONSISTENCY_FIELD_GROUPS = {
    "guardian_identity": "identity_documents",
    "minor_identity": "identity_documents",
    "relationship_link": "guardian_relationship",
    "relationship_document_linkage": "guardian_relationship",
    "explicit_relationship_entry": "guardian_relationship",
    "applicant_guardian_role": "guardian_relationship",
    "signature_presence": "commitment_signatures",
    "signature_method": "commitment_signatures",
    "invoice_phone": "mobile_ownership",
    "number_status": "mobile_ownership",
    "ownership_proof": "mobile_ownership",
    "guardian_phone_holder": "mobile_ownership",
}
CONSISTENCY_GROUP_REQUIRED_MATERIALS = {
    "identity_documents": "请重新提交监护人与未成年人清晰、完整且关键身份字段可读的身份证明；错误打码或密集水印不得遮挡核验字段。",
    "guardian_relationship": "如申请人为兄弟姐妹等非法定监护人，不能直接代办；请补同一本户口本直接关系页、出生证明、父母关系或合法监护证明。",
    "commitment_signatures": "请重新提交包含双方亲笔签名的退款承诺书；电脑录入姓名不能替代签名。",
    "mobile_ownership": "请补充申请监护人的运营商手机号实名归属材料，需显示平台绑定业务手机号并可核验号码当前状态；如号码已注销，请补销户或原号码归属证明；支付截图不能替代手机号实名归属材料。",
}
CONSISTENCY_REQUIREMENTS = {
    "identity_age": "identity",
    "guardian_relationship": "relationship",
    "commitment_signatures": "commitment",
    "order_payment": "payment",
    "mobile_realname": "mobile_realname",
}
UNCERTAIN_ACTIONABLE_FIELDS = {
    "guardian_identity",
    "minor_identity",
    "relationship_link",
    "relationship_document_linkage",
    "explicit_relationship_entry",
    "signature_presence",
    "signature_method",
    "field_alignment",
    "commitment_content",
    "refund_scope",
    "recipient_information",
    "signed_date",
    "account_bound_phone",
    "account_nickname",
    "consumption_time_range",
    "refund_amount",
    "refund_method",
    "payment_recipient",
    "order_reference",
    "order_item_scope",
    "item_quantity",
    "order_status",
    "payer_identity",
    "payment_status",
    "transaction_time",
    "amount",
    "merchant_identity",
    "transaction_id",
    "merchant_order_id",
    "transaction_scope",
    "commitment_amount",
    "invoice_phone",
    "number_status",
    "ownership_proof",
    "guardian_phone_holder",
}
CORRECTABLE_COMMITMENT_FIELDS = {
    "signature_presence",
    "signature_method",
    "field_alignment",
    "commitment_content",
    "refund_scope",
    "recipient_information",
    "signed_date",
    "account_bound_phone",
    "account_nickname",
    "consumption_time_range",
    "refund_method",
}


def _required_materials(
    field_consistency: Dict[str, Any],
    missing_requirement_ids: set[str] | None = None,
) -> List[str]:
    required: Dict[str, str] = {}
    payment_process_fields = {"payment_password_access", "guardian_discovery_process"}
    missing_requirement_ids = missing_requirement_ids or set()
    for check in field_consistency.get("checks") or []:
        if CONSISTENCY_REQUIREMENTS.get(str(check.get("check_id") or "")) in missing_requirement_ids:
            continue
        for field in check.get("field_results") or []:
            field_name = str(field.get("field_name") or "")
            payment_process_required = field_name in payment_process_fields and check.get("low_age") is True
            if field_name in payment_process_fields and not payment_process_required:
                continue
            instruction = CONSISTENCY_FIELD_REQUIRED_MATERIALS.get(field_name)
            status = str(field.get("status") or "")
            has_evidence = bool(
                field.get("evidence_image_indices") or check.get("evidence_image_indices")
            )
            uncertain_actionable = (
                status == "not_assessed"
                and (payment_process_required or (field_name in UNCERTAIN_ACTIONABLE_FIELDS and has_evidence))
            ) or (
                status == "uncertain"
                and (
                    payment_process_required
                    or (field_name in UNCERTAIN_ACTIONABLE_FIELDS and has_evidence)
                )
            )
            if (
                (status == "mismatched" or uncertain_actionable)
                and instruction
            ):
                group = CONSISTENCY_FIELD_GROUPS.get(field_name, field_name)
                required.setdefault(group, CONSISTENCY_GROUP_REQUIRED_MATERIALS.get(group, instruction))
    return list(required.values())


def _consistency_message(check_id: str, status: str, field_rows: List[Dict[str, Any]]) -> str:
    if status != "mismatched":
        return CONSISTENCY_MESSAGES[status]
    mismatched = [item for item in field_rows if item.get("status") == "mismatched"]
    fields = "、".join(
        CONSISTENCY_FIELD_LABELS.get(str(item.get("field_name") or ""), str(item.get("field_name") or ""))
        for item in mismatched
    ) or "可见字段"
    images = sorted({
        int(index)
        for item in mismatched
        for index in item.get("evidence_image_indices") or []
        if str(index).isdigit()
    })
    image_text = f"请回看图片 {'、'.join(str(index) for index in images)}。" if images else "请回看对应图片。"
    return f"{CONSISTENCY_CHECK_LABELS.get(check_id, '所提供材料')}中以下可见字段互相对不上：{fields}。{image_text}"


def _chunks(items: Sequence[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
    return [list(items[index:index + size]) for index in range(0, len(items), size)]


def _safe_metric_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_metric_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0.0, parsed) if math.isfinite(parsed) else default


def _consistent_request_profile(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    profiles = [
        item.get("request_profile")
        for item in results
        if isinstance(item.get("request_profile"), dict)
        and item.get("request_profile")
    ]
    if not profiles:
        return {}
    comparable_keys = (
        "provider",
        "model",
        "thinking_level",
        "media_resolution",
        "max_output_tokens",
        "native_video_count",
        "sampling_fps",
        "transport",
    )
    first = {key: profiles[0].get(key) for key in comparable_keys}
    if any(
        {key: profile.get(key) for key in comparable_keys} != first
        for profile in profiles[1:]
    ):
        return {}
    return first


def _metric_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "model_calls": sum(_safe_metric_int(item.get("_model_calls"), 1) for item in items),
        "model_latency_seconds_sum": round(sum(_safe_metric_float(item.get("latency_seconds")) for item in items), 2),
        "input_tokens": sum(_safe_metric_int((item.get("usage") or {}).get("input_tokens")) for item in items),
        "output_tokens": sum(_safe_metric_int((item.get("usage") or {}).get("output_tokens")) for item in items),
        "total_tokens": sum(_safe_metric_int((item.get("usage") or {}).get("total_tokens")) for item in items),
        "estimated_usd": round(sum(_safe_metric_float((item.get("cost") or {}).get("estimated_usd")) for item in items), 6),
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
        key: sum(_safe_metric_int((item.get("usage") or {}).get(key)) for item in (first, second))
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
                sum(_safe_metric_float((item.get("cost") or {}).get("estimated_usd")) for item in (first, second)),
                6,
            )
        },
        "latency_seconds": round(sum(_safe_metric_float(item.get("latency_seconds")) for item in (first, second)), 2),
        "_model_calls": _safe_metric_int(first.get("_model_calls"), 1) + _safe_metric_int(second.get("_model_calls"), 1),
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


def _minor_refund_policy(case: Dict[str, Any]) -> Dict[str, Any]:
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
    editor_metadata = sorted(
        index for index, item in image_by_index.items() if item.get("editor_metadata_present") is True
    )
    suspected_editing = {
        int(item["image_index"])
        for item in observations
        if "suspected_editing" in (item.get("quality_issues") or [])
    }
    specific_editing = {
        int(item["image_index"])
        for item in observations
        if item.get("editing_evidence_codes")
    }
    corroborated_editing: set[int] = set()
    for check in field_consistency.get("checks") or []:
        if (
            str(check.get("tamper_risk") or "").lower() == "high"
            and "suspected_editing" in (check.get("risk_reason_codes") or [])
        ):
            corroborated_editing.update(
                int(index) for index in check.get("tamper_evidence_image_indices") or []
            )
    confirmed_editing = specific_editing.intersection(corroborated_editing)
    suspected_editing.update(specific_editing)
    suspected_editing.update(corroborated_editing)
    suspected_editing.update(editor_metadata)
    evidence_indices = sorted(suspected_editing)
    if confirmed_editing:
        severity = "critical"
        risk_score = min(0.94, 0.78 + 0.04 * len(evidence_indices))
        conclusion = "发现较强的疑似编辑或修改线索，请优先回看标红图片。"
    elif editor_metadata and set(evidence_indices) == set(editor_metadata):
        severity = "warning"
        risk_score = 0.42
        conclusion = "图片元数据显示曾由编辑软件处理；这不等同于内容造假，已标黄供人工抽检。"
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
        "editor_metadata_image_indices": editor_metadata,
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
            document_state = str(raw.get("document_state") or "filled")
            sop_eligibility = str(raw.get("sop_eligibility") or "valid")
            editing_evidence_codes = [
                str(value)
                for value in (raw.get("editing_evidence_codes") or raw.get("editing_evidence") or [])
                if str(value) in ALLOWED_EDITING_EVIDENCE_CODES
            ][:8]
            evidence_type = str(raw.get("order_payment_evidence_type") or "unknown")
            scope_coverage = str(raw.get("application_scope_coverage") or "unknown")
            observation = ReviewMinorMaterialObservation.model_validate({
                "image_index": image_index,
                "asset_ref": f"supplemental_image_{image_index}",
                "document_type": document_type,
                "document_types": document_types,
                "subject_role": role if role in ALLOWED_ROLES else "unknown",
                "document_side": side if side in ALLOWED_SIDES else "unknown",
                "issuing_country_or_region": raw.get("issuing_country_or_region") or "unknown",
                "readability": readability,
                "document_state": (
                    document_state if document_state in ALLOWED_DOCUMENT_STATES else "unknown"
                ),
                "sop_eligibility": (
                    sop_eligibility if sop_eligibility in ALLOWED_SOP_ELIGIBILITY else "unknown"
                ),
                "order_payment_evidence_type": (
                    evidence_type
                    if document_type == "order_payment_proof"
                    and evidence_type in ALLOWED_ORDER_PAYMENT_EVIDENCE_TYPES
                    else "unknown"
                ),
                "application_scope_coverage": (
                    scope_coverage
                    if document_type == "order_payment_proof"
                    and scope_coverage in ALLOWED_APPLICATION_SCOPE_COVERAGE
                    else "unknown"
                ),
                "document_box_2d": raw.get("document_box_2d") or [],
                "quality_issues": quality_issues,
                "editing_evidence_codes": editing_evidence_codes,
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


def _sop_usable(observation: Dict[str, Any]) -> bool:
    return (
        _usable(observation)
        and observation.get("document_state") == "filled"
        and observation.get("sop_eligibility") == "valid"
    )


def _sop_present(observation: Dict[str, Any]) -> bool:
    document_types = set(observation.get("document_types") or [])
    if "order_payment_proof" in document_types:
        return (
            observation.get("readability") in {"clear", "partial"}
            and observation.get("document_state") not in {"blank_template", "example"}
            and observation.get("sop_eligibility") != "invalid"
        )
    strict_mobile = bool(document_types.intersection({"mobile_realname_proof", "carrier_invoice"}))
    if strict_mobile:
        return (
            observation.get("readability") in {"clear", "partial"}
            and observation.get("document_state") == "filled"
            and observation.get("sop_eligibility") == "valid"
        )
    return (
        observation.get("readability") in {"clear", "partial"}
        and observation.get("document_state") not in {"blank_template", "example"}
        and observation.get("sop_eligibility") not in {"invalid", "supporting_only"}
    )


def _official_exception_proof(observation: Dict[str, Any], role: str) -> bool:
    return (
        set(observation.get("document_types") or []) == {"other"}
        and observation.get("subject_role") == role
        and observation.get("document_side") == "multiple"
        and observation.get("readability") in {"clear", "partial"}
        and observation.get("document_state") == "filled"
        and observation.get("sop_eligibility") == "valid"
    )


def _payment_process_statement(observation: Dict[str, Any]) -> bool:
    return (
        set(observation.get("document_types") or []) == {"other"}
        and observation.get("subject_role") == "not_applicable"
        and observation.get("document_side") == "page"
        and observation.get("readability") in {"clear", "partial"}
        and observation.get("document_state") == "filled"
        and observation.get("sop_eligibility") == "valid"
    )


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
    legal_guardianship = [
        item for item in observations if _official_exception_proof(item, "not_applicable")
    ]
    phone_exception = [item for item in observations if _official_exception_proof(item, "guardian")]
    relationship = candidates("household_register", "birth_certificate") + legal_guardianship
    minor_identity_replacement = [
        item for item in candidates("household_register", "birth_certificate")
        if "birth_certificate" in set(item.get("document_types") or [])
        or item.get("subject_role") == "minor"
    ]
    commitment = candidates("signed_commitment")
    payment = candidates("order_payment_proof")
    mobile_verified = candidates("mobile_realname_proof")
    mobile = candidates("mobile_realname_proof", "carrier_invoice") + phone_exception

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

    def has_both_sides(items: List[Dict[str, Any]], predicate: Callable[[Dict[str, Any]], bool]) -> bool:
        return {"front", "back"}.issubset({
            str(item.get("document_side") or "") for item in items if predicate(item)
        })

    guardian_identity_present = has_both_sides(guardian_identity, _sop_present)
    guardian_identity_usable = has_both_sides(guardian_identity, _sop_usable)
    minor_identity_present = has_both_sides(minor_identity, _sop_present) or any(
        _sop_present(item) for item in minor_identity_replacement
    )
    minor_identity_usable = has_both_sides(minor_identity, _sop_usable) or any(
        _sop_usable(item) for item in minor_identity_replacement
    )
    identity_present = guardian_identity_present and minor_identity_present
    identity_usable = guardian_identity_usable and minor_identity_usable
    identity_evidence = identity + minor_identity_replacement

    def payment_complete(predicate: Callable[[Dict[str, Any]], bool]) -> bool:
        evidence_types = {
            str(item.get("order_payment_evidence_type") or "unknown")
            for item in payment
            if predicate(item) and item.get("application_scope_coverage") == "complete"
        }
        return "combined" in evidence_types or {"order", "payment"}.issubset(evidence_types)

    rows = [
        (
            "identity",
            "未成年人及监护人身份证明",
            identity_present,
            identity_usable,
            bool(identity),
            identity_evidence,
            "监护人身份证及未成年人身份证均需正反面；未成年人无身份证时可由其户口本信息页或出生证明替代。",
            "needs_manual_consistency_check",
        ),
        (
            "relationship",
            "监护关系证明",
            any(_sop_present(item) for item in relationship),
            any(_sop_usable(item) for item in relationship),
            bool(relationship),
            relationship,
            "通常户口本相关页或出生证明二选一；如关系链不能闭合，可使用盖章的合法监护证明。",
            "needs_manual_consistency_check",
        ),
        (
            "commitment",
            "双方签字退款申请承诺书",
            any(_sop_present(item) for item in commitment),
            any(_sop_usable(item) for item in commitment),
            bool(commitment),
            commitment,
            "视觉初审只核对签名是否为亲笔书写及签署主体；法定真实性不由视觉模型单独认定。",
            "needs_manual_consistency_check",
        ),
        (
            "payment",
            "订单及支付凭证",
            payment_complete(_sop_present),
            payment_complete(_sop_usable),
            bool(payment),
            payment,
            "订单材料和支付材料均需提供，并逐笔或以可解释汇总覆盖申请范围；单独一类材料不能视为齐全。",
            "needs_business_system_check",
        ),
        (
            "mobile_realname",
            "绑定手机号实名归属证明",
            any(_sop_present(item) for item in mobile),
            any(_sop_usable(item) for item in mobile),
            bool(mobile),
            mobile,
            "运营商实名材料、主副卡关系证明或销户/原号码归属证明必须连接本案申请监护人与绑定号码；空白模板、示例图和普通账号页不能替代。",
            "confirmed_by_visual_category" if any(_sop_usable(item) for item in mobile_verified) else "needs_manual_consistency_check",
        ),
    ]
    return [
        {
            "requirement_id": requirement_id,
            "label": label,
            "status": status(present),
            "quality_status": quality_status(usable, observed),
            "evidence_refs": [item["asset_ref"] for item in evidence],
            "evidence_image_indices": [item["image_index"] for item in evidence],
            "rule_note": note,
            "validation_status": (
                validation_status if present
                else "needs_manual_quality_check" if observed
                else "not_validated"
            ),
        }
        for requirement_id, label, present, usable, observed, evidence, note, validation_status in rows
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
    legal_guardianship = [
        int(item["image_index"])
        for item in observations
        if _official_exception_proof(item, "not_applicable")
    ]
    commitment = indices("signed_commitment")
    payment = indices("order_payment_proof")
    mobile = indices("mobile_realname_proof", "carrier_invoice")
    payment_process_statement = [
        int(item["image_index"])
        for item in observations
        if _payment_process_statement(item)
    ]
    phone_exception = [
        int(item["image_index"])
        for item in observations
        if _official_exception_proof(item, "guardian")
    ]
    relationship += legal_guardianship
    mobile += phone_exception
    plans = {
        "identity_age": guardian + guardian_passport + minor + minor_passport + relationship + payment_process_statement,
        "guardian_relationship": guardian_passport + minor_passport + relationship,
        "commitment_signatures": guardian + minor + relationship + commitment,
        "order_payment": guardian + payment + commitment,
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
            (clear_guardian_passport or guardian_passport)[:1]
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


def _date_value(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _age_facts(birth_date: date | None, assessment_date: date | None) -> tuple[str, bool | None, bool | None]:
    if birth_date is None or assessment_date is None or birth_date > assessment_date:
        return "unknown", None, None
    years = assessment_date.year - birth_date.year - (
        (assessment_date.month, assessment_date.day) < (birth_date.month, birth_date.day)
    )
    if years < 10:
        return "under_10", True, years < 9
    if years < 18:
        return "10_to_17", False, False
    return "18_or_over", False, False


def _normalize_consistency_checks(
    results: List[Dict[str, Any]] | None,
    failures: List[Dict[str, Any]] | None,
    assessment_date: Any = None,
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
        payment_capability_risks = []
        low_age_values: List[bool] = []
        under_nine_values: List[bool] = []
        age_confidence_values: List[str] = []
        age_band_values: List[str] = []
        relationship_evidence_values: List[str] = []
        minor_birth_dates: List[date] = []
        same_household_group_statuses: List[str] = []
        risk_reason_codes = set()
        tamper_evidence_indices: set[int] = set()
        for result in check_results:
            parsed = result.get("parsed") or {}
            raw = parsed.get("consistency_check") or {}
            birth_date = _date_value(raw.get("minor_birth_date_iso"))
            if birth_date is not None:
                minor_birth_dates.append(birth_date)
            relationship_evidence_type = str(raw.get("relationship_evidence_type") or "uncertain")
            relationship_evidence_values.append(
                relationship_evidence_type
                if relationship_evidence_type in RELATIONSHIP_EVIDENCE_TYPES
                else "uncertain"
            )
            payment_capability_risk = str(raw.get("payment_capability_risk") or "unknown")
            payment_capability_risks.append(
                payment_capability_risk if payment_capability_risk in PAYMENT_CAPABILITY_RISKS else "unknown"
            )
            if isinstance(raw.get("low_age"), bool):
                low_age_values.append(raw["low_age"])
            if isinstance(raw.get("under_nine"), bool):
                under_nine_values.append(raw["under_nine"])
            age_confidence = str(raw.get("age_confidence") or "unknown")
            age_confidence_values.append(
                age_confidence if age_confidence in AGE_CONFIDENCE else "unknown"
            )
            age_band = str(raw.get("age_band") or "unknown")
            if age_band in {"under_10", "10_to_17", "18_or_over", "unknown"}:
                age_band_values.append(age_band)
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
            if relationship_evidence_type == "same_household_direct_link":
                role_groups: Dict[str, set[str]] = {"guardian": set(), "minor": set()}
                for group in raw.get("relationship_document_groups") or []:
                    if not isinstance(group, dict) or group.get("document_type") != "household_register":
                        continue
                    try:
                        image_index = int(group.get("image_index"))
                    except (TypeError, ValueError):
                        continue
                    role = str(group.get("subject_role") or "unknown")
                    document_group = str(group.get("document_group") or "uncertain")
                    if image_index not in expected_indices or role not in role_groups or document_group not in {
                        "group_1", "group_2", "group_3", "group_4",
                    }:
                        continue
                    role_groups[role].add(document_group)
                if role_groups["guardian"] and role_groups["minor"]:
                    same_household_group_statuses.append(
                        "matched" if role_groups["guardian"] & role_groups["minor"] else "mismatched"
                    )
                else:
                    same_household_group_statuses.append("uncertain")
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
            tamper_evidence_indices.update(
                int(value)
                for value in raw.get("tamper_evidence_image_indices") or []
                if str(value).isdigit() and int(value) in expected_indices
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
        relationship_evidence_type = "not_applicable"
        if check_id == "guardian_relationship":
            bridge_types = {
                value for value in relationship_evidence_values
                if value in {
                    "same_household_direct_link", "birth_certificate", "legal_guardianship_proof",
                }
            }
            if len(bridge_types) == 1:
                relationship_evidence_type = next(iter(bridge_types))
            elif bridge_types:
                relationship_evidence_type = "uncertain"
            elif "separate_household_books_without_bridge" in relationship_evidence_values:
                relationship_evidence_type = "separate_household_books_without_bridge"
            else:
                relationship_evidence_type = "uncertain"
            fields_by_name = {item["field_name"]: item for item in field_rows}
            valid_bridge = relationship_evidence_type in {
                "same_household_direct_link", "birth_certificate", "legal_guardianship_proof",
            }
            bridge_fields_matched = all(
                (fields_by_name.get(field_name) or {}).get("status") == "matched"
                for field_name in ("relationship_document_linkage", "explicit_relationship_entry")
            )
            if valid_bridge and not bridge_fields_matched:
                relationship_evidence_type = (
                    "separate_household_books_without_bridge"
                    if relationship_evidence_type == "same_household_direct_link"
                    and (fields_by_name.get("relationship_document_linkage") or {}).get("status") == "mismatched"
                    else "uncertain"
                )
                for field_name in (
                    "relationship_document_linkage", "explicit_relationship_entry", "relationship_link",
                ):
                    if field_name in fields_by_name:
                        fields_by_name[field_name]["status"] = "uncertain"
            if relationship_evidence_type == "same_household_direct_link" and (
                len(same_household_group_statuses) != len(check_results)
                or set(same_household_group_statuses) != {"matched"}
            ):
                relationship_evidence_type = (
                    "separate_household_books_without_bridge"
                    if "mismatched" in same_household_group_statuses else "uncertain"
                )
                for field_name in ("relationship_document_linkage", "relationship_link"):
                    if field_name in fields_by_name:
                        fields_by_name[field_name]["status"] = "uncertain"
            if relationship_evidence_type == "separate_household_books_without_bridge":
                for field_name in (
                    "relationship_document_linkage", "explicit_relationship_entry", "relationship_link",
                ):
                    if field_name in fields_by_name:
                        fields_by_name[field_name]["status"] = "uncertain"
                risk_reason_codes.discard("conflicting_fields")
                risk_reason_codes.add("evidence_gap")
            if relationship_evidence_type not in {
                "same_household_direct_link", "birth_certificate", "legal_guardianship_proof",
            }:
                for field in field_rows:
                    if field["field_name"] == "relationship_link":
                        field["status"] = "uncertain"
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
        age_identity_matched = all(
            next(
                (item.get("status") for item in field_rows if item.get("field_name") == field_name),
                "not_assessed",
            ) == "matched"
            for field_name in ("minor_identity", "age_eligibility")
        )
        trusted_birth_date = (
            minor_birth_dates[0]
            if minor_birth_dates
            and len(minor_birth_dates) == len(check_results)
            and len(set(minor_birth_dates)) == 1
            else None
        )
        age_band, low_age, under_nine = _age_facts(
            trusted_birth_date if coverage_ok and age_identity_matched else None,
            _date_value(assessment_date),
        )
        age_confidence = "high" if age_band != "unknown" else "unknown"
        payment_process_required = low_age is True
        decision_fields = field_rows if payment_process_required else [
            item for item in field_rows
            if item.get("field_name") not in {"payment_password_access", "guardian_discovery_process"}
        ]
        field_statuses = {item["status"] for item in decision_fields}
        if "mismatched" in field_statuses:
            status = "mismatched"
        elif field_statuses == {"matched"} and tamper_risk == "low" and coverage_ok and not quality_uncertain_indices:
            status = "matched"
        else:
            status = "uncertain"
        normalized[check_id] = {
            "check_id": check_id,
            "relationship_evidence_type": relationship_evidence_type,
            "status": status,
            "message": _consistency_message(check_id, status, field_rows),
            "field_results": field_rows,
            "tamper_risk": tamper_risk,
            "risk_reason_codes": sorted(risk_reason_codes),
            "evidence_image_indices": sorted(required_indices),
            "tamper_evidence_image_indices": sorted(tamper_evidence_indices),
            "coverage_complete": coverage_ok,
            "segment_count": len(check_results),
            "age_band": age_band,
            "low_age": low_age,
            "under_nine": under_nine,
            "age_confidence": age_confidence,
            "payment_capability_risk": (
                "high" if (
                    low_age is True
                    and any(
                        item.get("field_name") in {"payment_password_access", "guardian_discovery_process"}
                        and item.get("status") != "matched"
                        for item in field_rows
                    )
                ) or (under_nine is True and age_confidence == "high")
                else "none" if under_nine is False or age_confidence in {"high", "low"}
                else "unknown"
            ),
        }
    checks = []
    for check_id in CONSISTENCY_FIELDS:
        checks.append(normalized.get(check_id, {
            "check_id": check_id,
            "relationship_evidence_type": "uncertain" if check_id == "guardian_relationship" else "not_applicable",
            "status": "not_assessed",
            "message": CONSISTENCY_MESSAGES["not_assessed"],
            "field_results": [],
            "tamper_risk": "uncertain",
            "risk_reason_codes": ["evidence_gap"] if check_id in failed_ids else [],
            "evidence_image_indices": [],
            "tamper_evidence_image_indices": [],
            "age_band": "unknown",
            "low_age": None,
            "under_nine": None,
            "age_confidence": "unknown",
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
    field_consistency = _normalize_consistency_checks(
        consistency_results,
        consistency_failures,
        (case.get("order_context") or {}).get("assessment_at")
        or (case.get("order_context") or {}).get("created_at"),
    )
    consistency_by_id = {item["check_id"]: item for item in field_consistency["checks"]}
    relationship_check = consistency_by_id.get("guardian_relationship") or {}
    commitment_check = consistency_by_id.get("commitment_signatures") or {}
    guardian_signer = next(
        (
            field for field in commitment_check.get("field_results") or []
            if field.get("field_name") == "guardian_signer"
        ),
        {},
    )
    applicant_guardian_role = next(
        (
            field for field in relationship_check.get("field_results") or []
            if field.get("field_name") == "applicant_guardian_role"
        ),
        {},
    )
    if (
        relationship_check.get("status") == "matched"
        and guardian_signer.get("status") == "mismatched"
        and applicant_guardian_role.get("status") == "matched"
    ):
        applicant_guardian_role["status"] = "mismatched"
        relationship_check["status"] = "mismatched"
        relationship_check["message"] = "关系证明中的法定监护人与承诺书申请监护人不一致。"
        relationship_check["risk_reason_codes"] = sorted({
            *(relationship_check.get("risk_reason_codes") or []),
            "conflicting_fields",
        })
        field_consistency["verdict"] = "mismatched"
        field_consistency["message"] = CONSISTENCY_MESSAGES["mismatched"]
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

    identity_check = consistency_by_id.get("identity_age") or {}
    unreadable_identity = any(
        field.get("field_name") in {"guardian_identity", "minor_identity"}
        and field.get("status") in {"uncertain", "not_assessed"}
        and field.get("visibility") in {"masked", "unreadable", "partial"}
        for field in identity_check.get("field_results") or []
    )
    if unreadable_identity:
        identity_item = next(item for item in checklist if item["requirement_id"] == "identity")
        identity_item["quality_status"] = "needs_manual_confirmation"
        identity_item["validation_status"] = "visual_identity_fields_unreadable"

    relationship_link = next(
        (
            field for field in relationship_check.get("field_results") or []
            if field.get("field_name") == "relationship_link"
        ),
        {},
    )
    if coverage_complete and relationship_link.get("status") in {"uncertain", "not_assessed"}:
        relationship_item = next(item for item in checklist if item["requirement_id"] == "relationship")
        relationship_item.update(
            {
                "status": "not_observed_after_full_scan",
                "quality_status": "needs_manual_confirmation",
                "validation_status": "visual_relationship_link_unresolved",
                "rule_note": "现有材料未建立申请人与未成年人之间的直接亲子或监护关系，请补同一本户口本直接关系页、出生证明或法定监护证明。",
            }
        )

    missing_requirement_ids = {
        item["requirement_id"]
        for item in checklist
        if item["status"] == "not_observed_after_full_scan"
    }
    required_materials = _required_materials(field_consistency, missing_requirement_ids)

    present_count = sum(1 for item in checklist if item["status"] == "present")
    uncertain_count = sum(1 for item in checklist if item.get("quality_status") == "needs_manual_confirmation")
    not_observed = [item for item in checklist if item["status"] == "not_observed_after_full_scan"]
    payment_process_statuses = {
        str(field.get("field_name") or ""): str(field.get("status") or "not_assessed")
        for field in identity_check.get("field_results") or []
        if str(field.get("field_name") or "") in {"payment_password_access", "guardian_discovery_process"}
    }
    payment_process_matched = (
        len(payment_process_statuses) == 2
        and all(status == "matched" for status in payment_process_statuses.values())
    )
    low_age = identity_check.get("low_age") if isinstance(identity_check.get("low_age"), bool) else None
    under_nine = identity_check.get("under_nine") if isinstance(identity_check.get("under_nine"), bool) else None
    age_confidence = str(identity_check.get("age_confidence") or "unknown")
    under_nine_high_confidence = under_nine is True and age_confidence == "high"
    payment_process_gap = low_age is True and not payment_process_matched
    payment_process_evidence_status = "matched" if payment_process_matched else "unresolved"
    payment_capability_risk = {
        "level": "high" if payment_process_gap or under_nine_high_confidence else "none",
        "low_age": low_age,
        "under_nine": under_nine,
        "age_confidence": age_confidence,
        "process_evidence_status": payment_process_evidence_status,
        "requires_review": under_nine_high_confidence,
        "requires_more_material": payment_process_gap,
        "effect": (
            "低于 10 周岁，支付密码来源或监护发现过程尚未闭环，需定向补充；同时年龄判断为未满 9 周岁高置信，请授权人员额外重点核验，年龄关注不覆盖材料事实。"
            if payment_process_gap and under_nine_high_confidence
            else "低于 10 周岁，支付密码来源或监护发现过程尚未闭环，需定向补充对应过程说明。"
            if payment_process_gap
            else "申请时未满 9 周岁且年龄判断为高置信，请授权人员额外重点核验；年龄关注不覆盖五类材料事实，也不决定退款或支持结论。"
            if under_nine_high_confidence
            else ""
        ),
        "evidence_image_indices": identity_check.get("evidence_image_indices") or [],
    }

    policy = _minor_refund_policy(case)
    authoritative_required = policy["authoritative_verification"] == "required"
    authenticity = _authenticity_assessment(case, observations, field_consistency)
    authenticity_blocked = bool(authenticity["blocks_visual_precheck"])
    commitment_completeness_gap = any(
        field.get("field_name") in {"commitment_content", "refund_scope", "recipient_information", "signed_date"}
        and field.get("status") in {"uncertain", "not_assessed"}
        for field in (consistency_by_id.get("commitment_signatures") or {}).get("field_results") or []
    )
    guardian_phone_holder_gap = any(
        field.get("field_name") == "guardian_phone_holder"
        and field.get("status") in {"uncertain", "not_assessed"}
        for field in (consistency_by_id.get("mobile_realname") or {}).get("field_results") or []
    )
    mismatched_fields = {
        (str(check.get("check_id") or ""), str(field.get("field_name") or ""))
        for check in field_consistency.get("checks") or []
        for field in check.get("field_results") or []
        if field.get("status") == "mismatched"
    }
    correctable_commitment_mismatch = bool(mismatched_fields) and all(
        check_id == "commitment_signatures" and field_name in CORRECTABLE_COMMITMENT_FIELDS
        for check_id, field_name in mismatched_fields
    )
    manual_field_conflict = (
        field_consistency["verdict"] == "mismatched"
        and not correctable_commitment_mismatch
    )

    if coverage_complete and manual_field_conflict:
        predicted_label = "review"
        decision = "manual_review"
        system_yes_no = "REVIEW"
        confidence = 0.84
        readiness = "visual_conflict_requires_review"
        visual_precheck_status = "needs_review"
        conclusion = "可见字段存在明确冲突，需授权人员回看标红图片并决定补正路径；本轮只形成材料人工核验建议，不形成退款业务结论。"
    elif (
        coverage_complete
        and present_count == len(checklist)
        and (commitment_completeness_gap or correctable_commitment_mismatch)
    ):
        predicted_label = "review"
        decision = "request_more_material"
        system_yes_no = "REVIEW"
        confidence = 0.72
        readiness = "needs_complete_commitment"
        visual_precheck_status = "incomplete"
        conclusion = "退款承诺书的承诺内容、退款范围、收款信息或签署日期尚未完整确认；请补交字段完整的承诺书。"
    elif coverage_complete and present_count == len(checklist) and guardian_phone_holder_gap:
        predicted_label = "review"
        decision = "request_more_material"
        system_yes_no = "REVIEW"
        confidence = 0.72
        readiness = "needs_guardian_phone_ownership"
        visual_precheck_status = "incomplete"
        conclusion = "手机号实名材料尚未确认号码属于本案申请监护人；请补充申请监护人的号码归属材料。"
    elif coverage_complete and present_count == len(checklist) and required_materials:
        predicted_label = "review"
        decision = "request_more_material"
        system_yes_no = "REVIEW"
        confidence = 0.72
        readiness = "needs_specific_material_correction"
        visual_precheck_status = "incomplete"
        conclusion = "五类材料类别已识别，但条件性过程说明或必审字段尚未闭环；请只补充材料缺口清单点名的内容。"
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
    elif not_observed:
        predicted_label = "review"
        decision = "request_more_material"
        system_yes_no = "REVIEW"
        confidence = 0.66
        readiness = "needs_specific_material"
        visual_precheck_status = "incomplete"
        missing_labels = "、".join(item["label"] for item in not_observed)
        conclusion = f"全量图片已处理，当前缺少可按 SOP 采信的{missing_labels}；请只补充这些材料。"
        if required_materials:
            conclusion += " 已提交材料另有字段待补正，详见材料缺口清单。"
    elif (
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
    elif coverage_complete and present_count == len(checklist):
        predicted_label = "positive"
        decision = "visual_precheck_passed_with_warnings"
        system_yes_no = "YES"
        confidence = 0.78
        readiness = "ready_with_visual_warnings"
        visual_precheck_status = "passed"
        conclusion = "五类材料已齐全，未发现明确字段冲突或阻断性修改风险；可按甲方现行流程继续，标黄项仅供抽检。"
    else:
        predicted_label = "review"
        decision = "manual_review"
        system_yes_no = "REVIEW"
        confidence = round(min(0.69, 0.45 + 0.04 * present_count + 0.02 * uncertain_count), 2)
        readiness = "incomplete_processing" if not coverage_complete else "manual_consistency_review"
        visual_precheck_status = "incomplete"
        conclusion = "材料包未完成全量可靠识别或仍有角色/清晰度待确认，不能据此声称用户缺少材料。"

    material_gaps = [
        item["rule_note"]
        if item["requirement_id"] == "relationship"
        else (
            "请补充申请监护人的运营商绑定手机号实名归属证明，需显示平台绑定业务手机号；如号码已注销，请补销户或原号码归属证明；支付截图不能替代手机号实名归属材料。"
            if item["requirement_id"] == "mobile_realname"
            else f"请补充：{item['label']}。已识别的空白模板、示例图或辅助截图不能替代该必交材料。"
        )
        for item in not_observed
    ]
    material_gaps.extend(item for item in required_materials if item not in material_gaps)
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
            and not correctable_commitment_mismatch
            or field_consistency["status"] in {"degraded", "not_completed"}
            or authenticity_blocked
            or authoritative_required
            or under_nine_high_confidence
        )
    )
    business_follow_up_reason = (
        "当前请求已完成结构修复和逐张恢复；仍未覆盖时可受控重跑整案，可能重复模型成本，且不要求用户补件。"
        if technical_processing_incomplete
        else "Agent只给资料初审建议，不执行退款或拒绝；甲方可按当前流程继续、抽检或要求用户补充指定材料。"
    )
    if technical_processing_incomplete:
        next_step = "请受控重跑整案；全部资料处理完成后再生成审核建议，达到重试上限后再转授权人员。"
    elif manual_field_conflict:
        next_step = "请授权人员回看报告中标红的冲突图片，并按材料缺口清单决定补正路径。"
        if payment_process_gap:
            next_step += " 同时补充支付密码来源和监护发现过程说明。"
    elif payment_process_gap and under_nine_high_confidence:
        next_step = "请先定向补充支付密码来源和监护发现过程；同时由授权人员重点核验独立支付能力，年龄关注不得覆盖五类材料事实。"
    elif payment_process_gap:
        next_step = "请只补充未成年人如何获得或得知支付密码，以及监护人如何、何时发现消费的说明。"
    elif under_nine_high_confidence:
        next_step = "申请时未满 9 周岁且年龄判断为高置信；请授权人员额外重点核验独立支付能力，年龄关注不得改变五类材料事实结论。"
    elif predicted_label == "positive":
        next_step = ""
    elif authenticity_blocked:
        next_step = "请优先打开报告中标红的疑似编辑图片；确认原图无误后可重新送审。"
    elif authoritative_required:
        next_step = "当前工单显式启用了严格验真，请完成甲方配置的核验步骤；没有可用接口时请改回默认策略。"
    else:
        next_step = (
            "请用户只补充报告点名的材料；不要重复要求已经通过初审的资料。"
            if not_observed else
            "请回看报告中标黄的字段或图片；能确认一致时按现行流程继续，不能确认时只补对应材料。"
        )

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
            "message": item.get("message") or "可见字段存在冲突，请回看对应图片。",
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
        if authenticity["severity"] == "critical"
    ]
    assessment = {
        "sop_version": "minor_refund_2_0",
        "conclusion": conclusion,
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
        "required_materials": material_gaps,
        "authenticity_assessment": authenticity,
        "payment_capability_risk": payment_capability_risk,
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
    effective_workers = max(1, min(_safe_metric_int(workers, 1), 8))
    images = list(case.get("supplemental_images") or [])
    frames = list(case.get("frames") or [])
    image_batch_size = max(1, min(_safe_metric_int(os.getenv("REVIEW_MINOR_IMAGE_BATCH_SIZE", "4"), 4), 6))
    frame_batch_size = max(1, min(_safe_metric_int(case.get("model_frames_per_call"), 24), 24))
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
    detail_crop_count = 0
    image_metric_results: List[Dict[str, Any]] = []
    video_metric_results: List[Dict[str, Any]] = []
    consistency_metric_results: List[Dict[str, Any]] = []
    recovery_call_budget = max(
        0,
        min(_safe_metric_int(os.getenv("REVIEW_MINOR_RECOVERY_CALL_BUDGET", "16"), 16), 32),
    )
    recovery_calls_used = 0
    recovery_lock = Lock()

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

        def invoke_repair(retry_case: Dict[str, Any]) -> Dict[str, Any] | None:
            nonlocal recovery_calls_used
            with recovery_lock:
                if recovery_calls_used >= recovery_call_budget:
                    return None
                recovery_calls_used += 1
            try:
                return invoke(retry_case)
            except Exception as exc:
                return {
                    "status": "failed",
                    "error": sanitize_error_text(exc, 500),
                    "_model_calls": 1,
                }

        if kind == "image" and result.get("status") == "success":
            try:
                schema_retries = int(os.getenv("REVIEW_MINOR_SCHEMA_RETRIES", "1") or 1)
            except ValueError:
                schema_retries = 1
            schema_retries = max(0, min(schema_retries, 1))
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
                repair_result = invoke_repair(retry_case)
                if repair_result is None:
                    break
                result = _merge_semantic_attempts(result, repair_result)
            missing = sorted(set(indices) - _result_observed_indices(result))
            images_by_index = {int(item["image_index"]): item for item in batch}
            for image_index in missing:
                for recovery_index in range(1):
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
                    repair_result = invoke_repair(retry_case)
                    if repair_result is None:
                        break
                    result = _merge_semantic_attempts(result, repair_result)
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
                    completed.append((kind, index, [], {"status": "failed", "error": sanitize_error_text(exc, 500), "_model_calls": 1}))
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
    if preliminary_assessment["coverage_complete"]:
        material_inventory = preliminary_assessment["material_inventory"]
        inventory_by_index = {
            int(item["image_index"]): item
            for item in material_inventory
            if str(item.get("image_index") or "").isdigit()
        }
        selected_image_indices = {
            int(item["image_index"])
            for job in _consistency_image_jobs(material_inventory, images)
            for item in job["selected"]
        }
        detail_images = []
        for image in images:
            image_index = int(image.get("image_index") or 0)
            if image_index not in selected_image_indices:
                detail_images.append(image)
                continue
            observation = inventory_by_index.get(image_index) or {}
            cropped = prepare_image_detail_crop(
                image,
                observation.get("document_box_2d") or [],
                Path(image.get("api_path") or image.get("path") or ".").parent / "detail_crops",
            )
            detail_crop_count += int(bool(cropped.get("detail_crop_box_2d")))
            detail_images.append(cropped)
        consistency_jobs = _consistency_image_jobs(material_inventory, detail_images)

        def review_consistency(job: Dict[str, Any]) -> Dict[str, Any]:
            check_id = str(job["check_id"])
            selected = list(job["selected"])
            selected_by_index = {int(item["image_index"]): item for item in selected}
            check_case = dict(case)
            structured = dict(case.get("structured_business_context") or {})
            expected_indices = [int(item["image_index"]) for item in selected]
            structured["analysis_mode"] = "minor_material_consistency"
            structured["minor_consistency_check"] = {
                "check_id": check_id,
                "segment_index": job["segment_index"],
                "segment_total": job["segment_total"],
                "expected_image_indices": expected_indices,
                "material_context": [
                    {
                        key: inventory_by_index[image_index].get(key)
                        for key in ("image_index", "document_type", "subject_role", "document_side", "readability")
                    } | {
                        "detail_crop_applied": bool(
                            selected_by_index.get(image_index, {}).get("detail_crop_box_2d")
                        ),
                    }
                    for image_index in expected_indices
                    if image_index in inventory_by_index
                ],
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
                    result = {"status": "failed", "error": sanitize_error_text(exc, 500), "_model_calls": 1}
                    consistency_metric_results.append(result)
                    consistency_failures.append({
                        "check_id": check_id,
                        "segment_index": job["segment_index"],
                        "error": sanitize_error_text(exc, 500),
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
        key: sum(_safe_metric_int((item.get("usage") or {}).get(key)) for item in billed_results)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    cost = round(sum(_safe_metric_float((item.get("cost") or {}).get("estimated_usd")) for item in billed_results), 6)
    cost_observability = summarize_cost_observability(billed_results)
    failed_results = [item for item in billed_results if item.get("status") != "success"]
    first_status_code = next((item.get("status_code") for item in failed_results if item.get("status_code")), None)
    failure_types = {str(item.get("error_type") or "") for item in failed_results}
    failure_types.discard("")
    channel_route_attempts = [
        dict(attempt)
        for item in billed_results
        for attempt in (item.get("_channel_route_attempts") or [])
        if isinstance(attempt, dict)
    ]
    return {
        "status": "success" if image_rows or not images else "failed",
        "error": "minor_material_all_image_batches_failed" if images and not image_rows else "",
        "status_code": first_status_code,
        "error_type": next(iter(failure_types)) if len(failure_types) == 1 else "",
        "_channel_route_attempts": channel_route_attempts,
        "latency_seconds": round(time.time() - wall_started, 2),
        "model_latency_seconds_sum": round(sum(_safe_metric_float(item.get("latency_seconds")) for item in billed_results), 2),
        "usage": usage,
        "cost": {"estimated_usd": cost},
        "request_profile": _consistent_request_profile(billed_results),
        **cost_observability,
        "parsed": parsed,
        "chunking": {
            "effective_workers": effective_workers,
            "segment_count": len(image_batches) + len(frame_batches) + len(consistency_jobs),
            "frames_per_segment": frame_batch_size,
            "total_frames": len(frames),
            "total_model_calls": sum(_safe_metric_int(item.get("_model_calls"), 1) for item in billed_results),
            "document_detail_crop_count": detail_crop_count,
            "recovery_call_budget": recovery_call_budget,
            "recovery_calls_used": recovery_calls_used,
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
