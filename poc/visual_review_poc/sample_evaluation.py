# -*- coding: utf-8 -*-
"""工作台离线样本表解析与探索性一致率统计。"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException, UploadFile


ALLOWED_SAMPLE_SUFFIXES = {".csv", ".json"}
SAMPLE_MAX_BYTES = 5 * 1024 * 1024
TARGET_REVIEW_TASKS = ("video_unboxing", "product_damage", "minor_material")
TASK_PUBLIC_NAMES = {
    "video_unboxing": "开箱视频",
    "product_damage": "商品有伤",
    "minor_material": "资料审核",
    "wrong_item": "发错货",
    "unknown": "未识别场景",
}
FIELD_ALIASES = {
    "task": ("task", "scenario", "scene", "queue", "业务队列", "场景", "审核场景", "任务"),
    "human_label": ("human_label", "manual_label", "final_label", "human_result", "result", "人工结论", "最终人工结论", "人工最终结论", "结论"),
    "predicted_label": ("predicted_label", "model_label", "system_label", "review_label", "assistant_label", "辅助结论", "系统结论", "预测结论"),
    "user_text": ("user_text", "customer_text", "claim_text", "诉求", "用户诉求", "用户描述", "客服记录"),
    "human_reason": ("human_reason", "manual_reason", "reason", "人工原因", "人工结论原因", "结论原因", "原因"),
    "order_item": ("order_item", "product_name", "item_name", "商品名", "订单商品名", "商品"),
    "sku": ("sku", "spec", "sku_spec", "variant", "规格", "款式", "SKU", "SKU规格"),
    "material": ("video", "video_url", "image", "image_url", "material", "material_url", "素材", "视频", "图片", "资料"),
}


def _row_value(row: Dict[str, Any], aliases: tuple[str, ...]) -> str:
    lookup = {str(key).strip().lower(): value for key, value in row.items()}
    for alias in aliases:
        value = lookup.get(alias.strip().lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_task(value: str) -> str:
    raw = str(value or "").strip().lower()
    compact = re.sub(r"[\s_\-/]+", "", raw)
    if raw in {"video_unboxing", "unboxing", "unboxing_video"} or any(key in compact for key in ("开箱", "拆箱", "unboxing")):
        return "video_unboxing"
    if raw in {"product_damage", "damage", "damaged_item"} or any(key in compact for key in ("有伤", "破损", "划痕", "damage")):
        return "product_damage"
    if raw in {"minor_material", "minor", "minor_refund"} or any(key in compact for key in ("未成年", "监护", "资料", "minor")):
        return "minor_material"
    if raw in {"wrong_item", "wrong_sku", "sku_mismatch"} or any(key in compact for key in ("发错", "错发", "sku", "wrongitem")):
        return "wrong_item"
    return "unknown"


def _normalize_label(value: str) -> str:
    raw = str(value or "").strip().lower()
    compact = re.sub(r"[\s_\-/，。:：；;]+", "", raw)
    if not compact:
        return ""
    negative = {
        "fail", "failed", "no", "n", "false", "invalid", "reject", "rejected", "unsupported",
        "negative", "incomplete", "missing", "mismatch", "nodamage", "不通过", "未通过", "不合格",
        "不合规", "不支持", "拒绝", "无伤", "没伤", "未见损伤", "未破损", "没发错", "未发错",
        "不一致", "资料缺失", "缺失", "不完整", "不成立", "剪辑", "离镜",
    }
    positive = {
        "pass", "passed", "ok", "yes", "y", "true", "valid", "support", "supported", "confirmed",
        "positive", "approved", "approve", "accept", "complete", "match", "compliant", "damage",
        "damaged", "wrong", "通过", "合格", "合规", "支持", "确认", "确认有伤", "有伤", "破损",
        "发错", "错发", "资料完整", "完整", "一致", "同意", "可支持", "可通过", "成立",
    }
    review = {
        "suspect", "manualreview", "review", "uncertain", "unclear", "ambiguous", "needreview",
        "pending", "疑似", "存疑", "人工复核", "待复核", "不确定", "看不清", "需补件", "补件", "待确认",
    }
    if compact in negative:
        return "negative"
    if compact in positive:
        return "positive"
    if compact in review:
        return "review"
    return "unmapped:" + compact[:40]


def _valid_label(value: str) -> bool:
    return value in {"positive", "negative", "review"}


def _public_label(value: str) -> str:
    return {
        "positive": "正向",
        "negative": "负向",
        "review": "需复核",
    }.get(value, "未映射" if value.startswith("unmapped:") else "-")


def read_sample_rows(file: UploadFile) -> List[Dict[str, Any]]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SAMPLE_SUFFIXES:
        raise HTTPException(status_code=415, detail="仅支持 CSV 或 JSON 样本表")
    raw = file.file.read(SAMPLE_MAX_BYTES + 1)
    if len(raw) > SAMPLE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="样本表过大，请拆分后上传")
    if not raw:
        raise HTTPException(status_code=400, detail="样本表为空")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="样本表需要使用 UTF-8 编码") from exc
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV 缺少表头")
        rows = []
        for row in reader:
            if None in row:
                raise HTTPException(status_code=400, detail="CSV 行列数量与表头不一致")
            if any(str(value or "").strip() for value in row.values()):
                rows.append(dict(row))
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="JSON 格式无法解析") from exc
        if isinstance(payload, dict):
            payload = payload.get("samples") or payload.get("rows") or []
        if not isinstance(payload, list):
            raise HTTPException(status_code=400, detail="JSON 需要是数组或包含 samples 数组")
        bad_index = next((index for index, item in enumerate(payload, start=1) if not isinstance(item, dict)), None)
        if bad_index is not None:
            raise HTTPException(status_code=400, detail=f"JSON 第 {bad_index} 条样本不是对象")
        rows = list(payload)
    if not rows:
        raise HTTPException(status_code=400, detail="未读取到有效样本")
    if len(rows) > 5000:
        raise HTTPException(status_code=413, detail="单次最多评测 5000 条样本")
    return [{str(key): value for key, value in row.items()} for row in rows]


def _empty_task_stats() -> Dict[str, Any]:
    return {
        "total": 0,
        "evaluable": 0,
        "correct": 0,
        "accuracy": None,
        "labels": {"positive": 0, "negative": 0, "review": 0, "other": 0},
        "evaluable_labels": {"positive": 0, "negative": 0, "review": 0, "other": 0},
    }


def evaluate_sample_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    tasks: Dict[str, Dict[str, Any]] = {}
    missing_fields = {name: 0 for name in ("业务场景", "人工结论", "用户诉求", "素材", "商品信息", "规格信息", "人工原因")}
    errors: List[Dict[str, Any]] = []
    unmapped_labels: Dict[str, Dict[str, int]] = {"人工结论": {}, "辅助结论": {}}
    total = len(rows)
    evaluable = correct = target_total = target_evaluable = target_correct = 0

    for index, row in enumerate(rows, start=1):
        task = _normalize_task(_row_value(row, FIELD_ALIASES["task"]))
        human_label_raw = _row_value(row, FIELD_ALIASES["human_label"])
        predicted_label_raw = _row_value(row, FIELD_ALIASES["predicted_label"])
        human_label = _normalize_label(human_label_raw)
        predicted_label = _normalize_label(predicted_label_raw)
        stats = tasks.setdefault(task, _empty_task_stats())
        stats["total"] += 1
        if task in TARGET_REVIEW_TASKS:
            target_total += 1

        field_values = {
            "业务场景": task if task != "unknown" else "",
            "人工结论": human_label,
            "用户诉求": _row_value(row, FIELD_ALIASES["user_text"]),
            "素材": _row_value(row, FIELD_ALIASES["material"]),
            "商品信息": _row_value(row, FIELD_ALIASES["order_item"]),
            "规格信息": _row_value(row, FIELD_ALIASES["sku"]),
            "人工原因": _row_value(row, FIELD_ALIASES["human_reason"]),
        }
        for name, value in field_values.items():
            if not value:
                missing_fields[name] += 1

        for name, normalized, raw in (
            ("人工结论", human_label, human_label_raw),
            ("辅助结论", predicted_label, predicted_label_raw),
        ):
            if normalized.startswith("unmapped:"):
                key = raw[:40]
                unmapped_labels[name][key] = unmapped_labels[name].get(key, 0) + 1

        if human_label and _valid_label(human_label):
            stats["labels"][human_label] += 1
        elif human_label:
            stats["labels"]["other"] += 1

        if _valid_label(human_label) and _valid_label(predicted_label):
            evaluable += 1
            stats["evaluable"] += 1
            stats["evaluable_labels"][human_label] += 1
            matched = human_label == predicted_label
            if matched:
                correct += 1
                stats["correct"] += 1
            if task in TARGET_REVIEW_TASKS:
                target_evaluable += 1
                if matched:
                    target_correct += 1
            if not matched and len(errors) < 12:
                errors.append({
                    "row": index,
                    "task": TASK_PUBLIC_NAMES.get(task, task),
                    "human_label": _public_label(human_label),
                    "assistant_label": _public_label(predicted_label),
                })

    for stats in tasks.values():
        if stats["evaluable"]:
            stats["accuracy"] = round(stats["correct"] / stats["evaluable"], 4)

    readiness = {}
    for task in TARGET_REVIEW_TASKS:
        stats = tasks.get(task) or _empty_task_stats()
        labels = stats["evaluable_labels"]
        readiness[task] = {
            "name": TASK_PUBLIC_NAMES[task],
            "positive": labels["positive"],
            "negative": labels["negative"],
            "evaluable": stats["evaluable"],
            "minimum_ready": None,
            "recommended_ready": None,
        }

    return {
        "ok": True,
        "summary": {
            "total": total,
            "evaluable": evaluable,
            "correct": correct,
            "accuracy": round(correct / evaluable, 4) if evaluable else None,
            "target_total": target_total,
            "target_evaluable": target_evaluable,
            "target_correct": target_correct,
            "target_accuracy": round(target_correct / target_evaluable, 4) if target_evaluable else None,
            "non_target_total": total - target_total,
            "ready_for_accuracy": None,
            "minimum_required": "由双方评测方案根据场景风险约定；不是审核 API 的运行时门槛",
            "recommended_required": "报告只展示当前样本分布和探索性指标，不单方面设定商务验收数量",
        },
        "tasks": {TASK_PUBLIC_NAMES.get(task, task): stats for task, stats in sorted(tasks.items())},
        "readiness": readiness,
        "missing_fields": missing_fields,
        "unmapped_labels": unmapped_labels,
        "mismatches": errors,
    }
