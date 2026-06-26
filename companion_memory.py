# -*- coding: utf-8 -*-
"""Companion 记忆系统 — 规则提取用户画像 / 喜好 / 需求并持久化"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

# 常见 IP / 品类关键词（演示环境规则提取）
_KNOWN_IPS = (
    "原神", "排球少年", "咒术回战", "初音未来", "鬼灭之刃", "间谍过家家",
    "蓝色监狱", "文豪野犬", "明日方舟", "崩坏", "星穹铁道", "海贼王",
)

_PREFERENCE_PATTERNS = [
    (re.compile(r"(?:我)?(?:最)?喜欢(?:的)?(?:是|看|玩|买)?[「\"]?(.{2,16}?)[」\"]?(?:[，,。！!？?]|$)"), "preference", "喜好"),
    (re.compile(r"(?:我)?(?:很)?(?:讨厌|不喜欢)(?:的)?(?:是|看|玩)?[「\"]?(.{2,16}?)[」\"]?"), "preference", "排斥"),
    (re.compile(r"(?:平时|经常)(?:会|都)?(?:买|看|玩|追)[「\"]?(.{2,16}?)[」\"]?"), "interest", "兴趣"),
]

_PROFILE_PATTERNS = [
    (re.compile(r"我(?:叫|名字(?:叫|是))(.{1,8}?)(?:[，,。！!？?]|$)"), "profile", "称呼"),
    (re.compile(r"我(?:今年)?(\d{1,2})岁"), "profile", "年龄"),
    (re.compile(r"我(?:在|住在|来自)(.{2,12}?)(?:[，,。]|$)"), "profile", "地区"),
    (re.compile(r"我(?:是|做|从事)(.{2,12}?)(?:的|工作|行业)"), "profile", "职业"),
]

_NEED_PATTERNS = [
    (re.compile(r"(?:我)?(?:想|想要|需要|希望)(?:要)?(.{2,24}?)(?:[，,。！!？?]|$)"), "need", "需求"),
    (re.compile(r"(?:帮我|请帮|能不能帮)(.{2,24}?)(?:[，,。！!？?]|$)"), "need", "求助"),
    (re.compile(r"(?:担心|焦虑|着急)(.{2,16}?)(?:[，,。]|$)"), "need", "顾虑"),
]


def _fingerprint(category: str, key: str, value: str) -> str:
    raw = f"{category}|{key}|{value.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _clean_value(text: str) -> str:
    v = (text or "").strip()
    v = re.sub(r"^[「\"『]+|[」\"』]+[。！!？?吧呢啊]*$", "", v)
    v = re.sub(r"\s+", " ", v).strip()
    if len(v) < 2 or len(v) > 80:
        return ""
    if re.search(r"(测试|随便|哈哈|嗯嗯)", v):
        return ""
    return v


def extract_memories_from_text(
    user_message: str,
    assistant_reply: str = "",
) -> List[Dict[str, Any]]:
    """从用户本轮发言中提取可留存记忆（规则引擎，无需额外 LLM 调用）"""
    msg = (user_message or "").strip()
    if not msg or len(msg) < 3:
        return []

    found: List[Dict[str, Any]] = []
    seen_fp: set[str] = set()

    def _push(category: str, key: str, value: str, confidence: float = 0.75) -> None:
        val = _clean_value(value)
        if not val:
            return
        fp = _fingerprint(category, key, val)
        if fp in seen_fp:
            return
        seen_fp.add(fp)
        found.append(
            {
                "category": category,
                "memory_key": key,
                "memory_value": val,
                "source_message": msg[:200],
                "confidence": confidence,
                "fingerprint": fp,
            }
        )

    for pattern, cat, key in _PREFERENCE_PATTERNS + _PROFILE_PATTERNS + _NEED_PATTERNS:
        m = pattern.search(msg)
        if m:
            _push(cat, key, m.group(1))

    for ip in _KNOWN_IPS:
        if ip in msg:
            _push("interest", "IP偏好", ip, 0.85)

    # 从助理回复中捕捉用户已确认的称呼（弱信号）
    if assistant_reply and "主人" not in msg:
        nick = re.search(r"好的[，,]?(.{1,8})(?:～|~|！)", assistant_reply)
        if nick:
            _push("profile", "称呼", nick.group(1), 0.5)

    return found[:8]


def format_memories_for_prompt(memories: List[Dict[str, Any]], limit: int = 12) -> str:
    """将记忆格式化为 LLM system 注入片段"""
    if not memories:
        return ""
    lines = ["【已记住的用户信息 — 回复时自然运用，勿生硬罗列】"]
    cat_labels = {
        "preference": "喜好",
        "profile": "画像",
        "need": "需求",
        "interest": "兴趣",
    }
    for m in memories[:limit]:
        cat = cat_labels.get(m.get("category") or "", m.get("category") or "记忆")
        key = m.get("memory_key") or ""
        val = m.get("memory_value") or ""
        lines.append(f"- {cat}/{key}: {val}")
    return "\n".join(lines)
