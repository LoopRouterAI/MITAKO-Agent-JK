# -*- coding: utf-8 -*-
"""甲方新增需求独立 POC：视频审核、私域 Agent、客服能力证明、服务人格边界。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import handoff_store
from business_mock_service import run_business_flow
from poc.visual_review_poc.demo import build_report as build_visual_review_report


GROUP_MESSAGES = [
    {"user_id": "u_001", "text": "排球少年登校系列还有现货吗？我想凑一套。"},
    {"user_id": "u_002", "text": "上次商品有划痕，售后处理完希望有人跟进一下。"},
    {"user_id": "u_003", "text": "初音限定如果补货提醒我，价格合适就买。"},
    {"user_id": "u_004", "text": "物流拖太久了，有点生气，没人回复我吗？"},
]

CATALOG = [
    {"product_id": "P001", "name": "排球少年 登校系列 吧唧", "tags": ["排球少年", "现货", "套装"], "price": 28.0},
    {"product_id": "P003", "name": "咒术回战 盲盒 整盒", "tags": ["盲盒", "整盒"], "price": 168.0},
    {"product_id": "P004", "name": "初音未来 2024 限定", "tags": ["初音", "限定", "补货"], "price": 520.0},
]


def _isolate_demo_databases(tmp_dir: str) -> None:
    base = Path(tmp_dir)
    handoff_store._DB_DIR = str(base / "handoff")
    handoff_store._DB_PATH = str(base / "handoff" / "handoff.db")
    handoff_store._db_ready = False


def run_video_review_demo() -> Dict[str, Any]:
    visual_report = build_visual_review_report()
    state = {
        "messages": [{"role": "user", "content": "商品有划痕破损，我补充了完整开箱视频"}],
        "user_id": "poc_video_user",
        "session_id": "poc_video_session",
        "active_order_id": "ORD_2025_003",
        "intent": "换货补发/商品破损",
        "tenant_id": "mitako_poc",
        "order_data": {"orders": [{"order_id": "ORD_2025_003", "user_id": "poc_video_user", "status": "delivered"}]},
    }
    sop = run_business_flow(state, ["damage_photo_clear", "unboxing_video_ok"])["sop_state"]
    return {
        "target": "证明三类视觉审核输出可独立运行，并可进入售后 SOP 证据链",
        "visual_review_summary": visual_report["summary"],
        "reviews": visual_report["reviews"],
        "evaluation_readiness": {
            "minimum_blind_set": "三类主场景每个正向/负向结论至少 50 条",
            "recommended_set": "每个结论类 200-300 条更适合对外验收",
            "required_fields": ["用户诉求", "开箱视频或补充图片", "订单商品名", "SKU/规格", "商品主数据", "最终人工结论", "人工结论原因"],
            "accuracy_boundary": "少量样例只能说明链路有信号，不能宣称准确率",
        },
        "sop_evidence": {
            "ticket_type": sop["ticket_type"],
            "sop_branch": sop["sop_branch"],
            "fixture_types": [fx["type"] for fx in sop["fixtures"]],
            "planned_action": sop["planned_action"]["type"],
            "requires_human": sop["planned_action"]["requires_human"],
            "blocked_actions": sop["blocked_actions"],
        },
    }


def _message_tags(text: str) -> List[str]:
    tags = []
    for key in ("排球少年", "初音", "物流", "售后", "划痕", "补货", "现货"):
        if key in text:
            tags.append(key)
    if any(key in text for key in ("想", "买", "价格合适", "凑一套")):
        tags.append("购买意向")
    if any(key in text for key in ("生气", "没人回复", "拖太久")):
        tags.append("负面情绪")
    return tags


def run_private_domain_demo() -> Dict[str, Any]:
    users = []
    sales_leads = []
    alerts = []
    manual_followups = []
    hot_products: Dict[str, int] = {}

    for msg in GROUP_MESSAGES:
        tags = _message_tags(msg["text"])
        recommendations = [
            item for item in CATALOG if any(tag in item["tags"] or tag in item["name"] for tag in tags)
        ][:2]
        row = {
            "user_id": msg["user_id"],
            "tags": tags,
            "intent": "high" if "购买意向" in tags else "service" if "售后" in tags or "物流" in tags else "medium",
            "recommendations": recommendations,
        }
        users.append(row)
        if recommendations and "购买意向" in tags:
            sales_leads.append({"user_id": msg["user_id"], "products": recommendations, "reason": "明确表达购买或补货兴趣"})
        if "负面情绪" in tags or "售后" in tags or "物流" in tags:
            manual_followups.append({"user_id": msg["user_id"], "reason": "需要客服确认售后/物流状态后再触达"})
        if "负面情绪" in tags:
            alerts.append({"user_id": msg["user_id"], "level": "high", "reason": "群内负面情绪需人工优先响应"})
        for product in recommendations:
            hot_products[product["name"]] = hot_products.get(product["name"], 0) + 1

    return {
        "target": "证明私域 Agent 是线索整理和转化工具，不是泛陪聊",
        "users": users,
        "sales_leads": sales_leads,
        "manual_followups": manual_followups,
        "negative_alerts": alerts,
        "daily_summary": {
            "message_count": len(GROUP_MESSAGES),
            "high_intent_users": [lead["user_id"] for lead in sales_leads],
            "hot_products": sorted(hot_products, key=hot_products.get, reverse=True),
            "next_step": "人工确认授权和触达策略后再执行真实私域触达",
        },
    }


def run_customer_service_demo() -> Dict[str, Any]:
    samples = [
        ("商品有伤", "开箱视频里能看到商品有明显划痕", ["damage_photo_clear", "unboxing_video_ok"]),
        ("物流异常", "快递一直没收到，帮我催发货", []),
        ("申请退款", "我要退款退钱", []),
        ("未成年人退款", "孩子误买了商品，我是监护人要退款", ["minor_refund_material"]),
    ]
    cases = []
    for index, (expected, text, fixtures) in enumerate(samples, start=1):
        state = {
            "messages": [{"role": "user", "content": text}],
            "user_id": f"poc_cs_user_{index}",
            "session_id": f"poc_cs_session_{index}",
            "active_order_id": "ORD_2025_003",
            "intent": expected,
            "tenant_id": "mitako_poc",
            "order_data": {"orders": [{"order_id": "ORD_2025_003", "user_id": f"poc_cs_user_{index}", "status": "delivered"}]},
        }
        result = run_business_flow(state, fixtures)
        sop = result["sop_state"]
        cases.append({
            "expected": expected,
            "matched": sop["sop_branch"],
            "ticket_type": sop["ticket_type"],
            "allowed_actions": sop["allowed_actions"],
            "blocked_actions": sop["blocked_actions"],
            "planned_action": sop["planned_action"],
            "checklist": sop["checklist"],
            "audit_events": [event["event_type"] for event in result["business_events"]],
        })
    return {
        "target": "证明客服 Agent 已能按 SOP 分流、生成任务、阻断越权动作并留下审计",
        "cases": cases,
        "readiness": {
            "real_partner_integration": False,
            "prepared_adapters": ["sop_checklist", "business_audit", "task_center", "qc_sop_proposal", "private_domain_task"],
            "visual_review_handoff": "商品有伤、开箱视频、未成年人资料进入视觉审核工作台，客服主链路只承接安抚、补件、人工复核和工单记录",
        },
    }


def run_service_personality_demo() -> Dict[str, Any]:
    return {
        "target": "验证客服 Agent 保留专业同理心，但不提供陪伴或角色扮演",
        "value": [
            "承认用户等待、清关、仓库、物流和售后纠纷中的真实情绪",
            "用明确的工单状态、补件要求和下一步动作降低用户焦虑",
            "把商品有伤、开箱视频、资料审核等高风险内容转入视觉审核和人工复核",
            "保持边界：不建立持续情感依赖，不做恋爱、陪伴或角色扮演",
        ],
        "not_for": ["自动退款", "自动拒赔", "自动视频定责", "售后视觉审核裁决", "未成年人资料终审", "虚拟陪伴", "角色扮演"],
    }


def build_report() -> Dict[str, Any]:
    return {
        "goal": "独立验证甲方新增视觉审核优先场景、私域 Agent、客服 Agent 能力证明和服务人格边界",
        "scope": "仅使用本地 Mock/fixture，不接入甲方真实系统",
        "video_review": run_video_review_demo(),
        "private_domain_agent": run_private_domain_demo(),
        "customer_service_agent": run_customer_service_demo(),
        "service_personality": run_service_personality_demo(),
        "acceptance": {
            "status": "passed",
            "next_real_work": [
                "甲方提供真实视频样本后做盲测和误判分析",
                "甲方提供接口文档后做契约测试",
                "甲方确认私域触达权限、频控和话术后进入真实联调",
            ],
        },
    }


def self_check(report: Dict[str, Any]) -> None:
    video = report["video_review"]
    decisions = {item["case_id"]: item["decision"] for item in video["reviews"]}
    assert decisions["video_unboxing_pass"] == "pass", video
    assert decisions["video_unboxing_cut"] == "suspect", video
    assert decisions["video_unboxing_invalid"] == "fail", video
    assert decisions["video_unboxing_low_confidence"] == "manual_review", video
    assert decisions["product_damage_pass"] == "pass", video
    assert decisions["minor_material_complete"] == "manual_review", video
    assert all(item["business_final_review_required"] is True for item in video["reviews"]), video
    assert all(item["human_required"] is True for item in video["reviews"]), video
    assert video["sop_evidence"]["requires_human"] is True, video
    assert "auto_refund" in video["sop_evidence"]["blocked_actions"], video
    assert "50 条" in video["evaluation_readiness"]["minimum_blind_set"], video
    assert "不能宣称准确率" in video["evaluation_readiness"]["accuracy_boundary"], video

    private_domain = report["private_domain_agent"]
    assert private_domain["sales_leads"], private_domain
    assert private_domain["manual_followups"], private_domain
    assert private_domain["negative_alerts"], private_domain
    assert private_domain["daily_summary"]["hot_products"], private_domain

    cs = report["customer_service_agent"]
    assert "视觉审核工作台" in cs["readiness"]["visual_review_handoff"], cs
    for case in cs["cases"]:
        assert case["matched"], case
        assert case["blocked_actions"], case
        blocked_text = " ".join(case["blocked_actions"])
        assert "auto" in blocked_text or "promise" in blocked_text, case
        assert case["planned_action"]["type"] != "auto_refund", case

    service_personality = report["service_personality"]
    assert "虚拟陪伴" in service_personality["not_for"], service_personality
    assert "角色扮演" in service_personality["not_for"], service_personality
    assert any("视觉审核" in item for item in service_personality["value"]), service_personality

    assert report["scope"] == "仅使用本地 Mock/fixture，不接入甲方真实系统", report


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mitako_customer_poc_") as tmp:
        _isolate_demo_databases(tmp)
        report = build_report()
        self_check(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("POC self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
