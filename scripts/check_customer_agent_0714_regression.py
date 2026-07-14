# -*- coding: utf-8 -*-
"""0714 甲方反馈专项回归：业务事实、审核闭环与交互编排。"""
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
    _build_damage_material_reply,
    _build_lottery_detail_reply,
    _build_minor_refund_status_reply,
    _build_product_inventory_reply,
    check_transfer_rules,
    classify_intent,
    plan_business_readiness_flow,
    query_order_system,
    safety_review_agent,
    sanitize_customer_reply,
)
from business_readiness_service import classify_sop_branch, run_business_flow  # noqa: E402
from handoff_service import build_human_welcome, enqueue_handoff, post_user_message  # noqa: E402
import handoff_store  # noqa: E402
from main import _recent_review_attachments, _select_primary_customer_card, desk_sessions  # noqa: E402
from private_domain import store as private_domain_store  # noqa: E402


class _Queue:
    async def put(self, _item: Dict[str, Any]) -> None:
        return None

    def put_nowait(self, _item: Dict[str, Any]) -> None:
        return None


def _config(**values: Any) -> Dict[str, Any]:
    return {"configurable": {"event_queue": _Queue(), **values}}


async def _classify(text: str) -> Dict[str, Any]:
    return await classify_intent(
        {
            "messages": [{"role": "user", "content": text}],
            "user_id": "usr_006",
            "session_id": "regression_0714",
            "intent": "",
            "emotion_level": 2,
        },
        _config(),
    )


async def run() -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def record(name: str, ok: bool, detail: Any = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    lottery = await _classify("订单 #026102 的抽赏中奖率和活动规则是什么")
    record("带订单号的抽赏问题不误判物流", lottery.get("intent") == "盲盒相关/吞烫质疑", lottery)

    lottery_shipping = await _classify("这个20抽里稀有款概率、保底和发货时效分别是什么？")
    record(
        "抽赏概率与发货时效组合问题优先识别为抽赏",
        lottery_shipping.get("intent") == "盲盒相关/吞烫质疑",
        lottery_shipping,
    )

    minor = await _classify("订单 #026606 为什么需要证明手机号实名归属")
    record("未成年人退款追问不误判物流", minor.get("intent") == "退款退货/未成年人退款", minor)

    damage = await _classify("订单 #026301 商品有伤，照片应该拍哪些角度")
    record("商品有伤材料问题不误判物流", damage.get("intent") == "换货补发/商品破损", damage)

    enriched_damage_state = {
        "messages": [{
            "role": "user",
            "content": "商品有伤，照片应该拍哪些角度？\n\n[用户已上传附件]\n- evidence.jpg；建议=需要VIP客服复审",
        }],
        "raw_user_content": "商品有伤，照片应该拍哪些角度？",
        "user_id": "usr_003",
        "session_id": "regression_0714_attachment_intent",
        "intent": "",
        "emotion_level": 2,
    }
    enriched_damage = await classify_intent(enriched_damage_state, _config())
    enriched_transfer = await check_transfer_rules({**enriched_damage_state, **enriched_damage}, _config())
    record(
        "附件审核摘要中的VIP客服字样不触发用户会话转接",
        enriched_damage.get("intent") == "换货补发/商品破损" and enriched_transfer.get("should_transfer") is False,
        {"intent": enriched_damage.get("intent"), "transfer": enriched_transfer},
    )
    damage_safety = await safety_review_agent(
        {
            **enriched_damage_state,
            **enriched_damage,
            "reply_draft": "我已经记录到这个问题了，会继续核实。",
            "order_data": {"orders": [], "order_lookup_failed": True},
            "logistics_data": {},
            "sop_state": {"ticket_type": "damage"},
        },
        _config(),
    )
    record(
        "订单事实兜底不覆盖商品有伤确定性材料清单",
        all(k in damage_safety.get("reply_draft", "") for k in ["正面", "背面", "左右侧", "问题部位近景"]),
        damage_safety,
    )

    inventory = await _classify("HQ-SCHOOL-BADGE-SET 哪个 SKU 规格有现货")
    record("SKU 现货查询识别为售前商品咨询", inventory.get("intent") == "售前商品咨询", inventory)

    lottery_sop = classify_sop_branch("订单 #026102 的活动规则和中奖率是什么", "盲盒相关/吞烫质疑")
    record("抽赏规则使用独立 SOP 而非物流模板", lottery_sop.get("ticket_type") == "lottery", lottery_sop)

    lottery_reply = _build_lottery_detail_reply({
        "order_data": {"orders": [
            {"items": [{"item_id": "itm_bl_keychain", "name": "蓝色监狱 Q版挂件"}]},
            {"items": [{"item_id": "itm_bl_lottery_20", "name": "蓝色监狱大赏盲盒 20 抽连包"}]},
        ]},
    })
    record(
        "抽赏回答从多订单中定位活动并包含概率、复核和发货时效",
        all(k in lottery_reply for k in ["S档", "1%", "1 个工作日", "3-5 个工作日"]),
        lottery_reply,
    )

    lottery_orders = await query_order_system(
        {
            "messages": [{"role": "user", "content": "这个20抽里稀有款概率、保底和发货时效分别是什么？"}],
            "user_id": "usr_002",
            "session_id": "regression_0714_lottery_order",
            "active_order_id": "",
            "intent": "盲盒相关/吞烫质疑",
        },
        _config(),
    )
    lottery_item_ids = {
        item.get("item_id")
        for order in (lottery_orders.get("order_data") or {}).get("orders") or []
        for item in order.get("items") or []
    }
    record("抽赏咨询无前端焦点时仍拉取用户订单事实", "itm_bl_lottery_20" in lottery_item_ids, sorted(lottery_item_ids))

    inventory_reply = _build_product_inventory_reply({}, "HQ-SCHOOL-BADGE-SET 哪个规格有现货")
    record("SKU 查询一次性返回各规格库存", all(k in inventory_reply for k in ["日向翔阳", "影山飞雄", "月岛萤", "现货"]), inventory_reply)

    damage_reply = _build_damage_material_reply()
    record("商品有伤正面回答拍摄角度", all(k in damage_reply for k in ["正面", "背面", "左右侧", "问题部位近景"]), damage_reply)
    record(
        "外包装材料词不被内部外包身份防泄漏规则误伤",
        sanitize_customer_reply(damage_reply) == damage_reply,
        sanitize_customer_reply(damage_reply),
    )

    order_result = await query_order_system(
        {
            "messages": [{"role": "user", "content": "请查订单 #026606 的审核进度"}],
            "user_id": "usr_006",
            "session_id": "regression_0714_order",
            "active_order_id": "ORD_2026_601",
            "intent": "退款退货/未成年人退款",
        },
        _config(),
    )
    focused = ((order_result.get("order_data") or {}).get("orders") or [{}])[0]
    record("本轮明确订单号优先于页面残留焦点", focused.get("order_id") == "ORD_2026_606", focused)

    minor_status_reply = _build_minor_refund_status_reply({"order_data": {"orders": [focused]}})
    record(
        "未成年人审核状态给出当前节点时效和复核办法",
        all(k in minor_status_reply for k in ["实名归属证明", "1-2 个工作日", "生产值需由甲方"]),
        minor_status_reply,
    )

    foreign_order = await query_order_system(
        {
            "messages": [{"role": "user", "content": "请查订单 #024001"}],
            "user_id": "usr_006",
            "session_id": "regression_0714_foreign_order",
            "active_order_id": "ORD_2026_601",
            "intent": "物流追踪/催发货",
        },
        _config(),
    )
    foreign_data = foreign_order.get("order_data") or {}
    record(
        "其他用户订单号不回退到当前焦点订单",
        foreign_data.get("order_lookup_failed") is True and not foreign_data.get("orders"),
        foreign_data,
    )

    business = await plan_business_readiness_flow(
        {
            "messages": [{"role": "user", "content": "为什么需要我的手机号实名归属"}],
            "user_id": "usr_006",
            "session_id": "regression_0714_minor",
            "intent": "退款退货/未成年人退款",
            "order_data": {"orders": [focused]},
        },
        _config(),
    )
    record("人工审批需求不等于会话立即转人工", business.get("should_transfer") is not True, business)

    handoff_store.create_handoff_offer(
        "regression_0714_consent",
        "usr_006",
        "AI建议转接VIP客服",
        "mitako",
    )
    consent = await check_transfer_rules(
        {
            "messages": [
                {"role": "assistant", "content": "需要的话我可以帮您转接VIP客服继续核对。"},
                {"role": "user", "content": "好的"},
            ],
            "intent": "退款退货/申请退款",
            "emotion_level": 2,
            "session_id": "regression_0714_consent",
            "user_id": "usr_006",
        },
        _config(),
    )
    record("用户同意此前转接提议后真实进入转接规则", consent.get("should_transfer") is True, consent)

    no_focus = run_business_flow({
        "messages": [{"role": "user", "content": "你们这里主要卖什么？"}],
        "user_id": "usr_007",
        "session_id": "regression_0714_general",
        "intent": "闲聊互动",
        "order_data": {},
        "active_order_id": "",
    })
    record("普通咨询不自动抓取用户第一笔订单", not (no_focus.get("sop_state") or {}).get("order_id"), no_focus.get("sop_state"))

    result = {
        "messages": [{"role": "user", "content": "具体看一下现在卡在哪个环节"}],
        "intent": "物流追踪/催发货",
        "compensation_given": [{"type": "points", "amount": 500}],
        "business_cards": [{"type": "business_action", "data": {"action": {"type": "warehouse_task"}}}],
        "order_data": {
            "orders": [{
                "order_id": "ORD_2024_001",
                "status": "pending_shipment",
                "status_label": "出荷延期 180 天",
                "items": [{"name": "排球少年登校系列吧唧套装"}],
            }]
        },
        "logistics_data": {"timeline": []},
        "sop_state": {"ticket_type": "logistics"},
    }
    card = _select_primary_customer_card(result)
    record("同一轮只编排一个主卡片", bool(card) and card.get("type") == "order_progress", card)

    concise = {**result, "messages": [{"role": "user", "content": "请一句话告诉我处理结论"}]}
    record("一句话请求不插入流程卡片", _select_primary_customer_card(concise) is None)

    general_card = _select_primary_customer_card({
        "messages": [{"role": "user", "content": "你们支持哪些支付方式？"}],
        "intent": "闲聊互动",
        "business_cards": [{"type": "business_action", "data": {"action": {"type": "none"}}}],
        "sop_state": {"ticket_type": "general"},
    })
    record("普通问答不插入无关流程卡", general_card is None, general_card)

    review_task_id = "RV-0714-REGRESSION"
    if not private_domain_store.get_review_task(review_task_id):
        private_domain_store.create_review_task({
            "task_id": review_task_id,
            "user_id": "usr_006",
            "session_id": "regression_0714_review",
            "tenant_id": "mitako",
            "scenario": "product_damage",
            "file_name": "damage.mp4",
            "stored_name": "damage.mp4",
            "mime_type": "video/mp4",
            "size": 1024,
            "status": "REVIEW_COMPLETED",
            "result": {
                "agent_brief": {"conclusion": "发现商品表面划痕", "next_step": "提交售后复核"},
                "summary": {"confidence": 0.91, "needs_human_review": False},
                "report": {"html_url": "/reports/RV-0714-REGRESSION.html"},
            },
        })
    review_context = _recent_review_attachments(
        "usr_006", "regression_0714_review", "mitako", "之前视频审核结果和置信度是什么"
    )
    record(
        "后续追问可按会话回填历史审核任务",
        bool(review_context) and review_context[0].get("review_task_id") == review_task_id,
        review_context,
    )

    welcome = build_human_welcome(
        {"name": "岚星", "agent_id": "CS-0816"},
        {"summary": "用户咨询退款到账", "orders": ["我已经记录到这个问题了，会继续核实"]},
    )
    record("坐席首句不把泛化回复拼成订单", "关联订单" not in welcome, welcome)

    queue_session = "regression_0714_queue_message"
    handoff_store.delete_session(queue_session, tenant_id="mitako")
    enqueue_handoff(queue_session, {
        "user_id": "usr_006",
        "tenant_id": "mitako",
        "summary": "用户等待人工期间补充材料",
        "orders": ["ORD_2026_606(minor_review_rejected)"],
        "required_tier": "standard",
    })
    queued_message = await post_user_message(queue_session, "我再补充一张材料", "usr_006")
    record("排队期间用户补充消息可持久化", queued_message.get("ok") is True, queued_message)

    first_reply_session = "regression_0714_first_reply"
    handoff_store.ensure_chat_session(first_reply_session, "usr_006", "mitako")
    handoff_store.append_message(
        first_reply_session,
        "human",
        "您好，我已接手当前会话。",
        agent_id="CS-0816",
        meta={"kind": "welcome"},
    )
    first_reply_entry = handoff_store.get_session(first_reply_session) or {}
    record("自动欢迎语不计入真人首响", not first_reply_entry.get("last_agent_reply_at"), first_reply_entry)

    all_queue = await desk_sessions(scope="all", user={"role": "super_admin", "tenant_id": "mitako", "agent_id": ""})
    record(
        "管理员全队列接口可用且不引用不存在角色",
        all_queue.get("ok") is True and all_queue.get("scope") == "all",
        {"count": len(all_queue.get("sessions") or [])},
    )

    frontend_text = (ROOT / "src" / "hooks" / "useChatSSE.js").read_text(encoding="utf-8")
    record("附件默认文案不要求自动转客服", "请帮我创建审核任务并转客服确认" not in frontend_text)

    ok = all(item["ok"] for item in checks)
    report = {
        "ok": ok,
        "passed": sum(1 for item in checks if item["ok"]),
        "total": len(checks),
        "checks": checks,
    }
    out = ROOT / "tests" / "reports" / "customer_agent_0714_regression_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
