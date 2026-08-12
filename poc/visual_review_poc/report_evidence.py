# -*- coding: utf-8 -*-
"""客服报告中的证据归一化、媒体回链与画廊渲染。"""
from __future__ import annotations

import html
import os
import re
from typing import Any, Dict, List, Optional


_SUMMARY_EVIDENCE_PRIORITY = {
    "issue_visible": 0,
    "issue_visible_in_continuous_opening": 0,
    "supplemental_damage_visible": 1,
    "claimed_item": 2,
    "warehouse_verification": 2,
    "sealed_start": 3,
    "waybill_visible": 4,
    "continuous": 5,
    "single_take_continuity": 5,
    "all_items_shown": 6,
    "has_offscreen": 7,
    "has_speed_change": 8,
    "has_edit": 9,
}


def _readable_fact(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, (list, tuple)):
        parts = [_readable_fact(item) for item in value]
        return "；".join(dict.fromkeys(part for part in parts if part))
    if not isinstance(value, dict):
        return str(value)

    subject = str(
        value.get("subject")
        or value.get("subject_id")
        or value.get("name")
        or ""
    ).strip()
    fact = _readable_fact(
        value.get("fact")
        or value.get("description")
        or value.get("reason")
        or value.get("text")
        or value.get("message")
    )
    if fact:
        return f"{subject}：{fact}" if subject and subject not in fact else fact
    state = _readable_fact(
        value.get("state")
        or value.get("status")
        or value.get("visibility")
        or value.get("result")
    )
    return f"{subject}：{state}" if subject and state else subject or state


def _h(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        value = _readable_fact(value)
    return html.escape(str(value if value is not None else ""))


def _source_label(value: Any) -> str:
    mapping = {
        "supplementary_image": "补充图片",
        "supplemental_image": "补充图片",
        "video_frame": "视频帧",
        "frame": "视频帧",
        "video": "视频",
        "image": "图片",
    }
    return mapping.get(str(value or "").strip().lower(), str(value or "证据"))


def _timestamp_key(value: Any) -> str:
    """将秒数或时分秒时间戳归一化，供证据与画廊回链。"""
    if value in (None, ""):
        return ""
    text = str(value).strip().lower()
    if not text or text in {"n/a", "na", "-"}:
        return ""
    text = re.sub(r"^(?:t\s*=\s*)", "", text)
    text = re.sub(r"\s*(?:seconds?|secs?|s|秒)$", "", text)
    try:
        if ":" not in text:
            seconds = float(text)
        else:
            parts = [float(part) for part in text.split(":")]
            if len(parts) == 2:
                seconds = parts[0] * 60 + parts[1]
            elif len(parts) == 3:
                seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
            else:
                return text
        return f"{seconds:.3f}"
    except (TypeError, ValueError):
        return text


def _file_key(value: Any) -> str:
    if value in (None, ""):
        return ""
    return os.path.basename(str(value).strip().replace("\\", "/")).casefold()


def _as_text_list(value: Any) -> List[str]:
    if value in (None, "", []):
        return []
    values = value if isinstance(value, list) else [value]
    result: List[str] = []
    for item in values:
        if item in (None, ""):
            continue
        if isinstance(item, dict):
            text = (
                item.get("fact")
                or item.get("description")
                or item.get("reason")
                or item.get("limitation")
                or item.get("gap")
                or item.get("message")
            )
            if text:
                result.append(str(text))
        else:
            result.append(str(item))
    return result


def _merge_evidence_items(candidates: List[Any]) -> List[Dict[str, Any]]:
    """按业务优先级排序，并合并同一素材同一时刻的重复说明。"""
    normalized: List[Dict[str, Any]] = []
    seen_exact = set()
    for position, raw in enumerate(candidates):
        item = dict(raw) if isinstance(raw, dict) else {"fact": raw}
        asset_ref = str(item.get("asset_ref") or "").strip()
        native_match = re.fullmatch(r"native_video_(\d+)", asset_ref)
        image_match = re.fullmatch(r"supplemental_image_(\d+)", asset_ref)
        if native_match and item.get("video_index") is None:
            item["video_index"] = int(native_match.group(1))
        if image_match and item.get("image_index") is None:
            item["image_index"] = int(image_match.group(1))
            item.setdefault("source_type", "supplemental_image")
        elif native_match:
            item.setdefault("source_type", "video_frame")
        fact = _readable_fact(
            item.get("fact")
            or item.get("visible_facts")
            or item.get("description")
        ).strip()
        if fact:
            item["fact"] = fact
        signature = (
            str(item.get("field") or ""),
            asset_ref,
            _timestamp_key(item.get("timestamp")),
            fact,
        )
        if signature in seen_exact:
            continue
        seen_exact.add(signature)
        item["_source_position"] = position
        normalized.append(item)

    normalized.sort(
        key=lambda item: (
            _SUMMARY_EVIDENCE_PRIORITY.get(str(item.get("field") or ""), 50),
            int(item.get("_source_position") or 0),
        )
    )

    merged: List[Dict[str, Any]] = []
    merge_indexes: Dict[str, int] = {}
    for item in normalized:
        timestamp = _timestamp_key(item.get("timestamp"))
        asset_ref = str(item.get("asset_ref") or "").strip()
        subject = (
            f"video:{item.get('video_index')}"
            if item.get("video_index") is not None
            else f"image:{item.get('image_index')}"
            if item.get("image_index") is not None
            else asset_ref
        )
        merge_key = f"{subject}@{timestamp}" if subject and timestamp else ""
        if not timestamp and asset_ref.startswith("supplemental_image_"):
            merge_key = asset_ref
        if merge_key and merge_key in merge_indexes:
            target = merged[merge_indexes[merge_key]]
            facts = [
                part.strip()
                for value in (
                    _readable_fact(target.get("fact")).strip(),
                    _readable_fact(item.get("fact")).strip(),
                )
                for part in value.split("；")
                if part.strip().rstrip("。；; ")
            ]
            target["fact"] = "；".join(
                dict.fromkeys(part.rstrip("。；; ") for part in facts)
            )
            continue
        item.pop("_source_position", None)
        if merge_key:
            merge_indexes[merge_key] = len(merged)
        merged.append(item)
    return merged


def _summary_evidence_items(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """首屏优先展示争议事实，并合并同一素材同一时刻的重复说明。"""
    candidates: List[Any] = []
    for key in ("evidence_refs", "adopted_evidence", "supporting_evidence"):
        value = parsed.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    return _merge_evidence_items(candidates)


def _list_html(value: Any, empty_text: str) -> str:
    items = _as_text_list(value)
    if not items:
        return f'<p class="muted">{_h(empty_text)}</p>'
    return '<ul class="boundary-list">' + "".join(f"<li>{_h(item)}</li>" for item in items[:8]) + "</ul>"


def _risky_frame_findings(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    no_risk_values = {"", "0", "false", "low", "none", "normal", "无", "无异常", "正常", "未见异常", "低"}
    findings: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        risk = str(item.get("risk") or "").strip().lower()
        if risk in no_risk_values:
            continue
        findings.append(
            {
                **item,
                "source_type": item.get("source_type") or "video_frame",
                "fact": item.get("fact") or item.get("visible_facts") or item.get("description") or "该帧存在需复核的视觉风险。",
                "why_it_matters": item.get("why_it_matters") or f"风险标记：{item.get('risk')}",
            }
        )
    return findings


def _issue_timestamp_items(value: Any) -> List[Dict[str, Any]]:
    if value in (None, "", []):
        return []
    values = value if isinstance(value, list) else [value]
    result: List[Dict[str, Any]] = []
    for item in values:
        if isinstance(item, dict):
            result.append(
                {
                    **item,
                    "source_type": item.get("source_type") or "video_frame",
                    "fact": item.get("fact") or item.get("description") or item.get("visible_facts") or item.get("reason") or "该时间点被标记为问题位置。",
                    "why_it_matters": item.get("why_it_matters") or "建议VIP客服重点查看该时间点及其前后连续画面。",
                }
            )
        elif item not in (None, ""):
            result.append(
                {
                    "source_type": "video_frame",
                    "timestamp": item,
                    "fact": "该时间点被标记为问题位置。",
                    "why_it_matters": "建议VIP客服重点查看该时间点及其前后连续画面。",
                }
            )
    return result


def _evidence_items(
    items: Any,
    media_gallery: Optional[Dict[str, Any]] = None,
    default_status: str = "已采信",
) -> str:
    if not isinstance(items, list) or not items:
        return '<p class="muted">审核Agent没有给出可采信证据，建议客服查看原始素材。</p>'
    media_gallery = media_gallery or {}
    frame_candidates: Dict[str, List[Dict[str, Any]]] = {}
    timestamp_candidates: Dict[str, List[Dict[str, Any]]] = {}
    video_frame_map: Dict[str, Dict[str, Any]] = {}
    video_timestamp_map: Dict[str, Dict[str, Any]] = {}
    file_map: Dict[str, Dict[str, Any]] = {}
    video_map = {
        str(item.get("video_index")): item
        for item in media_gallery.get("videos") or []
        if item.get("video_index") is not None and item.get("url")
    }
    single_video = (
        (media_gallery.get("videos") or [None])[0]
        if len(media_gallery.get("videos") or []) == 1
        else None
    )
    for frame in media_gallery.get("frames") or []:
        for key in (frame.get("global_frame_index"), frame.get("frame_index")):
            if key is not None:
                frame_candidates.setdefault(str(key), []).append(frame)
                if frame.get("video_index") is not None:
                    video_frame_map[f"{frame.get('video_index')}:{key}"] = frame
        timestamp_key = _timestamp_key(frame.get("timestamp"))
        if timestamp_key:
            timestamp_candidates.setdefault(timestamp_key, []).append(frame)
            if frame.get("video_index") is not None:
                video_timestamp_map[f"{frame.get('video_index')}:{timestamp_key}"] = frame
        file_key = _file_key(frame.get("file_name") or frame.get("file"))
        if file_key:
            file_map[file_key] = frame
    frame_map = {key: values[0] for key, values in frame_candidates.items() if len(values) == 1}
    timestamp_map = {key: values[0] for key, values in timestamp_candidates.items() if len(values) == 1}
    image_map = {
        str(item.get("image_index")): item
        for item in media_gallery.get("images") or []
        if item.get("image_index") is not None
    }
    for image in media_gallery.get("images") or []:
        file_key = _file_key(image.get("file_name") or image.get("file"))
        if file_key:
            file_map[file_key] = image
    reference_map = {
        str(item.get("reference_index")): item
        for item in media_gallery.get("official_references") or []
        if item.get("reference_index") is not None
    }

    def media_preview(item: Dict[str, Any]) -> str:
        frame_key = item.get("global_frame_index")
        if frame_key is None:
            frame_key = item.get("frame_index")
        image_key = item.get("image_index")
        reference_key = item.get("reference_index")
        video_frame_key = (
            f"{item.get('video_index')}:{frame_key}"
            if item.get("video_index") is not None and frame_key is not None
            else ""
        )
        media = video_frame_map.get(video_frame_key) or (frame_map.get(str(frame_key)) if frame_key is not None else None)
        media_label = "查看视频时间点"
        if media is None and image_key is not None:
            media = image_map.get(str(image_key))
            media_label = "查看补充图片"
        if media is None and reference_key is not None:
            media = reference_map.get(str(reference_key))
            media_label = "查看官方参考图"
        timestamp_key = _timestamp_key(item.get("timestamp"))
        if media is None and timestamp_key:
            video_key = f"{item.get('video_index')}:{timestamp_key}" if item.get("video_index") is not None else ""
            media = video_timestamp_map.get(video_key) or timestamp_map.get(timestamp_key)
        if media is None:
            media = file_map.get(_file_key(item.get("file_name") or item.get("file")))
        direct_video = video_map.get(str(item.get("video_index"))) or single_video
        if timestamp_key and isinstance(direct_video, dict) and direct_video.get("url"):
            direct_video_url = f"{direct_video['url']}#t={timestamp_key}"
            if media is None:
                media = {"video_url": direct_video_url, "timestamp": item.get("timestamp")}
            elif not media.get("video_url"):
                media = {**media, "video_url": direct_video_url}
        if media in (media_gallery.get("images") or []):
            media_label = "查看补充图片"
        if media in (media_gallery.get("official_references") or []):
            media_label = "查看官方参考图"
        if not media or not (media.get("url") or media.get("video_url")):
            return ""
        video_link = ""
        if media.get("video_url"):
            preview_seconds = _timestamp_key(media.get("timestamp") or item.get("timestamp"))
            video_link = (
                f'<button class="jump preview-trigger" type="button" data-preview-kind="video" '
                f'data-preview-src="{_h(media.get("video_url"))}" data-preview-seconds="{_h(preview_seconds)}" '
                f'data-preview-title="原视频 {_h(media.get("timestamp") or item.get("timestamp") or "")}">'
                f'预览原视频 {_h(media.get("timestamp") or item.get("timestamp") or "")}</button>'
            )
        if not media.get("url"):
            return f'<div class="evidence-media">{video_link}</div>'
        return (
            '<div class="evidence-media">'
            f'<button class="thumb preview-trigger" type="button" data-preview-kind="image" '
            f'data-preview-src="{_h(media.get("url"))}" data-preview-title="{_h(media.get("file") or media_label)}">'
            f'<img src="{_h(media.get("url"))}" alt="{_h(media.get("file") or "证据素材")}"></button>'
            f"{video_link}</div>"
        )

    cards: List[str] = []
    for index, raw_item in enumerate(items[:12], start=1):
        item = raw_item if isinstance(raw_item, dict) else {"description": raw_item}
        source = item.get("timestamp") or item.get("file_name") or item.get("file") or f"证据 {index}"
        fact = _readable_fact(
            item.get("fact")
            or item.get("visible_facts")
            or item.get("description")
            or item.get("why_it_matters")
            or "该证据未附可公开的事实说明。"
        )
        why_it_matters = _readable_fact(item.get("why_it_matters"))
        confidence = item.get("confidence")
        evidence_impact = ""
        if why_it_matters and why_it_matters != fact:
            evidence_impact = f'<p class="evidence-impact"><strong>证据作用</strong>{_h(why_it_matters)}</p>'
        cards.append(
            '<article class="evidence-card">'
            f'<small>{_h(_source_label(item.get("source_type")))} · {_h(source)}</small>'
            f"{media_preview(item)}<p>{_h(fact)}</p>{evidence_impact}"
            f'<b>{_h(confidence if confidence not in (None, "") else default_status)}</b>'
            "</article>"
        )
    return "".join(cards) or '<p class="muted">审核Agent没有给出可采信证据，建议客服查看原始素材。</p>'


def _gallery_items(items: List[Dict[str, Any]], kind: str) -> str:
    html_items: List[str] = []
    visible_items = items if kind == "补充图片" else items[:24]
    for item in visible_items:
        if not item.get("url"):
            continue
        subtitle = item.get("timestamp") or item.get("file") or "-"
        video_link = ""
        if item.get("video_url"):
            video_link = (
                f'<button class="inline-preview preview-trigger" type="button" data-preview-kind="video" '
                f'data-preview-src="{_h(item.get("video_url"))}" data-preview-seconds="{_h(_timestamp_key(item.get("timestamp")))}" '
                f'data-preview-title="视频时间点 {_h(item.get("timestamp") or "")}">预览视频时间点</button>'
            )
        image_index = item.get("image_index")
        anchor = f' id="image-{_h(image_index)}"' if image_index not in (None, "") else ""
        html_items.append(
            f'<figure class="media-tile"{anchor}>'
            f'<button class="preview-trigger" type="button" data-preview-kind="image" '
            f'data-preview-src="{_h(item.get("url"))}" data-preview-title="{_h(item.get("file") or kind)}">'
            f'<img src="{_h(item.get("url"))}" alt="{_h(item.get("file") or kind)}"></button>'
            f"<figcaption><b>{_h(kind)}</b><span>{_h(subtitle)}</span>{video_link}</figcaption>"
            "</figure>"
        )
    return "".join(html_items) or '<p class="muted">本轮报告没有可预览素材。</p>'
