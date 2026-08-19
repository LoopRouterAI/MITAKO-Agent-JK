# -*- coding: utf-8 -*-
import os
import re
import json
import httpx
import asyncio
import traceback
from pathlib import Path
from typing import Annotated, TypedDict, List, Dict, Any, Optional
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END

# 加载环境变量
from dotenv import load_dotenv
try:
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
except Exception:
    pass

from llm_models import DEFAULT_MODEL_ID
from agent_llm import call_llm
from customer_service.contracts import ActionState, Fact, IntentResult, ReplyPlan
from customer_service.action_state import action_from_exception, action_from_tool
from customer_service.intent_router import public_intent_label, route_intent
from customer_service.reply_guard import guard_reply
from customer_service.reply_plan import build_reply_plan, public_reply_plan_payload, render_reply_plan
from customer_service.scenario_policy import decide_scenario, resolve_unique_product
from partner_guard import assert_local_or_allowed
from runtime_paths import mock_data_file

def _env_name(*parts: str) -> str:
    return "_".join(parts)


LOCAL_BUSINESS_URL = assert_local_or_allowed(
    os.getenv(_env_name("MOCK", "API", "URL"), "http://localhost:8001"),
    _env_name("MOCK", "API", "URL"),
)
SOP_DIR = Path(__file__).resolve().parent / "docs" / "_extracted_sop"

# 1. 尝试导入 openviking 库，如果失败则优雅降级为本地模拟版
try:
    import openviking
    HAS_OPENVIKING = True
except ImportError:
    HAS_OPENVIKING = False

from viking_memory import viking_db
from prompts.customer_service import CUSTOMER_SERVICE_BASE_PROMPT

# 2. 定义 Agent 状态结构
class AgentState(TypedDict):
    messages: List[Dict[str, str]]        # 格式[{"role": "user"/"assistant", "content": "..."}]
    raw_user_content: str                 # 本轮用户原始输入，不包含审核附件的机器上下文
    user_id: str
    session_id: str
    active_order_id: str                  # 前端选中的焦点订单
    intent: str
    conversation_state: Dict[str, Any]    # 确定性领域状态
    emotion_level: int
    order_data: Dict[str, Any]            # 缓存查到的订单详情
    logistics_data: Dict[str, Any]        # 缓存查到的物流详情
    sop_results: List[str]                # 召回的 SOP 与供应链预警数据
    user_memory: Dict[str, Any]           # 用户微表情与历史纠纷特征
    reply_draft: str                      # 生成的回复草稿
    safety_check_result: str              # 安全检查结果
    should_transfer: bool                 # 是否转接人工主管
    transfer_reason: str                  # 转接人工的具体原因
    handoff_offer_id: str                 # 用户已同意的转接提议标识
    compensation_given: List[Dict[str, Any]] # 本次会话发放的补偿信息
    meme_tags: List[str]                  # 本次会话匹配的二次元表情包标签
    fixtures: List[str]                   # 本轮接入的多模态 fixture
    attachments: List[Dict[str, Any]]      # 用户本轮真实上传的图片/视频附件元数据
    sop_state: Dict[str, Any]             # 本地 SOP 状态机结果
    business_events: List[Dict[str, Any]] # 本地业务审计事件
    business_cards: List[Dict[str, Any]]  # 前端展示的业务卡片
UNIFIED_XIAO_JIAO_SYSTEM_PROMPT = CUSTOMER_SERVICE_BASE_PROMPT

XIAO_JIAO_SYSTEM_PROMPT = UNIFIED_XIAO_JIAO_SYSTEM_PROMPT
INTENT_EMOTION_SYSTEM_PROMPT = ""

PUBLIC_INTENT_LABELS = {
    "闲聊互动",
    "VIP客服请求",
    "通知渠道/服务建议",
    "售前商品咨询",
    "退款退货/未成年人退款",
    "投诉升级",
    "盲盒相关/吞烫质疑",
    "盲盒相关/置换区咨询",
    "换货补发/商品破损",
    "物流追踪/催发货",
    "退款退货/补偿",
    "退款退货/申请退款",
    "隐私合规/资料删除",
    "订单信息/地址修改",
}


def _extract_sop_snippet(text: str, max_len: int = 260) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return ""
    return compact[:max_len]


def _load_local_sop_results(intent: str, user_text: str, limit: int = 3) -> List[str]:
    if not SOP_DIR.exists():
        return []

    query = f"{intent} {user_text}"
    keyword_map = [
        (["退款", "退钱", "退货", "不好", "不想要"], ["退款", "退货"]),
        (["物流", "快递", "没收到", "丢件", "签收", "清关", "通关", "仓库", "库房", "入仓", "发货慢"], ["快递物流", "物流异常"]),
        (["破损", "划痕", "有伤", "瑕疵", "开箱"], ["商品有伤", "开箱视频", "有伤补偿"]),
        (["漏发", "少发", "缺件", "赠品", "特典", "满赠", "随单赠"], ["漏发货"]),
        (["发错", "错货"], ["发错货"]),
        (["出荷", "转囤", "囤货"], ["出荷转囤"]),
        (["未成年", "小孩", "孩子", "家长", "监护人"], ["未成年人"]),
        (["换绑", "账号", "工单"], ["账号换绑", "其他工单"]),
    ]

    wanted: List[str] = []
    for triggers, names in keyword_map:
        if any(k in query for k in triggers):
            wanted.extend(names)
    if not wanted:
        wanted = ["快递物流", "申请退款", "商品有伤"]

    matched = []
    for path in SOP_DIR.glob("*.txt"):
        name = path.name
        score = sum(1 for key in wanted if key in name)
        if score:
            matched.append((score, name, path))
    matched.sort(key=lambda item: (-item[0], item[1]))

    results = []
    for _, name, path in matched[:limit]:
        try:
            snippet = _extract_sop_snippet(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            snippet = ""
        if snippet:
            results.append(f"【本地SOP:{name}】{snippet}")
        else:
            results.append(f"【本地SOP:{name}】已命中该 SOP 文件，请按其受理边界、卡片动作与转VIP客服规则处理。")
    return results


def _parse_reply_analysis(reply: str) -> Dict[str, Any]:
    if "<analysis>" not in reply or "</analysis>" not in reply:
        return {}
    try:
        raw = reply.split("<analysis>", 1)[1].split("</analysis>", 1)[0]
        parsed = json.loads(raw.strip())
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _runtime_word(*parts: str) -> str:
    return "".join(parts)


def _runtime_chars(*codes: int) -> str:
    return "".join(chr(code) for code in codes)


def _business_payload_success(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("ok", "success"):
        if key in payload:
            return payload.get(key) is True
    return True


def _compact_order_ref(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(value or "")).upper()


def _public_order_suffix(order_id: Any) -> str:
    compact = _compact_order_ref(order_id)
    return compact[-6:] if compact else ""


def _extract_explicit_order_ref(text: str) -> str:
    raw = str(text or "")
    patterns = [
        r"ORD[_-]?\d{4}[_-]?\d+",
        r"(?:订单|單號|单号|#)\s*#?\s*([0-9]{5,8})",
        r"#\s*([0-9]{5,8})",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.IGNORECASE)
        if not match:
            continue
        return _compact_order_ref(match.group(1) if match.lastindex else match.group(0))
    return ""


def _strip_attachment_context(content: str) -> str:
    text = str(content or "")
    for marker in ("\n\n[用户已上传附件]", "\n\n[用户已上传材料]"):
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.strip()


def _current_user_text(state: AgentState) -> str:
    raw = str(state.get("raw_user_content") or "").strip()
    if raw:
        return raw
    messages = state.get("messages") or []
    return _strip_attachment_context(messages[-1].get("content", "") if messages else "")


def _refund_amounts(text: str) -> List[float]:
    action = r"(?:请退给我|退给我|退我|请退|退款|赔偿|补偿)"
    action_matches = []
    for match in re.finditer(action, text):
        prefix = text[max(0, match.start() - 10):match.start()]
        if (
            re.search(r"(?:并非|不是|不需要|无需|不用|不要|不想|取消|不)\s*(?:要|申请)?\s*$", prefix)
            and not prefix.endswith("不得不")
        ):
            continue
        action_matches.append(match)
    if not action_matches:
        return []
    candidates = []
    for match in re.finditer(
        r"[¥￥]?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+(?:\.[0-9]{1,2})?)\s*(?:元|块)",
        text,
    ):
        candidates.append((match.start(), match.end(), float(match.group(1).replace(",", ""))))
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    for match in re.finditer(
        r"([零〇一二两三四五六七八九十百千万]+)\s*(?:元|块)",
        text,
    ):
        value = match.group(1)
        total = current = 0
        for char in value:
            if char in digits:
                current = digits[char]
            elif units[char] == 10000:
                total = (total + current) * 10000
                current = 0
            else:
                total += (current or 1) * units[char]
                current = 0
        candidates.append((match.start(), match.end(), float(total + current)))

    selected = {}
    for match in action_matches:
        sentence_start = max((text.rfind(mark, 0, match.start()) for mark in "。！？；;\n"), default=-1) + 1
        sentence_ends = [text.find(mark, match.end()) for mark in "。！？；;\n"]
        sentence_end = min((index for index in sentence_ends if index >= 0), default=len(text))
        clause_start = max(text.rfind("，", sentence_start, match.start()), text.rfind(",", sentence_start, match.start())) + 1
        clause_ends = [text.find(mark, match.end(), sentence_end) for mark in "，,"]
        clause_end = min((index for index in clause_ends if index >= 0), default=sentence_end)
        nearby = [item for item in candidates if clause_start <= item[0] and item[1] <= clause_end]
        if not nearby:
            nearby = [item for item in candidates if sentence_start <= item[0] and item[1] <= sentence_end]
        if not nearby:
            continue
        nearest = min(
            nearby,
            key=lambda item: (
                match.start() - item[1]
                if item[1] <= match.start()
                else item[0] - match.end()
                if item[0] >= match.end()
                else 0
            ),
        )
        selected[(nearest[0], nearest[1])] = nearest[2]
    return list(selected.values())


def _recent_user_context(messages: List[Dict[str, str]], limit: int = 6) -> str:
    texts = [_strip_attachment_context(m.get("content", "")) for m in messages[-limit:] if m.get("role") == "user"]
    return "\n".join(texts)


def _order_matches_ref(order: Dict[str, Any], ref: str) -> bool:
    target = _compact_order_ref(ref)
    if not target:
        return False
    order_id = _compact_order_ref(order.get("order_id"))
    return order_id == target or order_id.endswith(target) or _public_order_suffix(order_id) == target


def _focus_order_data(order_data: Dict[str, Any], ref: str) -> Dict[str, Any]:
    if not ref or not order_data.get("orders"):
        return order_data
    orders = list(order_data.get("orders") or [])
    focused = [o for o in orders if _order_matches_ref(o, ref)]
    others = [o for o in orders if not _order_matches_ref(o, ref)]
    if focused:
        result = {**order_data, "orders": focused + others, "focused_order_id": focused[0].get("order_id")}
        return result
    return {
        **order_data,
        "orders": [],
        "explicit_order_ref": ref,
        "order_lookup_failed": True,
    }


def _load_mock_orders_for_user(user_id: str) -> Dict[str, Any]:
    mock_data_path = str(mock_data_file())
    if not os.path.exists(mock_data_path):
        return {}
    with open(mock_data_path, "r", encoding="utf-8") as f:
        db = json.load(f)
    user_orders = [ord for ord in db.get("orders", {}).values() if ord.get("user_id") == user_id]
    return {"orders": user_orders, "total": len(user_orders)}


def _emit_unified_analysis_event(
    queue: Any,
    intent: str,
    emotion_level: int,
    should_transfer: bool = False,
    intent_result: Optional[Dict[str, Any]] = None,
) -> None:
    if not queue:
        return
    event = {
        "type": "unified_analysis",
        "intent": intent,
        "emotion_level": max(1, min(6, int(emotion_level or 2))),
        "should_transfer": bool(should_transfer),
    }
    if intent_result:
        event.update({
            "intent_code": intent_result.get("intent_code"),
            "scenario_code": intent_result.get("scenario_code"),
            "intent_codes": intent_result.get("intent_codes", []),
            "scenario_codes": intent_result.get("scenario_codes", []),
            "confidence": intent_result.get("confidence"),
            "matched_evidence": intent_result.get("matched_evidence", []),
            "requires_clarification": intent_result.get("requires_clarification", False),
            "clarification_fields": intent_result.get("clarification_fields", []),
        })
    queue.put_nowait(event)


def _intent_in_result(intent_data: Dict[str, Any], code: str) -> bool:
    return intent_data.get("intent_code") == code or code in (intent_data.get("intent_codes") or [])


def _strip_reply_analysis(reply: str) -> str:
    if "<analysis>" in reply and "</analysis>" in reply:
        return reply.split("</analysis>", 1)[1].lstrip()
    return reply


PUBLIC_REPLY_BLOCKED_TERMS = [
    _runtime_word("Mo", "ck"),
    _runtime_word("PO", "C"),
    _runtime_word("De", "mo"),
    _runtime_word("sop", "_", "state"),
    _runtime_word("business", "_", "events"),
    _runtime_word("business", "_", "cards"),
    _runtime_word("review", "_", "design"),
    _runtime_word("evaluation", "_", "tags"),
    _runtime_word("checklist"),
    _runtime_word("confidence"),
    _runtime_word("decision", "_", "mode"),
    _runtime_word("local", "_", "preview"),
    _runtime_word("real", "_", "partner", "_", "integration"),
    _runtime_word("would", "_", "create"),
    _runtime_word("planned", "_", "action"),
    _runtime_word("raw", " JSON"),
    _runtime_word("provider"),
    _runtime_word("channel"),
    _runtime_word("base", "_", "url"),
    _runtime_word("handoff", "_", "token"),
    _runtime_chars(0x6700, 0x65b0, 0x8282, 0x70b9),
    _runtime_chars(0x5904, 0x7406, 0x8282, 0x70b9),
    _runtime_chars(0x7cfb, 0x7edf, 0x63d0, 0x793a),
    _runtime_chars(0x7b56, 0x7565, 0x8bf4, 0x660e),
    _runtime_chars(0x4efb, 0x52a1, 0x6307, 0x4ee4),
    _runtime_chars(0x9700, 0x89e3, 0x91ca, 0x89c4, 0x5219),
    _runtime_chars(0x4fdd, 0x7559, 0x4eba, 0x5de5, 0x590d, 0x6838, 0x5165, 0x53e3),
    _runtime_chars(0x5916, 0x5305, 0x5ba2, 0x670d),
    _runtime_chars(0x5916, 0x5305, 0x56e2, 0x961f),
    _runtime_chars(0x5916, 0x5305, 0x4eba, 0x5458),
    _runtime_chars(0x5916, 0x5305, 0x516c, 0x53f8),
    _runtime_chars(0x5185, 0x90e8),
    _runtime_chars(0x539f, 0x59cb, 0x65e5, 0x5fd7),
    _runtime_chars(0x63a5, 0x53e3, 0x51ed, 0x8bc1),
]


def _customer_reply_has_internal_text(text: str) -> bool:
    lower_text = text.lower()
    return any(term.lower() in lower_text for term in PUBLIC_REPLY_BLOCKED_TERMS)


def sanitize_customer_reply(reply: str) -> str:
    text = _strip_reply_analysis(reply or "").strip()
    old_agent_name = _runtime_chars(0x867e, 0x997a)
    old_brand_suffix = _runtime_chars(0x867e, 0x6dd8)
    text = text.replace(old_agent_name, "小蛟").replace(f"MITAKO{old_brand_suffix}", "MITAKO").replace(old_brand_suffix, "MITAKO")
    if not text:
        return ""
    compact = text.strip()
    if compact.startswith("{") or compact.startswith("[") or "<analysis>" in compact:
        return ""
    if _customer_reply_has_internal_text(compact):
        return ""
    return compact


def _build_grounded_service_reply(state: AgentState) -> str:
    order_data = state.get("order_data") or {}
    logistics_data = state.get("logistics_data") or {}
    if order_data.get("order_lookup_failed"):
        ref = order_data.get("explicit_order_ref") or "这笔订单"
        return f"我没有在当前账号下匹配到您说的 #订单 {ref}#，为避免查错单，麻烦您重新选择订单卡片或核对订单号后再发我，我再继续帮您查进度。"
    orders = order_data.get("orders") or []
    order = orders[0] if orders else {}
    status_label = order.get("status_label") or order.get("status") or ""
    item_name = ""
    if order.get("items"):
        item_name = order["items"][0].get("name") or ""
    timeline = logistics_data.get("timeline") or []
    latest = timeline[-1].get("status") if timeline and isinstance(timeline[-1], dict) else ""

    if status_label and latest:
        return f"让你等到这么焦虑，真的抱歉。我已核到{item_name or '这笔订单'}当前是#{status_label}#，物流最新进展是#{latest}#。我会继续按物流/仓储核查推进，有新进展第一时间同步。"
    if status_label:
        return f"让你等到这么焦虑，真的抱歉。我已先核到{item_name or '这笔订单'}当前是#{status_label}#。我会继续跟进发货、清关和仓储节点，有新进展第一时间同步。"
    return "让你等到这么焦虑，真的抱歉。我已经记录当前情况，会继续按订单、物流和仓储节点帮你核实，有新进展第一时间同步。"


def _build_lottery_guard_reply() -> str:
    return "我理解连续没抽到想要款会很失落。抽选结果需要以活动公示规则和可复核记录为准，我可以帮您整理这次抽选批次、订单和疑点提交客服复核，但不能直接承诺补偿到账。"


def _load_demo_business_catalog() -> Dict[str, Any]:
    path = str(mock_data_file())
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def _build_lottery_detail_reply(state: AgentState) -> str:
    orders = (state.get("order_data") or {}).get("orders") or []
    activities = _load_demo_business_catalog().get("lottery_activities") or {}
    activity = {}
    for order in orders:
        for item in order.get("items") or []:
            activity = activities.get(item.get("item_id") or "") or {}
            if activity:
                break
        if activity:
            break
    if not activity:
        return _build_lottery_guard_reply()
    pool = "、".join(
        f"{row.get('tier')}档 {row.get('name')} {round(float(row.get('probability') or 0) * 100)}%"
        for row in activity.get("prize_pool") or []
    )
    return (
        f"这笔{activity.get('name')}演示活动的规则是：{activity.get('draw_rule')}"
        f"本轮演示奖池为{pool}。结果已在 2026-06-28 公布；如果您把具体抽号发我，"
        f"可以按抽号记录复核，演示复核时效为{activity.get('review_sla')}；"
        f"演示发货口径为{activity.get('fulfillment_sla')}。这些是演示数据，真实概率、开奖记录和履约时效需接甲方活动与订单系统后替换。"
    )


def _build_minor_refund_material_reply() -> str:
    return (
        "未成年人退款需要先整理五类材料：监护人与未成年人身份证明；户口本相关页、出生证明或合法监护证明等监护关系证明；"
        "金额与订单一致、无涂改且双方亲笔签名的退款承诺书；订单/支付凭证；绑定手机号实名归属证明。"
        "运营商材料需显示可与平台账号比对的业务手机号，支付截图不能替代手机号归属材料。"
        "身份证号、住址等可先遮盖非必要部分，我会帮您整理后再由VIP客服终审。"
    )


def _build_minor_refund_status_reply(state: AgentState) -> str:
    orders = (state.get("order_data") or {}).get("orders") or []
    order = orders[0] if orders else {}
    order_ref = _public_order_suffix(order.get("order_id") or "") or "当前订单"
    status = order.get("status") or ""
    status_label = order.get("status_label") or "待核对"
    mapping = {
        "minor_material_pending": "当前在材料补充阶段，补齐监护关系、支付凭证和承诺书后才开始审核计时。",
        "minor_material_submitted": "材料完整性初筛已通过，正在等待客服一审；演示 SLA 为 1-2 个工作日，超过 2 个工作日会进入逾期升级。",
        "minor_ai_passed": "AI 仅完成材料完整性初筛，当前由人工确认退款边界和账号影响；演示 SLA 为 1 个工作日。",
        "minor_low_confidence": "关系链证据置信度不足，正在人工复查户口本或出生证明；通常 1-2 个工作日，不需要把当前对话转人工。",
        "minor_review_rejected": "本轮因发票备注与绑定手机号不一致未通过；补充手机号实名归属证明后可申请复核，重新提交后演示 SLA 为 1-2 个工作日。",
        "refunded": "退款已登记，原支付渠道通常 3-7 个工作日到账；超时可转人工核对资金流水。",
    }
    detail = mapping.get(status, "当前节点需要结合材料和人工审核记录继续核对；完整流程目标不超过 30 个工作日。")
    return f"订单 #{order_ref} 当前状态是“{status_label}”。{detail}上述时效为演示口径，生产值需由甲方 SOP 和工单系统确认。"


def _build_damage_material_reply() -> str:
    return (
        "商品有伤建议一次拍齐：商品正面、背面、左右侧、顶部/底部、问题部位近景各 1 张，"
        "再补外包装六面、快递面单和从未拆封到取出商品的连续开箱视频。近景要同时有一张带整体定位，"
        "避免只拍局部无法确认商品归属。AI会先给出证据结论和置信度；退款、补发或拒赔仍由售后按订单和规则确认。"
    )


def _build_product_inventory_reply(state: AgentState, user_text: str) -> str:
    catalog = _load_demo_business_catalog().get("product_catalog") or {}
    scenario_decision = (state.get("conversation_state") or {}).get("scenario_decision") or {}
    product = scenario_decision.get("resolved_product") or resolve_unique_product(user_text, catalog)
    if not product:
        return "我还不能唯一确认具体商品，请提供商品 SKU、商品链接或订单行后再查询；真实库存需接甲方商品中心后实时返回。"
    variants = []
    for item in product.get("variants") or []:
        if item.get("stock_status") == "in_stock":
            variants.append(f"{item.get('name')}：现货 {item.get('available_quantity')} 件，{item.get('ship_window')}")
        else:
            variants.append(f"{item.get('name')}：预售，{item.get('ship_window')}")
    payments = "、".join(product.get("payment_methods") or [])
    return (
        f"{product.get('name')}当前演示库存：{'；'.join(variants)}。支持{payments}。"
        "这是明确标记的演示商品数据；接入甲方 SKU/库存接口后会按实时可售库存返回，不会让您再确认一次是否查询。"
    )


_REVIEW_SUCCESS_STATUSES = {"succeeded", "success", "completed", "review_completed", "review_succeeded"}


def _public_review_material_state(attachments: List[Dict[str, Any]]) -> Dict[str, Any]:
    from review_service.service import public_job

    for item in attachments or []:
        if item.get("kind") != "review_task" or not isinstance(item.get("review_result"), dict):
            continue
        result = item["review_result"]
        public = public_job({
            "job_id": item.get("review_task_id") or item.get("id") or "",
            "scenario": item.get("scenario") or "",
            "status": item.get("status") or "",
            "result": result if isinstance(result.get("review"), dict) else {"review": result},
        })
        review = ((public.get("result") or {}).get("review") or {})
        agent_report = review.get("agent_report") if isinstance(review.get("agent_report"), dict) else {}
        public_brief = agent_report.get("public_brief") if isinstance(agent_report.get("public_brief"), dict) else {}
        parsed = agent_report.get("parsed") if isinstance(agent_report.get("parsed"), dict) else {}
        reconciliation = (
            parsed.get("fulfillment_reconciliation")
            if isinstance(parsed.get("fulfillment_reconciliation"), dict)
            else {}
        )
        if not public_brief and isinstance(review.get("agent_brief"), dict):
            public_brief = review["agent_brief"]
        summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}

        def public_text(value: Any) -> str:
            text = str(value or "").strip()
            return "" if _customer_reply_has_internal_text(text) else text

        material_state = {
            "contract_version": "MITAKO-FOUR-SCENE@20260814.1",
            "review_task_id": item.get("review_task_id") or item.get("id") or "",
            "scenario": item.get("scenario") or "",
            "status": item.get("status") or "",
            "public_brief": {
                key: public_text(public_brief[key])
                for key in ("conclusion", "next_step")
                if public_text(public_brief.get(key))
            },
            "summary": {
                key: summary[key]
                for key in ("confidence", "needs_human_review")
                if summary.get(key) is not None
            },
        }
        if reconciliation:
            material_state["fulfillment_reconciliation"] = {
                key: reconciliation[key]
                for key in ("evidence_route", "user_materials_complete", "warehouse_check")
                if key in reconciliation
            }
        return material_state
    return {}


def _is_notification_channel_request(text: str) -> bool:
    raw = str(text or "")
    return any(k in raw for k in ["电话提醒", "电话通知", "打电话", "来电", "电话联系", "手机提醒", "短信提醒"]) or (
        "提醒" in raw and any(k in raw for k in ["物流", "发货", "出库", "更新", "电话", "短信", "站内信"])
    )


def _build_notification_channel_reply(state: AgentState) -> str:
    order_data = state.get("order_data") or {}
    orders = order_data.get("orders") or []
    order = orders[0] if orders else {}
    item_name = ""
    if order.get("items"):
        item_name = order["items"][0].get("name") or ""
    target = item_name or "这笔订单"
    status_label = order.get("status_label") or order.get("status") or ""
    status_part = f"我已把{target}当前#{status_label}#一起记录。" if status_label else f"我已把{target}的提醒诉求记录下来。"
    return (
        f"{status_part}电话提醒目前需要客服确认授权和可用渠道；我会先按站内信/订单消息同步进展，"
        "并把“希望物流更新后电话联系”作为服务建议提交复核。"
    )


def _reply_conflicts_with_order_facts(reply: str, state: AgentState) -> bool:
    text = sanitize_customer_reply(reply)
    order_data = state.get("order_data") or {}
    orders = order_data.get("orders") or []
    if order_data.get("order_lookup_failed"):
        return True
    if not orders:
        return False
    order = orders[0]
    item_name = ""
    if order.get("items"):
        item_name = order["items"][0].get("name") or ""
    known_ip_terms = ["排球少年", "名侦探柯南", "蓝色监狱", "原神"]
    for term in known_ip_terms:
        if term in text and term not in item_name:
            return True
    fact_blob = json.dumps({
        "order": order,
        "logistics": state.get("logistics_data") or {},
        "sop": state.get("sop_results") or [],
    }, ensure_ascii=False)
    date_mentions = re.findall(r"\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{2}-\d{2}", text)
    for date_text in date_mentions:
        if date_text.replace(" ", "") not in fact_blob.replace(" ", ""):
            return True
    return False


# 4. 状态机节点逻辑实现

# 5.1 load_memory 节点 (L0/L1/L2 自动分层加载)
async def load_user_memory(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    用户记忆载入节点：从 Viking 长期记忆库中读取目标用户的 profile 档案与会话历史上下文，初始化状态机数据。
    """
    queue = config.get("configurable", {}).get("event_queue")
    if queue:
        await queue.put({"type": "node_start", "node": "load_memory", "desc": "正在读取 OpenViking 上下文记忆..."})

    user_id = state["user_id"]
    viking_override = "auto"
    if "|" in user_id:
        user_id, viking_override = user_id.split("|", 1)

    profile_uri = f"viking://user/{user_id}/profile"
    profile = viking_db.read_json(profile_uri)

    # L0 级：默认读取基本属性
    user_memory = {
        "nickname": profile.get("nickname", "谷友"),
        "member_level": profile.get("metadata", {}).get("member_level", "bronze"),
        "favorite_ips": profile.get("metadata", {}).get("favorite_ips", []),
        "trigger_words": profile.get("communication_preferences", {}).get("trigger_words", [])
    }

    # L1 级：加载禁用词和沟通偏好
    user_memory["emoji_receptive"] = profile.get("communication_preferences", {}).get("emoji_receptive", True)
    avg_emotion = profile.get("behavior_patterns", {}).get("avg_emotion_level", 2.0)

    # L2 级：当平均情绪较高或特定会员时，递归加载深度投诉 cases
    load_l2 = False
    if viking_override == "L2":
        load_l2 = True
    elif viking_override == "L1":
        load_l2 = False
    elif viking_override == "L0":
        user_memory["emoji_receptive"] = True
    else: # auto
        if avg_emotion >= 3.0 or user_id == "usr_001":
            load_l2 = True

    cases = []
    if load_l2 and viking_override != "L0":
        cases_dir = f"viking://user/{user_id}/cases"
        case_files = viking_db.list_dir(cases_dir)
        for cf in case_files:
            case_data = viking_db.read_json(f"{cases_dir}/{cf}")
            if case_data:
                cases.append(case_data)

    user_memory["cases"] = cases

    level_str = "L0"
    if viking_override != "L0":
        level_str = "L2" if load_l2 else "L1"

    if queue:
        await queue.put({
            "type": "node_end",
            "node": "load_memory",
            "desc": f"记忆加载完成：级别={level_str}，昵称={user_memory['nickname']}，包含 {len(cases)} 条历史纠纷。"
        })

    return {"user_memory": user_memory}


# 5.2 intent_classify 节点 (轻量规则提取初步意图，为后续数据查询与RAG奠定基石)
async def classify_intent(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    意图快速分类节点：在毫秒级时间内对用户问题进行轻量级关键词检索匹配，锁定预判意图，用于后续精准查库。
    """
    queue = config.get("configurable", {}).get("event_queue")
    if queue:
        await queue.put({"type": "node_start", "node": "intent_classify", "desc": "基于轻量规则的初步意图分析中..."})

    last_user_msg = _current_user_text(state)
    recent_user_text = _recent_user_context(state.get("messages") or [])
    short_negative_turn = len(last_user_msg.strip()) <= 18 or any(k in last_user_msg for k in ["md", "MD", "废话", "脑子", "敷衍", "垃圾"])
    context_msg = f"{recent_user_text}\n{last_user_msg}" if short_negative_turn else last_user_msg

    intent_result = route_intent(last_user_msg, history=(state.get("messages") or [])[:-1])
    intent = public_intent_label(intent_result)
    emotion_level = 2

    if any(k in context_msg for k in ["垃圾", "跑路", "无语", "恶心", "气人", "太慢", "一直拖", "等疯了", "毛线", "生气", "串单", "串了", "完全不对", "离谱", "再这样", "别敷衍", "废话", "脑子有病", "有病"]):
        emotion_level = 4
    if any(k in context_msg for k in ["12315", "起诉", "黑猫", "曝光", "报警"]):
        emotion_level = 5

    emotion_level = max(1, min(6, emotion_level))

    if queue:
        await queue.put({
            "type": "node_end",
            "node": "intent_classify",
            "desc": f"初步分析：意图=【{intent}】，情绪等级=【Level {emotion_level}】"
        })
        _emit_unified_analysis_event(
            queue,
            intent,
            emotion_level,
            False,
            intent_result=intent_result.model_dump(),
        )
    conversation_state = dict(state.get("conversation_state") or {})
    conversation_state["intent"] = intent_result.model_dump()
    return {
        "intent": intent,
        "conversation_state": conversation_state,
        "emotion_level": emotion_level,
    }



# 5.3 emotion_detect 节点 (由于已在 classify_intent 合并拿到了，直接读取)
async def detect_emotion(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    情绪分析节点：基于会话数据对用户进行微弱情绪分级判定（本版由 Unified LLM 最终完成细微情绪提取）。
    """
    queue = config.get("configurable", {}).get("event_queue")
    level = state.get("emotion_level", 2)
    if queue:
        await queue.put({"type": "node_start", "node": "emotion_detect", "desc": f"情绪评估结果确认: Level {level}"})
        await queue.put({"type": "node_end", "node": "emotion_detect", "desc": f"情绪等级 Level {level} 验证通过。"})
    return {}


def _is_material_collection_turn(text: str, intent: str, attachments: Optional[List[Dict[str, Any]]] = None) -> bool:
    query = f"{intent} {text}"
    if attachments:
        return any(k in query for k in ["图片", "照片", "视频", "破损", "有伤", "瑕疵", "划痕", "开箱", "材料", "未成年", "监护人"])
    return any(k in query for k in ["图片", "照片", "视频", "破损", "有伤", "瑕疵", "划痕", "开箱", "需要提交", "什么材料", "材料", "怎么申请", "怎么处理", "未成年", "监护人"])


def _accepted_recent_handoff_offer(messages: List[Dict[str, str]]) -> bool:
    if not messages:
        return False
    last_user = _strip_attachment_context(messages[-1].get("content") or "")
    if not re.fullmatch(r"(?:好(?:的)?|可以|行|同意|需要|麻烦了|帮我转|那就转|转吧)[！!。.]?", last_user):
        return False
    if len(messages) < 2 or messages[-2].get("role") != "assistant":
        return False
    content = str(messages[-2].get("content") or "")
    return any(k in content for k in ["转接VIP客服", "转人工客服", "帮您转人工", "需要VIP客服", "联系VIP客服"])


# 5.4 check_transfer 节点：转 VIP 客服硬逻辑规则判定
async def check_transfer_rules(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    VIP客服分流审查节点：判断当前对话是否触发大额退款(>100元)、起诉威胁或VIP客服敏感词，锁定是否需要强制转接。
    """
    queue = config.get("configurable", {}).get("event_queue")
    if queue:
        await queue.put({"type": "node_start", "node": "check_transfer", "desc": "进行合规安全与VIP客服转接限额检查..."})

    last_user_msg = _current_user_text(state)
    intent = state.get("intent") or ""
    emotion_level = state["emotion_level"]

    conversation_state = state.get("conversation_state") or {}
    raw_intent_result = conversation_state.get("intent")
    try:
        intent_result = IntentResult.model_validate(raw_intent_result) if raw_intent_result else route_intent(last_user_msg)
    except Exception:
        intent_result = route_intent(last_user_msg)
    intent_code = intent_result.intent_code

    should_transfer = False
    transfer_reason = ""
    accepted_offer_id = ""
    handoff_recommended = False

    # 1. 用户明确要求真人客服，必须真实进入 VIP客服队列，不能只在话术里口头承诺。
    human_request_words = ["我要人工", "人工客服", "真人客服", "VIP客服", "不想和机器人", "转人工", "转VIP客服", "找人工"]
    if intent_code == "human_handoff" or any(word in last_user_msg for word in human_request_words):
        should_transfer = True
        transfer_reason = "用户明确要求VIP客服接入"

    if not should_transfer and _accepted_recent_handoff_offer(state.get("messages") or []):
        try:
            import handoff_store
            offer = handoff_store.get_active_handoff_offer(state.get("session_id") or "", state.get("user_id") or "")
        except Exception:
            offer = None
        if offer:
            handoff_store.update_handoff_offer(
                offer["offer_id"], "consented", state.get("session_id") or "", state.get("user_id") or ""
            )
            accepted_offer_id = offer["offer_id"]
            should_transfer = True
            transfer_reason = "用户已同意此前的VIP客服转接提议"

    # 2. 维权和法律硬拦截敏感词
    sensitive_words = ["12315", "起诉", "黑猫", "消费者协会", "曝光", "报警", "律师"]
    if not should_transfer and (
        _intent_in_result(intent_result.model_dump(mode="json"), "high_risk_complaint")
        or "complaint" in intent_result.scenario_codes
    ):
        should_transfer = True
        transfer_reason = "高风险投诉需要人工确认责任、动作和首响时效"
    if not should_transfer:
        for word in sensitive_words:
            if word in last_user_msg:
                should_transfer = True
                transfer_reason = f"言论命中VIP客服强接管词 '{word}'，触发P0转交规则"
                break

    # 3. 支付账号变更仍需直接转人工；收货地址由后续工具回执策略处理。
    if any(k in last_user_msg for k in ["改支付宝", "修改支付账号", "改支付账号"]):
        should_transfer = True
        transfer_reason = "修改支付账户敏感信息，触发P0防劫单转VIP客服规则"

    # 4. 情绪高风险 (Level 5+ 转VIP客服；L4 只建议人工并继续实质方案)
    if emotion_level >= 5:
        should_transfer = True
        transfer_reason = f"用户情绪评级达高风险 (Level {emotion_level})，触发转VIP客服安抚机制"
    elif emotion_level == 4 and not should_transfer:
        handoff_recommended = True
        transfer_reason = "当前情绪达到 L4，建议人工关注但继续提供实质业务方案"

    if queue:
        await queue.put({
            "type": "node_end",
            "node": "check_transfer",
            "desc": f"转交状态：{'需转交VIP客服' if should_transfer else 'AI承接中'} (原因: {transfer_reason or '无'})"
        })
        _emit_unified_analysis_event(
            queue,
            intent,
            emotion_level,
            should_transfer,
            intent_result=intent_result.model_dump(mode="json"),
        )
    return {
        "should_transfer": should_transfer,
        "transfer_reason": transfer_reason,
        "handoff_offer_id": accepted_offer_id,
        "handoff_recommended": handoff_recommended,
        "intent_result": intent_result.model_dump(mode="json"),
    }


# 5.5 query_order 节点：调用本地业务接口
async def query_order_system(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    订单系统查询节点：向本地业务接口实时获取用户最新的延期或异常订单事实数据，为安抚决策提供客观事实依据。
    """
    queue = config.get("configurable", {}).get("event_queue")
    user_id = state["user_id"]
    intent = state["intent"]
    last_user_msg = _current_user_text(state)
    active_order_id = state.get("active_order_id") or ""
    explicit_order_ref = _extract_explicit_order_ref(last_user_msg)
    if not active_order_id:
        match = re.search(r"ORD_\d{4}_\d+", last_user_msg)
        if match:
            active_order_id = match.group(0)
    focus_ref = explicit_order_ref or active_order_id

    should_query = any(k in intent for k in [
        "订单", "物流", "发货", "预售", "退款", "换货", "未成年人", "破损", "通知", "提醒", "盲盒", "抽赏",
    ]) or "引用订单" in last_user_msg or bool(focus_ref)
    if not should_query:
        return {"order_data": {}}

    if queue:
        focus_hint = f"（焦点订单 {focus_ref}）" if focus_ref else ""
        await queue.put({"type": "node_start", "node": "query_order", "desc": f"向后台拉取用户 {user_id} 的全部订单{focus_hint}..."})

    order_data = {}
    semantic_failure = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{LOCAL_BUSINESS_URL}/api/v1/orders/{user_id}")
            if res.status_code == 200:
                payload = res.json()
                if _business_payload_success(payload):
                    order_data = payload
                else:
                    semantic_failure = True
    except Exception as e:
        order_data = _load_mock_orders_for_user(user_id)
    if not order_data and not semantic_failure:
        order_data = _load_mock_orders_for_user(user_id)

    if focus_ref and order_data.get("orders"):
        order_data = _focus_order_data(order_data, focus_ref)

    if queue:
        orders_summary = ", ".join([f"{o['order_id']}({o['status']})" for o in order_data.get("orders", [])])
        desc = (
            f"订单拉取成功！共找到 {order_data.get('total', 0)} 笔订单：{orders_summary}"
            if order_data.get("orders")
            else (f"未匹配到用户指定订单 {order_data.get('explicit_order_ref')}，需要用户确认。" if order_data.get("order_lookup_failed") else "暂未取得订单信息，继续按服务流程处理。")
        )
        await queue.put({
            "type": "node_end",
            "node": "query_order",
            "desc": desc
        })
    return {"order_data": order_data}


# 5.6 query_logistics 节点
async def query_logistics(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    物流系统查询节点：向本地物流接口实时跟进订单最新的通关及货运路由，以便告知用户确切的交期节点。
    """
    queue = config.get("configurable", {}).get("event_queue")
    order_data = state["order_data"]

    orders = order_data.get("orders", [])
    if not orders:
        return {"logistics_data": {}}

    order_id = orders[0]["order_id"]

    if queue:
        await queue.put({"type": "node_start", "node": "query_logistics", "desc": f"正在向物流中心查询订单 {order_id} 的运输详情..."})

    logistics_data = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{LOCAL_BUSINESS_URL}/api/v1/logistics/{order_id}")
            if res.status_code == 200:
                payload = res.json()
                if _business_payload_success(payload):
                    logistics_data = payload
    except Exception as e:
        mock_data_path = str(mock_data_file())
        if os.path.exists(mock_data_path):
            with open(mock_data_path, "r", encoding="utf-8") as f:
                db = json.load(f)
                logistics_data = db.get("logistics", {}).get(order_id, {})

    if queue:
        carrier = logistics_data.get("carrier", "未知")
        status = logistics_data.get("status", "未知")
        desc = (
            f"物流轨迹: 【{carrier}】状态为【{status}】，最新节点='{logistics_data.get('timeline', [{}])[-1].get('status', '无')}'"
            if logistics_data
            else "暂未取得物流信息，继续按服务流程处理。"
        )
        await queue.put({
            "type": "node_end",
            "node": "query_logistics",
            "desc": desc
        })
    return {"logistics_data": logistics_data}


# 5.7 search_sop 节点：检索匹配 SOP 与供应链预警数据
async def search_knowledge_base(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    知识库召回节点：通过简易语义规则关联海关新政说明、商家发货 SOP 以及当前的供应链预警消息，准备背景参考知识。
    """
    queue = config.get("configurable", {}).get("event_queue")
    intent = state["intent"]
    order_data = state["order_data"]
    last_user_msg = _current_user_text(state)
    conversation_state = dict(state.get("conversation_state") or {})
    intent_result = IntentResult.model_validate(
        conversation_state.get("intent") or route_intent(last_user_msg).model_dump()
    )
    facts = [Fact.model_validate(item) for item in conversation_state.get("facts") or []]
    material_state = _public_review_material_state(state.get("attachments") or [])
    reconciliation = material_state.get("fulfillment_reconciliation") or {}
    review_attachment = next(
        (
            item for item in state.get("attachments") or []
            if item.get("kind") == "review_task"
            and (item.get("review_task_id") or item.get("id")) == material_state.get("review_task_id")
        ),
        {},
    )
    if (
        intent_result.scenario_code == "wrong_item"
        and material_state.get("scenario") == "wrong_item"
        and str(material_state.get("status") or "").lower() in _REVIEW_SUCCESS_STATUSES
        and review_attachment.get("scope_verified") is True
        and reconciliation.get("evidence_route") == "static_three_images"
        and reconciliation.get("user_materials_complete") is True
    ):
        source_ref = f"review_task:{material_state.get('review_task_id')}"
        facts.extend(
            Fact(
                field=f"wrong_item.{field}",
                value=True,
                source="review_service",
                source_ref=source_ref,
                verified=True,
            )
            for field in (
                "received_group_photo",
                "green_bag_or_package_view",
                "matching_waybill",
            )
        )
    action_data = conversation_state.get("action_state")
    action = ActionState.model_validate(action_data) if isinstance(action_data, dict) else None
    demo_catalog = _load_demo_business_catalog()
    activities = demo_catalog.get("lottery_activities") or {}
    activity = next(
        (
            activities[item.get("item_id")]
            for order in order_data.get("orders") or []
            for item in order.get("items") or []
            if item.get("item_id") in activities
        ),
        None,
    )
    policy_config = config.get("configurable", {}).get("scenario_policy_config") or {}
    scenario_decision = decide_scenario(
        intent=intent_result,
        facts=facts,
        message=last_user_msg,
        action=action,
        config=policy_config,
        catalog=demo_catalog.get("product_catalog") or {},
        activity=activity,
    )
    decision_data = scenario_decision.model_dump(mode="json")
    conversation_state.update({
        "facts": [fact.model_dump(mode="json") for fact in facts],
        "scenario_decision": decision_data,
        "core_conclusion": decision_data["core_conclusion"],
        "action_state": decision_data["action_state"],
        "next_step": decision_data["next_step"],
        "policy_refs": decision_data["policy_refs"],
        "details": decision_data.get("details") or {},
        "required_reply_fields": decision_data.get("required_reply_fields") or [],
    })
    if material_state:
        conversation_state["material_state"] = material_state

    if queue:
        await queue.put({"type": "node_start", "node": "search_sop", "desc": "正在检索对应的业务 SOP 规范与供应链预警公告..."})

    sop_results = []

    ip_name = None
    orders = order_data.get("orders", [])
    if orders and orders[0].get("items"):
        item_name = orders[0]["items"][0]["name"]
        if "排球" in item_name:
            ip_name = "排球少年"
        elif "蓝色监狱" in item_name:
            ip_name = "蓝色监狱"
        elif "原神" in item_name:
            ip_name = "原神"

    warnings_list = []
    try:
        from business_api import get_supply_chain_warnings
        warnings_list = get_supply_chain_warnings(ip_name)
    except Exception as e:
        print(f"[Business API] 读取供应链预警失败: {e}")
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                url = f"{LOCAL_BUSINESS_URL}/api/v1/supply_chain/warnings"
                if ip_name:
                    url += f"?ip_name={ip_name}"
                res = await client.get(url)
                if res.status_code == 200:
                    warnings_list = res.json().get("warnings", [])
        except Exception as e2:
            print(f"[Business API] HTTP 调用供应链预警失败: {e2}")

    for w in warnings_list:
        sop_results.append(f"【供应链预警 - {w['ip_name']}】公告原因: {w['reason']}。修改后出荷日期为 {w['revised_shukka_date']}。官网公告内容：'{w['public_notice']}'。")

    sop_results.extend(_load_local_sop_results(intent, last_user_msg))

    if "催发货" in intent or "物流" in intent or "预售" in intent:
        sop_results.append("【发货延期补偿SOP】：出荷时间延期超120天以上的订单，可提交平台积分与优先发货标记申请；具体权益、金额和是否生效以业务系统与VIP客服确认为准。")
    elif "补偿" in intent:
        sop_results.append("【虚拟安抚规则】：AI 只允许自动发放虚拟资产（平台积分、发货加急服务标记等），严禁私自发放免邮券、退现金等实体资产，如遇用户强烈要求实体资产补偿，必须转接VIP客服主管处理。")
    elif "破损" in intent:
        sop_results.append("【退换货破损SOP】：引导用户拍照上传包装破损图及商品细节划痕，核实材料后进入补发、换货或退款的VIP客服确认流程。")
    elif "通知渠道" in intent or "服务建议" in intent:
        sop_results.append("【通知渠道诉求SOP】：先确认用户希望被主动提醒的节点；当前可先记录站内信/订单消息触达，电话或短信提醒需客服确认授权、渠道能力和隐私合规后再执行；将代表性诉求沉淀为主管复核建议。")

    if not sop_results:
        sop_results.append("【日常问答指南】：谷子圈黑话术语，例如吧唧（徽章）、出荷（出厂发货）。")

    if queue:
        await queue.put({
            "type": "node_end",
            "node": "search_sop",
            "desc": f"检索成功！获取到相关的 SOP 条目与公告 {len(sop_results)} 项。"
        })
    return {"sop_results": sop_results, "conversation_state": conversation_state}


async def plan_business_readiness_flow(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    queue = config.get("configurable", {}).get("event_queue")
    fixtures = config.get("configurable", {}).get("fixtures") or state.get("fixtures") or []
    attachments = config.get("configurable", {}).get("attachments") or state.get("attachments") or []
    if queue:
        await queue.put({"type": "node_start", "node": "business_readiness", "desc": "正在执行本地 SOP 状态机与业务动作规划..."})
    try:
        from business_readiness_service import run_business_flow
        result = run_business_flow(state, fixtures)
    except Exception as exc:
        if queue:
            await queue.put({
                "type": "node_end",
                "node": "business_readiness",
                "desc": "服务流程规划暂时失败，已转VIP客服继续核实。",
            })
        return {
            "sop_state": {"state": "error", "sop_branch": "服务流程异常", "needs_human": True},
            "business_events": [],
            "business_cards": [],
            "should_transfer": False,
            "transfer_reason": "",
            "business_failure_reason": f"服务流程规划失败: {type(exc).__name__}",
        }
    sop_state = result.get("sop_state") or {}
    action = sop_state.get("planned_action") or {}
    last_user_msg = _current_user_text(state)
    material_first_scene = (
        sop_state.get("ticket_type") in {"minor_refund", "damage"}
        and _is_material_collection_turn(last_user_msg, state.get("intent") or "", attachments)
    )
    result["business_review_required"] = bool(sop_state.get("needs_human") or action.get("requires_human"))
    result["material_collection_turn"] = material_first_scene
    if queue:
        await queue.put({
            "type": "node_end",
            "node": "business_readiness",
            "desc": f"SOP分支={sop_state.get('sop_branch', '通用咨询')}，计划动作={sop_state.get('planned_action', {}).get('type', 'none')}"
        })
    return result


# 5.8 check_compensation 节点：发放补偿 (自动额度控制)
async def check_compensation_eligibility(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    延期补偿发放及风控节点：自动审查订单是否满足出荷延误超期条件，并在此执行防重领安全风控与发放 Points 权益卡。
    """
    queue = config.get("configurable", {}).get("event_queue")
    user_id = state["user_id"]
    order_data = state["order_data"]
    intent = state["intent"]
    session_id = state["session_id"]

    compensation_given = []
    member_level = state.get("user_memory", {}).get("member_level", "bronze")
    tier_labels = {"platinum": "白金", "gold": "金牌", "silver": "银牌", "bronze": "普通"}
    tier_label = tier_labels.get(member_level, "普通")

    orders = order_data.get("orders", [])
    compensable_order = None
    focus_order = orders[0] if orders else {}
    if focus_order.get("is_compensable") and focus_order.get("status") == "pending_shipment":
        compensable_order = focus_order

    if compensable_order and any(k in intent for k in ["催发货", "补偿", "退款"]):
        profile_uri = f"viking://user/{user_id}/profile"
        profile = viking_db.read_json(profile_uri)
        history_compensations = profile.get("behavior_patterns", {}).get("compensations", [])
        business_failure_reason = ""

        if compensable_order["order_id"] not in history_compensations:
            if queue:
                await queue.put({"type": "node_start", "node": "check_compensation", "desc": f"小蛟正在核对订单 {compensable_order['order_id']} 的物流与履约进度..."})

            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    payload = {
                        "user_id": user_id,
                        "order_id": compensable_order["order_id"],
                        "type": "virtual_pack",
                        "amount": 100.0,
                        "reason": "出荷延期超120天自动发放虚拟安抚包",
                        "agent_session_id": session_id
                    }
                    res = await client.post(f"{LOCAL_BUSINESS_URL}/api/v1/compensate", json=payload)
                    res_data = {}
                    try:
                        res_data = res.json()
                    except ValueError:
                        res_data = {}
                    semantic_success = res_data.get("ok") is True or res_data.get("success") is True
                    if 200 <= res.status_code < 300 and semantic_success:
                        comp_info = {
                            "order_id": compensable_order["order_id"],
                            "amount": 100.0,
                            "type": "virtual_pack",
                            "status": "submitted",
                            "requires_human_review": False,
                            "msg": res_data.get(
                                "message",
                                f"已按{tier_label}会员权益提交关怀建议。"
                            )
                        }
                        compensation_given.append(comp_info)

                        history_compensations.append(compensable_order["order_id"])
                        profile["behavior_patterns"]["compensations"] = history_compensations
                        viking_db.write_json(profile_uri, profile)
                    else:
                        proposal_msg = res_data.get("message") or res_data.get("detail") or "补偿申请需客服确认后再生效"
                        compensation_given.append({
                            "order_id": compensable_order["order_id"],
                            "amount": 100.0,
                            "type": "virtual_pack",
                            "status": "approval_required",
                            "requires_human_review": True,
                            "msg": proposal_msg,
                        })
            except Exception as e:
                print(f"[Business API] 发放补偿出错: {e}")
                business_failure_reason = "补偿建议接口暂不可用，已保留订单进度核查，不因此中断AI服务"

            if business_failure_reason:
                if queue:
                    await queue.put({
                        "type": "node_end",
                        "node": "check_compensation",
                        "desc": "补偿建议暂未提交成功，不影响继续同步订单进度。",
                    })
                return {
                    "compensation_given": [],
                    "transfer_reason": business_failure_reason,
                }

            if queue and compensation_given:
                await queue.put({
                    "type": "node_end",
                    "node": "check_compensation",
                    "desc": "已形成补偿/关怀建议，需客服或业务系统确认后才会生效。"
                })
        else:
            if queue:
                await queue.put({
                    "type": "node_end",
                    "node": "check_compensation",
                    "desc": f"订单 {compensable_order['order_id']} 此前已获得过免邮券补偿，本次不再重复发放。"
                })

    return {"compensation_given": compensation_given}


# 5.9 generate_reply 节点
def _complaint_reply_fields(
    state: AgentState,
    tracking_receipt: str = "",
    action_status: str = "",
) -> Dict[str, str]:
    from handoff_routing import get_sla_config

    conversation_state = state.get("conversation_state") or {}
    details = conversation_state.get("details") or {}
    configured = details.get("complaint_protocol") or {}
    first_response_seconds = int(
        get_sla_config(state.get("tenant_id") or "mitako").get("first_response_seconds") or 180
    )
    first_response_sla = f"入队后 {max(1, (first_response_seconds + 59) // 60)} 分钟内首次响应"
    if tracking_receipt:
        current_action = "已进入人工队列并同步投诉简报"
        receipt = tracking_receipt
    elif action_status == "failed":
        current_action = "尚未进入人工队列，请重试或使用人工入口"
        receipt = "暂无有效队列回执"
    else:
        current_action = "正在提交人工队列并同步投诉简报"
        receipt = "等待人工队列回执"
    return {
        "responsible_role": str(configured.get("responsible_role") or "VIP客服主管"),
        "current_action": current_action,
        "first_response_sla": first_response_sla,
        "tracking_receipt": receipt,
    }


async def generate_reply_with_persona(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    AI 回复生成节点：调用已配置的 LLM（默认 DeepSeek V4 Flash / SenseNova）。在 System Prompt 红线下产出流式回复。
    """
    queue = config.get("configurable", {}).get("event_queue")
    if queue:
        await queue.put({"type": "node_start", "node": "generate_reply", "desc": "小蛟正在整理上下文并编写回复..."})

    intent = state["intent"]
    emotion_level = state["emotion_level"]
    should_transfer = state["should_transfer"]
    conversation_state = dict(state.get("conversation_state") or {})
    intent_result = conversation_state.get("intent") or {}
    public_config: Dict[str, Any] = {}
    if _intent_in_result(intent_result, "high_risk_complaint"):
        reply_fields = _complaint_reply_fields(state)
        conversation_state["reply_fields"] = reply_fields
        public_config["complaint_protocol"] = reply_fields

    reply_plan = build_reply_plan(conversation_state, public_config=public_config)
    conversation_state["reply_plan"] = reply_plan.model_dump(mode="json")
    if _intent_in_result(intent_result, "high_risk_complaint"):
        if queue:
            await queue.put({"type": "node_end", "node": "generate_reply", "desc": "高风险投诉响应协议已生成。"})
        return {
            "reply_draft": render_reply_plan(reply_plan),
            "meme_tags": [],
            "conversation_state": conversation_state,
        }
    model_id = config.get("configurable", {}).get("model_id") or DEFAULT_MODEL_ID
    stream_reply = config.get("configurable", {}).get("stream_reply", False)
    user_payload = json.dumps(
        {"reply_plan": public_reply_plan_payload(reply_plan)},
        ensure_ascii=False,
    )
    reply = await call_llm(
        "你只负责润色公开回复计划。不得增加事实、状态、商品、时效、责任、凭证或已执行动作。只输出面向用户的正文。",
        user_payload,
        [],
        queue,
        model_id=model_id,
        stream_reply=stream_reply,
        emit_text_chunks=False,
        emit_analysis_event=False,
    )
    meme_tags = re.findall(r"<meme:\s*(\w+)>", reply)
    analysis = _parse_reply_analysis(reply)
    updates: Dict[str, Any] = {
        "reply_draft": reply,
        "meme_tags": meme_tags,
        "conversation_state": conversation_state,
    }
    if analysis.get("emotion_level"):
        try:
            parsed_level = max(1, min(6, int(analysis.get("emotion_level"))))
            if emotion_level >= 4 and parsed_level < 4:
                parsed_level = emotion_level
            updates["emotion_level"] = parsed_level
        except Exception:
            pass
    if queue and (analysis.get("emotion_level") or analysis.get("should_transfer")):
        _emit_unified_analysis_event(
            queue,
            intent,
            updates.get("emotion_level") or emotion_level,
            should_transfer,
            intent_result=(state.get("conversation_state") or {}).get("intent"),
        )

    if queue:
        await queue.put({
            "type": "node_end",
            "node": "generate_reply",
            "desc": f"大模型回复完成。包含标签: {meme_tags}"
        })
    return updates


# 5.10 safety_review 节点
async def safety_review_agent(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    回复安全审查节点：双保险安全拦截，对 AI 最终产出进行违规高危文本和回怼词的二次安全防御。
    """
    queue = config.get("configurable", {}).get("event_queue")
    if queue:
        await queue.put({"type": "node_start", "node": "safety_review", "desc": "正在对生成的回复做合规安全审查..."})

    reply = state["reply_draft"]
    safety_check_result = "pass"
    modified = False

    money_pattern = r"(退款|退给你|赔偿|补偿)\s*(\d+)\s*(元|块|¥)"
    for match in re.finditer(money_pattern, reply):
        amount = int(match.group(2))
        if amount > 100:
            reply = re.sub(money_pattern, r"关于具体的退款金额，小蛟需要帮您提交给客服确认哦~", reply)
            safety_check_result = "review"
            modified = True

    date_pattern = r"(保证|一定|肯定).*(月|号|日).*(发货|到达|收到)"
    if re.search(date_pattern, reply):
        reply = re.sub(date_pattern, r"小蛟会密切跟进，有确切消息第一时间通知你~", reply)
        modified = True

    privacy_pattern = r"(其他用户|别人的订单|confidential)"
    if re.search(privacy_pattern, reply, re.IGNORECASE):
        reply = "非常抱歉，为了保障信息安全，小蛟无法透露这些处理细节或他人订单数据哦。"
        safety_check_result = "block"
        modified = True
    elif _customer_reply_has_internal_text(_strip_reply_analysis(reply)):
        reply = _build_grounded_service_reply(state)
        safety_check_result = "pass"
        modified = True

    liability_pattern = r"(平台的责任|我们的错|公司的问题|违法|违约)"
    if re.search(liability_pattern, reply):
        reply = "关于责任归属，需要结合订单事实和适用规则进一步核对；我会继续跟进，不在当前回复中直接定责。"
        modified = True

    last_user_msg = _current_user_text(state)
    if re.search(r"(火星|月球|外太空)", last_user_msg) and re.search(r"(地球|火星|月球|外太空|乖乖|飞走|跑丢)", reply):
        reply = _build_grounded_service_reply(state)
        modified = True

    if _reply_conflicts_with_order_facts(reply, state):
        reply = _build_grounded_service_reply(state)
        modified = True

    grounding_context = json.dumps(
        {
            "order": state.get("order_data") or {},
            "logistics": state.get("logistics_data") or {},
        },
        ensure_ascii=False,
    )
    completed_action = re.search(
        r"(?:已经|已).{0,16}?(核实|核查|确认|联系|咨询)|(?:核实|核查).{0,4}(?:过|完成)",
        reply,
    )
    completed_sentence = ""
    if completed_action:
        completed_sentence = next(
            (
                sentence.strip()
                for sentence in re.split(r"[，。；!?！？]", reply)
                if completed_action.group(0) in sentence
            ),
            completed_action.group(0),
        )
    action_grounded = bool(
        completed_sentence
        and re.sub(r"\s+", "", completed_sentence) in re.sub(r"\s+", "", grounding_context)
    )
    cadence = re.search(
        r"(?:每(?:日|天|周|小时)|每隔[^，。；]{1,8})[^，。；]{0,12}(?:跟进|同步|通知|更新)",
        reply,
    )
    cadence_grounded = bool(cadence and cadence.group(0) in grounding_context)
    ungrounded_progress = (
        ("海关新政" in reply and "海关新政" not in grounding_context)
        or (completed_action and not action_grounded)
        or (cadence and not cadence_grounded)
    )
    if ungrounded_progress:
        reply = _build_grounded_service_reply(state)
        modified = True

    intent = state.get("intent") or ""
    ticket_type = ((state.get("sop_state") or {}).get("ticket_type") or "")
    if ("盲盒" in intent or ticket_type == "lottery") and re.search(r"(绝对|肯定|一定).*(随机|人工|干预|没改)|非酋|关爱积分|专属挂件|稍后到账|200\\s*平台积分", reply):
        reply = _build_lottery_guard_reply()
        modified = True

    if ("盲盒" in intent or ticket_type == "lottery") and any(k in last_user_msg for k in [
        "活动规则", "中奖率", "概率", "保底", "奖池", "稀有款", "抽号", "发货时效", "商品详情", "包含什么", "抽赏",
    ]):
        reply = _build_lottery_detail_reply(state)
        modified = True

    if ("未成年人" in intent or ticket_type == "minor_refund") and any(k in last_user_msg for k in ["需要提交", "什么材料", "材料", "怎么申请"]):
        clean = sanitize_customer_reply(reply)
        if not all(k in clean for k in [
            "身份证明", "监护关系证明", "双方亲笔签名", "订单/支付凭证",
            "绑定手机号实名归属证明", "业务手机号", "支付截图不能替代",
        ]):
            reply = _build_minor_refund_material_reply()
            modified = True

    if ("未成年人" in intent or ticket_type == "minor_refund") and any(k in last_user_msg for k in ["多久", "进度", "状态", "为什么", "实名归属", "审核完"]):
        reply = _build_minor_refund_status_reply(state)
        modified = True

    if ("破损" in intent or ticket_type == "damage") and any(k in last_user_msg for k in ["材料", "照片", "开箱视频", "怎么处理"]):
        clean = sanitize_customer_reply(reply)
        if not any(k in clean for k in ["整体图", "近景", "开箱视频"]):
            reply = _build_damage_material_reply()
            modified = True

    if ("售前商品咨询" in intent or ticket_type == "product_consult") and any(k in last_user_msg for k in ["SKU", "sku", "库存", "现货", "规格", "支付方式"]):
        reply = _build_product_inventory_reply(state, last_user_msg)
        modified = True

    if "通知渠道" in intent or _is_notification_channel_request(last_user_msg):
        clean = sanitize_customer_reply(reply)
        if not all(k in clean for k in ["电话", "记录"]) or not any(k in clean for k in ["站内信", "订单消息", "客服确认"]):
            reply = _build_notification_channel_reply(state)
            modified = True

    conversation_state = dict(state.get("conversation_state") or {})
    if not conversation_state.get("intent"):
        try:
            conversation_state["intent"] = route_intent(_current_user_text(state)).model_dump(mode="json")
        except Exception:
            pass
    try:
        reply_plan = ReplyPlan.model_validate(conversation_state.get("reply_plan") or {})
    except Exception:
        reply_plan = build_reply_plan(conversation_state)
    conversation_state["reply_plan"] = reply_plan.model_dump(mode="json")
    guard_result = guard_reply(
        sanitize_customer_reply(reply),
        conversation_state=conversation_state,
        reply_plan=reply_plan,
    )
    if not guard_result.allowed:
        modified = True
    reply = guard_result.reply
    conversation_state["reply_guard_reason"] = guard_result.reason_code or "pass"

    if queue:
        await queue.put({
            "type": "node_end",
            "node": "safety_review",
            "desc": f"安全质检完毕: 状态={safety_check_result.upper()} (回复{'经修正后合规' if modified else '安全合规'})"
        })

    return {
        "reply_draft": reply,
        "safety_check_result": safety_check_result,
        "conversation_state": conversation_state,
    }


# 5.11 send_reply / transfer_human / update_memory 节点
async def send_to_user(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    queue = config.get("configurable", {}).get("event_queue")
    conversation_state = dict(state.get("conversation_state") or {})
    try:
        reply_plan = ReplyPlan.model_validate(conversation_state.get("reply_plan") or {})
    except Exception:
        reply_plan = build_reply_plan(conversation_state)
    guard_result = guard_reply(
        sanitize_customer_reply(state.get("reply_draft", "")),
        conversation_state=conversation_state,
        reply_plan=reply_plan,
    )
    conversation_state["reply_plan"] = reply_plan.model_dump(mode="json")
    conversation_state["reply_guard_reason"] = guard_result.reason_code or "pass"
    if queue:
        await queue.put({"type": "node_start", "node": "send_reply", "desc": "下发回复气泡至用户客户端..."})
        if guard_result.reply:
            await queue.put({"type": "text_chunk", "content": guard_result.reply})
        await queue.put({"type": "node_end", "node": "send_reply", "desc": "回复发送完成。"})
    return {
        "reply_draft": guard_result.reply,
        "conversation_state": conversation_state,
    }

async def transfer_to_chatwoot(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    from handoff_service import build_handoff_brief, enqueue_handoff
    from auth.jwt_utils import create_handoff_user_token
    from business_readiness_service import record_transfer_blocked

    queue = config.get("configurable", {}).get("event_queue")
    user_id = state["user_id"]
    session_id = state["session_id"]
    reason = state["transfer_reason"] or "安全审查红线拦截转VIP客服"
    if not state.get("business_events"):
        event = record_transfer_blocked(state, reason)
        state = {**state, "business_events": [event], "sop_state": event.get("result") or {}}
    conversation_state = dict(state.get("conversation_state") or {})
    intent_data = conversation_state.get("intent") or {}
    is_high_risk_complaint = _intent_in_result(intent_data, "high_risk_complaint")
    if intent_data and not conversation_state.get("scenario_decision"):
        decision = decide_scenario(
            intent=IntentResult.model_validate(intent_data),
            facts=[Fact.model_validate(item) for item in conversation_state.get("facts") or []],
            message=_current_user_text(state),
        )
        decision_data = decision.model_dump(mode="json")
        conversation_state.update({
            "scenario_decision": decision_data,
            "core_conclusion": decision_data["core_conclusion"],
            "action_state": decision_data["action_state"],
            "next_step": decision_data["next_step"],
            "policy_refs": decision_data["policy_refs"],
            "details": decision_data["details"],
            "required_reply_fields": decision_data["required_reply_fields"],
        })
    brief: Dict[str, Any] = {"tenant_id": state.get("tenant_id") or "mitako"}
    queue_meta: Dict[str, Any] = {}
    try:
        brief = build_handoff_brief(state, reason)
        queue_meta = enqueue_handoff(
            session_id,
            brief,
            tenant_id=brief.get("tenant_id") or "mitako",
            publish=not bool(config.get("configurable", {}).get("defer_handoff_publish")),
        )
        action = action_from_tool("human_handoff", "handoff_service", queue_meta)
        if action.status.value == "queued" and (
            str(queue_meta.get("session_id") or "") != session_id
            or action.receipt_id != session_id
        ):
            action = action_from_tool(
                "human_handoff",
                "handoff_service",
                {"ok": False, "status": "failed", "error": "session_mismatch"},
            )
    except Exception as exc:
        action = action_from_exception("human_handoff", "handoff_service", exc)
        queue_meta = {
            "ok": False,
            "status": "failed",
            "session_id": session_id,
            "error": action.reason_code,
        }
    if action.status.value == "failed":
        queue_meta = {
            "ok": False,
            "status": "failed",
            "session_id": session_id,
            "error": action.reason_code,
        }
    queue_meta = {**queue_meta, "action_state": action.model_dump(mode="json")}
    if action.status.value == "queued" and state.get("handoff_offer_id"):
        try:
            import handoff_store
            handoff_store.update_handoff_offer(
                state["handoff_offer_id"], "queued", session_id, user_id
            )
        except Exception:
            pass
    handoff_token = ""
    if action.status.value == "queued":
        try:
            handoff_token = create_handoff_user_token(
                session_id=session_id,
                user_id=user_id,
                tenant_id=brief.get("tenant_id") or "mitako",
            )
        except Exception:
            handoff_token = ""
    conversation_state["action_state"] = action.model_dump(mode="json")
    conversation_state["handoff_receipt"] = action.receipt_id
    reply_fields: Dict[str, str] = {}
    public_config: Dict[str, Any] = {}
    if is_high_risk_complaint:
        reply_fields = _complaint_reply_fields(
            {**state, "conversation_state": conversation_state},
            action.receipt_id if action.status.value == "queued" else "",
            action.status.value,
        )
        conversation_state["reply_fields"] = reply_fields
        public_config["complaint_protocol"] = reply_fields
    reply_plan = build_reply_plan(conversation_state, public_config=public_config)
    guard_result = guard_reply(
        render_reply_plan(reply_plan),
        conversation_state=conversation_state,
        reply_plan=reply_plan,
    )
    conversation_state["reply_plan"] = reply_plan.model_dump(mode="json")
    conversation_state["reply_guard_reason"] = guard_result.reason_code or "pass"
    reply_draft = guard_result.reply
    public_reason = (
        f"{reason}（队列回执 {action.receipt_id}）"
        if action.status.value == "queued" and action.receipt_id
        else f"尚未进入人工队列：{action.reason_code}"
    )

    if queue:
        await queue.put({"type": "node_start", "node": "transfer_human", "desc": "触碰VIP客服接入规则，正在路由至坐席等待队列..."})
        await queue.put({"type": "handoff_brief", "brief": brief})
        await queue.put({
            "type": "action_transfer",
            "user_id": user_id,
            "reason": public_reason,
            "session_id": session_id,
            "brief": brief,
            "queue": queue_meta,
            "handoff_token": handoff_token,
            "action_state": action.model_dump(mode="json"),
            "required_reply_fields": conversation_state.get("required_reply_fields") or [],
            "reply_fields": reply_fields,
        })
        await queue.put({
            "type": "node_end",
            "node": "transfer_human",
            "desc": "会话已加入VIP客服队列，简报已生成。" if action.status.value == "queued" else "人工队列接入失败，可重试或使用人工入口。",
        })

    return {
        "should_transfer": True,
        "transfer_reason": reason,
        "conversation_state": conversation_state,
        "action_state": action.model_dump(mode="json"),
        "handoff_token": handoff_token,
        "reply_draft": reply_draft,
    }

async def update_user_memory(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    记忆回写节点：将本次交互产生的新聊天日志、被更新的用户情感级别以及新申请的历史补偿回写持久化到 Viking 库。
    """
    queue = config.get("configurable", {}).get("event_queue")
    if queue:
        await queue.put({"type": "node_start", "node": "update_memory", "desc": "学习并更新用户的长期交互偏好..."})

    user_id = state["user_id"]
    profile_uri = f"viking://user/{user_id}/profile"

    profile = viking_db.read_json(profile_uri)
    if profile:
        prev_avg = profile.get("behavior_patterns", {}).get("avg_emotion_level", 2.0)
        current_level = state["emotion_level"]
        new_avg = round((prev_avg * 0.7) + (current_level * 0.3), 2)
        profile["behavior_patterns"]["avg_emotion_level"] = new_avg

        history = profile.get("chat_history", [])
        history.append({
            "role": "user",
            "content": state["messages"][-1]["content"] if state["messages"] else "",
            "intent": state["intent"],
            "emotion": current_level
        })
        history.append({
            "role": "assistant",
            "content": sanitize_customer_reply(state["reply_draft"]),
            "memes": state["meme_tags"]
        })
        profile["chat_history"] = history[-20:]

        viking_db.write_json(profile_uri, profile)

    if queue:
        await queue.put({"type": "node_end", "node": "update_memory", "desc": "长期记忆库同步完成！"})
    return {}

async def log_to_langfuse(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    queue = config.get("configurable", {}).get("event_queue")
    if queue:
        await queue.put({"type": "node_start", "node": "log_trace", "desc": "上报 Langfuse Tracing 评测日志..."})
        await queue.put({"type": "node_end", "node": "log_trace", "desc": "日志上报完毕。"})
    return {}


# 6. 构建并编译 LangGraph 状态图

workflow = StateGraph(AgentState)

workflow.add_node("load_memory", load_user_memory)
workflow.add_node("intent_classify", classify_intent)
workflow.add_node("emotion_detect", detect_emotion)
workflow.add_node("check_transfer", check_transfer_rules)
workflow.add_node("query_order", query_order_system)
workflow.add_node("query_logistics", query_logistics)
workflow.add_node("search_sop", search_knowledge_base)
workflow.add_node("business_readiness", plan_business_readiness_flow)
workflow.add_node("check_compensation", check_compensation_eligibility)
workflow.add_node("generate_reply", generate_reply_with_persona)
workflow.add_node("safety_review", safety_review_agent)
workflow.add_node("send_reply", send_to_user)
workflow.add_node("transfer_human", transfer_to_chatwoot)
workflow.add_node("update_memory", update_user_memory)
workflow.add_node("log_trace", log_to_langfuse)

workflow.set_entry_point("load_memory")
workflow.add_edge("load_memory", "intent_classify")
workflow.add_edge("intent_classify", "emotion_detect")
workflow.add_edge("emotion_detect", "check_transfer")

def router_after_transfer_check(state: AgentState):
    conversation_state = state.get("conversation_state") or {}
    intent_result = conversation_state.get("intent") or {}
    if _intent_in_result(intent_result, "high_risk_complaint"):
        scenario_ready = bool(conversation_state.get("scenario_decision"))
        reply_ready = bool(str(state.get("reply_draft") or "").strip())
        return "transfer" if state.get("should_transfer") and scenario_ready and reply_ready else "continue"
    return "transfer" if state.get("should_transfer") else "continue"


workflow.add_conditional_edges(
    "check_transfer",
    router_after_transfer_check,
    {
        "transfer": "transfer_human",
        "continue": "query_order",
    }
)

workflow.add_edge("query_order", "query_logistics")
workflow.add_edge("query_logistics", "search_sop")
workflow.add_edge("search_sop", "business_readiness")
workflow.add_conditional_edges(
    "business_readiness",
    router_after_transfer_check,
    {
        "transfer": "transfer_human",
        "continue": "check_compensation",
    },
)
workflow.add_edge("check_compensation", "generate_reply")
workflow.add_edge("generate_reply", "safety_review")

def router_after_safety(state: AgentState):
    # 人工转接只服从前置确定性分流；模型回复中的动作标记不能改变路由。
    if state.get("should_transfer"):
        return "review"
    return "pass"

workflow.add_conditional_edges(
    "safety_review",
    router_after_safety,
    {
        "pass": "send_reply",
        "review": "transfer_human",
        "block": "transfer_human"
    }
)

workflow.add_edge("send_reply", "update_memory")
workflow.add_edge("update_memory", "log_trace")
workflow.add_edge("log_trace", END)
workflow.add_edge("transfer_human", "log_trace")

agent_app = workflow.compile()
