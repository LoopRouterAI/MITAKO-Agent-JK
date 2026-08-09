# -*- coding: utf-8 -*-
"""把高级客服可编辑规则与不可变业务底线合并为单案快照。"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from prompts.catalog import ensure_rule_key
from prompts.governance_store import get_active_version, get_cached_active_version


LOGGER = logging.getLogger("mitako.business_rules")

IMMUTABLE_BUSINESS_BASELINES = {
    "visual.product_damage": """不可变商品有伤底线：
- 视频加速、缺少 EXIF、裁剪、锐化或单一疑似生成痕迹都只能作为橙色风险信号，不能单独判材料不合格；只有它实际妨碍默认一帧每秒下的关键事实判断，或与多项异常交叉印证时，才要求补原速或原始材料。
- 看见损伤与证明损伤形成时间、原因必须分开；同物关联成立且所诉损伤清晰可见时，即使损伤成因仍无法确定，也不能只为确认损伤成因要求重交开箱视频；不得把可见伤情直接等同于商家、物流或用户责任。
- 争议商品曝光后应切换为跟踪争议商品；外箱完成开箱起点证明后离镜，不得等同为争议商品离镜。""",
    "visual.wrong_item": """不可变发错货底线：
- 发错货必须有实际收到未购买商品；只有数量减少而没有错误商品时应按漏发货审查。
- 订单版本基准、应收身份、实收错误身份及包裹/面单关联已由清晰照片形成闭环时，可以给出明确证据结论，不能机械强制完整开箱视频。""",
    "visual.missing_item": """不可变漏发货底线：
- 漏发货必须是应收数量少且没有收到其他错误商品；少了 A 又多了未购买的 C 应转发错货审查。
- 模型、抽帧、上传或外部服务失败属于系统处理失败，不得冒充用户材料缺失。
- 只有带版本、来源和核验编号的结构化仓库终核可以覆盖历史待核实备注；待核实备注本身不能下结论。""",
    "visual.minor_refund": """不可变未成年人审核底线：
- 未满九周岁且年龄证据置信度高时，应突出独立支付能力风险并要求高级客服重点复核支付来源和监护过程；不能仅凭年龄支持、拒绝或完成退款。
- 申请人与未成年人分处两本户口本时，必须由出生证明、同一本户口本直接关系页或合法监护证明建立桥接；仅身份字段一致不能闭合亲子或法定监护关系。
- 未提交、已提交但不可读、字段冲突和关系链无法闭环必须分别表述，不能笼统归为材料不全。""",
}


def capture_rule_snapshot(prompt_key: str, tenant_id: str) -> Dict[str, Any]:
    """每个案件只调用一次；失败时优先使用进程内最近成功版本。"""
    key = ensure_rule_key(prompt_key)
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("租户不能为空")
    try:
        active = get_active_version(tenant, key)
        status = "active" if active else "built_in"
    except Exception as exc:
        active = get_cached_active_version(tenant, key)
        status = "degraded_cached" if active else "degraded_built_in"
        LOGGER.error("读取业务规则版本失败，使用最近成功版本或内置规则：%s", exc)
    return {
        "tenant_id": tenant,
        "prompt_key": key,
        "version": int((active or {}).get("version") or 0),
        "mode": str((active or {}).get("mode") or "built_in"),
        "content": str((active or {}).get("content") or "").strip(),
        "resolution_status": status,
    }


def public_snapshot_metadata(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not snapshot:
        return {}
    return {
        "key": snapshot.get("prompt_key"),
        "version": snapshot.get("version"),
        "mode": snapshot.get("mode"),
        "resolution_status": snapshot.get("resolution_status"),
    }


def resolve_business_rules(
    *,
    prompt_key: str,
    default_rules: str,
    tenant_id: str = "mitako",
    snapshot: Optional[Dict[str, Any]] = None,
) -> str:
    key = ensure_rule_key(prompt_key)
    tenant = str(tenant_id or "").strip()
    current = snapshot or capture_rule_snapshot(key, tenant)
    if current.get("prompt_key") != key or current.get("tenant_id") != tenant:
        raise ValueError("业务规则快照与当前租户或规则入口不一致")

    default = default_rules.strip()
    content = str(current.get("content") or "").strip()
    if not content:
        editable = default
    elif current.get("mode") == "replace":
        editable = content
    elif default:
        editable = f"{default}\n\n高级客服已发布的补充业务规则：\n{content}"
    else:
        editable = content

    immutable = IMMUTABLE_BUSINESS_BASELINES.get(key, "").strip()
    return f"{editable}\n\n{immutable}".strip() if immutable else editable
