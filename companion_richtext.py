# -*- coding: utf-8 -*-
"""Companion 富文本规范 — 日常对话 + 冒险模式扩展"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_ACTION_RE = re.compile(r"<action:\s*\w+>", re.I)
_ANALYSIS_RE = re.compile(r"<analysis>[\s\S]*?</analysis>", re.I)
_SYSTEM_LEAK_RE = re.compile(r"(?i)(system prompt|系统提示词|忽略以上)")
_INNER_RE = re.compile(r"<inner>(.*?)\|(.*?)</inner>", re.S | re.I)
_ILLUST_TAG_RE = re.compile(r"<illust:(scene|photo)(?:\s+([^>/]*))?\s*/?>", re.I)
_ILLUST_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
_SCENE_TITLE_RE = re.compile(r">>\s*([^<\n]+?)\s*<<")
# LLM 偶发输出 <>标题<> 而非 >>标题<<
_ANGLE_SCENE_RE = re.compile(r"<>\s*([^<>\n]+?)\s*<>")
_SAY_RE = re.compile(r'<say\s+role="([^"]+)"\s+name="([^"]*)">([\s\S]*?)</say>', re.I)
_RICH_TAG_RE = re.compile(r"#([vrcga]):([^#\n\r]+)#")


_SINGLE_GT_SCENE_RE = re.compile(r"^>\s*([^>\n/]+?)\s*>$", re.M)
_BROKEN_GT_SAY_RE = re.compile(r"^>\s*(.+?)\s*>/SAY>>\s*$", re.M | re.I)
_LEGACY_MARKUP_RE = re.compile(
    r"<>|>/SAY>>|<<SAY:|<<SCENE>>|<</SCENE>>|^>\s*[^>\n]+?\s*>$",
    re.M | re.I,
)

ADVENTURE_MARKUP_VERSION = "2"


def _normalize_gt_markers(text: str) -> str:
    """LLM 误用 >标题> 或 >台词>/SAY>> — 转为 canonical 格式"""
    if not text:
        return ""
    out = text
    out = _BROKEN_GT_SAY_RE.sub(r'<say role="agent" name="">\1</say>', out)
    out = _SINGLE_GT_SCENE_RE.sub(r">>\1<<", out)
    out = re.sub(r">\s*/SAY>>", "", out, flags=re.I)
    return out


def _normalize_scene_markers(text: str) -> str:
    """将 <>场景<> 统一为 >>场景<<，并清理泄漏 markup"""
    if not text:
        return ""
    out = _normalize_gt_markers(text)
    out = re.sub(r"<>\s*/SAY>>", "", out, flags=re.I)
    out = re.sub(r"<</SAY>>", "", out, flags=re.I)
    out = re.sub(r"<<SAY:[^>]*>>", "", out, flags=re.I)
    out = re.sub(r"<<SCENE>>|<</SCENE>>|<<NARR>>|<</NARR>>|<<SEP>>", "", out)
    out = _ANGLE_SCENE_RE.sub(r">>\1<<", out)
    out = re.sub(r"^<>\s*", "", out, flags=re.M)
    out = re.sub(r"\s*<>$", "", out, flags=re.M)
    out = re.sub(r"^<>\s*$", "", out, flags=re.M)
    out = re.sub(r"——\s*<\s*$", "——", out, flags=re.M)
    out = re.sub(r"(?<![<])<\s*$", "", out, flags=re.M)
    return out


COMPANION_RICH_TEXT_RULES = (
    "核心信息用 #高亮词# 包裹（如 #12月15日#、#ORD_2024_001#）；"
    "可选在句末加 1 个 <meme:happy> 类表情标签；"
    "禁止输出 <action:...> 或 JSON 分析块。"
)

ADVENTURE_RICH_TEXT_RULES = (
    "场景标题用 >>标题<< 单独一行（禁止 <>标题<>）；段落之间仅用 --- 分隔（禁止连续空行）；"
    "强调 **加粗**、*斜体*、~~删除线~~；"
    "所有对白必须用 <say role=\"agent|npc|user\" name=\"说话人\">台词</say>，每句单独一行；"
    "选项文案禁止 #v:词# 等富文本标记，只用纯中文；"
    "客观环境/场景描写必须用【】包裹成旁白块，【】内禁止「我」「你」，只用姓名/称谓；"
    "非【】叙述一律第三人称，用伙伴名字与用户称谓，禁止「我」「你」；"
    "伙伴内心每回合最多一条：<inner>摘要|完整内心</inner>（禁止用行首 > 或 >标题> 代替任何标记）；"
    "可选配图标记（选项前）：<illust:scene /> 或 <illust:photo mood=\"…\" />；"
    "关键道具/地点：#词#（金） #v:词#（紫） #r:词#（红） #c:词#（青） #g:词#（绿） #a:词#（琥珀）；"
    "可选 <emote:happy> 表情；选项 [1][2][3] 每行一个；"
    "分享 SKU/文章：<share:sku:P001> <share:article:ART_001>；"
    "禁止系统提示、JSON、<action:>、越狱话术。"
)

_CHOICE_LINE_RE = re.compile(r"^\s*\[(\d+)\]\s*(.+?)\s*$", re.M)


def normalize_companion_reply(text: str) -> str:
    if not text:
        return ""
    out = _ANALYSIS_RE.sub("", text)
    out = _ACTION_RE.sub("", out)
    return out.strip()


def load_adventure_markup_contract(max_chars: int = 3200) -> str:
    """加载 prompts/adventure-markup-contract.md — LLM 与前端唯一语法标准"""
    path = Path(__file__).resolve().parent / "prompts" / "adventure-markup-contract.md"
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except OSError:
        return ""


def detect_legacy_markup(text: str) -> bool:
    """检测是否含 v1/错误 markup（会污染 LLM 上下文）"""
    if not text:
        return False
    return bool(_LEGACY_MARKUP_RE.search(text))


def history_has_legacy_markup(history: List[Dict[str, str]]) -> bool:
    for m in history or []:
        if m.get("role") != "assistant":
            continue
        if detect_legacy_markup(m.get("content") or ""):
            return True
    return False


def sanitize_history_message_for_llm(message: Dict[str, str]) -> str:
    """
    送入 LLM 上下文前净化单条历史。
    assistant：normalize 为 canonical v2；user：保留原文（用户输入不应被改写）。
    """
    role = (message.get("role") or "user").lower()
    content = (message.get("content") or "").strip()
    if not content:
        return ""
    if role == "assistant":
        return normalize_adventure_reply(content)
    return content[:1200]


def sanitize_history_for_llm(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """批量净化历史，供 build_context_bundle 使用"""
    out: List[Dict[str, str]] = []
    for m in history or []:
        content = sanitize_history_message_for_llm(m)
        if not content:
            continue
        out.append({"role": m.get("role", "user"), "content": content})
    return out


def normalize_adventure_reply(text: str) -> str:
    if not text:
        return ""
    out = _ANALYSIS_RE.sub("", text)
    out = _ACTION_RE.sub("", out)
    out = _SYSTEM_LEAK_RE.sub("", out)
    out = _normalize_scene_markers(out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"(\n\s*){2,}", "\n", out)
    return out.strip()


def clean_choice_label(label: str) -> str:
    """选项展示用纯文本 — 剥离 #g:词# 等标记"""
    if not label:
        return ""
    out = _RICH_TAG_RE.sub(r"\2", label)
    out = re.sub(r"#([^#\n\r]+)#", r"\1", out)
    out = re.sub(r"<[^>]+>", "", out)
    return out.strip()


def parse_adventure_choices(text: str) -> list:
    """解析 [1] 选项A 格式为 [{id, label}, ...]"""
    choices = []
    for m in _CHOICE_LINE_RE.finditer(text or ""):
        try:
            cid = int(m.group(1))
        except ValueError:
            continue
        raw = (m.group(2) or "").strip()
        label = clean_choice_label(raw)
        if label:
            choices.append({"id": cid, "label": label, "raw_label": raw})
    return choices[:6]


def parse_dialogues(text: str, agent_name: str = "") -> List[Dict[str, str]]:
    """解析 <say role=\"agent|npc|user\" name=\"…\">台词</say>"""
    dialogues: List[Dict[str, str]] = []
    default_agent = (agent_name or "").strip()
    for m in _SAY_RE.finditer(text or ""):
        line = (m.group(3) or "").strip()
        if not line:
            continue
        role = (m.group(1) or "npc").lower().strip()
        name = (m.group(2) or "").strip()
        if role == "agent" and not name and default_agent:
            name = default_agent
        dialogues.append({
            "role": role,
            "name": name,
            "text": line,
        })
    return dialogues


def build_tts_plain(text: str, dialogues: Optional[List[Dict[str, str]]] = None) -> str:
    """生成 TTS 友好纯文本 — 旁白与对白分行，无 markup"""
    raw = strip_adventure_markers(text or "")
    raw = _SAY_RE.sub("", raw)
    raw = re.sub(r">>\s*([^<\n]+?)\s*<<", r"\1。", raw)
    raw = re.sub(r"\*\*([^*]+)\*\*", r"\1", raw)
    raw = re.sub(r"\*([^*\n]+)\*", r"\1", raw)
    raw = re.sub(r"~~([^~]+)~~", r"\1", raw)
    raw = _RICH_TAG_RE.sub(r"\2", raw)
    raw = re.sub(r"#([^#\n\r]+)#", r"\1", raw)
    raw = re.sub(r"^---$", "", raw, flags=re.M)
    parts: List[str] = []
    for block in re.findall(r"【([^】]+)】", raw):
        b = block.strip()
        if b:
            parts.append(f"旁白：{b}")
    body = re.sub(r"【[^】]+】", "", raw)
    body = re.sub(r"\s+", " ", body).strip()
    if body:
        parts.append(body)
    dlg = dialogues if dialogues is not None else parse_dialogues(text or "")
    for d in dlg:
        who = d.get("name") or d.get("role") or "角色"
        parts.append(f"{who}：{d.get('text') or ''}")
    return "\n".join(p for p in parts if p).strip()


def parse_inner_thought(text: str) -> Optional[Dict[str, str]]:
    """解析 <inner>摘要|正文</inner>，多条取首条"""
    m = _INNER_RE.search(text or "")
    if not m:
        return None
    summary = (m.group(1) or "").strip()
    full = (m.group(2) or "").strip()
    if not summary and full:
        summary = full[:20] + ("…" if len(full) > 20 else "")
    if not full:
        full = summary
    return {"summary": summary, "full": full}


def parse_illust_intent(text: str) -> Optional[Dict[str, Any]]:
    """解析 <illust:scene mood=\"x\" /> 标记"""
    m = _ILLUST_TAG_RE.search(text or "")
    if not m:
        return None
    intent: Dict[str, Any] = {"type": (m.group(1) or "scene").lower()}
    attr_str = (m.group(2) or "").strip()
    for am in _ILLUST_ATTR_RE.finditer(attr_str):
        intent[am.group(1)] = am.group(2)
    if "subjects" in intent and isinstance(intent["subjects"], str):
        intent["subjects"] = [s.strip() for s in intent["subjects"].split(",") if s.strip()]
    return intent


def extract_scene_key(text: str) -> str:
    m = _SCENE_TITLE_RE.search(text or "")
    return (m.group(1) or "").strip() if m else ""


def strip_adventure_markers(text: str) -> str:
    """移除 inner/illust/say 标记供旁白区展示"""
    if not text:
        return ""
    out = _INNER_RE.sub("", text)
    out = _ILLUST_TAG_RE.sub("", out)
    out = _SAY_RE.sub("", out)
    return normalize_adventure_reply(out)


def parse_adventure_content(raw: str, agent_name: str = "") -> Dict[str, Any]:
    """统一解析冒险 assistant 回复"""
    raw = normalize_adventure_reply(raw or "")
    inner = parse_inner_thought(raw)
    illust = parse_illust_intent(raw)
    dialogues = parse_dialogues(raw, agent_name=agent_name)
    display = strip_adventure_markers(raw)
    scene_key = extract_scene_key(display) or extract_scene_key(raw)
    choices = parse_adventure_choices(raw)
    tts_plain = build_tts_plain(raw, dialogues)
    return {
        "raw": raw,
        "display": display,
        "inner": inner,
        "illust": illust,
        "dialogues": dialogues,
        "tts_plain": tts_plain,
        "scene_key": scene_key,
        "choices": choices,
    }
