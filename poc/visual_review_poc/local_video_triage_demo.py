# -*- coding: utf-8 -*-
"""本地单样本视觉审核、抽帧和兼容报告工具。"""
from __future__ import annotations

import argparse
import base64
import html
import json
import logging
import math
import mimetypes
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import cv2
import httpx
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime_paths import app_root
from review_media_safety import ignored_upload_reason, valid_media_file
from poc.visual_review_poc.order_info_adapter import build_order_info_context, read_safe_ticket_manifest
from poc.visual_review_poc.model_auth import DEFAULT_GEMINI_MODEL, gemini_channel_options, resolve_gemini_model
from configs.model_catalog import MODEL_CONFIGS
from prompts.visual_review.schemas import REVIEW_RESPONSE_SCHEMA
from poc.visual_review_poc.observability import log_visual_event, sanitize_error_text
from prompts.visual_review.core import build_system_prompt, build_user_prompt, scenario_rules
from review_input_safety import read_user_conversation_history

ROOT = app_root()
POC_DIR = ROOT / "poc" / "visual_review_poc"
REPORT_DIR = POC_DIR / "reports" / "internal_archive"
TMP_DIR = ROOT / "tmp" / "visual_review_gemini35"
SAMPLE_LABELS = ROOT / "docs" / "三大审核场景的小量样本" / "sample_labels.json"
MODEL = DEFAULT_GEMINI_MODEL
GEMINI_PRICING_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"
DEFAULT_POLICY = {"auto_confidence": 0.80, "manual_confidence": 0.65}
LOGGER = logging.getLogger("mitako.visual_review")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gemini 单样本视觉审核")
    parser.add_argument("--video", required=True, help="本地视频路径")
    parser.add_argument("--scenario", choices=["video_unboxing", "product_damage", "minor_material"], default="", help="强制指定审核场景")
    parser.add_argument("--context-json", default="", help="客服证据包上下文 JSON")
    parser.add_argument("--fps", type=float, default=1.0, help="抽帧频率，默认 1fps")
    parser.add_argument("--max-frames", type=int, default=12, help="最多抽取帧数")
    parser.add_argument("--api-frame-limit", type=int, default=12, help="最多送入模型的帧数")
    parser.add_argument("--probe-seconds", type=float, default=0.0, help="只审核开头多少秒；0 表示覆盖全视频均匀抽帧")
    parser.add_argument("--frame-width", type=int, default=960, help="抽帧图片最大宽度")
    parser.add_argument("--supplemental-image-limit", type=int, default=12, help="同目录最多送入多少张补充图片")
    parser.add_argument("--request-timeout", type=int, default=300, help="单次请求超时秒数")
    parser.add_argument("--soft-retries", type=int, default=3, help="429/5xx 等软错误重试次数")
    return parser.parse_args()


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    values = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in values.items():
        os.environ.setdefault(key, value)


def load_env() -> None:
    load_env_file(ROOT / ".env")
    load_env_file(ROOT.parent / "JK-PromptReview" / ".env")


def h(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def json_block(data: Any) -> str:
    return h(json.dumps(data, ensure_ascii=False, indent=2))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore").strip() if path.exists() else ""


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(read_text(path) or "null")
    except Exception:
        return None


def mime_for(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def encode_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def image_meta(path: Path) -> Dict[str, Any]:
    meta = {
        "bytes": path.stat().st_size if path.exists() else None,
        "width": None,
        "height": None,
        "has_exif": None,
        "exif_software": "",
        "editor_metadata_present": False,
    }
    try:
        image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if image is not None:
            meta["height"], meta["width"] = image.shape[:2]
    except Exception:
        pass
    try:
        from PIL import Image

        with Image.open(path) as pil_image:
            exif = pil_image.getexif()
            meta["has_exif"] = bool(exif)
            software = str(exif.get(305) or "").strip()
            meta["exif_software"] = software
            meta["editor_metadata_present"] = any(
                marker in software.lower()
                for marker in ("adobe", "photoshop", "lightroom", "gimp", "affinity", "snapseed")
            )
    except Exception:
        meta["has_exif"] = None
    return meta


def infer_scenario(claim: str) -> str:
    text = str(claim or "")
    if any(word in text for word in ("有伤", "折损", "破损", "划痕", "损坏", "瑕疵")):
        return "product_damage"
    if any(word in text for word in ("未成年", "未成年人", "监护", "家长", "退费")):
        return "minor_material"
    return "video_unboxing"


def format_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    remain = seconds - minutes * 60
    return f"{minutes:02d}:{remain:05.2f}"


def resize_frame(frame: Any, width: int) -> Any:
    height, current_width = frame.shape[:2]
    if current_width <= width:
        return frame
    ratio = width / current_width
    return cv2.resize(frame, (width, int(height * ratio)), interpolation=cv2.INTER_AREA)


def adaptive_frame_budget(duration_seconds: float, source_bytes: int, limit: int) -> int:
    if duration_seconds >= 600:
        recommended = 24
    elif duration_seconds >= 180 or source_bytes >= 500 * 1024 * 1024:
        recommended = 18
    elif duration_seconds >= 60:
        recommended = 10
    else:
        recommended = 6
    return max(1, min(limit, recommended))


def sample_video_frames(
    video: Path,
    fps: float,
    max_frames: int,
    probe_seconds: float,
    frame_width: int,
    run_dir: Path,
    sampling_mode: str = "adaptive",
) -> Dict[str, Any]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"视频无法读取：{video}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total_frames / native_fps if native_fps else 0
    source_bytes = video.stat().st_size
    scan_frames = total_frames
    requested_count = max(1, int(math.ceil(duration * max(fps, 0.1))) + 1)
    candidate_count = min(requested_count, max(scan_frames, 1))
    candidates = sorted(
        {
            round(i * max(total_frames - 1, 0) / max(candidate_count - 1, 1))
            for i in range(candidate_count)
        }
    )
    frame_budget = (
        max(1, min(max_frames, len(candidates)))
        if sampling_mode == "dense"
        else adaptive_frame_budget(duration, source_bytes, max_frames)
    )
    if len(candidates) > frame_budget:
        positions = [round(i * (len(candidates) - 1) / max(frame_budget - 1, 1)) for i in range(frame_budget)]
        candidates = [candidates[pos] for pos in positions]

    frame_dir = run_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frames: List[Dict[str, Any]] = []
    for frame_number in candidates:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = cap.read()
        if not ok:
            continue
        frame = resize_frame(frame, frame_width)
        timestamp_seconds = round(frame_number / native_fps, 2) if native_fps else 0.0
        path = frame_dir / f"frame_{len(frames) + 1:03d}_{timestamp_seconds:.2f}s.webp"
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_WEBP_QUALITY, 101])
        frames.append(
            {
                "frame_index": len(frames) + 1,
                "timestamp": format_time(timestamp_seconds),
                "timestamp_seconds": timestamp_seconds,
                "file": path.name,
                "path": str(path),
                "uri": path.resolve().as_uri(),
            }
        )
    cap.release()
    if not frames:
        raise SystemExit("没有抽到可用帧")
    return {
        "source_bytes": source_bytes,
        "native_fps": round(native_fps, 2),
        "duration_seconds": round(duration, 2),
        "fps_requested": fps,
        "probe_seconds": probe_seconds,
        "sampling_strategy": f"full_timeline_{sampling_mode}",
        "sampling_mode": sampling_mode,
        "frame_budget": frame_budget,
        "timeline_coverage_ratio": round(
            min(1.0, (frames[-1]["timestamp_seconds"] - frames[0]["timestamp_seconds"]) / duration),
            4,
        ) if duration > 0 and len(frames) > 1 else 1.0,
        "model_input": {
            "type": "individual_lossless_webp_frames",
            "max_width": frame_width,
            "lossless": True,
        },
        "large_media_recommendation": (
            "object_storage_transcode_proxy"
            if source_bytes >= 500 * 1024 * 1024 or duration >= 600
            else "server_side_frame_sampling"
        ),
        "sampled_frames": len(frames),
        "frames": frames,
    }


def find_supplemental_images_in_dir(folder: Path, limit: int, resource_fields: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    image_exts = {".jpg", ".jpeg", ".png", ".webp"}
    images = [
        p
        for p in sorted(folder.iterdir())
        if p.is_file()
        and p.suffix.lower() in image_exts
        and not ignored_upload_reason(p.name)
        and valid_media_file(p)
    ]
    return [
        {
            "image_index": index + 1,
            "file": p.name,
            "path": str(p),
            "uri": p.resolve().as_uri(),
            "mime_type": mime_for(p),
            "fields": resource_fields.get(p.name, []),
            **image_meta(p),
        }
        for index, p in enumerate(images[:limit])
    ]


def find_supplemental_images(video: Path, limit: int, resource_fields: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    return find_supplemental_images_in_dir(video.parent, limit, resource_fields)


def order_info_context(path: Path, *, order_reference: str = "") -> Dict[str, Any]:
    """把甲方订单快照转换为最小化的 SKU/应发基准，不带用户和地址字段。"""
    return build_order_info_context(path, order_reference=order_reference)


def _blind_review_conversation(folder: Path) -> List[Dict[str, Any]]:
    return read_user_conversation_history(folder)


def load_case_from_folder(folder: Path, supplemental_limit: int, video: Optional[Path] = None) -> Dict[str, Any]:
    claim = read_text(folder / "content.txt")
    manifest = {}
    try:
        manifest = json.loads(read_text(folder / "manifest.json") or "{}")
    except Exception:
        manifest = {}
    evidence_assets = [
        {
            "file": item.get("local_file"),
            "fields": item.get("fields") or [],
            "status": item.get("status"),
        }
        for item in (manifest.get("resources") or [])
        if item.get("local_file")
    ]
    resource_fields = {str(item.get("local_file")): item.get("fields") or [] for item in (manifest.get("resources") or []) if item.get("local_file")}
    scenario = infer_scenario(claim)
    safe_ticket = read_safe_ticket_manifest(folder / "manifest.json")
    order_snapshot = order_info_context(
        folder / "order_info_snapshot.json",
        order_reference=safe_ticket.get("order_reference", ""),
    )
    conversation_history = _blind_review_conversation(folder)
    structured_business_context = {
        "order_items": read_json(folder / "order_items.json") or order_snapshot.get("order_items") or manifest.get("order_items") or [],
        "product_master_data": read_json(folder / "product_master.json") or order_snapshot.get("product_master_data") or manifest.get("product_master_data") or {},
        "warehouse_master_data": read_json(folder / "warehouse_master.json") or manifest.get("warehouse_master_data") or {},
        "sku_master_data": read_json(folder / "sku_master.json") or manifest.get("sku_master_data") or {},
        "fulfillment_baseline": order_snapshot.get("fulfillment_baseline") or {},
        "logistics": order_snapshot.get("logistics") or {},
        "conversation_history": conversation_history,
        "conversation_history_policy": "explicit_predecision_user_messages_only",
        "frontdesk_evidence_package": {
            "order_item": order_snapshot.get("order_items") or [],
            "product_master_data": order_snapshot.get("product_master_data") or {},
            "fulfillment_baseline": order_snapshot.get("fulfillment_baseline") or {},
            "logistics": order_snapshot.get("logistics") or {},
            "conversation_history": conversation_history,
        } if order_snapshot else {},
    }
    return {
        "case_id": folder.name,
        "scenario": scenario,
        "scenario_label": {"video_unboxing": "开箱/发错货审核", "product_damage": "商品有伤审核", "minor_material": "未成年人资料审核"}.get(scenario, scenario),
        "video_file": video.name if video else "",
        "video_path": str(video) if video else "",
        "customer_claim": claim,
        "order_context": {
            "ticket_id": safe_ticket.get("ticket_id"),
            "order_no": safe_ticket.get("order_reference"),
            "created_at": manifest.get("created_at"),
        },
        "evidence_assets": evidence_assets,
        "structured_business_context": structured_business_context,
        "supplemental_images": find_supplemental_images_in_dir(folder, supplemental_limit, resource_fields),
    }


def load_case(video: Path, supplemental_limit: int) -> Dict[str, Any]:
    return load_case_from_folder(video.parent, supplemental_limit, video)


def _structured_context_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if text[:1] in {"{", "["}:
            raise ValueError("送审业务字段不是有效 JSON") from exc
        return text


def apply_frontdesk_context(case: Dict[str, Any], scenario: str, raw_context: str) -> Dict[str, Any]:
    """把工作台录入的客服证据包并入模型上下文。"""
    try:
        context = json.loads(raw_context) if raw_context else {}
    except json.JSONDecodeError as exc:
        raise ValueError("送审业务上下文不是有效 JSON") from exc
    if not isinstance(context, dict):
        raise ValueError("送审业务上下文必须是 JSON 对象")
    business_scenario = str(context.get("business_scenario") or "").strip()
    if scenario:
        case["scenario"] = scenario
        case["scenario_label"] = {
            "wrong_item": "发错货审核",
            "missing_item": "漏发货审核",
            "product_damage": "商品有伤审核",
            "minor_refund": "未成年人退款资料审核",
        }.get(
            business_scenario,
            {"video_unboxing": "开箱/发错货审核", "product_damage": "商品有伤审核", "minor_material": "未成年人资料审核"}[scenario],
        )
    customer_claim = str(context.get("customer_claim") or "").strip()
    if customer_claim:
        case["customer_claim"] = customer_claim
    order_context = case.setdefault("order_context", {})
    for key in ("ticket_id", "user_id", "order_no", "logistics_status", "complaint_stage"):
        value = str(context.get(key) or "").strip()
        if value:
            order_context[key] = value
    assessment_at = str(context.get("assessment_at") or "").strip()
    if assessment_at:
        order_context["assessment_at"] = assessment_at
    structured = case.setdefault("structured_business_context", {})
    if business_scenario:
        structured["business_scenario"] = business_scenario
    frontdesk_fields = {
        "order_item": _structured_context_value(context.get("order_item")),
        "sku": _structured_context_value(context.get("sku")),
        "product_master_data": _structured_context_value(context.get("product_master_data")),
        "warehouse_master_data": _structured_context_value(context.get("warehouse_master_data")),
        "logistics": _structured_context_value(
            context.get("logistics_context") or context.get("logistics_status")
        ),
        "conversation_history": _structured_context_value(context.get("conversation_history")),
        "customer_tone": _structured_context_value(context.get("customer_tone")),
        "sop_context": _structured_context_value(context.get("sop_context")),
        "source_case": _structured_context_value(context.get("source_case")),
        "asset_manifest": _structured_context_value(context.get("asset_manifest")),
        "claim_scope": _structured_context_value(context.get("claim_scope")),
        "fulfillment_baseline": _structured_context_value(context.get("fulfillment_baseline")),
        "evidence_coverage": _structured_context_value(context.get("evidence_coverage")),
    }
    existing_frontdesk = structured.get("frontdesk_evidence_package")
    if not isinstance(existing_frontdesk, dict):
        existing_frontdesk = {}
    structured["frontdesk_evidence_package"] = {
        **existing_frontdesk,
        **{key: value for key, value in frontdesk_fields.items() if value},
    }
    continuity_policy = _structured_context_value(context.get("continuity_policy"))
    if isinstance(continuity_policy, dict):
        structured["continuity_policy"] = continuity_policy
    damage_causality_policy = _structured_context_value(context.get("damage_causality_policy"))
    if isinstance(damage_causality_policy, dict):
        structured["damage_causality_policy"] = damage_causality_policy
    review_routing_policy = _structured_context_value(context.get("review_routing_policy"))
    if isinstance(review_routing_policy, dict):
        structured["review_routing_policy"] = review_routing_policy
    minor_refund_policy = _structured_context_value(context.get("minor_refund_policy"))
    if isinstance(minor_refund_policy, dict):
        structured["minor_refund_policy"] = minor_refund_policy
    return case


def load_report_label(case_id: str) -> Dict[str, Any]:
    if not SAMPLE_LABELS.exists():
        return {"available": False}
    try:
        labels = json.loads(SAMPLE_LABELS.read_text(encoding="utf-8-sig")).get("samples") or {}
    except Exception:
        return {"available": False}
    item = labels.get(case_id)
    if not item:
        return {"available": False}
    return {
        "available": True,
        "source": "sample_labels.json，仅报告侧评测使用，未发送给模型",
        "expected_predicted_label": item.get("expected_predicted_label"),
        "human_conclusion": item.get("human_conclusion"),
        "previous_human_conclusion": item.get("previous_human_conclusion"),
    }


def _first_env(names: Iterable[str]) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def gemini_channels() -> List[Dict[str, Any]]:
    return [{**option, "soft_retries": 3} for option in gemini_channel_options()]


def classify_error(status: Optional[int], text: str) -> str:
    if status in {408, 409, 425, 429, 500, 502, 503, 504}:
        return "soft"
    lowered = (text or "").lower()
    return "soft" if any(t in lowered for t in ("timeout", "rate limit", "overloaded", "temporarily")) else "hard"


def post_json(channel: Dict[str, Any], payload: Dict[str, Any], timeout: int, soft_retries: int) -> Dict[str, Any]:
    attempts = max(soft_retries, channel.get("soft_retries", 0)) + 1
    last: Dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        started = time.time()
        log_visual_event(
            LOGGER,
            "visual_model_http_attempt",
            endpoint=channel["endpoint"],
            attempt=attempt,
            max_attempts=attempts,
            timeout_seconds=timeout,
            channel=channel.get("channel"),
            model=channel.get("model"),
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(channel["endpoint"], headers=channel["headers"], json=payload)
            latency = round(time.time() - started, 2)
            if response.status_code < 400:
                log_visual_event(
                    LOGGER,
                    "visual_model_http_success",
                    endpoint=channel["endpoint"],
                    attempt=attempt,
                    max_attempts=attempts,
                    status_code=response.status_code,
                    latency_seconds=latency,
                    channel=channel.get("channel"),
                    model=channel.get("model"),
                )
                return {"ok": True, "attempt": attempt, "status_code": response.status_code, "latency_seconds": latency, "data": response.json()}
            last = {
                "ok": False,
                "attempt": attempt,
                "status_code": response.status_code,
                "latency_seconds": latency,
                "error_type": classify_error(response.status_code, response.text),
                "error": response.text[:1500],
                "retry_after": response.headers.get("Retry-After"),
            }
        except Exception as exc:
            last = {"ok": False, "attempt": attempt, "status_code": None, "latency_seconds": round(time.time() - started, 2), "error_type": classify_error(None, str(exc)), "error": sanitize_error_text(exc, 1500)}
        log_visual_event(
            LOGGER,
            "visual_model_http_failure",
            endpoint=channel["endpoint"],
            attempt=attempt,
            max_attempts=attempts,
            status_code=last.get("status_code"),
            latency_seconds=last.get("latency_seconds"),
            error_type=last.get("error_type"),
            will_retry=bool(last.get("error_type") == "soft" and attempt < attempts),
            channel=channel.get("channel"),
            model=channel.get("model"),
        )
        if last.get("error_type") != "soft" or attempt == attempts:
            return last
        retry_after = last.get("retry_after")
        delay = min(float(retry_after), 30) if retry_after and str(retry_after).replace(".", "", 1).isdigit() else min(2 ** (attempt - 1), 10) + random.uniform(0.1, 0.5)
        time.sleep(delay)
    return last


def extract_text(data: Dict[str, Any]) -> str:
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    return "\n".join(str(p.get("text", "")) for p in parts if isinstance(p, dict) and p.get("text")).strip()


def extract_usage(data: Dict[str, Any]) -> Dict[str, Any]:
    usage = data.get("usageMetadata") or {}
    return {
        "input_tokens": usage.get("promptTokenCount"),
        "output_tokens": (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0),
        "total_tokens": usage.get("totalTokenCount"),
        "raw": usage,
    }


def estimate_cost(usage: Dict[str, Any], model: str = "") -> Dict[str, Any]:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    resolved_model = resolve_gemini_model(model)
    cfg = next((item for item in MODEL_CONFIGS.values() if item.get("model") == resolved_model), None)
    if not cfg:
        return {
            "estimated_usd": None,
            "input_usd_per_1m": None,
            "output_usd_per_1m": None,
            "basis": f"未配置 {resolved_model} 的成本口径。",
            "source": GEMINI_PRICING_SOURCE,
        }
    input_price = float(cfg["input_price"])
    output_price = float(cfg["output_price"])
    usd = input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price
    return {
        "estimated_usd": round(usd, 6),
        "input_usd_per_1m": input_price,
        "output_usd_per_1m": output_price,
        "basis": f"Google Gemini API {cfg['label']} 标准价格基准；第三方渠道可能另有加价。",
        "source": cfg["source"],
    }


def parse_model_json(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {"raw_value": value}
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if match:
            try:
                value = json.loads(match.group(0))
                return value if isinstance(value, dict) else {"raw_value": value}
            except Exception:
                pass
    return {"raw_text": text}


def enforce_boundary(result: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(result)
    output["business_action_allowed"] = False
    output["human_required"] = bool(output.get("human_required"))
    next_step = str(output.get("next_step") or "")
    executed_action = re.search(
        r"(?:已经|已完成|已|立即|直接)(?:执行)?(?:退款|退货|退换|理赔|补偿|赔付|拒赔|拒绝|补发|换货)",
        next_step,
    )
    if executed_action:
        output["next_step"] = "输出明确的证据结论和SOP处理建议；具体业务动作由甲方系统执行。"
        output["boundary_enforced"] = True
    return output


def build_payload(system_prompt: str, user_prompt: str, frames: List[Dict[str, Any]], images: List[Dict[str, Any]]) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = [{"text": user_prompt}]
    for frame in frames:
        path = Path(frame["path"])
        parts.append({"text": f"视频帧 {frame['frame_index']} / {frame['timestamp']} / {frame['file']}"})
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": encode_base64(path)}})
    for image in images:
        path = Path(image["path"])
        parts.append({"text": f"补充图片 {image['image_index']} / {image['file']}"})
        parts.append({"inlineData": {"mimeType": image["mime_type"], "data": encode_base64(path)}})
    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": REVIEW_RESPONSE_SCHEMA,
            "maxOutputTokens": 8192,
        },
    }


def call_gemini(payload: Dict[str, Any], timeout: int, soft_retries: int) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for channel in gemini_channels():
        response = post_json(channel, payload, timeout, soft_retries)
        attempt = {
            "channel": channel["channel"],
            "model": channel["model"],
            "status_code": response.get("status_code"),
            "latency_seconds": response.get("latency_seconds"),
            "attempt": response.get("attempt"),
            "ok": response.get("ok"),
            "error_type": response.get("error_type"),
            "error": response.get("error"),
        }
        if response.get("ok"):
            raw_text = extract_text(response["data"])
            parsed = enforce_boundary(parse_model_json(raw_text))
            usage = extract_usage(response["data"])
            unknown_cost_calls = sum(1 for item in attempts if not item.get("ok"))
            cost_status = "partial_unknown" if unknown_cost_calls else "estimated"
            cost = estimate_cost(usage, channel["model"])
            cost.update({"status": cost_status, "unknown_cost_calls": unknown_cost_calls})
            if unknown_cost_calls:
                cost["basis"] += f" 前序 {unknown_cost_calls} 次失败调用成本未知。"
            attempt.update({"raw_text": raw_text, "parsed": parsed, "usage": usage, "cost": cost})
            attempts.append(attempt)
            return {
                "status": "success",
                "winner": attempt,
                "attempts": attempts,
                "cost_status": cost_status,
                "unknown_cost_calls": unknown_cost_calls,
                "estimated_cost_calls": 1,
            }
        attempts.append(attempt)
        if response.get("error_type") == "soft":
            continue
    cost_status = "unknown" if attempts else "not_incurred"
    return {
        "status": "failed",
        "winner": None,
        "attempts": attempts,
        "cost_status": cost_status,
        "cost": {
            "estimated_usd": None,
            "status": cost_status,
            "basis": "模型调用失败，成本未知。" if attempts else "未发生模型调用，未产生费用。",
            "source": GEMINI_PRICING_SOURCE,
        },
    }


def evaluate(parsed: Dict[str, Any], label: Dict[str, Any]) -> Dict[str, Any]:
    if not label.get("available"):
        return {"available": False, "note": "没有报告侧人工标签。"}
    expected = str(label.get("expected_predicted_label") or "")
    actual = str(parsed.get("predicted_label") or "")
    return {
        "available": True,
        "definition": "命中只表示模型 predicted_label 与报告侧人工标签一致；人工标签未发送给模型。",
        "expected_predicted_label": expected,
        "actual_predicted_label": actual,
        "hit": actual == expected,
        "status": "match" if actual == expected else "label_conflict",
    }


def _safe_confidence(value: Any, default: float = 0.0) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, confidence)) if math.isfinite(confidence) else default


def policy_decision(parsed: Dict[str, Any], policy: Dict[str, Any] = DEFAULT_POLICY) -> Dict[str, Any]:
    label = str(parsed.get("predicted_label") or "").lower()
    confidence = _safe_confidence(parsed.get("confidence"))
    if label in {"positive", "negative"} and confidence >= float(policy["auto_confidence"]):
        return {
            "system_yes_no": "YES" if label == "positive" else "NO",
            "review_mode": "high_confidence_sample_review",
            "action": "高置信参考结论，可进入人工抽检队列。",
            "threshold": policy,
        }
    if confidence < float(policy["manual_confidence"]) or label not in {"positive", "negative"}:
        return {
            "system_yes_no": "REVIEW",
            "review_mode": "full_manual_review",
            "action": "低置信或证据不足，要求人工逐条查看。",
            "threshold": policy,
        }
    return {
        "system_yes_no": "YES" if label == "positive" else "NO",
        "review_mode": "optional_sample_review",
        "action": "中等置信事实建议，甲方可按风险偏好抽检，不要求逐单人工复核。",
        "threshold": policy,
    }


def detail(title: str, data: Any, open_: bool = True) -> str:
    return f"<details {'open' if open_ else ''}><summary>{h(title)}</summary><pre>{json_block(data)}</pre></details>"


def render_html(report: Dict[str, Any]) -> str:
    gemini = report.get("gemini") or {}
    parsed = ((gemini.get("winner") or {}).get("parsed") or {})
    winner = gemini.get("winner") or {}
    evaluation = report.get("evaluation") or {}
    frames = report.get("frames") or []
    images = report.get("supplemental_images") or []
    hit_text = "命中" if evaluation.get("hit") else "未命中" if evaluation.get("available") else "未评测"
    size_sku = parsed.get("size_sku_assessment") or {}
    continuity = parsed.get("continuity_assessment") or {}
    supporting = parsed.get("supporting_evidence") or []
    challenging = parsed.get("challenging_evidence") or []
    policy = report.get("policy_decision") or policy_decision(parsed)
    actual_model = str(winner.get("model") or report.get("model") or resolve_gemini_model())
    cost = winner.get("cost") or (
        estimate_cost(winner.get("usage") or {}, actual_model) if winner else gemini.get("cost")
    )
    if not cost:
        cost_status = "unknown" if gemini.get("attempts") else "not_incurred"
        cost = {
            "estimated_usd": None,
            "status": cost_status,
            "basis": "模型调用失败，成本未知。" if cost_status == "unknown" else "未发生模型调用，未产生费用。",
            "source": GEMINI_PRICING_SOURCE,
        }
    cost_display = (
        f"${cost['estimated_usd']}"
        if cost.get("estimated_usd") is not None
        else "成本未知" if cost.get("status") == "unknown" else "未发生"
    )
    label = str(parsed.get("predicted_label") or "")
    confidence = parsed.get("confidence")
    if parsed.get("visual_evidence_verdict"):
        visual_verdict = str(parsed.get("visual_evidence_verdict"))
    elif label == "positive":
        visual_verdict = f"视觉证据支持用户诉求，置信度 {confidence}。"
    elif label == "negative":
        visual_verdict = f"视觉证据不支持用户诉求，置信度 {confidence}。"
    else:
        visual_verdict = f"视觉证据仍需复核，置信度 {confidence}。"
    follow_up_reason = parsed.get("business_follow_up_reason") or "这里的人工跟进不是在否定视觉结论，而是因为退款、补发、拒赔、库存核对等业务动作必须由客服系统或VIP客服坐席执行。"

    def evidence_cards(items: List[Dict[str, Any]], empty: str) -> str:
        if not items:
            return f'<p class="muted">{h(empty)}</p>'
        cards = []
        for item in items:
            source = item.get("file") or item.get("timestamp") or item.get("source_type") or "-"
            cards.append(
                '<div class="evidence-card">'
                f'<small>{h(item.get("source_type") or "evidence")} · {h(source)}</small>'
                f'<p>{h(item.get("description") or item)}</p>'
                f'<b>置信度 {h(item.get("confidence"))}</b>'
                '</div>'
            )
        return "".join(cards)

    frame_figures = "".join(
        f'<figure><a class="media-link" href="#frame-{h(f["frame_index"])}" title="点击放大">'
        f'<img src="{h(f["uri"])}" alt="{h(f["file"])}"></a>'
        f'<figcaption>帧{h(f["frame_index"])} · {h(f["timestamp"])} · 点击放大</figcaption></figure>'
        for f in frames
    )
    image_figures = "".join(
        f'<figure><a class="media-link" href="#image-{h(i["image_index"])}" title="点击放大">'
        f'<img src="{h(i["uri"])}" alt="{h(i["file"])}"></a>'
        f'<figcaption>补充图{h(i["image_index"])} · {h(i["file"])} · 点击放大</figcaption></figure>'
        for i in images
    )
    lightboxes = "".join(
        f'<a id="frame-{h(f["frame_index"])}" class="lightbox" href="#" aria-label="关闭放大图">'
        f'<img src="{h(f["uri"])}" alt="{h(f["file"])}">'
        f'<span>帧{h(f["frame_index"])} · {h(f["timestamp"])} · 点击任意处关闭</span></a>'
        for f in frames
    ) + "".join(
        f'<a id="image-{h(i["image_index"])}" class="lightbox" href="#" aria-label="关闭放大图">'
        f'<img src="{h(i["uri"])}" alt="{h(i["file"])}">'
        f'<span>补充图{h(i["image_index"])} · {h(i["file"])} · 点击任意处关闭</span></a>'
        for i in images
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(actual_model)} 单样本审核报告</title>
  <style>
    body {{ margin:0; font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif; color:#182421; background:#f6fbf7; }}
    main {{ max-width:1280px; margin:0 auto; padding:24px 16px 56px; }}
    section {{ background:white; border:1px solid #dce8e3; border-radius:8px; padding:18px; margin:14px 0; box-shadow:0 12px 34px rgba(20,40,34,.07); }}
    h1 {{ margin:0 0 8px; font-size:30px; letter-spacing:0; }}
    h2 {{ margin:0 0 12px; font-size:20px; letter-spacing:0; }}
    p, li {{ line-height:1.7; }}
    .muted {{ color:#66736f; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; }}
    .cell {{ border:1px solid #dce8e3; border-radius:8px; padding:10px; background:#fbfdf9; }}
    .cell small {{ display:block; color:#66736f; margin-bottom:5px; }}
    .wide {{ grid-column:1 / -1; }}
    .evidence-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:10px; }}
    .evidence-card {{ border:1px solid #dce8e3; border-radius:8px; padding:12px; background:#fbfdf9; }}
    .evidence-card small {{ display:block; color:#66736f; margin-bottom:6px; }}
    .evidence-card p {{ margin:0 0 8px; }}
    .pill {{ display:inline-flex; border-radius:999px; padding:5px 10px; border:1px solid #c9ded5; background:#eaf7ef; color:#0f5d3f; font-size:12px; }}
    .fail {{ background:#fde8e5; color:#8f2f2a; border-color:#f2beb9; }}
    .media {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:10px; }}
    figure {{ margin:0; border:1px solid #dce8e3; border-radius:8px; overflow:hidden; background:white; }}
    .media-link {{ display:block; cursor:zoom-in; }}
    .media img {{ display:block; width:100%; aspect-ratio:16/9; object-fit:cover; background:#111; }}
    figcaption {{ padding:7px 9px; color:#66736f; font-size:12px; }}
    .lightbox {{ position:fixed; inset:0; z-index:50; display:none; place-items:center; padding:24px; background:rgba(7,16,13,.88); cursor:zoom-out; text-decoration:none; }}
    .lightbox:target {{ display:grid; }}
    .lightbox img {{ max-width:96vw; max-height:86vh; width:auto; height:auto; object-fit:contain; border-radius:8px; background:#111; box-shadow:0 20px 80px rgba(0,0,0,.45); }}
    .lightbox span {{ margin-top:12px; color:#fff; font-size:14px; }}
    details {{ border:1px dashed #d1e2db; border-radius:8px; padding:9px 11px; margin:10px 0; background:#fbfdf9; }}
    summary {{ cursor:pointer; font-weight:700; }}
    pre {{ white-space:pre-wrap; word-break:break-word; max-height:520px; overflow:auto; background:#14221e; color:#eaf4ef; border-radius:8px; padding:12px; font-size:12px; }}
  </style>
</head>
<body>
{lightboxes}
<main>
  <section>
    <span class="pill">单样本审计</span>
    <h1>{h(actual_model)} 单样本审核报告</h1>
    <p>本报告只验证一个开箱/发错货样本能否被当前模型审核清楚；不做模型选型，不设计多模型复核。</p>
  </section>

  <section>
    <h2>审核目标与证据包</h2>
    <div class="grid">
      <div class="cell"><small>用户诉求</small><b>{h((report.get("case") or {}).get("customer_claim"))}</b></div>
      <div class="cell"><small>视频帧</small><b>{h(len(frames))} 张</b></div>
      <div class="cell"><small>补充图片</small><b>{h(len(images))} 张</b></div>
      <div class="cell"><small>结构化主数据</small><b>{h("已提供" if any((report.get("case") or {}).get("structured_business_context", {}).values()) else "未提供，需从图片证据提取")}</b></div>
      <div class="cell wide"><small>本轮判断目标</small><b>核对订单要求的角色/款式/尺寸与用户实际收到的实物、包装、合格证是否一致，并评估开箱视频一镜到底可信度和调包风险。</b></div>
    </div>
  </section>

  <section>
    <h2>模型到底说了什么</h2>
    <div class="grid">
      <div class="cell"><small>API 状态</small><b>{h(report["gemini"].get("status"))}</b></div>
      <div class="cell"><small>模型</small><b>{h(actual_model)}</b></div>
      <div class="cell"><small>模型结论 decision</small><b>{h(parsed.get("decision"))}</b></div>
      <div class="cell"><small>诉求标签 predicted_label</small><b>{h(parsed.get("predicted_label"))}</b></div>
      <div class="cell"><small>后端可读结论</small><b>{h(parsed.get("system_yes_no") or policy.get("system_yes_no"))}</b></div>
      <div class="cell"><small>置信度</small><b>{h(parsed.get("confidence"))}</b></div>
      <div class="cell"><small>历史标签对比</small><b>{h(hit_text)}</b></div>
      <div class="cell"><small>耗时</small><b>{h(winner.get("latency_seconds"))}s</b></div>
      <div class="cell"><small>Token</small><b>{h((winner.get("usage") or {}).get("total_tokens"))}</b></div>
      <div class="cell"><small>估算成本</small><b>{h(cost_display)}</b></div>
      <div class="cell wide"><small>策略动作</small><b>{h(policy.get("action"))}</b><p class="muted">阈值：高置信 ≥ {h((policy.get("threshold") or {}).get("auto_confidence"))}；低置信 &lt; {h((policy.get("threshold") or {}).get("manual_confidence"))}。</p></div>
    </div>
    <p><b>视觉质检结论：</b>{h(visual_verdict)}</p>
    <p><b>模型核心理由：</b>{h(parsed.get("confidence_reason"))}</p>
    <p><b>业务跟进建议：</b>{h(parsed.get("next_step"))}</p>
    <p><b>为什么还要人工：</b>{h(follow_up_reason)}</p>
    <p><b>历史标签对比是什么意思：</b>这是报告侧用本地人工标签做的回归对照，不是 Gemini 输出，也不是业务裁决。如果旧人工标签被复盘修正，报告会按修正后的标签重新评测。</p>
    <p><b>是否泄题：</b>这是报告侧说明，不是 Gemini 输出。发送给模型的是用户诉求、订单上下文、抽帧帧号/时间戳、补充图片文件名和图片内容；没有发送 sample_labels.json、human_conclusion、expected_predicted_label 或人工答案。</p>
    <p class="muted">{h(cost.get("basis"))} 来源：{h(cost.get("source") or GEMINI_PRICING_SOURCE)}</p>
  </section>

  <section>
    <h2>规格与连续性判断</h2>
    <div class="grid">
      <div class="cell"><small>订单要求</small><pre>{json_block(parsed.get("expected_order_item"))}</pre></div>
      <div class="cell"><small>实际实物</small><pre>{json_block(parsed.get("actual_received_item"))}</pre></div>
      <div class="cell wide"><small>尺寸/SKU 结论</small><p>{h(size_sku.get("assessment"))}</p></div>
      <div class="cell wide"><small>视频连续性与调包风险</small><p>{h(continuity.get("reason"))}</p><p class="muted">连续性分数：{h(continuity.get("continuity_score"))}；调包风险：{h(continuity.get("swap_risk_level"))}</p></div>
    </div>
  </section>

  <section>
    <h2>模型采信的证据</h2>
    <div class="evidence-grid">{evidence_cards(supporting, "模型未列出支持证据。")}</div>
    <h2 style="margin-top:16px">模型列出的反证或风险</h2>
    <div class="evidence-grid">{evidence_cards(challenging, "模型未列出明显反证。")}</div>
  </section>

  <section>
    <h2>送入模型的帧</h2>
    <div class="media">{frame_figures}</div>
  </section>

  <section>
    <h2>送入模型的补充图片</h2>
    <div class="media">{image_figures or '<p>无</p>'}</div>
  </section>

  <section>
    <h2>报告详情</h2>
    {detail("发送给模型的 SystemPrompt", report.get("system_prompt"))}
    {detail("发送给模型的审核任务 Prompt", report.get("user_prompt"))}
    {detail("输入证据包摘要", report.get("case"))}
    {detail("模型原始返回全文", winner.get("raw_text"))}
    {detail("模型返回 JSON 解析结果", parsed)}
    {detail("报告侧人工评测标签", report.get("report_label"))}
    {detail("报告侧评测结果", evaluation)}
    {detail("请求统计与重试", {"winner": {k: v for k, v in winner.items() if k not in {"raw_text", "parsed"}}, "attempts": report["gemini"].get("attempts")}, False)}
  </section>
</main>
</body>
</html>"""


def run(args: argparse.Namespace) -> Dict[str, Any]:
    load_env()
    video = Path(args.video).expanduser().resolve()
    if not video.exists():
        raise SystemExit(f"视频不存在：{video}")
    if not gemini_channels():
        raise SystemExit(
            "未找到 Gemini 渠道 Key 或 Base URL：BananaRouter、百度、API易各需 Key + Base URL；"
            "Google 官方只需 Key。旧部署可将 BROUTER_API_KEY、BRouter_API_KEY 或 APIYI_API_KEY "
            "与 VISION_REVIEW_GEMINI_BASE_URL 配对。"
        )

    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = TMP_DIR / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    case = load_case(video, args.supplemental_image_limit)
    case = apply_frontdesk_context(case, args.scenario, args.context_json)
    frame_sample = sample_video_frames(video, args.fps, args.max_frames, args.probe_seconds, args.frame_width, run_dir)
    frames = frame_sample["frames"][: max(1, args.api_frame_limit)]
    system_prompt = build_system_prompt(case["scenario"])
    user_prompt = build_user_prompt(case, frame_sample, frames)
    payload = build_payload(system_prompt, user_prompt, frames, case["supplemental_images"])
    gemini = call_gemini(payload, args.request_timeout, args.soft_retries)
    parsed = ((gemini.get("winner") or {}).get("parsed") or {})
    report_label = load_report_label(case["case_id"])
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": ((gemini.get("winner") or {}).get("model") or resolve_gemini_model()),
        "case": {
            "case_id": case["case_id"],
            "scenario": case["scenario"],
            "scenario_label": case["scenario_label"],
            "video_file": case["video_file"],
            "customer_claim": case["customer_claim"],
            "order_context": case["order_context"],
            "structured_business_context": case["structured_business_context"],
            "evidence_assets": case["evidence_assets"],
        },
        "frame_sampling": {k: v for k, v in frame_sample.items() if k != "frames"},
        "frames": frames,
        "supplemental_images": case["supplemental_images"],
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "not_sent_to_model": ["sample_labels.json", "human_conclusion", "expected_predicted_label", "人工答案"],
        "gemini": gemini,
        "report_label": report_label,
        "evaluation": evaluate(parsed, report_label),
        "policy_decision": policy_decision(parsed),
    }
    json_path = REPORT_DIR / f"gemini35_single_audit_{stamp}.json"
    html_path = REPORT_DIR / f"gemini35_single_audit_{stamp}.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    return {"json_report": str(json_path), "html_report": str(html_path), "summary": report["evaluation"]}


def main() -> int:
    result = run(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
