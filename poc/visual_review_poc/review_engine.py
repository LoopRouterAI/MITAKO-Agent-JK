# -*- coding: utf-8 -*-
"""视觉审核 POC 规则引擎：接真实模型时只替换 model_signals 来源。"""
from __future__ import annotations

from typing import Any, Dict, List


SCENARIO_LABELS = {
    "video_unboxing": "开箱视频审核",
    "product_damage": "商品有伤审核",
    "minor_material": "未成年人资料审核",
}


def review_case(case: Dict[str, Any]) -> Dict[str, Any]:
    scenario = case["scenario"]
    signals = case["model_signals"]
    if scenario == "video_unboxing":
        return _review_video_unboxing(case, signals)
    if scenario == "product_damage":
        return _review_product_damage(case, signals)
    if scenario == "minor_material":
        return _review_minor_material(case, signals)
    raise ValueError(f"未知视觉审核场景: {scenario}")


def _base(case: Dict[str, Any], signals: Dict[str, Any], decision: str, issues: List[str], next_step: str) -> Dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "scenario": case["scenario"],
        "scenario_label": SCENARIO_LABELS[case["scenario"]],
        "title": case["title"],
        "decision": decision,
        "confidence": signals.get("confidence", 0),
        "issues": issues,
        "evidence": signals.get("evidence", ""),
        "next_step": next_step,
        "human_required": decision in {"manual_review", "suspect"},
        "evidence_ready": decision == "pass",
        "business_final_review_required": True,
        "mock_only": True,
        "boundary": "本结果来自 POC fixture，只证明流程和字段契约；最终业务动作由甲方规则执行，human_required 只表示证据是否必须人工复核。",
    }


def _review_video_unboxing(case: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[str] = []
    if not signals["one_take"] or signals["cut_detected"]:
        issues.append("疑似剪辑或非一镜到底")
    if not signals["six_sides"]:
        issues.append("未完整展示商品六面")
    if signals["item_left_frame"]:
        issues.append("商品曾离开画面")
    if not signals["waybill_visible"]:
        issues.append("快递盒或面单信息不完整")
    if not signals["defect_visible"]:
        issues.append("瑕疵不可见或不清晰")
    if signals["confidence"] < 0.8:
        issues.append("视觉置信度不足")

    if signals["item_left_frame"] and not signals["waybill_visible"]:
        decision = "fail"
    elif signals["confidence"] < 0.65:
        decision = "manual_review"
    elif issues:
        decision = "suspect"
    else:
        decision = "pass"
    next_step = "可进入售后证据链" if decision == "pass" else "进入人工复核，不自动定责"
    if decision == "fail":
        next_step = "要求重新提交合规开箱材料，不自动拒赔"
    return _base(case, signals, decision, issues, next_step)


def _review_product_damage(case: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[str] = []
    if not signals["damage_visible"]:
        issues.append("瑕疵不可见")
    if signals["blurred"]:
        issues.append("图片模糊")
    if signals["reflection_blocked"]:
        issues.append("反光或遮挡影响判断")
    if not signals["package_context_visible"]:
        issues.append("商品与包装/订单上下文不足")
    if signals["confidence"] < 0.75:
        issues.append("视觉置信度不足")

    decision = "pass" if not issues else "manual_review"
    result = _base(
        case,
        signals,
        decision,
        issues,
        "证据初筛通过，可按甲方现行售后流程继续" if decision == "pass" else "要求补拍具体缺口或由授权人员复核",
    )
    result["damage_type"] = signals.get("damage_type", "")
    result["damage_area"] = signals.get("damage_area", "")
    result["damage_severity"] = signals.get("damage_severity", "")
    return result


def _review_minor_material(case: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[str] = []
    if not signals["guardian_statement_present"]:
        issues.append("缺少监护人说明")
    if not signals["minor_identity_present"]:
        issues.append("缺少未成年人身份材料")
    if not signals["order_ownership_match"]:
        issues.append("订单归属未匹配")
    if not signals["payment_proof_present"]:
        issues.append("缺少付款证明")
    if not signals["sensitive_info_masked"]:
        issues.append("敏感信息未遮盖")
    if signals["tamper_suspected"]:
        issues.append("材料疑似篡改")

    if issues:
        decision = "request_more_material" if not signals["tamper_suspected"] else "manual_review"
        next_step = "只补齐清单点名的材料；疑似篡改时由授权人员回看原图"
    else:
        decision = "pass"
        next_step = "资料初筛通过，可按甲方现行流程继续；本 Mock 不执行退款"
    result = _base(case, signals, decision, issues, next_step)
    result["redacted_ocr_text"] = signals.get("ocr_text", "")
    result["input_sensitive_info_masked"] = signals["sensitive_info_masked"]
    result["sensitive_info_safe"] = True
    return result


def summarize_reviews(reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_scenario: Dict[str, Dict[str, int]] = {}
    for item in reviews:
        bucket = by_scenario.setdefault(item["scenario"], {"total": 0, "pass": 0, "suspect": 0, "fail": 0, "manual": 0})
        bucket["total"] += 1
        if item["decision"] == "pass":
            bucket["pass"] += 1
        elif item["decision"] == "suspect":
            bucket["suspect"] += 1
        elif item["decision"] == "fail":
            bucket["fail"] += 1
        else:
            bucket["manual"] += 1
    return {
        "priority_basis": "甲方反馈三类视觉审核占客服人力约 60%，爆单时还会挤占主链路客服人力。",
        "coverage": by_scenario,
        "adapter_contract": [
            "case_id",
            "scenario",
            "decision",
            "confidence",
            "issues",
            "evidence",
            "next_step",
            "human_required",
            "evidence_ready",
            "business_final_review_required",
            "mock_only",
        ],
    }
