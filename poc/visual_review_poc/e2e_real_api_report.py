# -*- coding: utf-8 -*-
"""Gemini 真实 API 可行性 E2E：下载公开素材，有 Key 则真实请求，无 Key 则出阻塞报告。"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, List

import httpx

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = Path(__file__).resolve().parent / "reports" / "internal_archive"
ASSET_DIR = ROOT / "tmp" / "gemini_e2e_assets"
DEFAULT_MODEL = "gemini-3.5-flash"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SAMPLES = [
    {
        "case_id": "online_product_damage",
        "scenario": "product_damage",
        "title": "公开样例：损伤/划痕包装图",
        "url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Parker%27s_Tiger_Tim_Toffee_-_TWCMS-G12131_%2816692709511%29.jpg",
        "mime_type": "image/jpeg",
        "source": "Wikimedia Commons / Tyne & Wear Archives & Museums",
    },
    {
        "case_id": "online_minor_material",
        "scenario": "minor_material",
        "title": "公开样例：身份证样张",
        "url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Identity_card_of_the_State_of_Califorinia%2C_sample_%282010%29.jpg",
        "mime_type": "image/jpeg",
        "source": "Wikimedia Commons / public domain sample",
    },
    {
        "case_id": "online_video_keyframe_proxy",
        "scenario": "video_unboxing",
        "title": "公开样例：包装/商品关键帧替代物",
        "url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Broken_phone_box.jpg",
        "mime_type": "image/jpeg",
        "source": "Wikimedia Commons / public domain",
    },
]


SCHEMA = {
    "type": "object",
    "properties": {
        "case_id": {"type": "string"},
        "scenario": {"type": "string"},
        "decision": {"type": "string", "enum": ["pass", "suspect", "fail", "manual_review", "request_more_material"]},
        "confidence": {"type": "number"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "string"},
        "next_step": {"type": "string"},
        "human_required": {"type": "boolean"},
        "mock_only": {"type": "boolean"},
        "boundary": {"type": "string"},
    },
    "required": ["case_id", "scenario", "decision", "confidence", "issues", "evidence", "next_step", "human_required", "mock_only", "boundary"],
}


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def download_samples() -> List[Dict[str, Any]]:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    assets = []
    for sample in SAMPLES:
        target = ASSET_DIR / f"{sample['case_id']}.jpg"
        status = "cached" if target.exists() and target.stat().st_size > 0 else "downloaded"
        if status == "downloaded":
            try:
                req = urllib.request.Request(sample["url"], headers={"User-Agent": "MITAKO-POC/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    target.write_bytes(resp.read())
            except Exception as exc:
                _write_fallback_image(target, sample)
                status = f"fallback_generated: {type(exc).__name__}"
        actual_mime_type = "image/png" if "fallback_generated" in status else sample["mime_type"]
        assets.append({**sample, "local_path": str(target), "bytes": target.stat().st_size, "download_status": status, "actual_mime_type": actual_mime_type})
    return assets


def _write_fallback_image(target: Path, sample: Dict[str, Any]) -> None:
    width, height = 480, 320
    pixels = []
    bg = (248, 250, 252)
    marker = {
        "product_damage": (220, 38, 38),
        "minor_material": (37, 99, 235),
        "video_unboxing": (22, 163, 74),
    }.get(sample["scenario"], (15, 23, 42))
    for y in range(height):
        row = []
        for x in range(width):
            color = bg
            if 35 < x < 445 and 35 < y < 285:
                if x in range(36, 40) or x in range(441, 445) or y in range(36, 40) or y in range(281, 285):
                    color = (30, 41, 59)
            if sample["scenario"] == "product_damage" and 160 < x < 330 and 170 < y < 185:
                color = marker
            if sample["scenario"] == "minor_material" and 140 < x < 340 and 150 < y < 220:
                color = marker if x in range(141, 145) or x in range(336, 340) or y in range(151, 155) or y in range(216, 220) else bg
            if sample["scenario"] == "video_unboxing" and 145 < x < 335 and 130 < y < 230:
                color = marker if x in range(146, 150) or x in range(331, 335) or y in range(131, 135) or y in range(226, 230) else bg
            row.extend(color)
        pixels.append(bytes(row))
    raw = b"".join(b"\x00" + row for row in pixels)
    def chunk(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    target.write_bytes(png)


def build_prompt(sample: Dict[str, Any]) -> str:
    return f"""你是客服视觉审核助手。请根据图片判断场景：{sample['scenario']}。
样例标题：{sample['title']}。
只输出 JSON，字段必须匹配 schema。
业务边界：
- 只做辅助初筛和人工复核建议。
- 不自动定责、不自动拒赔、不自动退款、不自动补发。
- 未成年人资料即使看起来完整，也必须 human_required=true。
- 当前素材来自公开网络样例，不代表甲方真实样本。
请把 mock_only 设为 false，boundary 写明“真实 Gemini API 调用结果，仍需甲方样本盲测和人工复核”。"""


def call_gemini(sample: Dict[str, Any], api_key: str, model: str) -> Dict[str, Any]:
    image_b64 = base64.b64encode(Path(sample["local_path"]).read_bytes()).decode("ascii")
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": build_prompt(sample)},
                    {"inline_data": {"mime_type": sample.get("actual_mime_type") or sample["mime_type"], "data": image_b64}},
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "response_schema": SCHEMA,
            "temperature": 0.1,
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    with httpx.Client(timeout=60) as client:
        response = client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code, "error": response.text[:1200]}
    data = response.json()
    text = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [{}])[0].get("text", "")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {"raw_text": text}
    return {"ok": True, "status_code": response.status_code, "result": parsed}


def build_report() -> Dict[str, Any]:
    load_env()
    assets = download_samples()
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    model = os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
    results = []
    if api_key:
        for sample in assets:
            started = time.time()
            result = call_gemini(sample, api_key, model)
            result["latency_seconds"] = round(time.time() - started, 2)
            result["case_id"] = sample["case_id"]
            result["scenario"] = sample["scenario"]
            results.append(result)
    return {
        "goal": "验证三类视觉审核能否用 Gemini 真实 API 跑通端到端结构化报告",
        "model": model,
        "api_key_configured": bool(api_key),
        "materials": assets,
        "run_status": "real_api_called" if api_key else "blocked_missing_gemini_api_key",
        "results": results,
        "feasibility": {
            "technical_path": "可行：公开素材下载、inline image、结构化 JSON schema、报告生成链路已固定。",
            "current_blocker": "" if api_key else "当前 .env 未配置 GEMINI_API_KEY/GOOGLE_API_KEY，因此未发起真实 Gemini 请求。",
            "next_step": "配置 Gemini Key 后重跑本脚本；随后替换为甲方脱敏样本做盲测。",
        },
    }


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report()
    report_path = REPORT_DIR / f"gemini_real_api_feasibility_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"报告已写入: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
