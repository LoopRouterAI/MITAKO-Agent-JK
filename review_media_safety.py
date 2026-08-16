# -*- coding: utf-8 -*-
"""视觉审核入口共用的文件筛选与媒体内容校验。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MEDIA_SUFFIXES = VIDEO_SUFFIXES | IMAGE_SUFFIXES
FOLDER_SUFFIXES = MEDIA_SUFFIXES | {".txt", ".json"}
SYSTEM_FILE_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
SKIP_REASON_LABELS = {
    "system_directory": "系统目录文件",
    "hidden_file": "隐藏文件",
    "appledouble_file": "macOS 资源副本",
    "system_file": "系统元数据文件",
    "unsupported_suffix": "不支持的文件格式",
    "empty_file": "空文件",
    "invalid_media_content": "文件扩展名与实际媒体内容不一致",
}


def normalized_upload_parts(name: str) -> list[str]:
    return [part for part in str(name or "").replace("\\", "/").split("/") if part]


def ignored_upload_reason(name: str) -> Optional[str]:
    """识别目录上传中的系统文件，必须在文件名清洗前调用。"""
    parts = normalized_upload_parts(name)
    if not parts:
        return "hidden_file"
    lowered = [part.lower() for part in parts]
    if "__macosx" in lowered:
        return "system_directory"
    basename = lowered[-1]
    if basename.startswith("._"):
        return "appledouble_file"
    if basename in SYSTEM_FILE_NAMES:
        return "system_file"
    if any(part.startswith(".") for part in parts):
        return "hidden_file"
    return None


def valid_media_magic(suffix: str, head: bytes) -> bool:
    normalized = str(suffix or "").lower()
    if normalized in {".jpg", ".jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    if normalized == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if normalized == ".webp":
        return head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    if normalized in {".mp4", ".mov", ".m4v"}:
        return b"ftyp" in head[:32]
    if normalized in {".webm", ".mkv"}:
        return head.startswith(b"\x1aE\xdf\xa3")
    return normalized in {".txt", ".json"}


def valid_media_file(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in MEDIA_SUFFIXES:
        return False
    try:
        with path.open("rb") as stream:
            return valid_media_magic(path.suffix, stream.read(32))
    except OSError:
        return False


def public_skip_reason(reason: str) -> str:
    return SKIP_REASON_LABELS.get(reason, "不可用文件")
