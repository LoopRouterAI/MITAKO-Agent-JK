# -*- coding: utf-8 -*-
"""从甲方样本生成不含人工答案的视觉审核证据包。"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review_input_safety import assert_review_input_safe, sanitize_review_input
from review_media_safety import ignored_upload_reason


MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm", ".mkv"}
SAFE_MANIFEST_KEYS = {"id", "type", "order_no", "created_at", "updated_at", "resources"}


def _customer_context(source: Path) -> dict:
    reply_path = source / "reply.json"
    if not reply_path.exists():
        return {"source": "customer_messages_only", "messages": []}
    try:
        rows = json.loads(reply_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        rows = []
    messages = []
    seen = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or str(row.get("from") or "").lower() != "user":
            continue
        text = str(row.get("text") or "").strip()
        if not text or text == "用户拒绝了售后方案":
            continue
        text = str(sanitize_review_input(text)).strip()
        if not text or text == "[评测标签已隔离]":
            continue
        text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号已脱敏]", text)
        normalized = re.sub(r"\s+", "", text)
        if normalized in seen:
            continue
        seen.add(normalized)
        messages.append(
            {
                "created_at": row.get("created_at"),
                "text": text,
                "has_media": bool(row.get("image")),
            }
        )
    return {
        "source": "customer_messages_only",
        "messages": messages[-40:],
        "excluded": "管理员消息、系统处置结果、人工标注和最终审核答案",
    }


def build_bundle(source: Path, output: Path) -> dict:
    if not source.is_dir():
        raise ValueError(f"样本目录不存在：{source}")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    copied = []
    for item in source.iterdir():
        if (
            item.is_file()
            and ignored_upload_reason(item.name) is None
            and (item.suffix.lower() in MEDIA_SUFFIXES or item.name == "content.txt")
        ):
            target = output / item.name
            if item.suffix.lower() in MEDIA_SUFFIXES:
                try:
                    os.link(item, target)
                except OSError:
                    shutil.copy2(item, target)
            else:
                shutil.copy2(item, target)
            copied.append(item.name)

    source_manifest = {}
    manifest_path = source / "manifest.json"
    if manifest_path.exists():
        source_manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    safe_manifest = {key: source_manifest.get(key) for key in SAFE_MANIFEST_KEYS if key in source_manifest}
    safe_manifest["resources"] = [
        {
            "local_file": item.get("local_file"),
            "fields": item.get("fields") or [],
            "status": item.get("status"),
        }
        for item in source_manifest.get("resources") or []
        if isinstance(item, dict) and item.get("local_file") in copied
    ]
    assert_review_input_safe(safe_manifest)
    (output / "manifest.json").write_text(json.dumps(safe_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    order_path = source / "order_info_snapshot.json"
    if order_path.exists():
        try:
            safe_order = sanitize_review_input(json.loads(order_path.read_text(encoding="utf-8-sig")))
        except (OSError, json.JSONDecodeError):
            safe_order = {}
        if safe_order:
            assert_review_input_safe(safe_order)
            (output / "order_info_snapshot.json").write_text(
                json.dumps(safe_order, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            copied.append("order_info_snapshot.json")
    customer_context = _customer_context(source)
    if customer_context["messages"]:
        assert_review_input_safe(customer_context)
        (output / "customer_context.json").write_text(
            json.dumps(customer_context, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    included_files = sorted(item.name for item in output.iterdir() if item.is_file())
    audit = {
        "source_case_id": source.name,
        "copied_files": copied,
        "included_files": included_files,
        "excluded_files": sorted(item.name for item in source.iterdir() if item.is_file() and item.name not in copied and item.name != "manifest.json"),
        "manifest_keys": sorted(safe_manifest),
        "customer_message_count": len(customer_context["messages"]),
        "label_isolation": "annotation、reply 原文件、管理员消息、人工结论和正负样本标签未复制；只保留清洗后的用户本人消息。",
    }
    (output / "blind_bundle_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="生成视觉审核盲测证据包")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build_bundle(args.source, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
