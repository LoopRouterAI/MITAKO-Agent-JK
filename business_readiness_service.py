# -*- coding: utf-8 -*-
"""本地业务就绪闭环：SOP 状态机、样例材料接入、幂等审计。"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List

import handoff_store
from business_api import load_data


def _last_user_text(state: Dict[str, Any]) -> str:
    raw = str(state.get("raw_user_content") or "").strip()
    if raw:
        return raw
    for msg in reversed(state.get("messages") or []):
        if msg.get("role") == "user":
            text = str(msg.get("content") or "")
            for marker in ("\n\n[用户已上传附件]", "\n\n[用户已上传材料]"):
                if marker in text:
                    text = text.split(marker, 1)[0]
            return text.strip()
    return ""


def classify_sop_branch(text: str, intent: str = "") -> Dict[str, Any]:
    query = f"{intent} {text}"
    rules = [
        ("missing", "赠品/特典权益核对", ["赠品", "特典", "满赠", "随单赠"], ["lookup_entitlement_rule", "create_after_sales_card"], ["assume_lottery_probability", "auto_reissue"]),
        ("lottery", "抽赏规则与结果复核", ["盲盒", "抽赏", "抽选", "中奖率", "概率", "保底", "奖池", "稀有款", "抽号", "活动规则", "中奖名单", "吞烫", "普款"], ["answer_lottery_rules", "create_lottery_review"], ["promise_win", "change_probability"]),
        ("product_consult", "商品/库存/预售咨询", ["售前商品咨询", "还没下单", "想买", "库存", "现货", "预售", "规格", "SKU", "sku", "商品咨询", "支付方式"], ["answer_product_policy"], ["promise_delivery_date", "reserve_inventory"]),
        ("minor_refund", "未成年人退款", ["未成年", "孩子", "小孩", "家长", "监护人", "监护关系", "实名归属", "承诺书"], ["request_materials", "explain_review_status"], ["auto_refund", "auto_reject"]),
        ("account_binding", "账号换绑", ["换绑", "账号", "手机号", "改绑"], ["create_ticket"], ["auto_change_account"]),
        ("damage", "商品有伤", ["破损", "有伤", "划痕", "烂了", "瑕疵", "开箱"], ["create_after_sales_card"], ["auto_refund", "auto_reissue"]),
        ("missing", "漏发/发错货", ["漏发", "少发", "缺件", "发错", "错货"], ["create_after_sales_card", "create_warehouse_task"], ["auto_reissue"]),
        ("notification_preference", "通知渠道与服务建议", ["电话提醒", "电话通知", "打电话", "来电", "电话联系", "手机提醒", "短信提醒"], ["record_service_preference", "create_qc_sop_proposal"], ["promise_phone_call"]),
        ("logistics", "物流异常", ["物流", "没收到", "快递", "丢件", "拒签", "催发货", "出荷", "清关", "通关", "仓库", "库房", "入仓", "发货慢", "物流慢"], ["create_warehouse_task"], ["promise_delivery_date"]),
        ("refund", "申请退款", ["退款", "退钱", "全额", "退货退款", "退货", "不好", "不想要"], ["create_refund_card"], ["auto_cash_refund"]),
    ]
    for ticket_type, branch, keys, allowed, blocked in rules:
        if any(k in query for k in keys):
            needs_human = ticket_type in {"refund", "minor_refund", "account_binding"} or any(k in query for k in ["大额", "980", "身份证"])
            return {
                "ticket_type": ticket_type,
                "sop_branch": branch,
                "state": "intent_checked",
                "allowed_actions": allowed,
                "blocked_actions": blocked,
                "needs_human": needs_human,
                "conversation_handoff_required": False,
                "matched_keywords": [k for k in keys if k in query],
            }
    return {
        "ticket_type": "general",
        "sop_branch": "通用咨询",
        "state": "intent_checked",
        "allowed_actions": ["answer_with_sop"],
        "blocked_actions": ["auto_refund", "auto_reissue", "auto_change_account"],
        "needs_human": False,
        "conversation_handoff_required": False,
        "matched_keywords": [],
    }


def get_multimodal_fixture(fixture_id: str) -> Dict[str, Any]:
    fixtures = {
        "damage_photo_clear": {
            "fixture_id": fixture_id,
            "type": "image_damage",
            "result": {"damage_type": "明显划痕", "confidence": 0.92, "sop": "商品有伤-初步判定"},
        },
        "unboxing_video_ok": {
            "fixture_id": fixture_id,
            "type": "video_unboxing",
            "result": {"has_unboxing_video": True, "confidence": 0.88, "sop": "商品有伤-有开箱视频"},
        },
        "unboxing_video_suspected_cut": {
            "fixture_id": fixture_id,
            "type": "video_unboxing",
            "result": {"continuity_risk": True, "confidence": 0.81, "sop": "商品有伤-开箱视频连续性疑点"},
        },
        "minor_refund_material": {
            "fixture_id": fixture_id,
            "type": "minor_refund",
            "result": {"guardian_material_complete": False, "confidence": 0.84, "sop": "未成年人退款2.0版本"},
        },
    }
    return fixtures.get(fixture_id, {})


def _first_order(state: Dict[str, Any]) -> Dict[str, Any]:
    if (state.get("order_data") or {}).get("order_lookup_failed"):
        return {}
    orders = (state.get("order_data") or {}).get("orders") or []
    if orders:
        return orders[0]
    active_order_id = state.get("active_order_id") or ""
    db = load_data()
    if active_order_id:
        order = db.get("orders", {}).get(active_order_id, {})
        if order and order.get("user_id") == (state.get("user_id") or ""):
            return order
    return {}


def _stable_key(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _event(
    *,
    state: Dict[str, Any],
    event_type: str,
    status: str,
    order_id: str = "",
    payload: Dict[str, Any] | None = None,
    result: Dict[str, Any] | None = None,
    idempotency_seed: str = "",
) -> Dict[str, Any]:
    return handoff_store.append_business_event(
        session_id=state.get("session_id") or "",
        user_id=state.get("user_id") or "",
        tenant_id=state.get("tenant_id") or "mitako",
        order_id=order_id,
        event_type=event_type,
        idempotency_key=_stable_key(state.get("session_id") or "", order_id, event_type, idempotency_seed),
        status=status,
        payload=payload or {},
        result=result or {},
    )


def _checklist_item(label: str, status: str, note: str, owner: str = "AI") -> Dict[str, str]:
    return {"label": label, "status": status, "note": note, "owner": owner}


def _review_design(sop_state: Dict[str, Any], fixtures: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    ticket_type = sop_state.get("ticket_type") or "general"
    query = f"{text} {sop_state.get('sop_branch', '')}"
    fixture_types = {fx.get("type") for fx in fixtures}
    confidence = max(((fx.get("result") or {}).get("confidence", 0) for fx in fixtures), default=0)
    base = {
        "decision_mode": "辅助初筛，最终由人工确认",
        "confidence": round(confidence, 2) if confidence else None,
        "customer_policy": "先承接情绪，再同步已确认事实和下一步，不暴露模型、供应商、接口或内部审计字段",
        "staff_policy": "展示 SOP 分支、材料状态、置信度和人工确认点，禁止自动退款、自动补发、自动改绑",
    }
    if ticket_type == "damage":
        is_video = "video_unboxing" in fixture_types or any(k in query for k in ["视频审核", "开箱视频", "剪辑", "离开镜头"])
        base.update({
            "scene": "视频审核" if is_video else "商品有伤",
            "optimized_checks": [
                "核对开箱过程是否连续、箱体是否离开镜头、关键画面是否存在跳切" if is_video else "核对商品本体、包装外观、细节图和订单归属",
                "输出初筛置信度和疑点，不直接承诺退款或补发",
                "售后/VIP客服复核材料后再执行真实业务动作",
            ],
        })
        return base
    if ticket_type == "minor_refund":
        base.update({
            "scene": "未成年人资料审核",
            "optimized_checks": [
                "核对监护人身份、订单归属、付款关系和隐私材料完整性",
                "只做材料完整性与风险初筛，不自动同意或拒绝退款",
                "材料与退款动作由VIP客服/主管确认，但当前用户沟通仍由AI继续承接",
            ],
        })
        return base
    if ticket_type == "logistics":
        base.update({
            "scene": "履约与物流异常",
            "optimized_checks": [
                "拆分发货、清关、入仓、仓库排单、承运商轨迹等节点",
                "给用户明确下一步核查动作，不承诺绝对到货或出荷日期",
                "形成仓储/履约协同任务，接口联通前由人工执行",
            ],
        })
        return base
    if ticket_type == "notification_preference":
        base.update({
            "scene": "通知渠道与服务建议",
            "optimized_checks": [
                "确认用户希望在物流、出库或审核更新时被主动提醒",
                "仅承诺当前可用的站内信/订单消息，电话或短信需授权和渠道能力确认",
                "将代表性诉求沉淀为客服主管/产品复盘建议",
            ],
        })
        return base
    if ticket_type == "product_consult":
        base.update({
            "scene": "商品/库存/预售咨询",
            "optimized_checks": [
                "确认用户是否已下单；未下单时只回答商品、库存、预售和售后规则",
                "库存数量以下单页和甲方商品接口为准，不编造具体库存",
                "不生成订单物流卡，不承诺确定出货日期",
            ],
        })
        return base
    if ticket_type == "lottery":
        base.update({
            "scene": "抽赏规则与结果复核",
            "optimized_checks": [
                "优先回答活动规则、奖池、概率公示和当前订单抽选结果",
                "不把抽赏质疑归类为物流或仓库异常",
                "需要复核时生成抽赏复核事项，不承诺改概率或必中",
            ],
        })
        return base
    if ticket_type == "refund":
        base.update({
            "scene": "退货退款",
            "optimized_checks": [
                "区分不喜欢、质量问题、错漏发和破损证据",
                "现金退款和退货退款进入人工审批，不自动核销",
                "优先安抚不满情绪，解释材料和受理边界",
            ],
        })
        return base
    base.update({
        "scene": sop_state.get("sop_branch") or "通用咨询",
        "optimized_checks": ["按本地 SOP 回答并记录上下文，必要时转VIP客服确认"],
    })
    return base


def _evaluation_tags(sop_state: Dict[str, Any], fixtures: List[Dict[str, Any]]) -> List[str]:
    tags = [
        "persona:enfj-a",
        "tone:empathy-first",
        f"sop:{sop_state.get('ticket_type') or 'general'}",
        "guard:no-internal-disclosure",
        "guard:no-auto-refund",
    ]
    scene = (sop_state.get("review_design") or {}).get("scene")
    if scene:
        tags.append(f"review:{scene}")
    if fixtures:
        tags.append("visual:fixture-reviewed")
    if sop_state.get("needs_human"):
        tags.append("business-review:required")
    return tags


def build_sop_checklist(sop_state: Dict[str, Any], order: Dict[str, Any], fixtures: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    ticket_type = sop_state.get("ticket_type") or "general"
    order_id = order.get("order_id") or ""
    review_design = sop_state.get("review_design") or {}
    checklist = [
        _checklist_item(
            "核对用户与订单",
            "done" if order_id else "pending",
            f"已命中订单 {order_id}" if order_id else "订单信息待补齐，需人工在业务系统核对",
        ),
        _checklist_item(
            "确认 SOP 分支",
            "done",
            f"已匹配「{sop_state.get('sop_branch', '通用咨询')}」",
        ),
        _checklist_item(
            "禁止越权动作",
            "blocked",
            "、".join(sop_state.get("blocked_actions") or ["auto_refund", "auto_reissue", "auto_change_account"]),
            "规则引擎",
        ),
    ]
    if ticket_type in {"damage", "minor_refund"}:
        visual_note = "需补充照片/开箱视频/监护人材料后再处理"
        if fixtures:
            confidence = max((fx.get("result") or {}).get("confidence", 0) for fx in fixtures)
            visual_note = f"已读取材料，视觉初筛置信度约 {round(confidence * 100)}%，仍需人工确认"
        checklist.append(_checklist_item(
            "核验证据材料",
            "done" if fixtures else "pending",
            visual_note,
        ))
    if review_design.get("scene") == "视频审核":
        checklist.append(_checklist_item(
            "核验视频连续性",
            "done" if fixtures else "pending",
            "重点确认开箱过程是否连续、箱体是否离开镜头、关键画面是否存在剪辑断点",
            "售后审核",
        ))
    if ticket_type in {"refund", "minor_refund", "account_binding", "damage"}:
        checklist.append(_checklist_item(
            "VIP客服审批",
            "required",
            "现金退款、账号变更、补发换货需人工授权确认",
            "VIP客服",
        ))
    if ticket_type in {"missing", "logistics"}:
        checklist.append(_checklist_item(
            "跨部门任务",
            "ready",
            "已生成履约协同任务，待业务接口联通后自动派发",
            "仓储协同",
        ))
    if ticket_type == "notification_preference":
        checklist.append(_checklist_item(
            "服务建议记录",
            "ready",
            "已记录用户希望物流更新后被电话/短信提醒；真实触达需确认授权和渠道能力",
            "客服主管",
        ))
    if ticket_type == "product_consult":
        checklist.append(_checklist_item(
            "商品信息核对",
            "ready",
            "按商品接口同步库存、预售说明、退换规则；未接入前仅展示演示商品信息",
            "商品中心",
        ))
    checklist.append(_checklist_item(
        "下一步话术",
        "ready",
        "先同步已确认事实，再说明需人工/仓储确认的边界",
        "VIP客服",
    ))
    return checklist


def _task_center(action: Dict[str, Any], order_id: str, ticket_type: str) -> Dict[str, Any]:
    if action.get("type") == "warehouse_task":
        return {
            "task_id": f"WH-TASK-{_stable_key(order_id, ticket_type)[:8]}",
            "status": "ready_for_dispatch",
            "owner_role": "仓库/履约协同组",
            "sla_minutes": 30 if ticket_type == "logistics" else 60,
            "next_step": "由人工按此任务在业务系统核查包裹状态，接口联通后可自动派发",
        }
    if action.get("type") in {"ticket", "after_sales_card"}:
        return {
            "task_id": f"CS-TASK-{_stable_key(order_id, ticket_type, action.get('type', ''))[:8]}",
            "status": "ready_for_human_review",
            "owner_role": "售后/升级处理组",
            "sla_minutes": 120,
            "next_step": "VIP客服确认材料、金额和账号归属后再在业务系统操作",
        }
    if action.get("type") == "service_feedback":
        return {
            "task_id": f"QC-TASK-{_stable_key(order_id, ticket_type, action.get('type', ''))[:8]}",
            "status": "ready_for_review",
            "owner_role": "客服主管/产品复盘",
            "sla_minutes": 1440,
            "next_step": "主管复核是否开放电话/短信提醒能力；未联通前只作为服务建议记录",
        }
    return {}


def _qc_sop_proposal(sop_state: Dict[str, Any], action: Dict[str, Any], order_id: str) -> Dict[str, Any]:
    return {
        "proposal_id": f"SOP-REVIEW-{_stable_key(order_id, sop_state.get('ticket_type', 'general'))[:8]}",
        "status": "drafted",
        "trigger": sop_state.get("sop_branch") or "通用咨询",
        "risk_level": "high" if action.get("requires_human") else "medium",
        "findings": [
            "已识别需人工确认的高风险动作" if action.get("requires_human") else "已识别可走本地任务中心的跨部门动作",
            "已阻断自动退款、自动补发、自动改绑等越权动作",
        ],
        "next_step": "质检复核后可沉淀为服务流程更新建议",
    }


def _private_domain_task(sop_state: Dict[str, Any], order_id: str) -> Dict[str, Any]:
    return {
        "task_id": f"PD-TASK-{_stable_key(order_id, sop_state.get('sop_branch', 'general'))[:8]}",
        "status": "drafted",
        "channel": "private_domain_followup",
        "segment": "售后跟进/高风险安抚",
        "touchpoint": "企微、社群、App Push 等授权触达渠道",
        "next_step": "人工确认客户授权与触达策略后再进入真实私域运营链路",
    }


def record_transfer_blocked(state: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    handoff_store.ensure_chat_session(
        state.get("session_id") or "",
        state.get("user_id") or "",
        state.get("tenant_id") or "mitako",
    )
    text = _last_user_text(state)
    sop_state = classify_sop_branch(text, state.get("intent") or "")
    sop_state.update({
        "state": "transferred_before_action",
        "reason": reason or state.get("transfer_reason") or "高风险会话先转VIP客服",
        "readiness": {"mode": "local_preview", "real_partner_integration": False},
        "checklist": build_sop_checklist(sop_state, {}, []),
    })
    return _event(
        state=state,
        event_type="service_transfer_blocked",
        status="local_preview",
        payload={"text": text[:300], "reason": sop_state["reason"]},
        result=sop_state,
    )


def run_business_flow(state: Dict[str, Any], fixtures: List[str] | None = None) -> Dict[str, Any]:
    handoff_store.ensure_chat_session(
        state.get("session_id") or "",
        state.get("user_id") or "",
        state.get("tenant_id") or "mitako",
    )
    text = _last_user_text(state)
    sop_state = classify_sop_branch(text, state.get("intent") or "")
    order = _first_order(state)
    order_id = order.get("order_id") or ""
    if order_id:
        sop_state["state"] = "order_loaded"
        sop_state["order_id"] = order_id
        first_item = (order.get("items") or [{}])[0]
        sop_state["order_snapshot"] = {
            "order_id": order_id,
            "item_name": first_item.get("name") or order.get("display_name") or order_id,
            "status": order.get("status") or "",
            "status_label": order.get("status_label") or order.get("status") or "待核对",
            "delay_days": order.get("delay_days") or 0,
        }

    events = [
        _event(
            state=state,
            event_type="sop_branch",
            status="matched",
            order_id=order_id,
            payload={"text": text[:300], "intent": state.get("intent") or ""},
            result=sop_state,
        )
    ]

    fixture_results = []
    for fixture_id in fixtures or []:
        fx = get_multimodal_fixture(fixture_id)
        if not fx:
            continue
        fixture_results.append(fx)
        result = fx.get("result") or {}
        if fx.get("type") == "image_damage":
            sop_state.update({"ticket_type": "damage", "sop_branch": result.get("sop") or "商品有伤"})
        elif fx.get("type") == "video_unboxing":
            sop_state.update({"ticket_type": "damage", "sop_branch": result.get("sop") or "商品有伤-有开箱视频"})
        elif fx.get("type") == "minor_refund":
            sop_state.update({"ticket_type": "minor_refund", "sop_branch": result.get("sop") or "未成年人退款", "needs_human": True})
        events.append(
            _event(
                state=state,
                event_type="multimodal_fixture",
                status="checked",
                order_id=order_id,
                payload={"fixture_id": fixture_id},
                result=fx,
                idempotency_seed=fixture_id,
            )
        )

    action = {"type": "none", "requires_human": bool(sop_state.get("needs_human"))}
    ticket_type = sop_state.get("ticket_type")
    if ticket_type == "damage" and order_id:
        action = {
            "type": "after_sales_card",
            "card_type": "damage_review",
            "requires_human": True,
            "reason": "商品有伤需人工确认补发/换货，已生成售后处理单",
        }
    elif ticket_type in {"missing", "logistics"} and order_id:
        action = {
            "type": "warehouse_task",
            "task_type": "check_package" if ticket_type == "missing" else "expedite_shipment",
            "requires_human": False,
            "reason": "已生成履约协同任务，用于跨部门核查",
        }
    elif ticket_type == "product_consult":
        action = {
            "type": "product_info",
            "requires_human": False,
            "reason": "按商品信息、预售说明和售后规则回答，不生成订单物流处理单",
        }
    elif ticket_type == "lottery":
        action = {
            "type": "lottery_review",
            "requires_human": False,
            "reason": "按活动规则、奖池公示和抽选记录回答；存在争议时记录复核事项",
        }
    elif ticket_type == "notification_preference":
        action = {
            "type": "service_feedback",
            "requires_human": False,
            "reason": "已记录通知渠道偏好和服务建议，电话/短信触达需客服主管确认能力与授权",
        }
    elif ticket_type in {"refund", "minor_refund", "account_binding"}:
        action = {
            "type": "ticket",
            "requires_human": True,
            "reason": "高风险售后动作只能进入人工授权确认",
        }

    sop_state["state"] = "action_planned"
    sop_state["fixtures"] = fixture_results
    action["task_center"] = _task_center(action, order_id, ticket_type)
    sop_state["planned_action"] = action
    sop_state["review_design"] = _review_design(sop_state, fixture_results, text)
    sop_state["evaluation_tags"] = _evaluation_tags(sop_state, fixture_results)
    sop_state["checklist"] = build_sop_checklist(sop_state, order, fixture_results)
    sop_state["readiness"] = {
        "mode": "local_preview",
        "real_partner_integration": False,
        "data_mode": "demo",
        "source_system": "mitako_fixture",
        "integration_status": "not_connected",
        "prepared_adapters": ["sop_checklist", "business_audit", "task_center", "qc_sop_proposal", "private_domain_task"],
    }
    if action["type"] != "none":
        events.append(
            _event(
                state=state,
                event_type=f"service_{action['type']}",
                status="planned",
                order_id=order_id,
                payload={"ticket_type": ticket_type, "branch": sop_state.get("sop_branch")},
                result=action,
            )
        )
        events.append(
            _event(
                state=state,
                event_type="service_qc_sop_proposal",
                status="drafted",
                order_id=order_id,
                payload={"ticket_type": ticket_type, "branch": sop_state.get("sop_branch")},
                result=_qc_sop_proposal(sop_state, action, order_id),
            )
        )
        events.append(
            _event(
                state=state,
                event_type="service_private_domain_task",
                status="drafted",
                order_id=order_id,
                payload={"ticket_type": ticket_type, "branch": sop_state.get("sop_branch")},
                result=_private_domain_task(sop_state, order_id),
            )
        )

    return {
        "sop_state": sop_state,
        "business_events": events,
        "business_cards": [{"type": "business_action", "data": {"sop": sop_state, "action": action}}],
    }
