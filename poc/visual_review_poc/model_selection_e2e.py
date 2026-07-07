# -*- coding: utf-8 -*-
"""三大审核场景模型选型 E2E：同一证据包，多模型对比。"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

import cv2
import httpx
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from poc.visual_review_poc.local_video_triage_demo import (
    DEFAULT_POLICY,
    POC_DIR,
    REPORT_DIR,
    TMP_DIR,
    build_system_prompt,
    enforce_boundary,
    evaluate,
    extract_usage,
    format_time,
    h,
    json_block,
    load_case,
    load_case_from_folder,
    load_env,
    load_report_label,
    parse_model_json,
    policy_decision,
    sample_video_frames,
)
from runtime_paths import app_root

ROOT = app_root()
SAMPLE_ROOT = ROOT / "docs" / "三大审核场景的小量样本"
CNY_PER_USD = 7.0
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
PRICING_NOTE = "Gemini 3.1 Flash Lite 按用户成本表 0.25/1.50 USD 每百万 tokens 并按 7 元/USD 折算；Qwen3.5-Flash 与 Doubao Seed 2.0 Lite 按用户提供阶梯价依据输入 tokens 选择区间；本轮未使用音频输入。Gemini 3.5 Flash 仍按脚本内官方价格基准估算。"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


MODEL_CONFIGS: Dict[str, Dict[str, Any]] = {
    "gemini35": {
        "label": "Gemini 3.5 Flash",
        "provider": "gemini_native",
        "model": "gemini-3.5-flash",
        "input_price": 1.50,
        "output_price": 9.00,
        "currency": "USD",
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
    },
    "gemini31lite": {
        "label": "Gemini 3.1 Flash Lite",
        "provider": "gemini_native",
        "model": "gemini-3.1-flash-lite",
        "input_price": 0.25,
        "output_price": 1.50,
        "currency": "USD",
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
    },
    "qwen35flash": {
        "label": "Qwen3.5 Flash",
        "provider": "openai_compatible",
        "model": "qwen3.5-flash",
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "key_env": "DASHSCOPE_API_KEY",
        "input_price": 0.20,
        "output_price": 2.00,
        "currency": "CNY",
        "source": "用户提供成本表：Qwen3.5-Flash 阶梯价",
        "pricing_tiers": [
            {"max_input_tokens": 128_000, "input_price": 0.20, "output_price": 2.00},
            {"max_input_tokens": 256_000, "input_price": 0.80, "output_price": 8.00},
            {"max_input_tokens": 1_000_000, "input_price": 1.20, "output_price": 12.00},
        ],
    },
    "doubao20lite": {
        "label": "Doubao Seed 2.0 Lite",
        "provider": "openai_compatible",
        "model": "doubao-seed-2-0-lite-260428",
        "display_model": "doubao-seed-2.0-lite",
        "endpoint": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "key_env": "ARK_API_KEY",
        "input_price": 0.60,
        "output_price": 3.60,
        "currency": "CNY",
        "source": "用户提供成本表：Doubao-Seed-2.0-lite 阶梯价",
        "pricing_tiers": [
            {"max_input_tokens": 32_000, "input_price": 0.60, "output_price": 3.60},
            {"max_input_tokens": 128_000, "input_price": 0.90, "output_price": 5.40},
            {"max_input_tokens": 256_000, "input_price": 1.80, "output_price": 10.80},
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="三大审核场景模型选型 E2E")
    parser.add_argument("--samples-dir", default=str(SAMPLE_ROOT), help="样本目录")
    parser.add_argument("--models", default="gemini35,gemini31lite,doubao20lite", help="逗号分隔模型 key")
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--max-frames-per-video", type=int, default=6)
    parser.add_argument("--api-frame-limit", type=int, default=18)
    parser.add_argument("--probe-seconds", type=float, default=0.0)
    parser.add_argument("--frame-width", type=int, default=960)
    parser.add_argument("--supplemental-image-limit", type=int, default=20)
    parser.add_argument("--request-timeout", type=int, default=300)
    parser.add_argument("--soft-retries", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=4)
    return parser.parse_args()


def mime_for(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "image/jpeg"


def data_url(path: Path, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def compress_image(src: Path, dest: Path, max_edge: int = 1280, quality: int = 82) -> Path:
    raw = np.fromfile(str(src), dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if image is None:
        return src
    h0, w0 = image.shape[:2]
    scale = min(1.0, max_edge / max(h0, w0))
    if scale < 1.0:
        image = cv2.resize(image, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return src
    dest.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(dest))
    return dest


def prepare_media(items: List[Dict[str, Any]], media_dir: Path) -> List[Dict[str, Any]]:
    prepared = []
    for index, item in enumerate(items, start=1):
        src = Path(item["path"])
        api_path = compress_image(src, media_dir / f"{index:03d}_{src.stem}.jpg")
        copied = dict(item)
        copied["api_path"] = str(api_path)
        copied["api_mime_type"] = "image/jpeg" if api_path.suffix.lower() in {".jpg", ".jpeg"} else mime_for(api_path)
        copied["api_bytes"] = api_path.stat().st_size if api_path.exists() else None
        prepared.append(copied)
    return prepared


def load_case_bundle(sample_dir: Path, args: argparse.Namespace, run_dir: Path) -> Dict[str, Any]:
    videos = sorted(p for p in sample_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES)
    case = load_case(videos[0], args.supplemental_image_limit) if videos else load_case_from_folder(sample_dir, args.supplemental_image_limit)
    if not videos and not case.get("supplemental_images"):
        raise SystemExit(f"样本缺少可审核的视频或图片：{sample_dir}")
    all_frames: List[Dict[str, Any]] = []
    video_summaries = []
    for video_index, video in enumerate(videos, start=1):
        sample = sample_video_frames(video, args.fps, args.max_frames_per_video, args.probe_seconds, args.frame_width, run_dir / f"video_{video_index}")
        picked = sample["frames"]
        video_summaries.append({"video_index": video_index, "file": video.name, **{k: v for k, v in sample.items() if k != "frames"}})
        for frame in picked:
            copied = dict(frame)
            copied["video_index"] = video_index
            copied["video_file"] = video.name
            copied["global_frame_index"] = len(all_frames) + 1
            all_frames.append(copied)
    case["videos"] = video_summaries
    case["frames"] = all_frames[: args.api_frame_limit]
    case["supplemental_images"] = case["supplemental_images"][: args.supplemental_image_limit]
    media_dir = run_dir / "api_media"
    case["frames"] = prepare_media(case["frames"], media_dir / "frames")
    case["supplemental_images"] = prepare_media(case["supplemental_images"], media_dir / "images")
    return case


def build_selection_prompt(case: Dict[str, Any]) -> str:
    frames = [
        {
            "global_frame_index": f["global_frame_index"],
            "video_index": f["video_index"],
            "video_file": f["video_file"],
            "timestamp": f["timestamp"],
            "file": f["file"],
        }
        for f in case["frames"]
    ]
    images = [
        {
            "image_index": i["image_index"],
            "file": i["file"],
            "fields": i.get("fields", []),
            "width": i.get("width"),
            "height": i.get("height"),
            "has_exif": i.get("has_exif"),
        }
        for i in case["supplemental_images"]
    ]
    return f"""请基于同一证据包进行售后视觉审核。

审核场景：{case.get("scenario_label")}
用户诉求：{case.get("customer_claim") or "未提供"}
订单/工单上下文：{json.dumps(case.get("order_context") or {}, ensure_ascii=False)}
结构化业务上下文：{json.dumps(case.get("structured_business_context") or {}, ensure_ascii=False)}
证据资源字段说明：{json.dumps(case.get("evidence_assets") or [], ensure_ascii=False)}
视频清单：{json.dumps(case.get("videos") or [], ensure_ascii=False)}
送入模型的视频帧清单：{json.dumps(frames, ensure_ascii=False)}
送入模型的补充图片清单：{json.dumps(images, ensure_ascii=False)}

审核方法要求：
1. 先拆解用户诉求：用户认为应该收到什么、实际收到什么、争议类型是什么。
2. 再核对业务上下文：订单商品名、SKU、规格、角色、款式、数量、随机/盲抽规则，以及仓库/商品主数据。
3. 对所有视频按 video_index + global_frame_index + timestamp 做跨帧审查：箱子/商品是否持续在镜头内，是否离镜、跳切、遮挡、换手、剪辑或可能调包。
4. 对补充图片做交叉验证：是否能对应视频里的同一实物，是否有 EXIF、低分辨率、AI 水印、生成痕迹、局部裁剪或过度锐化风险。
5. 必须同时写支持证据和反证/不确定性。证据足够时要敢于输出 positive 或 negative；证据不足才输出 review。
6. 只能引用已提供的帧编号和时间戳，不得编造不存在的时间点。
7. 样本目录名、人工结论、expected_predicted_label 没有提供给你；你只能根据本证据包独立判断。

请严格输出 JSON 对象，字段：
- decision: pass / manual_review / request_more_material / fail。只表示 POC 流转，不代表业务裁决。
- predicted_label: positive / negative / review。
- system_yes_no: YES / NO / REVIEW。
- confidence: 0 到 1。
- overall_audit: 整体审核结论，必须包含 conclusion、confidence、core_reason、business_follow_up_suggestion。
- visual_evidence_verdict: 一句话视觉质检结论。
- visual_qc_conclusion: 视觉质检结论，必须包含 verdict、confidence、core_reason。
- confidence_reason: 置信度理由。
- video_audit_conclusion: 视频审核结论，必须包含 continuity_score、continuity_reason、swap_risk_level(high/medium/low)、edit_or_cut_risk、opening_integrity。
- customer_claim_parse: expected_item、claimed_received_item、claimed_mismatch_type。
- expected_order_item: 订单要求的商品/角色/SKU/规格/数量。
- actual_received_item: 实际收到的商品/角色/SKU/规格/数量或破损事实。
- audit_methods: 实际使用的审核方法数组。
- frame_findings: 每帧一句客观观察，必须含 video_index、global_frame_index、timestamp、visible_facts、risk。
- adopted_evidence: 模型采信的关键证据数组，每项必须含 source_type、video_index、global_frame_index 或 image_index、timestamp、file、fact、why_it_matters、confidence；必须能回链到上方帧清单或补充图片清单。
- supporting_evidence: 支持用户诉求的证据数组。
- challenging_evidence: 反证或风险数组。
- continuity_assessment: 多视频整体连续性、调包/剪辑风险。
- authenticity_assessment: 图片真实性、AI生成/水印/EXIF/低分辨率/裁剪风险，尤其商品有伤场景必须填写。
- size_sku_assessment: 发错货/发错尺寸场景填写；其他场景可写 null。
- issue_timestamps: 问题帧数组，只能使用上面帧清单中的时间戳。
- skeptical_questions: 你主动质疑自己结论的问题数组。
- material_gaps: 还缺什么材料。
- conclusion_argument: support、challenge、why_not_final_business_decision。
- business_action_allowed: false。
- human_required: true。
- business_follow_up_reason: 人工跟进原因。
- next_step: 后续人工客服建议，不直接退款、拒赔、补发或定责。
- model_limitations: 局限。
"""


def gemini_payload(system_prompt: str, user_prompt: str, case: Dict[str, Any]) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = [{"text": user_prompt}]
    for frame in case["frames"]:
        path = Path(frame["api_path"])
        parts.append({"text": f"视频{frame['video_index']} 帧{frame['global_frame_index']} / {frame['timestamp']} / {frame['video_file']}"})
        parts.append({"inline_data": {"mime_type": frame["api_mime_type"], "data": base64.b64encode(path.read_bytes()).decode("ascii")}})
    for image in case["supplemental_images"]:
        path = Path(image["api_path"])
        parts.append({"text": f"补充图片 {image['image_index']} / {image['file']} / fields={image.get('fields', [])}"})
        parts.append({"inline_data": {"mime_type": image["api_mime_type"], "data": base64.b64encode(path.read_bytes()).decode("ascii")}})
    return {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": parts}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0.1, "maxOutputTokens": 8192},
    }


def openai_messages(system_prompt: str, user_prompt: str, case: Dict[str, Any]) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for frame in case["frames"]:
        path = Path(frame["api_path"])
        content.append({"type": "text", "text": f"视频{frame['video_index']} 帧{frame['global_frame_index']} / {frame['timestamp']} / {frame['video_file']}"})
        content.append({"type": "image_url", "image_url": {"url": data_url(path, frame["api_mime_type"])}})
    for image in case["supplemental_images"]:
        path = Path(image["api_path"])
        content.append({"type": "text", "text": f"补充图片 {image['image_index']} / {image['file']} / fields={image.get('fields', [])}"})
        content.append({"type": "image_url", "image_url": {"url": data_url(path, image["api_mime_type"])}})
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}]


def classify_error(status: Optional[int], text: str) -> str:
    if status in {408, 409, 425, 429, 500, 502, 503, 504}:
        return "soft"
    lowered = (text or "").lower()
    return "soft" if any(t in lowered for t in ("timeout", "rate limit", "overloaded", "temporarily")) else "hard"


def estimate_model_cost(cfg: Dict[str, Any], usage: Dict[str, Any]) -> Dict[str, Any]:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    tiers = cfg.get("pricing_tiers") or []
    tier = next((item for item in tiers if input_tokens <= int(item["max_input_tokens"])), None)
    input_price = float((tier or cfg).get("input_price", 0))
    output_price = float((tier or cfg).get("output_price", 0))
    amount = input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price
    usd = amount if cfg["currency"] == "USD" else amount / CNY_PER_USD
    return {
        "amount": round(amount, 6),
        "currency": cfg["currency"],
        "estimated_usd": round(usd, 6),
        "input_price_per_1m": input_price,
        "output_price_per_1m": output_price,
        "pricing_tier": tier,
        "fx_cny_per_usd": CNY_PER_USD,
        "source": cfg["source"],
        "note": "本轮未使用音频输入；音频单价未计入。",
    }


def post_with_retries(endpoint: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int, retries: int) -> Dict[str, Any]:
    last: Dict[str, Any] = {}
    for attempt in range(1, retries + 2):
        started = time.time()
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(endpoint, headers=headers, json=payload)
            latency = round(time.time() - started, 2)
            if response.status_code < 400:
                return {"ok": True, "status_code": response.status_code, "latency_seconds": latency, "data": response.json(), "attempt": attempt}
            last = {"ok": False, "status_code": response.status_code, "latency_seconds": latency, "error": response.text[:1600], "error_type": classify_error(response.status_code, response.text), "attempt": attempt, "retry_after": response.headers.get("Retry-After")}
        except Exception as exc:
            last = {"ok": False, "status_code": None, "latency_seconds": round(time.time() - started, 2), "error": str(exc)[:1600], "error_type": classify_error(None, str(exc)), "attempt": attempt}
        if last["error_type"] != "soft" or attempt > retries:
            return last
        retry_after = last.get("retry_after")
        delay = min(float(retry_after), 30) if retry_after and str(retry_after).replace(".", "", 1).isdigit() else min(2 ** (attempt - 1), 8) + random.uniform(0.1, 0.4)
        time.sleep(delay)
    return last


def gemini_request_options(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    options: List[Dict[str, Any]] = []
    apiyi_key = os.getenv("APIYI_API_KEY")
    if apiyi_key:
        base = os.getenv("APIYI_GEMINI_BASE_URL", "https://api.apiyi.com").rstrip("/")
        options.append({
            "endpoint": f"{base}/v1beta/models/{cfg['model']}:generateContent",
            "headers": {"x-goog-api-key": apiyi_key, "Content-Type": "application/json"},
        })
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        base = os.getenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
        options.append({
            "endpoint": f"{base}/v1beta/models/{cfg['model']}:generateContent",
            "headers": {"x-goog-api-key": gemini_key, "Content-Type": "application/json"},
        })
    return options


def extract_openai_text(data: Dict[str, Any]) -> str:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                texts.append(str(item.get("text") or item.get("content") or item.get("output_text") or ""))
        return "\n".join(t for t in texts if t).strip()
    return str(message.get("reasoning_content") or "").strip()


def compact_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """保留模型响应里用于复盘的内容，避免把整包重复图像或无关字段塞进报告。"""
    output = {
        "id": data.get("id"),
        "model": data.get("model"),
        "usage": data.get("usage") or data.get("usageMetadata"),
    }
    if data.get("choices") is not None:
        output["choices"] = data.get("choices")
    if data.get("candidates") is not None:
        output["candidates"] = data.get("candidates")
    if data.get("promptFeedback") is not None:
        output["promptFeedback"] = data.get("promptFeedback")
    return output


def call_model(cfg: Dict[str, Any], case: Dict[str, Any], timeout: int, retries: int) -> Dict[str, Any]:
    system_prompt = build_system_prompt(case["scenario"])
    user_prompt = build_selection_prompt(case)
    if cfg["provider"] == "gemini_native":
        options = gemini_request_options(cfg)
        if not options:
            return {"status": "skipped", "error": "missing_api_key"}
        payload = gemini_payload(system_prompt, user_prompt, case)
        response: Dict[str, Any] = {}
        failures: List[Dict[str, Any]] = []
        for option in options:
            response = post_with_retries(option["endpoint"], option["headers"], payload, timeout, retries)
            if response.get("ok"):
                break
            failures.append({key: response.get(key) for key in ("status_code", "latency_seconds", "error_type", "attempt")})
        if not response.get("ok"):
            return {"status": "failed", **response, "attempts": failures}
        text = "\n".join(p.get("text", "") for p in (((response["data"].get("candidates") or [{}])[0].get("content") or {}).get("parts") or []) if isinstance(p, dict))
        usage = extract_usage(response["data"])
    else:
        key = os.getenv(cfg["key_env"])
        if not key:
            return {"status": "skipped", "error": f"missing_{cfg['key_env']}"}
        payload = {
            "model": cfg["model"],
            "messages": openai_messages(system_prompt, user_prompt, case),
            "temperature": 0.1,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        response = post_with_retries(cfg["endpoint"], {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, payload, timeout, retries)
        if not response.get("ok"):
            return {"status": "failed", **response}
        text = extract_openai_text(response["data"])
        raw_usage = response["data"].get("usage") or {}
        usage = {
            "input_tokens": raw_usage.get("prompt_tokens"),
            "output_tokens": raw_usage.get("completion_tokens"),
            "total_tokens": raw_usage.get("total_tokens"),
            "raw": raw_usage,
        }
    parsed_before_boundary = parse_model_json(text)
    parsed = enforce_boundary(parsed_before_boundary)
    label = load_report_label(case["case_id"])
    return {
        "status": "success",
        "model": cfg["model"],
        "display_model": cfg.get("display_model") or cfg["model"],
        "label": cfg["label"],
        "provider": cfg["provider"],
        "status_code": response.get("status_code"),
        "attempt": response.get("attempt"),
        "latency_seconds": response.get("latency_seconds"),
        "usage": usage,
        "cost": estimate_model_cost(cfg, usage),
        "raw_text": text,
        "raw_response": compact_response(response.get("data") or {}),
        "parsed_before_boundary": parsed_before_boundary,
        "parsed": parsed,
        "evaluation": evaluate(parsed, label),
        "policy_decision": policy_decision(parsed),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }


def score_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("status") != "success":
        return {"quality": 0, "value": 0, "field_completeness": 0, "evidence_reference_score": 0}
    parsed = result.get("parsed") or {}
    hit = 1 if (result.get("evaluation") or {}).get("hit") else 0

    def value_at(path: str) -> Any:
        current: Any = parsed
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    required_paths = [
        "predicted_label",
        "system_yes_no",
        "confidence",
        "overall_audit.conclusion",
        "overall_audit.confidence",
        "overall_audit.core_reason",
        "overall_audit.business_follow_up_suggestion",
        "visual_qc_conclusion.verdict",
        "visual_qc_conclusion.confidence",
        "visual_qc_conclusion.core_reason",
        "video_audit_conclusion.continuity_score",
        "video_audit_conclusion.continuity_reason",
        "video_audit_conclusion.swap_risk_level",
        "video_audit_conclusion.edit_or_cut_risk",
        "adopted_evidence",
        "frame_findings",
        "business_follow_up_reason",
        "next_step",
    ]
    field_completeness = sum(1 for path in required_paths if value_at(path) not in (None, "", [])) / len(required_paths)
    adopted = parsed.get("adopted_evidence") or parsed.get("supporting_evidence") or []
    referenced = [
        item
        for item in adopted
        if isinstance(item, dict)
        and (item.get("timestamp") or item.get("global_frame_index") or item.get("frame_index") or item.get("image_index") or item.get("file"))
        and (item.get("fact") or item.get("description"))
    ]
    evidence_reference_score = min(1.0, len(referenced) / 3) if adopted else 0.0
    structured = 1 if field_completeness >= 0.85 and evidence_reference_score >= 0.67 else 0
    confidence = float(parsed.get("confidence") or 0)
    quality = hit * 35 + structured * 15 + field_completeness * 25 + evidence_reference_score * 20 + confidence * 5
    cost = float((result.get("cost") or {}).get("estimated_usd") or 0.001)
    value = quality / max(cost, 0.001)
    return {
        "quality": round(quality, 2),
        "value": round(value, 2),
        "field_completeness": round(field_completeness, 2),
        "evidence_reference_score": round(evidence_reference_score, 2),
    }


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_model: Dict[str, List[Dict[str, Any]]] = {}
    for row in results:
        by_model.setdefault(row["model_key"], []).append(row)
    summaries = []
    for key, rows in by_model.items():
        ok_rows = [r for r in rows if r["result"].get("status") == "success"]
        scores = [score_result(r["result"]) for r in rows]
        total_cost = sum(float(((r["result"].get("cost") or {}).get("estimated_usd") or 0)) for r in ok_rows)
        total_original_cost = sum(float(((r["result"].get("cost") or {}).get("amount") or 0)) for r in ok_rows)
        currency = MODEL_CONFIGS[key]["currency"]
        hit_count = sum(1 for r in ok_rows if (r["result"].get("evaluation") or {}).get("hit"))
        structured_count = sum(1 for r in ok_rows if score_result(r["result"])["field_completeness"] >= 0.85 and score_result(r["result"])["evidence_reference_score"] >= 0.67)
        full_success = len(ok_rows) == len(rows) and len(rows) > 0
        eligible = full_success and hit_count == len(rows) and structured_count == len(rows)
        summaries.append(
            {
                "model_key": key,
                "label": MODEL_CONFIGS[key]["label"],
                "success": len(ok_rows),
                "total": len(rows),
                "hit": hit_count,
                "structured": structured_count,
                "hit_rate": round(hit_count / max(len(rows), 1), 3),
                "structured_rate": round(structured_count / max(len(rows), 1), 3),
                "avg_quality": round(sum(s["quality"] for s in scores) / max(len(scores), 1), 2),
                "avg_value": round(sum(s["value"] for s in scores) / max(len(scores), 1), 2),
                "total_cost_usd": round(total_cost, 6),
                "total_cost_amount": round(total_original_cost, 6),
                "currency": currency,
                "total_cost_display": f"{round(total_original_cost, 6)} {currency} / ${round(total_cost, 6)}",
                "avg_latency": round(sum(float(r["result"].get("latency_seconds") or 0) for r in ok_rows) / max(len(ok_rows), 1), 2),
                "eligible_for_recommendation": eligible,
                "exclusion_reason": "" if eligible else "未满足 100% 成功、100% 报告侧命中、100% 结构化完整且证据可回链的 POC 推荐门槛。",
            }
        )
    eligible_summaries = [s for s in summaries if s["eligible_for_recommendation"]]
    recommend_effect = max(eligible_summaries, key=lambda x: (x["avg_quality"], x["hit"], x["structured"], -x["avg_latency"])) if eligible_summaries else None
    recommend_value = sorted(eligible_summaries, key=lambda x: (x["total_cost_usd"], -x["avg_quality"], x["avg_latency"]))[:2]
    return {"models": summaries, "best_effect": recommend_effect, "best_value": recommend_value}


def render_html(report: Dict[str, Any]) -> str:
    def file_uri_to_path(uri: str) -> Optional[Path]:
        parsed = urlparse(str(uri or ""))
        if parsed.scheme != "file":
            return None
        path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return Path(path)

    def media_src(uri: str) -> str:
        path = file_uri_to_path(uri)
        if path and path.exists():
            mime = mime_for(path)
            return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
        return uri

    def money(cost: Dict[str, Any]) -> str:
        if not cost:
            return "-"
        amount = cost.get("amount")
        currency = cost.get("currency")
        usd = cost.get("estimated_usd")
        return f"{h(amount)} {h(currency)} / ${h(usd)}"

    def field_score(result: Dict[str, Any]) -> str:
        score = score_result(result)
        return f"{h(score.get('field_completeness'))} / {h(score.get('evidence_reference_score'))}"

    def model_status(m: Dict[str, Any]) -> str:
        if m.get("eligible_for_recommendation"):
            return "可进入推荐池"
        return m.get("exclusion_reason") or "未进入推荐池"

    summary_rows = "".join(
        "<tr>"
        f"<td><b>{h(m['label'])}</b><br><small>{h(m['model_key'])}</small></td>"
        f"<td>{m['success']}/{m['total']}</td>"
        f"<td>{m['hit']} / {h(m.get('hit_rate'))}</td>"
        f"<td>{m['structured']} / {h(m.get('structured_rate'))}</td>"
        f"<td>{m['avg_quality']}</td>"
        f"<td>{m['avg_value']}</td>"
        f"<td>{h(m.get('total_cost_display') or ('$' + str(m['total_cost_usd'])))}</td>"
        f"<td>{m['avg_latency']}s</td>"
        f"<td>{h(model_status(m))}</td>"
        "</tr>"
        for m in report["summary"]["models"]
    )

    case_packages: Dict[str, Dict[str, Any]] = {}
    for row in report["results"]:
        case_packages.setdefault(
            row["case_id"],
            {
                "case_id": row["case_id"],
                "scenario_label": row["scenario_label"],
                "evidence_package": row["evidence_package"],
            },
        )

    evidence_sections = []
    for case in case_packages.values():
        package = case["evidence_package"]
        video_rows = "".join(
            f"<tr><td>{h(v.get('video_index'))}</td><td>{h(v.get('file'))}</td><td>{h(v.get('duration_seconds'))}s</td><td>{h(v.get('native_fps'))}</td><td>{h(v.get('sampled_frames'))}</td></tr>"
            for v in package.get("videos", [])
        )
        frame_cards = "".join(
            "<figure>"
            f"<a href=\"{h(media_src(f.get('api_uri') or f.get('uri')))}\" target=\"_blank\"><img src=\"{h(media_src(f.get('api_uri') or f.get('uri')))}\" alt=\"{h(f.get('file'))}\"></a>"
            f"<figcaption>视频{h(f.get('video_index'))} · 全局帧{h(f.get('global_frame_index'))} · {h(f.get('timestamp'))}</figcaption>"
            "</figure>"
            for f in package.get("frames", [])
        )
        image_cards = "".join(
            "<figure>"
            f"<a href=\"{h(media_src(i.get('api_uri') or i.get('uri')))}\" target=\"_blank\"><img src=\"{h(media_src(i.get('api_uri') or i.get('uri')))}\" alt=\"{h(i.get('file'))}\"></a>"
            f"<figcaption>补充图{h(i.get('image_index'))} · {h(i.get('file'))}</figcaption>"
            "</figure>"
            for i in package.get("supplemental_images", [])
        )
        evidence_sections.append(
            f"""<details class="case-block" open>
              <summary>{h(case['case_id'])} · {h(case['scenario_label'])} · {h(package.get('frames_sent'))} 帧 / {h(package.get('supplemental_images_sent'))} 张补充图</summary>
              <h3>视频清单</h3>
              <table><thead><tr><th>序号</th><th>文件</th><th>时长</th><th>原生 FPS</th><th>送入帧数</th></tr></thead><tbody>{video_rows}</tbody></table>
              <h3>送入模型的视频帧</h3>
              <div class="media-grid">{frame_cards}</div>
              <h3>送入模型的补充图片</h3>
              <div class="media-grid">{image_cards}</div>
            </details>"""
        )

    detail_rows = []
    for row in report["results"]:
        result = row["result"]
        parsed = result.get("parsed") or {}
        usage = result.get("usage") or {}
        eval_result = result.get("evaluation") or {}
        detail_rows.append(
            "<tr>"
            f"<td>{h(row['case_id'])}<br><small>{h(row['scenario_label'])}</small></td>"
            f"<td><b>{h(MODEL_CONFIGS[row['model_key']]['label'])}</b><br><small>{h(result.get('display_model') or result.get('model'))}</small></td>"
            f"<td>{h(result.get('status'))}</td>"
            f"<td>{h(parsed.get('system_yes_no') or (result.get('policy_decision') or {}).get('system_yes_no'))}</td>"
            f"<td>{h(parsed.get('predicted_label'))}</td>"
            f"<td>{h(parsed.get('confidence'))}</td>"
            f"<td>{h(eval_result.get('hit'))}</td>"
            f"<td>{field_score(result)}</td>"
            f"<td>{h(usage.get('input_tokens'))} / {h(usage.get('output_tokens'))} / {h(usage.get('total_tokens'))}</td>"
            f"<td>{money(result.get('cost') or {})}</td>"
            f"<td>{h(result.get('latency_seconds'))}s</td>"
            f"<td>{h(parsed.get('visual_evidence_verdict') or parsed.get('confidence_reason') or result.get('error'))}</td>"
            "</tr>"
        )
    raw_details = "".join(
        f"""<details>
          <summary>{h(row['case_id'])} / {h(MODEL_CONFIGS[row['model_key']]['label'])} · 模型原始返回与解析</summary>
          <div class="subgrid">
            <div><h3>模型原始文本</h3><pre>{h((row['result'].get('raw_text') or row['result'].get('error') or ''))}</pre></div>
            <div><h3>模型原始解析 JSON</h3><pre>{json_block(row['result'].get('parsed_before_boundary') or {})}</pre></div>
            <div><h3>边界保护后结果</h3><pre>{json_block(row['result'].get('parsed') or {})}</pre></div>
            <div><h3>接口响应摘要</h3><pre>{json_block(row['result'].get('raw_response') or {})}</pre></div>
          </div>
          <details><summary>本次 System Prompt</summary><pre>{h(row['result'].get('system_prompt') or '')}</pre></details>
          <details><summary>本次 User Prompt</summary><pre>{h(row['result'].get('user_prompt') or '')}</pre></details>
        </details>"""
        for row in report["results"]
    )
    best_effect = report["summary"].get("best_effect") or {}
    best_value = report["summary"].get("best_value") or []
    best_value_text = "、".join(m["label"] for m in best_value) if best_value else "暂无满足推荐门槛的模型"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>三大审核模型选型 E2E</title>
  <style>
    :root {{ --ink:#1d2723; --muted:#6f7b74; --line:#dfe7de; --paper:#fffdf7; --wash:#f4f1e8; --accent:#5f7f5d; --deep:#15211d; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif; background:var(--wash); color:var(--ink); }}
    main {{ max-width:1480px; margin:0 auto; padding:26px 16px 64px; }}
    section {{ background:var(--paper); border:1px solid var(--line); border-radius:8px; padding:18px; margin:14px 0; box-shadow:0 12px 30px rgba(35,45,36,.06); }}
    h1 {{ margin:0 0 8px; font-size:30px; letter-spacing:0; }}
    h2 {{ margin:0 0 12px; font-size:20px; letter-spacing:0; }}
    h3 {{ margin:14px 0 8px; font-size:15px; }}
    p, li {{ line-height:1.7; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ border-bottom:1px solid var(--line); padding:10px; text-align:left; vertical-align:top; }}
    th {{ background:#ece8dc; color:#26322c; }}
    small,.muted {{ color:var(--muted); }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:var(--deep); color:#edf5ee; padding:12px; border-radius:8px; max-height:520px; overflow:auto; font-size:12px; line-height:1.55; }}
    details {{ border:1px solid var(--line); border-radius:8px; padding:10px 12px; margin:10px 0; background:#fffefa; }}
    summary {{ cursor:pointer; font-weight:700; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:10px; }}
    .subgrid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:12px; }}
    .cell {{ border:1px solid var(--line); border-radius:8px; padding:12px; background:#fbfaf3; }}
    .cell b {{ display:block; margin-top:5px; font-size:18px; }}
    .media-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(130px,1fr)); gap:10px; }}
    figure {{ margin:0; border:1px solid var(--line); border-radius:8px; overflow:hidden; background:white; }}
    figure img {{ width:100%; aspect-ratio:9/12; object-fit:cover; display:block; }}
    figcaption {{ padding:7px; font-size:12px; color:var(--muted); line-height:1.4; }}
    .table-scroll {{ overflow:auto; }}
    .pill {{ display:inline-block; padding:3px 8px; border-radius:999px; background:#e7ece4; color:#334238; font-size:12px; }}
    @media (max-width:760px) {{ main {{ padding:14px 10px 40px; }} section {{ padding:13px; }} h1 {{ font-size:24px; }} table {{ min-width:900px; }} }}
  </style>
</head>
<body>
<main>
  <section>
    <h1>三大审核模型选型 E2E</h1>
    <p>同一 Case 的多视频已合并为一个证据包；所有候选模型接收同一批抽帧和补充图片。人工标签只在报告侧评测使用，没有进入模型 Prompt。样本量仍小，本报告只能给 POC 选型信号，不代表生产准确率。</p>
    <p><span class="pill">命中定义</span> 命中只表示模型输出的 predicted_label 与报告侧人工标签一致；它不是模型自己给自己的评分，也不是业务裁决。</p>
    <p><span class="pill">成本口径</span> {h(report.get('pricing_note') or '成本为报告侧估算，实际以渠道账单为准。')}</p>
  </section>
  <section>
    <h2>推荐结论</h2>
    <div class="grid">
      <div class="cell"><small>效果最好/最稳候选</small><b>{h(best_effect.get('label') or '暂无满足推荐门槛的模型')}</b></div>
      <div class="cell"><small>性价比最高两个</small><b>{h(best_value_text)}</b></div>
      <div class="cell"><small>策略阈值</small><b>≥{DEFAULT_POLICY['auto_confidence']} 高置信抽检；&lt;{DEFAULT_POLICY['manual_confidence']} 逐条人工</b></div>
      <div class="cell"><small>推荐准入</small><b>100% 成功 + 100% 命中 + 结构化完整</b></div>
    </div>
  </section>
  <section>
    <h2>模型汇总</h2>
    <div class="table-scroll"><table><thead><tr><th>模型</th><th>成功</th><th>命中/命中率</th><th>结构化/完整率</th><th>质量分</th><th>性价比分</th><th>总成本（原币 / USD）</th><th>平均耗时</th><th>推荐状态</th></tr></thead><tbody>{summary_rows}</tbody></table></div>
  </section>
  <section>
    <h2>证据包核对</h2>
    {''.join(evidence_sections)}
  </section>
  <section>
    <h2>逐 Case 结果</h2>
    <div class="table-scroll"><table><thead><tr><th>Case</th><th>模型</th><th>状态</th><th>YES/NO</th><th>标签</th><th>置信度</th><th>命中</th><th>字段/证据回链</th><th>输入/输出/总 tokens</th><th>成本</th><th>耗时</th><th>结论摘要</th></tr></thead><tbody>{''.join(detail_rows)}</tbody></table></div>
  </section>
  <section>
    <h2>原始返回与解析</h2>
    {raw_details}
  </section>
</main>
</body>
</html>"""


def run(args: argparse.Namespace) -> Dict[str, Any]:
    load_env()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = TMP_DIR / f"model_selection_{stamp}"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    sample_dirs = [p for p in sorted(Path(args.samples_dir).iterdir()) if p.is_dir() and p.name.startswith("sample_")]
    model_keys = [m.strip() for m in args.models.split(",") if m.strip() in MODEL_CONFIGS]
    cases = [load_case_bundle(sample_dir, args, run_dir / sample_dir.name) for sample_dir in sample_dirs]
    jobs = []
    for case in cases:
        for model_key in model_keys:
            jobs.append((case, model_key))

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        future_map = {
            pool.submit(call_model, MODEL_CONFIGS[model_key], case, args.request_timeout, args.soft_retries): (case, model_key)
            for case, model_key in jobs
        }
        for future in as_completed(future_map):
            case, model_key = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"status": "failed", "error": str(exc)[:1600]}
            results.append(
                {
                    "case_id": case["case_id"],
                    "scenario": case["scenario"],
                    "scenario_label": case["scenario_label"],
                    "model_key": model_key,
                    "result": result,
                    "evidence_package": {
                        "videos": case["videos"],
                        "frames_sent": len(case["frames"]),
                        "frames": [
                            {
                                "global_frame_index": f["global_frame_index"],
                                "video_index": f["video_index"],
                                "video_file": f["video_file"],
                                "timestamp": f["timestamp"],
                                "file": f["file"],
                                "uri": f.get("uri"),
                                "api_uri": Path(f["api_path"]).resolve().as_uri() if f.get("api_path") else f.get("uri"),
                                "api_bytes": f.get("api_bytes"),
                            }
                            for f in case["frames"]
                        ],
                        "supplemental_images_sent": len(case["supplemental_images"]),
                        "supplemental_images": [
                            {
                                "image_index": i["image_index"],
                                "file": i["file"],
                                "fields": i.get("fields", []),
                                "uri": i.get("uri"),
                                "api_uri": Path(i["api_path"]).resolve().as_uri() if i.get("api_path") else i.get("uri"),
                                "api_bytes": i.get("api_bytes"),
                                "width": i.get("width"),
                                "height": i.get("height"),
                                "has_exif": i.get("has_exif"),
                            }
                            for i in case["supplemental_images"]
                        ],
                    },
                }
            )
    results.sort(key=lambda x: (x["case_id"], x["model_key"]))
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "models": {key: MODEL_CONFIGS[key] for key in model_keys},
        "summary": summarize(results),
        "results": results,
        "pricing_note": PRICING_NOTE,
    }
    json_path = REPORT_DIR / f"visual_model_selection_e2e_{stamp}.json"
    html_path = REPORT_DIR / f"visual_model_selection_e2e_{stamp}.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    return {"json_report": str(json_path), "html_report": str(html_path), "summary": report["summary"]}


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
