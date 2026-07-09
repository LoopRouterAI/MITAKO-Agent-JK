# -*- coding: utf-8 -*-
"""0709 客服 Agent 用户端反馈专项回归。

覆盖人工反馈里的 P0/P1：负面短句不降级、L4 不强制转人工、补偿审批不阻断、
内部节点不外泄、电话提醒进入建议闭环、视觉审核失败态也能被客服读取。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import (  # noqa: E402
    check_compensation_eligibility,
    check_transfer_rules,
    classify_intent,
    safety_review_agent,
    sanitize_customer_reply,
)
from business_readiness_service import run_business_flow  # noqa: E402
from main import _chat_attachment_context_line, _handoff_user_message_analysis  # noqa: E402
from poc.visual_review_poc.report_renderer import safe_agent_next_step  # noqa: E402


class _Queue:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    async def put(self, item: Dict[str, Any]) -> None:
        self.events.append(item)

    def put_nowait(self, item: Dict[str, Any]) -> None:
        self.events.append(item)


def _config() -> Dict[str, Any]:
    return {"configurable": {"event_queue": _Queue()}}


async def _classify(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    state = {
        "messages": messages,
        "user_id": "usr_001",
        "session_id": "regression_0709",
        "intent": "",
        "emotion_level": 2,
    }
    return await classify_intent(state, _config())


async def run() -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def record(name: str, ok: bool, detail: Any = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    logistic_context = [
        {"role": "user", "content": "我想咨询订单 #024001，物流到底怎么还没发"},
        {"role": "assistant", "content": "我先帮您核对仓库和物流进度。"},
        {"role": "user", "content": "md 说些废话"},
    ]
    r1 = await _classify(logistic_context)
    record("短负面句保持物流上下文和 L4", r1["intent"] == "物流追踪/催发货" and r1["emotion_level"] >= 4, r1)

    insult_context = [
        {"role": "user", "content": "我想核对蓝色监狱抽赏规则，为什么别人中了"},
        {"role": "assistant", "content": "我可以帮您整理批次和复核入口。"},
        {"role": "user", "content": "你脑子有病"},
    ]
    r2 = await _classify(insult_context)
    record("辱骂不降成闲聊", r2["intent"] == "盲盒相关/吞烫质疑" and r2["emotion_level"] >= 4, r2)

    transfer = await check_transfer_rules(
        {
            "messages": [{"role": "user", "content": "你们太垃圾了！这么慢的物流"}],
            "intent": "物流追踪/催发货",
            "emotion_level": 4,
        },
        _config(),
    )
    record("L4 只提示人工，不强制入队", transfer.get("should_transfer") is False, transfer)

    comp = await check_compensation_eligibility(
        {
            "messages": [{"role": "user", "content": "我想咨询订单 #024001，现在进度和补偿呢"}],
            "user_id": "usr_001",
            "session_id": "regression_0709",
            "intent": "物流追踪/催发货",
            "user_memory": {"member_level": "gold"},
            "order_data": {
                "orders": [
                    {
                        "order_id": "ORD_2024_001",
                        "status": "pending_shipment",
                        "is_compensable": True,
                    }
                ]
            },
        },
        _config(),
    )
    record("补偿建议失败或待审批不强制转人工", comp.get("should_transfer") is not True, comp)

    leaked = "最新节点：用户质疑中奖率，需解释规则并保留人工复核入口。"
    sanitized = sanitize_customer_reply(leaked)
    record("公开回复清洗内部节点", "最新节点" not in sanitized and "处理节点" not in sanitized, sanitized)

    safety = await safety_review_agent(
        {
            "reply_draft": f"<analysis>{{}}</analysis>\n{leaked}",
            "messages": [{"role": "user", "content": "为什么我 20 抽都没中"}],
            "intent": "盲盒相关/吞烫质疑",
            "order_data": {
                "orders": [
                    {
                        "order_id": "ORD_2026_102",
                        "status": "delivered",
                        "status_label": "抽奖结果已公布",
                        "items": [{"name": "蓝色监狱大赏盲盒 20 抽连包"}],
                    }
                ]
            },
            "logistics_data": {},
            "sop_results": [],
        },
        _config(),
    )
    record(
        "安全审查清洗内部节点且不转人工",
        safety.get("safety_check_result") == "pass" and "最新节点" not in sanitize_customer_reply(safety.get("reply_draft")),
        safety,
    )

    phone = await _classify(
        [
            {"role": "user", "content": "我想咨询订单 #026008，物流有更新吗"},
            {"role": "assistant", "content": "我会继续同步订单消息。"},
            {"role": "user", "content": "你就不能打电话提醒我吗"},
        ]
    )
    business = run_business_flow(
        {
            "messages": [{"role": "user", "content": "你就不能打电话提醒我吗"}],
            "user_id": "usr_001",
            "session_id": "regression_0709_phone",
            "intent": phone["intent"],
            "order_data": {"orders": [{"order_id": "ORD_2026_008", "status": "pending_shipment"}]},
        }
    )
    action = ((business.get("sop_state") or {}).get("planned_action") or {})
    record("电话提醒形成服务建议事件", phone["intent"] == "通知渠道/服务建议" and action.get("type") == "service_feedback", {"intent": phone, "action": action})

    handoff_analysis = await _handoff_user_message_analysis(
        {
            "brief": {
                "conversation_snippet": [
                    {"role": "user", "content": "我想咨询订单 #024001，物流为什么还没动"},
                    {"role": "assistant", "content": "已同步给客服继续处理。"},
                ]
            }
        },
        "你们太垃圾了！！还不知道我的诉求吗！！",
        "usr_001",
        "session_usr_001",
    )
    record(
        "人工服务期间负面情绪实时更新",
        handoff_analysis["emotion_level"] >= 4 and handoff_analysis["intent"] == "物流追踪/催发货",
        handoff_analysis,
    )

    review_line = _chat_attachment_context_line(
        {
            "id": "RV-FAILED",
            "kind": "review_task",
            "name": "broken.mp4",
            "mime_type": "video/mp4",
            "size": 123,
            "url": "/api/v1/private-domain/review-tasks/RV-FAILED",
            "status": "REVIEW_FAILED",
            "scenario": "product_damage",
            "boundary": "视觉审核未完成，需VIP客服人工复核或稍后重试。",
            "review_result": {
                "summary": {"review_status": "failed", "needs_human_review": True},
                "agent_brief": {
                    "conclusion": "视觉审核未完成：模型调用失败",
                    "next_step": "请VIP客服人工复核原始素材。",
                },
            },
        }
    )
    record("视觉审核失败态可进入客服上下文", "视觉审核未完成" in review_line and "请VIP客服人工复核" in review_line, review_line)

    guarded_next_step = safe_agent_next_step("拒绝当前无效凭证，通知用户重新上传真实商品图。")
    record(
        "视觉审核建议不得自动拒绝或定责",
        "拒绝" not in guarded_next_step and "VIP客服复核" in guarded_next_step,
        guarded_next_step,
    )

    ok = all(item["ok"] for item in checks)
    report = {
        "ok": ok,
        "passed": sum(1 for item in checks if item["ok"]),
        "total": len(checks),
        "checks": checks,
    }
    report_dir = ROOT / "tests" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / "customer_agent_0709_regression_latest.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
