# -*- coding: utf-8 -*-
"""用 OpenAI 图片模型复核两个由视频模型自主发现的候选窗口。"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

import httpx
from dotenv import load_dotenv


RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["target_identity_summary", "candidate_a", "candidate_b", "preferred_candidate"],
    "properties": {
        "target_identity_summary": {"type": "string"},
        "candidate_a": {"$ref": "#/$defs/candidate"},
        "candidate_b": {"$ref": "#/$defs/candidate"},
        "preferred_candidate": {
            "type": "string",
            "enum": ["a", "b", "both", "neither", "uncertain"],
        },
    },
    "$defs": {
        "candidate": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "identity_match", "identity_confidence", "visible_traits",
                "issue_visibility", "issue_confidence", "issue_description", "reason",
            ],
            "properties": {
                "identity_match": {
                    "type": "string",
                    "enum": ["matched", "not_matched", "uncertain"],
                },
                "identity_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "visible_traits": {"type": "array", "items": {"type": "string"}},
                "issue_visibility": {
                    "type": "string",
                    "enum": ["visible", "not_visible", "uncertain"],
                },
                "issue_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "issue_description": {"type": "string"},
                "reason": {"type": "string"},
            },
        }
    },
}


def _image_part(path: Path) -> Dict[str, str]:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:{mime};base64,{encoded}",
        "detail": "high",
    }


def _append_images(content: List[Dict[str, str]], label: str, paths: Iterable[Path]) -> None:
    content.append({"type": "input_text", "text": label})
    content.extend(_image_part(path) for path in paths)


def build_payload(
    model: str,
    references: List[Path],
    claim_images: List[Path],
    candidate_a: List[Path],
    candidate_b: List[Path],
) -> Dict[str, Any]:
    content: List[Dict[str, str]] = [{
        "type": "input_text",
        "text": (
            "只做商品身份与可见伤点复核，不判断开箱完整性、责任或售后。"
            "官方参考图只定义目标商品标准外观；用户伤点图只提供目标商品身份和所诉位置，"
            "不能证明伤点在开箱时已存在。逐组比较角色、发型、姿态、服饰、面具位置、"
            "底座和颜色；相似系列商品不得写 matched。候选帧过小、模糊或遮挡时写 uncertain。"
        ),
    }]
    _append_images(content, "官方目标商品参考图：", references)
    _append_images(content, "用户提交的目标商品及所诉伤点参考图：", claim_images)
    _append_images(content, "候选 A 的相邻原分辨率视频帧：", candidate_a)
    _append_images(content, "候选 B 的相邻原分辨率视频帧：", candidate_b)
    return {
        "model": model,
        "reasoning": {"effort": "high"},
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "candidate_identity_review",
                "strict": True,
                "schema": RESPONSE_SCHEMA,
            }
        },
    }


def _output_text(data: Dict[str, Any]) -> str:
    texts = [
        str(content.get("text") or "")
        for item in data.get("output") or []
        if isinstance(item, dict)
        for content in item.get("content") or []
        if isinstance(content, dict) and content.get("type") == "output_text"
    ]
    return "\n".join(item for item in texts if item).strip()


def _media_manifest(groups: Dict[str, List[Path]]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        group: [
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in paths
        ]
        for group, paths in groups.items()
    }


def run_model(
    client: httpx.Client,
    endpoint: str,
    api_key: str,
    model: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    started = time.perf_counter()
    response = client.post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
    )
    wall_seconds = round(time.perf_counter() - started, 2)
    request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
    if response.is_error:
        return {
            "model": model,
            "status": "failed",
            "status_code": response.status_code,
            "request_id": request_id,
            "wall_seconds": wall_seconds,
            "error": response.text[:2000],
        }
    data = response.json()
    text = _output_text(data)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    return {
        "model": model,
        "status": "success" if isinstance(parsed, dict) else "invalid_output",
        "status_code": response.status_code,
        "request_id": request_id or data.get("id"),
        "wall_seconds": wall_seconds,
        "usage": data.get("usage") or {},
        "result": parsed,
        "raw_text": "" if isinstance(parsed, dict) else text[:4000],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAI 候选帧身份与伤点 A/B")
    parser.add_argument("--reference", type=Path, action="append", required=True)
    parser.add_argument("--claim-image", type=Path, action="append", required=True)
    parser.add_argument("--candidate-a", type=Path, action="append", required=True)
    parser.add_argument("--candidate-b", type=Path, action="append", required=True)
    parser.add_argument("--models", nargs="+", default=["gpt-5.6-luna", "gpt-5.6-terra"])
    parser.add_argument("--base-url", default="https://api.apiyi.com/v1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("APIYI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("未配置 APIYI_API_KEY")
    groups = {
        "references": args.reference,
        "claim_images": args.claim_image,
        "candidate_a": args.candidate_a,
        "candidate_b": args.candidate_b,
    }
    missing = [str(path) for paths in groups.values() for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(f"图片不存在：{missing}")

    endpoint = args.base_url.rstrip("/") + "/responses"
    results = []
    with httpx.Client(timeout=httpx.Timeout(600, connect=20), trust_env=False) as client:
        for model in args.models:
            payload = build_payload(
                model,
                args.reference,
                args.claim_image,
                args.candidate_a,
                args.candidate_b,
            )
            results.append(run_model(client, endpoint, api_key, model, payload))
    report = {
        "experiment": "openai_candidate_identity_ab_v1",
        "label_isolation": "只使用官方参考图、用户提交图和模型自主候选帧；不读取人工标签或答案时间窗。",
        "media": _media_manifest(groups),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] == "success" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
