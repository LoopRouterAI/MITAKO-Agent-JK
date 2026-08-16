# -*- coding: utf-8 -*-
"""将工单清单与模型语义事实合成为场景专属材料齐全性。"""
from __future__ import annotations

import hashlib
import math
import warnings
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from poc.visual_review_poc.media_preflight import build_media_preflight_plan


VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
DOCUMENT_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".json"}
PRODUCT_OPENING_REQUIREMENTS = {
    "sealed_start", "waybill_visible", "continuous",
    "claimed_item_presentation", "issue_assessable",
}
MINOR_REQUIRED_MATERIALS = {
    "identity": "未成年人及监护人身份证明",
    "relationship": "监护关系证明",
    "commitment": "双方签字退款申请承诺书",
    "payment": "订单或支付凭证",
    "mobile_realname": "绑定手机号实名归属证明",
}
MINOR_PAYMENT_PROCESS_REQUIREMENTS = {
    "payment_password_access": (
        "payment_password_access_explanation",
        "未成年人如何获得或得知支付密码的说明",
    ),
    "guardian_discovery_process": (
        "guardian_discovery_process_explanation",
        "监护人如何、何时发现消费的说明",
    ),
}


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _confidence(*values: Any) -> Optional[float]:
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(parsed):
            return round(max(0.0, min(parsed, 1.0)), 4)
    return None


def _media_kind(asset: Dict[str, Any]) -> str:
    mime = str(asset.get("mime_type") or "").lower()
    suffix = Path(str(asset.get("original_name") or asset.get("stored_name") or "")).suffix.lower()
    if mime.startswith("video/") or suffix in VIDEO_SUFFIXES:
        return "video"
    if mime.startswith("image/") or suffix in IMAGE_SUFFIXES:
        return "image"
    if mime.startswith(("application/", "text/")) or suffix in DOCUMENT_SUFFIXES:
        return "document"
    return "other"


def build_review_inventory(
    job: Dict[str, Any],
    *,
    media_forensics: Optional[Dict[str, Any]] = None,
    job_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """盘点实际收到的资产；声明字段不等同于模型确认的素材语义。"""
    assets = [item for item in job.get("assets") or [] if isinstance(item, dict)]
    forensic_assets = {
        str(item.get("asset_id") or ""): item
        for item in _dict(media_forensics).get("assets") or []
        if isinstance(item, dict) and str(item.get("asset_id") or "")
    }
    counts = {"video": 0, "image": 0, "document": 0, "other": 0}
    rows = []
    first_asset_by_sha256: Dict[str, str] = {}
    duplicate_asset_count = 0
    for asset in assets:
        kind = _media_kind(asset)
        forensic = _dict(forensic_assets.get(str(asset.get("asset_id") or "")))
        stored_name = str(asset.get("stored_name") or "")
        path = job_dir / stored_name if job_dir is not None and stored_name else None
        technical_status = str(forensic.get("status") or "not_assessed")
        page_count = None
        pixel_size = None
        technical_reason = ""
        sha256 = str(asset.get("sha256") or "").strip().lower()
        if not sha256 and path is not None and path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            sha256 = digest.hexdigest()
        duplicate_of = first_asset_by_sha256.get(sha256) if sha256 else None
        if sha256 and duplicate_of is None:
            first_asset_by_sha256[sha256] = str(asset.get("asset_id") or "")
        elif duplicate_of is not None:
            duplicate_asset_count += 1
        if path is not None and kind == "image":
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(path) as image:
                        width, height = image.size
                        if width <= 0 or height <= 0 or width * height > 40_000_000:
                            raise ValueError("image_pixel_limit")
                        image.verify()
                technical_status = "completed"
                pixel_size = {"width": width, "height": height}
            except (
                FileNotFoundError,
                Image.DecompressionBombError,
                Image.DecompressionBombWarning,
                UnidentifiedImageError,
                OSError,
                ValueError,
                MemoryError,
            ):
                technical_status = "failed"
                technical_reason = "image_decode_failed"
        elif path is not None and path.suffix.lower() == ".pdf":
            try:
                page_count = len(PdfReader(str(path), strict=True).pages)
                if page_count <= 0:
                    raise ValueError("pdf_has_no_pages")
                technical_status = "completed"
            except (FileNotFoundError, OSError, ValueError, PdfReadError):
                technical_status = "failed"
                technical_reason = "pdf_decode_failed"
        counts[kind] += 1
        rows.append({
            "asset_id": str(asset.get("asset_id") or ""),
            "media_kind": kind,
            "mime_type": str(asset.get("mime_type") or "application/octet-stream"),
            "size": max(0, int(asset.get("size") or 0)),
            "sha256": sha256,
            "duplicate_of": duplicate_of,
            "source": str(asset.get("source") or "user_upload"),
            "declared_fields": [str(item) for item in asset.get("fields") or [] if str(item)],
            "scan_status": "received",
            "technical_status": technical_status,
            "technical_reason": technical_reason,
            "duration_seconds": _dict(forensic.get("container")).get("duration_seconds"),
            "page_count": page_count,
            "pixel_size": pixel_size,
        })
    metadata = _dict(job.get("metadata"))
    baseline = _dict(metadata.get("fulfillment_baseline"))
    order_items = [item for item in metadata.get("order_items") or [] if isinstance(item, dict)]
    logistics = _dict(metadata.get("logistics"))
    return {
        "scenario": str(job.get("scenario") or metadata.get("scenario") or ""),
        "received_asset_count": len(rows),
        "unique_asset_count": len(rows) - duplicate_asset_count,
        "duplicate_asset_count": duplicate_asset_count,
        "media_counts": counts,
        "assets": rows,
        "business_inputs": {
            "customer_claim_present": bool(str(metadata.get("customer_claim") or "").strip()),
            "conversation_history_present": bool(metadata.get("conversation_history")),
            "order_reference_present": bool(str(metadata.get("order_no") or "").strip()),
            "order_item_count": len(order_items),
            "order_baseline_present": bool(baseline.get("expected_items") or metadata.get("order_items")),
            "fulfillment_baseline_version": str(baseline.get("baseline_version") or ""),
            "product_reference_present": bool(metadata.get("product_master_data")),
            "logistics_present": bool(logistics),
            "warehouse_data_present": bool(
                metadata.get("warehouse_master_data")
                or baseline.get("warehouse_verification")
            ),
        },
        "media_preflight": build_media_preflight_plan(
            assets,
            media_forensics=_dict(media_forensics),
        ),
        "boundary": "该清单只确认系统收到的文件和接口字段；素材业务类型由视觉语义审核确认。",
    }


def _check(
    requirement_id: str,
    label: str,
    status: str,
    *,
    required: bool = True,
    source: str,
    evidence_refs: Optional[Iterable[Dict[str, Any]]] = None,
    reason: str = "",
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    normalized_reason = reason.strip() or {
        "present": "已取得满足本项要求的可核验材料。",
        "missing": "本轮未收到满足本项要求的材料。",
        "invalid": "已收到相关材料，但当前证据不满足本项要求。",
        "unknown": "已收到相关材料，但现有证据不足以确认本项是否满足。",
        "not_applicable": "本案无需使用本项材料。",
    }.get(status, "本项状态待确认。")
    if confidence is None and source in {"metadata", "trusted_system"}:
        confidence = 1.0
    return {
        "requirement_id": requirement_id,
        "label": label,
        "required": required,
        "status": status,
        "source": source,
        "confidence": _confidence(confidence),
        "evidence_refs": [dict(item) for item in evidence_refs or [] if isinstance(item, dict)],
        "reason": normalized_reason,
    }


def _status_from_checks(checklist: List[Dict[str, Any]]) -> str:
    required = [item for item in checklist if item.get("required") is True]
    if any(item.get("status") in {"missing", "invalid"} for item in required):
        return "incomplete"
    if any(item.get("status") == "unknown" for item in required):
        return "indeterminate"
    return "complete" if required and all(item.get("status") == "present" for item in required) else "indeterminate"


def _reason(status: str, scene_label: str) -> str:
    if status == "not_required":
        return f"当前{scene_label}无需用户补充该类证据。"
    if status == "complete":
        return f"当前{scene_label}所需材料已形成可回看的审核证据。"
    if status == "incomplete":
        return f"当前{scene_label}仍缺少必要材料或已有材料不满足审核要求。"
    return f"系统已收到材料，但尚未确认其语义是否满足当前{scene_label}要求。"


def _missing_items(checklist: List[Dict[str, Any]]) -> List[str]:
    return [
        str(item.get("label") or "")
        for item in checklist
        if item.get("required") is True and item.get("status") in {"missing", "invalid"}
    ]


def _product_readiness(
    inventory: Dict[str, Any],
    parsed: Dict[str, Any],
    input_readiness: Dict[str, Any],
) -> Dict[str, Any]:
    missing_required = set(str(item) for item in input_readiness.get("missing_required") or [])
    claim_present = not bool({"customer_claim", "customer_claim_or_claim_scope"} & missing_required)
    opening = _dict(parsed.get("opening_video_evidence"))
    video_received = int(_dict(inventory.get("media_counts")).get("video") or 0) > 0
    opening_refs = [item for item in opening.get("evidence_refs") or [] if isinstance(item, dict)]
    validated_requirements = {
        str(item) for item in opening.get("validated_requirements") or [] if str(item)
    }
    if opening.get("present") is True and opening_refs:
        opening_status = "present"
    elif opening:
        opening_status = "invalid"
    elif video_received:
        opening_status = "unknown"
    else:
        opening_status = "missing"
    if (
        opening.get("sop_compliant") is True
        and opening_refs
        and PRODUCT_OPENING_REQUIREMENTS.issubset(validated_requirements)
    ):
        compliance_status = "present"
    elif opening:
        compliance_status = "invalid"
    elif video_received:
        compliance_status = "unknown"
    else:
        compliance_status = "missing"
    checklist = [
        _check(
            "claim_scope",
            "明确的商品有伤诉求与争议部位",
            "present" if claim_present else "missing",
            source="metadata",
        ),
        _check(
            "initial_opening_video",
            "包含初次拆开包裹动作的开箱视频",
            opening_status,
            source="model" if opening else "metadata",
            evidence_refs=opening_refs,
            reason=str(opening.get("reason") or ""),
            confidence=_confidence(opening.get("confidence"), parsed.get("confidence")),
        ),
        _check(
            "opening_video_sop_compliance",
            "开箱视频满足封箱起始、面单、连续性、商品展示与伤点可判断要求",
            compliance_status,
            source="model" if opening else "metadata",
            evidence_refs=opening_refs,
            reason=(
                "五项开箱审核要求均有原视频证据。"
                if compliance_status == "present"
                else "已收到视频，但完整开箱 SOP 尚未全部满足。"
            ),
            confidence=_confidence(opening.get("confidence"), parsed.get("confidence")),
        ),
    ]
    status = _status_from_checks(checklist)
    return {
        "scenario": "product_damage",
        "status": status,
        "confidence": _confidence(opening.get("confidence"), parsed.get("confidence")) or 0.0,
        "reason": _reason(status, "商品有伤场景"),
        "checklist": checklist,
        "missing_items": _missing_items(checklist),
        "warnings": [
            "材料齐全性不等于损伤事实成立，也不等于责任归属。",
        ],
    }


def _fulfillment_readiness(
    scenario: str,
    inventory: Dict[str, Any],
    parsed: Dict[str, Any],
    input_readiness: Dict[str, Any],
) -> Dict[str, Any]:
    reconciliation = _dict(parsed.get("fulfillment_reconciliation"))
    material_confidence = _confidence(
        reconciliation.get("observation_confidence"),
        reconciliation.get("confidence"),
        parsed.get("confidence"),
    )
    trusted_warehouse = scenario == "missing_item" and (
        bool(input_readiness.get("warehouse_verification"))
        or reconciliation.get("resolution_basis") == "warehouse_verification"
    )
    missing_required = {str(item) for item in input_readiness.get("missing_required") or []}
    asset_received = int(inventory.get("received_asset_count") or 0) > 0
    sufficient = reconciliation.get("evidence_sufficiency") == "sufficient"
    static_route_complete = (
        reconciliation.get("evidence_route") == "static_three_images"
        and reconciliation.get("user_materials_complete") is True
    )
    observed = bool(reconciliation.get("observed_items")) or trusted_warehouse
    received_evidence_refs = [
        ref
        for item in reconciliation.get("observed_items") or []
        if isinstance(item, dict)
        for ref in item.get("evidence_refs") or []
        if isinstance(ref, dict) and str(ref.get("asset_ref") or "").strip()
    ]
    package_evidence_refs = [
        ref
        for item in reconciliation.get("package_observations") or []
        if isinstance(item, dict)
        for ref in item.get("evidence_refs") or []
        if isinstance(ref, dict) and str(ref.get("asset_ref") or "").strip()
    ]
    evidence_refs = received_evidence_refs + package_evidence_refs
    if (sufficient or static_route_complete) and observed and (trusted_warehouse or received_evidence_refs):
        evidence_status = "present"
    elif reconciliation:
        evidence_status = "invalid"
    elif asset_received:
        evidence_status = "unknown"
    else:
        evidence_status = "missing"
    def input_status(*keys: str) -> str:
        return "missing" if missing_required.intersection(keys) else "present"

    if scenario == "wrong_item":
        package_linked = bool(package_evidence_refs) or any(
            isinstance(item, dict)
            and str(item.get("package_ref") or "").strip() not in {"", "unassigned"}
            and any(
                isinstance(ref, dict)
                and str(ref.get("field") or "") in {
                    "same_package_linkage", "waybill_visible", "waybill_matches_order",
                    "sealed_start", "opening_complete", "received_group_photo_complete",
                }
                for ref in item.get("evidence_refs") or []
            )
            for item in reconciliation.get("observed_items") or []
        )
        checklist = [
            _check(
                "expected_item_identity_baseline",
                "版本化应收商品身份与数量",
                input_status(
                    "order_item_baseline",
                    "all_expected_item_quantities",
                    "fulfillment_baseline.baseline_version",
                ),
                source="trusted_system",
            ),
            _check(
                "received_item_evidence",
                "实收商品身份证据",
                evidence_status,
                source="model" if reconciliation else "metadata",
                evidence_refs=received_evidence_refs,
                reason=str(reconciliation.get("decision_boundary") or ""),
                confidence=material_confidence,
            ),
            _check(
                "same_package_linkage",
                "实收商品与订单包裹的关联证据",
                (
                    "present"
                    if evidence_status == "present" and package_linked
                    else "invalid"
                    if reconciliation
                    else "missing"
                ),
                source="model" if reconciliation else "metadata",
                evidence_refs=package_evidence_refs,
                confidence=material_confidence,
            ),
            _check(
                "selection_rules",
                "随机款、隐藏款或选择规则",
                input_status(
                    "selection_rules_declaration",
                    "fulfillment_baseline.selection_rules_complete",
                ),
                source="trusted_system",
            ),
        ]
        scene_label = "发错货场景"
    elif trusted_warehouse:
        verification = _dict(reconciliation.get("warehouse_verification")) or _dict(
            input_readiness.get("warehouse_verification")
        )
        verification_ref = str(verification.get("verification_ref") or "").strip()
        checklist = [
            _check(
                "expected_quantity_baseline",
                "仓库终核采用的应发商品与数量基线",
                "present",
                source="trusted_system",
            ),
            _check(
                "warehouse_final_verification",
                "受信仓库终核事实",
                "present",
                source="trusted_system",
                reason=(f"仓库终核引用：{verification_ref}" if verification_ref else "已取得受信仓库终核。"),
            ),
            _check(
                "complete_package_coverage",
                "全部包裹与实收物品完整展示",
                "not_applicable",
                required=False,
                source="trusted_system",
                reason="本案由受信仓库终核替代视觉完整展示。",
            ),
        ]
        scene_label = "漏发货场景"
    else:
        evidence_route = str(reconciliation.get("evidence_route") or "")
        fulfillment_state = _dict(input_readiness.get("fulfillment_readiness"))
        delivered = fulfillment_state.get("all_expected_packages_delivered")
        delivery_status = (
            "present"
            if delivered is True
            else "missing"
            if delivered is False
            else "unknown"
        )
        trusted_composition = (
            evidence_route == "not_required"
            and reconciliation.get("resolution_basis") == "trusted_expected_item_resolution"
        )
        user_route_complete = reconciliation.get("user_materials_complete") is True
        route_status = (
            "not_applicable"
            if trusted_composition
            else
            "present"
            if user_route_complete and evidence_route in {
                "compliant_opening_video",
                "static_three_images",
            }
            else "invalid"
            if reconciliation
            else "unknown"
            if asset_received
            else "missing"
        )
        route_reason = {
            "compliant_opening_video": "合规开箱视频已覆盖封箱起点、视频内面单、物流匹配、一镜到底和全部内容展示。",
            "static_three_images": "静态三类材料已齐全：全家福、绿色自封袋和清晰面单；案件结论仍待仓库实发明细核验。",
            "not_required": "商品构成已由可信订单或商品规则核验：用户主张项不是独立应发项，本单无需用户补充开箱或静态三类材料。",
        }.get(evidence_route, str(reconciliation.get("decision_boundary") or ""))
        checklist = [
            _check(
                "expected_quantity_baseline",
                "版本化应发商品与数量",
                input_status(
                    "order_item_baseline",
                    "all_expected_item_quantities",
                    "fulfillment_baseline.baseline_version",
                ),
                source="trusted_system",
            ),
            _check(
                "package_item_mapping",
                "订单商品与各包裹的分包映射",
                input_status("package_item_mapping", "submitted_package_mapping"),
                source="trusted_system",
            ),
            _check(
                "benefit_and_selection_rules",
                "赠品、特典与选择规则",
                input_status("benefit_rules_declaration", "selection_rules_declaration"),
                source="trusted_system",
            ),
            _check(
                "missing_item_user_evidence_route",
                "合规开箱视频或静态三类材料路径",
                route_status,
                required=not trusted_composition,
                source="model" if reconciliation else "metadata",
                evidence_refs=evidence_refs,
                reason=route_reason,
                confidence=material_confidence,
            ),
            _check(
                "all_expected_packages_delivered",
                "全部应到包裹已有可核验签收状态",
                delivery_status,
                required=False,
                source="trusted_system",
                reason=(
                    "甲方物流快照已确认全部应发包裹均已签收或送达。"
                    if delivery_status == "present"
                    else "甲方物流快照尚未覆盖全部应发包裹，请先查询拆单、在途与签收状态。"
                    if delivery_status == "missing"
                    else "本轮未取得可核验的甲方物流快照，无法确认全部应发包裹状态。"
                ),
            ),
            _check(
                "warehouse_final_verification",
                "受信仓库终核事实",
                "not_applicable",
                required=False,
                source="trusted_system",
                reason="本案尚无受信仓库终核，按应发、分包、签收与实收证据审核。",
            ),
        ]
        scene_label = "漏发货场景"
    status = (
        "not_required"
        if scenario == "missing_item"
        and reconciliation.get("evidence_route") == "not_required"
        and reconciliation.get("resolution_basis") == "trusted_expected_item_resolution"
        else _status_from_checks(checklist)
    )
    warnings = [
        "材料齐全性不等于履约差异成立；差异由版本化应收基线与实收事实确定性比对。",
    ]
    if scenario in {"wrong_item", "missing_item"} and static_route_complete:
        warnings.append("用户静态三类材料已齐全，下一步由人工客服读取仓库实发明细；不要再次要求用户补同类材料。")
    return {
        "scenario": scenario,
        "status": status,
        "confidence": material_confidence if material_confidence is not None else 0.0,
        "reason": _reason(status, scene_label),
        "checklist": checklist,
        "missing_items": _missing_items(checklist),
        "warnings": warnings,
    }


def _minor_evidence_refs(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "source_type": "supplementary_image",
            "asset_ref": f"supplemental_image_{index}",
            "image_index": index,
            "fact": f"该图片用于核对{item.get('label') or '本类材料'}。",
        }
        for index in item.get("evidence_image_indices") or []
        if isinstance(index, int) and index > 0
    ]


def _minor_readiness(
    inventory: Dict[str, Any],
    parsed: Dict[str, Any],
) -> Dict[str, Any]:
    assessment = _dict(parsed.get("minor_material_assessment"))
    source_checklist = [item for item in assessment.get("checklist") or [] if isinstance(item, dict)]
    source_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for item in source_checklist:
        source_by_id.setdefault(str(item.get("requirement_id") or ""), []).append(item)
    checklist = []
    processing_complete = (
        assessment.get("processing_status") == "completed"
        and assessment.get("coverage_complete") is True
    )
    for requirement_id, label in MINOR_REQUIRED_MATERIALS.items():
        candidates = source_by_id.get(requirement_id) or []
        usable = next((
            item for item in candidates
            if str(item.get("status") or "") == "present"
            and str(item.get("quality_status") or "") == "usable"
            and _minor_evidence_refs(item)
        ), None)
        item = usable or (candidates[0] if candidates else {})
        observed = str(item.get("status") or "")
        validation = str(item.get("validation_status") or "")
        if validation == "visual_consistency_mismatched":
            status = "invalid"
        elif validation in {
            "visual_consistency_uncertain",
            "visual_relationship_link_unresolved",
            "not_assessed",
            "",
        } and observed == "present":
            status = "unknown"
        elif usable and validation == "visual_consistency_matched":
            status = "present"
        elif observed in {"not_observed_after_full_scan", "missing"}:
            status = "missing"
        elif observed == "present":
            status = "invalid"
        elif processing_complete:
            status = "missing"
        else:
            status = "unknown"
        checklist.append(_check(
            requirement_id,
            str(item.get("label") or label),
            status,
            source="model",
            evidence_refs=_minor_evidence_refs(item),
            reason=str(item.get("rule_note") or ""),
            confidence=_confidence(parsed.get("confidence")),
        ))
    payment_risk = _dict(assessment.get("payment_capability_risk"))
    if payment_risk.get("low_age") is True:
        identity_check = next((
            item
            for item in _dict(assessment.get("field_consistency")).get("checks") or []
            if isinstance(item, dict) and item.get("check_id") == "identity_age"
        ), {})
        process_fields = {
            str(item.get("field_name") or ""): item
            for item in identity_check.get("field_results") or []
            if isinstance(item, dict)
        }
        for field_name, (requirement_id, label) in MINOR_PAYMENT_PROCESS_REQUIREMENTS.items():
            field = _dict(process_fields.get(field_name))
            evidence_indices = [
                int(index)
                for index in field.get("evidence_image_indices") or []
                if isinstance(index, int) and index > 0
            ]
            evidence_refs = [
                {
                    "source_type": "supplementary_image",
                    "asset_ref": f"supplemental_image_{index}",
                    "image_index": index,
                    "fact": f"该图片用于核对{label}。",
                }
                for index in evidence_indices
            ]
            field_status = str(field.get("status") or "not_assessed")
            if field_status == "matched" and evidence_refs:
                status = "present"
            elif field_status == "mismatched" or evidence_refs:
                status = "invalid"
            else:
                status = "missing"
            checklist.append(_check(
                requirement_id,
                label,
                status,
                source="model",
                evidence_refs=evidence_refs,
                reason=(
                    f"现有材料已明确说明{label}。"
                    if status == "present"
                    else f"申请时未满 10 周岁，{label}尚未形成清晰、可回看的证据。"
                ),
                confidence=_confidence(parsed.get("confidence")),
            ))
    if not source_checklist or not processing_complete:
        status = "indeterminate"
    else:
        status = _status_from_checks(checklist)
    if status == "complete":
        reason = "未成年人退款五类必交材料均已识别为可用。"
    else:
        reason = _reason(status, "未成年人退款场景")
    return {
        "scenario": "minor_refund",
        "status": status,
        "confidence": _confidence(parsed.get("confidence")) or 0.0,
        "reason": reason,
        "checklist": checklist,
        "missing_items": _missing_items(checklist),
        "warnings": [
            "视觉字段一致不等于法定真实性；材料齐全不直接决定退款结果。",
        ],
    }


def derive_material_readiness(
    job: Dict[str, Any],
    parsed: Dict[str, Any],
    input_readiness: Dict[str, Any],
) -> Dict[str, Any]:
    """在模型完成语义识别后，生成唯一的场景材料齐全性结果。"""
    inventory = _dict(input_readiness.get("review_inventory")) or build_review_inventory(job)
    scenario = str(job.get("scenario") or _dict(job.get("metadata")).get("scenario") or "")
    if scenario == "product_damage":
        result = _product_readiness(inventory, parsed, input_readiness)
    elif scenario in {"wrong_item", "missing_item"}:
        result = _fulfillment_readiness(scenario, inventory, parsed, input_readiness)
    elif scenario == "minor_refund":
        result = _minor_readiness(inventory, parsed)
    else:
        result = {
            "scenario": scenario,
            "status": "indeterminate",
            "confidence": None,
            "reason": "当前场景尚未配置材料齐全性契约。",
            "checklist": [],
            "missing_items": [],
            "warnings": [],
        }
    return result
