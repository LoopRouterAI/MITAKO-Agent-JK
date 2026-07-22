# -*- coding: utf-8 -*-
"""将甲方订单快照转换为最小化、可送审的订单与履约基线。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote, urljoin, urlsplit


DEFAULT_PRODUCT_IMAGE_BASE_URL = "https://cdn-qiniu.danhaotuan.com/storage/mnt/zhonggu/"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def product_image_url(reference: Any) -> str:
    value = _text(reference).replace("\\", "/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return value if parsed.scheme.lower() == "https" and parsed.netloc else ""
    parts = [part for part in value.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return ""
    base = os.getenv("REVIEW_PRODUCT_IMAGE_BASE_URL", DEFAULT_PRODUCT_IMAGE_BASE_URL).strip()
    if not base.endswith("/"):
        base += "/"
    return urljoin(base, quote("/".join(parts), safe="/%"))


def _selection_rules(snapshot: Dict[str, Any], goods_id_to_ref: Dict[str, str]) -> list[Dict[str, Any]]:
    rules: list[Dict[str, Any]] = []
    for lottery in snapshot.get("lottery_info") or []:
        if not isinstance(lottery, dict):
            continue
        item_refs = []
        for goods_id in lottery.get("order_goods_ids") or []:
            item_ref = goods_id_to_ref.get(_text(goods_id))
            if item_ref and item_ref not in item_refs:
                item_refs.append(item_ref)
        if not item_refs:
            continue
        lottery_id = _text(lottery.get("lottery_id"))
        rules.append({
            "rule_ref": f"LOTTERY-{lottery_id}" if lottery_id else f"LOTTERY-{len(rules) + 1:03d}",
            "lottery_type": _text(lottery.get("lottery_type_code")),
            "name": _text(lottery.get("name")),
            "item_refs": item_refs,
            "rule_text": _text(lottery.get("rule1")),
            "source": "customer_order_info_snapshot",
        })
    return rules


def build_order_info_context(path: Path) -> Dict[str, Any]:
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    goods = snapshot.get("goods_list") if isinstance(snapshot, dict) else None
    if not isinstance(goods, list):
        return {}

    order_items: list[Dict[str, Any]] = []
    product_master: Dict[str, Dict[str, Any]] = {}
    item_by_key: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    goods_id_to_ref: Dict[str, str] = {}
    for item in goods:
        if not isinstance(item, dict):
            continue
        sku = _text(item.get("number") or item.get("id"))
        name = _text(item.get("name") or item.get("des"))
        specification = _text(item.get("intro") or item.get("des"))
        quantity = _positive_int(item.get("goods_num"))
        if not sku or not name or quantity <= 0:
            continue
        key = (sku, name, specification)
        existing = item_by_key.get(key)
        if existing:
            existing["expected_quantity"] += quantity
            item_ref = existing["item_ref"]
        else:
            item_ref = f"ORDER-LINE-{len(order_items) + 1:03d}"
            image_ref = _text(item.get("main_img"))
            image_url = product_image_url(image_ref)
            expected = {
                "item_ref": item_ref,
                "sku": sku,
                "product_name": name,
                "specification": specification,
                "expected_quantity": quantity,
                "product_image_ref": image_ref,
                "master_image_urls": [image_url] if image_url else [],
            }
            order_items.append(expected)
            item_by_key[key] = expected
            product_master[item_ref] = {
                "sku": sku,
                "product_name": name,
                "specification": specification,
                "product_image_ref": image_ref,
                "master_image_urls": list(expected["master_image_urls"]),
                "source": "customer_order_info_snapshot",
            }
        goods_id = _text(item.get("id"))
        if goods_id:
            goods_id_to_ref[goods_id] = item_ref

    if not order_items:
        return {}

    tracking_no = _text(snapshot.get("tracking_number"))
    carrier = _text(snapshot.get("tracking_company"))
    selection_rules = _selection_rules(snapshot, goods_id_to_ref)
    baseline = {
        "baseline_version": f"order_info_snapshot:{hashlib.sha256(path.read_bytes()).hexdigest()[:16]}",
        "expected_items": order_items,
        "packages": [],
        "package_mapping_status": "not_declared_in_snapshot",
        "split_shipment_status": "not_declared_in_snapshot",
        "benefit_rules": [],
        "benefit_rules_complete": False,
        "selection_rules": selection_rules,
        "selection_rules_complete": not selection_rules,
        "selection_rules_status": "incomplete" if selection_rules else "not_applicable",
        "standard_packing_list": [
            {
                "item_ref": item["item_ref"],
                "sku": item["sku"],
                "product_name": item["product_name"],
                "expected_quantity": item["expected_quantity"],
            }
            for item in order_items
        ],
        "source": "customer_order_info_snapshot",
    }
    return {
        "order_items": order_items,
        "product_master_data": product_master,
        "fulfillment_baseline": baseline,
        "logistics": {
            key: value
            for key, value in {
                "carrier": carrier,
                "tracking_ref": f"sha256:{hashlib.sha256(tracking_no.encode('utf-8')).hexdigest()[:16]}" if tracking_no else "",
            }.items()
            if value
        },
    }
