# -*- coding: utf-8 -*-
"""私域 Agent P0 规则引擎：规则优先，模型后接。"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from . import store


IP_WORDS = ["蓝色监狱", "蓝锁", "排球少年", "原神", "名侦探柯南", "崩坏", "星穹铁道", "咒术回战"]
WISH_WORDS = ["蹲", "求补", "补货", "想要", "有没有", "再贩", "许愿"]
ECHO_WORDS = ["我也是", "+1", "同问", "一样", "都没", "也没"]
RISK_WORDS = {
    "shipping": ["不发货", "没发货", "什么时候发", "清关没动", "预售太久", "拖了多久"],
    "refund": ["退款", "退钱", "不退", "不到账", "强制代币"],
    "blindbox": ["吞烫", "概率", "黑箱", "暗改", "抽不到"],
    "terms": ["霸王条款", "不合理", "欺负消费者", "协议陷阱"],
    "service": ["客服不回", "没人管", "踢皮球", "敷衍"],
    "complaint": ["黑猫", "12315", "投诉", "报警", "起诉", "维权", "小红书曝光", "微博挂", "诈骗", "跑路"],
}
TERM_ANSWERS = {
    "出荷": "出荷通常指商品从仓库或供应链节点发出，实际进度仍以订单页面和客服核实为准。",
    "再贩": "再贩是商品再次销售或重新开放购买，是否有库存、时间和规则要以活动页面为准。",
    "大赏": "大赏一般指抽赏活动里的高等级奖项，具体奖池、规则和公示以活动页面为准。",
    "小赏": "小赏一般指抽赏活动里的较基础奖项，中奖规则和奖池以当前活动页面为准。",
    "吧唧": "吧唧是徽章类谷子的常见叫法，购买时建议确认尺寸、角色和现货/预售状态。",
    "流麻": "流麻通常指流沙麻将牌类周边，购买时要关注尺寸、材质和包装保护。",
    "隐藏款": "隐藏款是奖池或盲抽里的稀有款式，不应理解为一定能抽中，概率以活动公示为准。",
}


def _visual_workbench_url() -> str:
    configured = os.getenv("VISUAL_WORKBENCH_URL", "").strip().rstrip("/")
    if configured:
        return configured
    port = os.getenv("VISUAL_WORKBENCH_PORT", "7861").strip() or "7861"
    return f"http://127.0.0.1:{port}"


def _multipart_post(url: str, fields: Dict[str, Any], files: List[Dict[str, Any]], timeout: int) -> Dict[str, Any]:
    boundary = f"----MITAKO{uuid4().hex}"
    chunks: List[bytes] = []
    for key, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
            str(value).encode("utf-8"),
            b"\r\n",
        ])
    for item in files:
        chunks.extend([
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{item["field"]}"; '
                f'filename="{item["filename"]}"\r\n'
            ).encode("utf-8"),
            f'Content-Type: {item["mime_type"]}\r\n\r\n'.encode("utf-8"),
            item["content"],
            b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Content-Length", str(len(body)))
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def _review_failure(status: str, message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": status,
        "message": message,
        "summary": {"review_status": "failed", "needs_human_review": True},
    }


def _review_agent_brief(task: Dict[str, Any], payload: Dict[str, Any], ok: bool) -> Dict[str, Any]:
    review = payload.get("review") if isinstance(payload.get("review"), dict) else payload
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    brief = review.get("agent_brief") if isinstance(review.get("agent_brief"), dict) else {}
    diagnostics = review.get("diagnostics") or payload.get("diagnostics") or {}
    if ok:
        conclusion = brief.get("conclusion") or review.get("conclusion") or "视觉审核已完成初筛，仍需VIP客服结合订单与售后规则确认。"
        next_step = brief.get("next_step") or "按初筛结果进入人工售后复核，不自动退款、补发、拒赔或定责。"
    else:
        reason = diagnostics.get("failure_reason") or payload.get("message") or "视觉审核未完成。"
        hint = diagnostics.get("operator_hint") or "请VIP客服人工复核原始素材；服务恢复后可重新发起审核。"
        conclusion = f"视觉审核未完成：{reason}"
        next_step = hint
    return {
        "conclusion": conclusion,
        "confidence": summary.get("confidence") if summary.get("confidence") is not None else brief.get("confidence"),
        "review_status": summary.get("review_status") or ("completed" if ok else "failed"),
        "needs_human_review": True,
        "next_step": next_step,
        "diagnostics": diagnostics if diagnostics else {},
        "task_id": task.get("task_id"),
    }


def _with_agent_brief(task: Dict[str, Any], payload: Dict[str, Any], ok: bool) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else _review_failure("invalid_review_payload", "visual review returned invalid payload")
    brief = _review_agent_brief(task, data, ok)
    if isinstance(data.get("review"), dict):
        data["review"] = {**data["review"], "agent_brief": {**brief, **(data["review"].get("agent_brief") or {})}}
    else:
        data["agent_brief"] = {**brief, **(data.get("agent_brief") or {})}
    return data


def _run_visual_review(task: Dict[str, Any], raw: bytes) -> Dict[str, Any]:
    if os.getenv("MITAKO_AUTO_VISUAL_REVIEW", "1").strip().lower() in {"0", "false", "no"}:
        return task
    timeout = int(os.getenv("VISUAL_REVIEW_CALLBACK_TIMEOUT_SECONDS", "300") or 300)
    base = _visual_workbench_url()
    fields = {
        "scenario": task.get("scenario") or "product_damage",
        "ticket_id": task["task_id"],
        "user_id": task.get("user_id") or "",
        "customer_claim": "用户上传售后审核材料，请生成公开初筛摘要。",
        "review_model": "standard",
        "fps": "1.0",
        "max_frames": "6",
        "api_frame_limit": "4",
        "probe_seconds": "12",
    }
    try:
        if str(task.get("mime_type") or "").startswith("video/"):
            payload = _multipart_post(
                f"{base}/api/review",
                {**fields, "source_type": "upload"},
                [{
                    "field": "file",
                    "filename": task.get("stored_name") or task.get("file_name") or "material.mp4",
                    "mime_type": task.get("mime_type") or "video/mp4",
                    "content": raw,
                }],
                timeout,
            )
        else:
            payload = _multipart_post(
                f"{base}/api/review-folder",
                fields,
                [{
                    "field": "files",
                    "filename": task.get("stored_name") or task.get("file_name") or "material.jpg",
                    "mime_type": task.get("mime_type") or "image/jpeg",
                    "content": raw,
                }],
                timeout,
            )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        payload = _review_failure("visual_review_unavailable", str(exc)[:180])

    ok = bool(payload.get("ok"))
    payload = _with_agent_brief(task, payload, ok)
    status = "REVIEW_COMPLETED" if ok else "REVIEW_FAILED"
    boundary = "视觉审核已完成初筛，仍需VIP客服结合订单与售后规则确认。" if ok else "视觉审核未完成，需VIP客服人工复核或稍后重试。"
    return store.update_review_task_result(task["task_id"], status=status, result=payload, boundary=boundary)


def run_visual_review_for_task(task_id: str) -> Dict[str, Any]:
    task = store.get_review_task(task_id)
    if not task:
        return {}
    path = store.upload_dir() / str(task.get("stored_name") or "")
    if not path.exists():
        return store.update_review_task_result(
            task_id,
            status="REVIEW_FAILED",
            result=_review_failure("material_file_missing", "stored material file not found"),
            boundary="视觉审核未完成，需VIP客服人工复核或重新上传材料。",
        )
    return _run_visual_review(task, path.read_bytes())


DEMO_GROUP_MESSAGES = [
    {
        "group_id": "wx_xt_bluelock_001",
        "group_name": "蓝锁凪玲补货 01 群",
        "owner_id": "op_private_01",
        "member_count": 486,
        "user_id": "external_demo_001",
        "external_user_id": "wm_user_001",
        "content": "蓝色监狱凪诚士郎吧唧有没有再贩？想要蹲补货，隐藏款概率怎么看？",
        "message_id": "demo-msg-001",
        "source": "demo_seed",
    },
    {
        "group_id": "wx_xt_haikyu_002",
        "group_name": "排球少年横断幕谷 02 群",
        "owner_id": "op_private_02",
        "member_count": 352,
        "user_id": "external_demo_002",
        "external_user_id": "wm_user_002",
        "content": "排球少年明信片求补货，想蹲影山和日向的现货，吧唧尺寸也想确认。",
        "message_id": "demo-msg-002",
        "source": "demo_seed",
    },
    {
        "group_id": "wx_xt_genshin_003",
        "group_name": "原神手办预售 03 群",
        "owner_id": "op_private_03",
        "member_count": 618,
        "user_id": "external_demo_003",
        "external_user_id": "wm_user_003",
        "content": "原神流麻和手办有没有新到货？预售多久能出荷，想要许愿雷电将军。",
        "message_id": "demo-msg-003",
        "source": "demo_seed",
    },
    {
        "group_id": "wx_xt_conan_004",
        "group_name": "柯南现货交换 04 群",
        "owner_id": "op_private_04",
        "member_count": 275,
        "user_id": "external_demo_004",
        "external_user_id": "wm_user_004",
        "content": "名侦探柯南安室透小赏还有吗？蹲一个补货提醒，想看小程序链接。",
        "message_id": "demo-msg-004",
        "source": "demo_seed",
    },
    {
        "group_id": "wx_xt_shipping_risk_005",
        "group_name": "蓝锁预售催发 05 群",
        "owner_id": "op_private_05",
        "member_count": 531,
        "user_id": "external_demo_005",
        "external_user_id": "wm_user_005",
        "content": "蓝锁这批怎么还不发货，我也是等很久了，都没人说明什么时候发。",
        "message_id": "demo-msg-005",
        "source": "demo_seed",
    },
    {
        "group_id": "wx_xt_blindbox_risk_006",
        "group_name": "抽赏争议 06 群",
        "owner_id": "op_private_06",
        "member_count": 744,
        "user_id": "external_demo_006",
        "external_user_id": "wm_user_006",
        "content": "这次抽赏是不是吞烫？概率看起来不对，客服不回，霸王条款太离谱。",
        "message_id": "demo-msg-006",
        "source": "demo_seed",
    },
    {
        "group_id": "wx_xt_complaint_007",
        "group_name": "售后维权关注 07 群",
        "owner_id": "op_private_07",
        "member_count": 298,
        "user_id": "external_demo_007",
        "external_user_id": "wm_user_007",
        "content": "退款不到账还没人管，再不处理就 12315 投诉，也准备小红书曝光。",
        "message_id": "demo-msg-007",
        "source": "demo_seed",
    },
    {
        "group_id": "wx_xt_daily_008",
        "group_name": "日常问答 08 群",
        "owner_id": "op_private_08",
        "member_count": 189,
        "user_id": "external_demo_008",
        "external_user_id": "wm_user_008",
        "content": "大赏和小赏区别是什么？隐藏款是不是一定会出？",
        "message_id": "demo-msg-008",
        "source": "demo_seed",
    },
]

DEMO_PRODUCT_EVENTS = [
    {
        "event_id": "PD-DEMO-PROD-001",
        "event_type": "restock",
        "item_id": "SKU-BLUELOCK-NAGI-BADGE-75",
        "ip_name": "蓝色监狱",
        "character_name": "凪诚士郎",
        "category": "吧唧",
        "price": 39.9,
        "stock": 320,
        "rarity": "normal",
        "mini_program_path": "/pages/item/detail?id=SKU-BLUELOCK-NAGI-BADGE-75",
        "app_deep_link": "mitako://item/SKU-BLUELOCK-NAGI-BADGE-75",
    },
    {
        "event_id": "PD-DEMO-PROD-002",
        "event_type": "new_arrival",
        "item_id": "SKU-HAIKYU-POSTCARD-SET",
        "ip_name": "排球少年",
        "character_name": "影山飞雄",
        "category": "明信片",
        "price": 28.0,
        "stock": 180,
        "rarity": "limited",
        "mini_program_path": "/pages/item/detail?id=SKU-HAIKYU-POSTCARD-SET",
        "app_deep_link": "mitako://item/SKU-HAIKYU-POSTCARD-SET",
    },
    {
        "event_id": "PD-DEMO-PROD-003",
        "event_type": "stock_alert",
        "item_id": "SKU-GENSHIN-FIGURE-RAIDEN",
        "ip_name": "原神",
        "character_name": "雷电将军",
        "category": "手办",
        "price": 399.0,
        "stock": 46,
        "rarity": "rare",
        "risk_flag": "fulfillment_risk",
        "mini_program_path": "/pages/item/detail?id=SKU-GENSHIN-FIGURE-RAIDEN",
        "app_deep_link": "mitako://item/SKU-GENSHIN-FIGURE-RAIDEN",
    },
    {
        "event_id": "PD-DEMO-PROD-004",
        "event_type": "rare_drop",
        "item_id": "SKU-CONAN-AMURO-LOTTERY-A",
        "ip_name": "名侦探柯南",
        "character_name": "安室透",
        "category": "抽赏",
        "price": 59.0,
        "stock": 24,
        "rarity": "rare",
        "mini_program_path": "/pages/lottery/detail?id=SKU-CONAN-AMURO-LOTTERY-A",
        "app_deep_link": "mitako://lottery/SKU-CONAN-AMURO-LOTTERY-A",
    },
]

DEMO_REVIEW_TASKS = [
    {
        "task_id": "RV-DEMO-VIDEO-001",
        "user_id": "external_demo_003",
        "session_id": "demo-session-video-001",
        "tenant_id": "mitako",
        "source": "demo_seed",
        "scenario": "video_unboxing",
        "file_name": "开箱缺件视频.mp4",
        "stored_name": "RV-DEMO-VIDEO-001.mp4",
        "mime_type": "video/mp4",
        "size": 18_432_000,
        "status": "MATERIAL_READY",
        "boundary": "演示任务：视频材料已生成审核任务；真实生产需接视频审核模型或人工复核。",
    },
    {
        "task_id": "RV-DEMO-IMAGE-002",
        "user_id": "external_demo_006",
        "session_id": "demo-session-image-002",
        "tenant_id": "mitako",
        "source": "demo_seed",
        "scenario": "product_damage",
        "file_name": "吧唧划痕照片.jpg",
        "stored_name": "RV-DEMO-IMAGE-002.jpg",
        "mime_type": "image/jpeg",
        "size": 2_468_000,
        "status": "MATERIAL_READY",
        "boundary": "演示任务：图片材料已生成审核任务；真实生产不在群内公开定责。",
    },
]


def integration_contracts() -> List[Dict[str, Any]]:
    return [
        {
            "key": "wechat_group_message",
            "name": "企微群消息入站",
            "status": "contract_pending",
            "method": "POST",
            "endpoint": "/api/v1/private-domain/group-message",
            "auth": "Bearer 管理员或集成 Token",
            "fields": ["group_id", "group_name", "external_user_id", "user_id", "content", "message_id", "sent_at", "source"],
            "owner": "企微服务商或甲方 Server",
            "note": "用于接会话存档或群机器人转发；当前本地已实现入站处理，不代表已拿到企微权限。",
        },
        {
            "key": "product_event",
            "name": "商品/抽赏/库存事件",
            "status": "local_contract_ready",
            "method": "POST",
            "endpoint": "/api/v1/private-domain/product-event",
            "auth": "Bearer 管理员或集成 Token",
            "fields": ["event_id", "event_type", "item_id", "ip_name", "character_name", "category", "price", "stock", "rarity", "mini_program_path", "app_deep_link", "risk_flag"],
            "owner": "商品库、抽赏系统、库存系统",
            "note": "本地可生成候选触达；真实上线需商品库提供字段、库存时效和履约风险回传。",
        },
        {
            "key": "customer_service_agent",
            "name": "客服任务协同",
            "status": "local_contract_ready",
            "method": "事件/接口回写",
            "endpoint": "customer_service_tasks",
            "auth": "后台内部角色权限",
            "fields": ["task_id", "user_id", "external_user_id", "group_id", "risk_level", "issue_type", "message_summary", "evidence_messages", "priority", "required_action"],
            "owner": "客服 Agent / 人工客服工作台",
            "note": "私域 Agent 只传证据摘要和处理建议，订单、退款、补偿仍由客服系统确认。",
        },
        {
            "key": "feishu_task_sync",
            "name": "飞书任务/群协同",
            "status": "contract_pending",
            "method": "待甲方 CLI / Bot 权限确认",
            "endpoint": "待联调：飞书任务、飞书群、审批或多维表格",
            "auth": "飞书 App 凭证与可用 API 范围",
            "fields": ["task_id", "owner", "status", "trace_id", "due_at", "result", "callback_url"],
            "owner": "飞书 CLI / 飞书开放平台",
            "note": "用于主管预警、日复盘和客服跟进；当前只展示契约，不伪装已创建飞书任务。",
        },
        {
            "key": "review_task_upload",
            "name": "用户图片/视频材料审核",
            "status": "local_contract_ready",
            "method": "POST multipart/form-data",
            "endpoint": "/api/v1/private-domain/review-tasks",
            "auth": "用户 Token 或开发鉴权旁路",
            "fields": ["user_id", "session_id", "source", "file"],
            "owner": "用户端照片、拍摄、视频上传",
            "note": "已能生成审核任务；视频审核 Key 和 Gemini 多模态 Key 只应通过本地环境配置，不提交到 Git。",
        },
        {
            "key": "review_job_service",
            "name": "甲方售后案件审核服务",
            "status": "local_contract_ready",
            "method": "POST multipart/form-data + GET 状态查询",
            "endpoint": "/api/v1/review/jobs",
            "auth": "Bearer 集成账号 Token + Idempotency-Key",
            "fields": ["client_case_id", "scenario", "ticket_id", "order_no", "customer_claim", "order_items", "product_master_data", "warehouse_master_data", "logistics", "conversation_history", "sop_context", "files"],
            "owner": "甲方客服 Server / 工单系统",
            "note": "每个案件支持多图、多视频和结构化上下文；批量任务由甲方并发提交，结果按 job_id 独立查询和重试。",
        },
    ]


def demo_script() -> List[Dict[str, str]]:
    return [
        {"step": "1", "title": "加载演示数据", "body": "点击后台按钮后生成 8 个群、4 个商品事件、2 个材料审核任务，并产生客服协同任务。"},
        {"step": "2", "title": "演示群消息入站", "body": "提交企微群消息契约字段，系统更新群画像、识别术语/许愿/风险，并在 L2+ 生成客服任务。"},
        {"step": "3", "title": "演示商品事件入站", "body": "提交商品补货或稀有掉落事件，系统按 IP、库存和风险状态生成待审核触达候选。"},
        {"step": "4", "title": "演示协同边界", "body": "页面展示企微、商品库、客服 Agent、飞书和材料审核的状态，明确哪些本地已就绪、哪些等待真实权限联调。"},
    ]


def _extract_tags(text: str) -> Dict[str, List[str]]:
    return {
        "ip": [word for word in IP_WORDS if word in text],
        "wish": [word for word in WISH_WORDS if word in text],
        "risk_terms": [word for words in RISK_WORDS.values() for word in words if word in text],
    }


def _risk_type(text: str) -> str:
    for issue_type in ("complaint", "terms", "blindbox", "service", "refund", "shipping"):
        words = RISK_WORDS[issue_type]
        if any(word in text for word in words):
            return issue_type
    return ""


def _risk_level(text: str) -> int:
    issue_type = _risk_type(text)
    if not issue_type:
        return 0
    if issue_type == "complaint":
        return 4
    if any(word in text for word in ECHO_WORDS):
        return 2
    if issue_type in {"blindbox", "terms", "service"}:
        return 3
    return 1


def _qa_reply(text: str, risk_level: int) -> str:
    if risk_level >= 2:
        return "大家的反馈我们已经看到。具体订单和售后问题需要结合订单状态核实，群里不方便公开处理，请先转 1 对 1 客服跟进。"
    for term, answer in TERM_ANSWERS.items():
        if term in text:
            return answer
    return ""


def process_group_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    group_id = (payload.get("group_id") or "").strip()
    if not group_id:
        raise ValueError("group_id_required")
    content = (payload.get("content") or "").strip()
    if not content:
        raise ValueError("content_required")

    tags = _extract_tags(content)
    risk_level = _risk_level(content)
    now = time.time()
    disabled_until = now + (12 * 3600 if risk_level == 2 else 72 * 3600 if risk_level >= 3 else 0)
    status = "marketing_disabled" if risk_level >= 2 else "normal"
    group = store.upsert_group({
        "group_id": group_id,
        "group_name": payload.get("group_name") or group_id,
        "owner_id": payload.get("owner_id") or "",
        "member_count": int(payload.get("member_count") or 0),
        "status": status,
        "risk_level": risk_level,
        "health_score": max(0, 100 - risk_level * 22),
        "marketing_disabled_until": disabled_until if risk_level >= 2 else 0,
        "tags": tags,
        "metrics": {
            "last_message_at": now,
            "last_negative": risk_level > 0,
            "last_wish": bool(tags["wish"]),
        },
    })

    issue_type = _risk_type(content)
    task = None
    if risk_level >= 2:
        task = store.create_customer_service_task({
            "task_id": f"PD-CS-{uuid4().hex[:10].upper()}",
            "user_id": payload.get("user_id") or "",
            "external_user_id": payload.get("external_user_id") or "",
            "group_id": group_id,
            "risk_level": risk_level,
            "issue_type": issue_type or "group_risk",
            "message_summary": content[:180],
            "evidence_messages": [content],
            "priority": "urgent" if risk_level >= 3 else "high",
            "required_action": "群内极简安抚，暂停营销，并转 1 对 1 客服核实。",
        })

    result = {
        "group": group,
        "risk_level": risk_level,
        "risk_type": issue_type,
        "need_disable_marketing": risk_level >= 2,
        "need_customer_service": risk_level >= 2,
        "need_supervisor_alert": risk_level >= 3,
        "reply": _qa_reply(content, risk_level),
        "tags": tags,
        "customer_service_task": task,
        "boundary": "规则快筛结果仅用于 POC 流程验证；真实生产需接入企微会话存档、上下文窗口和人工复核。",
    }
    store.add_event("group_message", payload, result, group_id=group_id, user_id=payload.get("user_id") or "")
    return result


def process_product_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    event_id = (payload.get("event_id") or f"PD-EVT-{uuid4().hex[:8].upper()}").strip()
    event = {**payload, "event_id": event_id}
    store.save_product_event(event)
    candidates: List[Dict[str, Any]] = []
    for group in store.list_groups(limit=200):
        tags = group.get("tags") or {}
        group_ips = set(tags.get("ip") or [])
        score = 0
        reasons = []
        if event.get("risk_flag"):
            candidates.append({"group_id": group["group_id"], "match_score": 0, "decision": "blocked", "reason": "商品存在履约/售后风险，不自动推送"})
            continue
        if int(group.get("risk_level") or 0) >= 2 or group.get("status") == "marketing_disabled":
            candidates.append({"group_id": group["group_id"], "match_score": 0, "decision": "blocked", "reason": "群处于风险或禁推状态"})
            continue
        if event.get("ip_name") and event.get("ip_name") in group_ips:
            score += 60
            reasons.append("IP 匹配")
        if event.get("character_name") and event.get("character_name") in str(tags):
            score += 20
            reasons.append("角色匹配")
        if int(event.get("stock") or 0) > 0:
            score += 10
            reasons.append("有库存")
        decision = "review" if score >= 60 else "skip"
        reason = "、".join(reasons) if reasons else "缺少可解释匹配信号"
        candidates.append({"group_id": group["group_id"], "match_score": score, "decision": decision, "reason": reason})

    for item in candidates:
        store.add_campaign_candidate(event_id, item["group_id"], item["match_score"], item["decision"], item["reason"])
    result = {
        "event": event,
        "candidates": candidates,
        "review_required": True,
        "boundary": "吃谷雷达 P0 只生成待审核推送建议，不直接群发。",
    }
    store.add_event("product_event", event, result)
    return result


def create_review_task_from_upload(
    *,
    user_id: str,
    session_id: str,
    tenant_id: str,
    file_name: str,
    mime_type: str,
    raw: bytes,
    source: str = "customer_upload",
    run_review: bool = True,
) -> Dict[str, Any]:
    if not raw:
        raise ValueError("empty_file")
    if len(raw) > 300 * 1024 * 1024:
        raise ValueError("file_too_large")
    if not (mime_type.startswith("image/") or mime_type.startswith("video/")):
        raise ValueError("unsupported_review_material")

    task_id = f"RV-{uuid4().hex[:12].upper()}"
    safe_name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", Path(file_name or "material").name).strip("._") or "material"
    ext = Path(safe_name).suffix.lower()
    stored_name = f"{task_id}{ext}"
    path = store.upload_dir() / stored_name
    path.write_bytes(raw)
    scenario = "video_unboxing" if mime_type.startswith("video/") else "product_damage"
    task = store.create_review_task({
        "task_id": task_id,
        "user_id": user_id,
        "session_id": session_id,
        "tenant_id": tenant_id,
        "source": source,
        "scenario": scenario,
        "file_name": safe_name,
        "stored_name": stored_name,
        "mime_type": mime_type,
        "size": len(raw),
        "status": "MATERIAL_READY",
        "boundary": "材料已接收并生成审核任务；当前不自动定责，需视觉审核工作台或人工客服继续处理。",
    })
    return _run_visual_review(task, raw) if run_review else task


def clear_demo_data() -> Dict[str, Any]:
    removed = store.clear_all_private_domain_data()
    return {
        "removed": removed,
        "snapshot": store.snapshot(),
        "demo_ready": False,
    }


def load_demo_data() -> Dict[str, Any]:
    clear_demo_data()
    group_results = [process_group_message(payload) for payload in DEMO_GROUP_MESSAGES]
    product_results = [process_product_event(payload) for payload in DEMO_PRODUCT_EVENTS]
    review_tasks = [store.create_review_task(task) for task in DEMO_REVIEW_TASKS]
    snapshot = store.snapshot()
    return {
        "snapshot": snapshot,
        "demo_ready": snapshot.get("group_count", 0) > 0,
        "summary": {
            "groups": len(group_results),
            "product_events": len(product_results),
            "review_tasks": len(review_tasks),
            "customer_service_tasks": snapshot.get("pending_task_count", 0),
            "campaign_candidates": len(store.list_campaign_candidates(limit=200)),
        },
        "demo_script": demo_script(),
        "integration_contracts": integration_contracts(),
    }


def dashboard_payload() -> Dict[str, Any]:
    snapshot = store.snapshot()
    return {
        "snapshot": snapshot,
        "groups": store.list_groups(limit=20),
        "events": store.list_events(limit=20),
        "customer_service_tasks": store.list_customer_service_tasks(limit=20),
        "review_tasks": store.list_review_tasks(limit=20),
        "campaign_candidates": store.list_campaign_candidates(limit=30),
        "demo_ready": snapshot.get("group_count", 0) > 0 or snapshot.get("event_count", 0) > 0,
        "demo_script": demo_script(),
        "integration_contracts": integration_contracts(),
        "interface_status": {
            "wechat_group_read": "contract_pending",
            "wechat_group_send": "contract_pending",
            "product_event_ingest": "local_contract_ready",
            "product_catalog": "contract_pending",
            "order_system": "contract_pending",
            "customer_service_agent": "local_contract_ready",
            "feishu_task_sync": "contract_pending",
            "visual_review_task": "local_contract_ready",
            "review_job_service": "local_contract_ready",
        },
    }
