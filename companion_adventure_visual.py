# -*- coding: utf-8 -*-
"""
冒险配图管线 — Prompt 构建、设定图、回合插图、主备生图
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from dotenv import load_dotenv

import companion_store as store
from agnes_image_service import generate_image_agnes
from image_service import generate_image

load_dotenv()

ILLUST_PRIMARY = os.getenv("ADVENTURE_ILLUST_PRIMARY", "sensenova-u1-fast")
ILLUST_FALLBACK = os.getenv("ADVENTURE_ILLUST_FALLBACK", "agnes-image-2.1-flash")
ILLUST_COOLDOWN = int(os.getenv("ADVENTURE_ILLUST_COOLDOWN_TURNS", "2"))
ILLUST_MAX_SESSION = int(os.getenv("ADVENTURE_ILLUST_MAX_PER_SESSION", "40"))
SIZE_SCENE = "2752x1536"
SIZE_PHOTO = "1760x2368"


class PromptBuilder:
    """高密度信息图 prompt — 见 docs/adventure/image-prompt-playbook.md"""

    @staticmethod
    def character_sheet(
        agent_name: str,
        world_title: str,
        visual_style: str,
        appearance: str = "",
    ) -> str:
        desc = appearance or f"与「{world_title}」世界观协调的年轻伙伴形象，气质亲和"
        return (
            f"VISUAL_WORLD: {visual_style}，严格遵守世界观「{world_title}」。\n"
            "你是国际一流电影人物原画师。制作电影级角色设计表，暗调深色背景，艺术化不对称网格排版。\n"
            f"角色：{agent_name}。{desc}。\n"
            "视图包含：五角度全身一致性（正/侧/背/3/4）、多角度表情头像、一张85mm浅景深电影特写。\n"
            "镜头：35mm全身自然曝光，85mm特写浅景深，柔和主光，半写实照片级。\n"
            "8K级细节，无噪点无过度锐化。禁止现代UI、水印、logo。"
        )

    @staticmethod
    def scene_board(
        scene_name: str,
        world_title: str,
        visual_style: str,
        scene_description: str,
    ) -> str:
        return (
            f"VISUAL_WORLD: {visual_style}，世界观「{world_title}」。\n"
            "你是国际顶级场景概念设计师。制作场景一致性与视觉开发设计板，深色高级UI，网格专业排版。\n"
            f"场景（空镜头无人物）：{scene_name}。{scene_description}。\n"
            "分区：主视觉宽幅氛围；左侧三格时间切片「白昼」「黄昏」「夜晚」；"
            "顶部四格空间视图；底部四格材质微距；右侧色标卡含HEX。\n"
            "电影美学，极致写实。禁止人物、水印。"
        )

    @staticmethod
    def turn_illust(
        illust_type: str,
        bible: Dict[str, Any],
        scene_key: str,
        intent: Dict[str, Any],
        char_caption: str = "",
        palette: Optional[List[str]] = None,
    ) -> Tuple[str, str]:
        """返回 (prompt, size)"""
        visual = bible.get("visual_style") or "cinematic semi-realistic"
        agent = bible.get("address_agent") or "伙伴"
        user = bible.get("address_user") or "主人"
        mood = intent.get("mood") or "叙事"
        subjects = intent.get("subjects") or [agent, user]
        if isinstance(subjects, str):
            subjects = [subjects]
        subj_str = "、".join(subjects[:4])
        hex_line = ", ".join(palette or ["#1a2a3a", "#c9a227", "#4fd1c5"])
        char_line = char_caption or f"{agent} 外观遵循角色设定表"

        if illust_type == "photo":
            prompt = (
                f"VISUAL_WORLD: {visual}。\n"
                f"竖构图3:4电影感肖像，主体 {agent}，情绪 {mood}，{char_line}。\n"
                f"场景 {scene_key or '当前场景'} 虚化 bokeh，85mm浅景深，柔和主光。\n"
                f"色板参考：{hex_line}。无文字无UI无水印。"
            )
            return prompt, SIZE_PHOTO

        prompt = (
            f"VISUAL_WORLD: {visual}。\n"
            f"电影剧照单帧16:9宽银幕。场景：{scene_key or '当前场景'}。\n"
            f"色板：{hex_line}。人物：{subj_str}（{char_line}）。\n"
            f"动作情绪：{mood}，35mm或50mm，ARRI Alexa 35色彩。\n"
            "无文字无UI无水印。"
        )
        return prompt, SIZE_SCENE


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


async def generate_image_with_fallback(
    prompt: str,
    size: str,
    primary: Optional[str] = None,
    fallback: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """返回 (result, model_id_used)"""
    primary_id = primary or ILLUST_PRIMARY
    fallback_id = fallback or ILLUST_FALLBACK
    try:
        result = await generate_image(prompt, primary_id, size, 1)
        return result, primary_id
    except Exception:
        if fallback_id and fallback_id != primary_id:
            result = await generate_image_agnes(prompt, fallback_id, size, 1)
            return result, fallback_id
        raise


def asset_captions_for_context(user_id: str, tenant_id: str) -> List[str]:
    assets = store.list_visual_assets(user_id, tenant_id=tenant_id, status="ready", limit=20)
    lines = []
    for a in assets:
        lines.append(f"- {a.get('asset_type')}:{a.get('entity_key')} url={a.get('image_url', '')[:80]}")
    return lines


async def ensure_opening_visual_assets(
    user_id: str,
    tenant_id: str,
    persona: Dict[str, Any],
    bible: Dict[str, Any],
    scene_key: str,
    scene_hint: str = "",
) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
    """开局生成角色表 + 场景板（若不存在）"""
    agent = bible.get("address_agent") or persona.get("agent_name") or "小伴"
    world = bible.get("world_title") or bible.get("world_setting") or "冒险世界"
    visual = bible.get("visual_style") or "cinematic"

    char_key = f"char:{agent}"
    existing_char = store.get_visual_asset_by_key(user_id, char_key, tenant_id=tenant_id)
    if not existing_char:
        prompt = PromptBuilder.character_sheet(agent, world, visual)
        yield ("visual_generating", {"asset_type": "character_sheet", "entity_key": char_key, "stage": "u1"})
        try:
            result, model_used = await generate_image_with_fallback(prompt, SIZE_SCENE)
            url = result["urls"][0]
            asset_id = store.save_visual_asset(
                user_id,
                tenant_id,
                asset_type="character_sheet",
                entity_key=char_key,
                image_url=url,
                prompt_text=prompt,
                prompt_hash=_prompt_hash(prompt),
                model_id=model_used,
                size=SIZE_SCENE,
                meta={"agent_name": agent},
            )
            yield (
                "visual_asset_ready",
                {
                    "asset_id": asset_id,
                    "asset_type": "character_sheet",
                    "entity_key": char_key,
                    "url": url,
                    "model_id": model_used,
                },
            )
        except Exception as exc:
            yield ("visual_asset_failed", {"asset_type": "character_sheet", "reason": str(exc)[:120]})

    sk = scene_key or f"{world}·序章"
    scene_entity = f"scene:{sk}"
    existing_scene = store.get_visual_asset_by_key(user_id, scene_entity, tenant_id=tenant_id)
    if not existing_scene:
        desc = scene_hint or f"{sk} 的核心氛围与光影，符合 {world} 设定"
        prompt = PromptBuilder.scene_board(sk, world, visual, desc)
        yield ("visual_generating", {"asset_type": "scene_board", "entity_key": scene_entity, "stage": "u1"})
        try:
            result, model_used = await generate_image_with_fallback(prompt, SIZE_SCENE)
            url = result["urls"][0]
            asset_id = store.save_visual_asset(
                user_id,
                tenant_id,
                asset_type="scene_board",
                entity_key=scene_entity,
                image_url=url,
                prompt_text=prompt,
                prompt_hash=_prompt_hash(prompt),
                model_id=model_used,
                size=SIZE_SCENE,
                meta={"scene_name": sk, "palette": ["#1a2a3a", "#c9a227", "#4fd1c5"]},
            )
            yield (
                "visual_asset_ready",
                {
                    "asset_id": asset_id,
                    "asset_type": "scene_board",
                    "entity_key": scene_entity,
                    "url": url,
                    "model_id": model_used,
                },
            )
        except Exception as exc:
            yield ("visual_asset_failed", {"asset_type": "scene_board", "reason": str(exc)[:120]})


def should_generate_turn_illust(user_id: str, tenant_id: str) -> Tuple[bool, str]:
    """cooldown + 配额检查"""
    count = store.count_turn_illusts(user_id, tenant_id=tenant_id)
    if count >= ILLUST_MAX_SESSION:
        return False, "session_limit"
    since = store.turns_since_last_illust(user_id, tenant_id=tenant_id)
    if since < ILLUST_COOLDOWN:
        return False, "cooldown"
    return True, ""


async def generate_turn_illustration(
    user_id: str,
    tenant_id: str,
    message_id: int,
    bible: Dict[str, Any],
    scene_key: str,
    intent: Dict[str, Any],
) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
    """回合插图 — yield illust_* 事件 payload"""
    ok, reason = should_generate_turn_illust(user_id, tenant_id)
    if not ok:
        yield ("illust_skipped", {"message_id": message_id, "reason": reason})
        return

    illust_type = (intent.get("type") or "scene").lower()
    agent = bible.get("address_agent") or "伙伴"
    char_asset = store.get_visual_asset_by_key(user_id, f"char:{agent}", tenant_id=tenant_id)
    char_caption = (char_asset or {}).get("meta", {}).get("agent_name") or agent
    if isinstance((char_asset or {}).get("meta"), str):
        try:
            char_caption = json.loads(char_asset["meta"]).get("agent_name", agent)
        except json.JSONDecodeError:
            pass

    scene_entity = f"scene:{scene_key}" if scene_key else ""
    scene_asset = store.get_visual_asset_by_key(user_id, scene_entity, tenant_id=tenant_id) if scene_entity else None
    palette = None
    if scene_asset and scene_asset.get("meta"):
        meta = scene_asset["meta"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except json.JSONDecodeError:
                meta = {}
        palette = meta.get("palette")

    prompt, size = PromptBuilder.turn_illust(
        illust_type, bible, scene_key, intent, char_caption=str(char_caption), palette=palette
    )
    aspect = "16:9" if size == SIZE_SCENE else "3:4"

    yield (
        "illust_queued",
        {"message_id": message_id, "illust_type": illust_type, "placeholder": True},
    )
    yield (
        "illust_generating",
        {"message_id": message_id, "stage": "u1", "model_id": ILLUST_PRIMARY},
    )

    store.update_adventure_message_illust(message_id, user_id, tenant_id, illust_status="queued")

    t0 = time.time()
    try:
        result, model_used = await generate_image_with_fallback(prompt, size)
        url = result["urls"][0]
        asset_id = store.save_visual_asset(
            user_id,
            tenant_id,
            asset_type="turn_illust",
            entity_key=f"turn:{message_id}",
            image_url=url,
            prompt_text=prompt,
            prompt_hash=_prompt_hash(prompt),
            model_id=model_used,
            size=size,
            meta={"message_id": message_id, "illust_type": illust_type},
        )
        store.update_adventure_message_illust(
            message_id, user_id, tenant_id, illust_status="ready", illust_asset_id=asset_id
        )
        yield (
            "api_log",
            {
                "id": f"illust_{message_id}_{uuid.uuid4().hex[:8]}",
                "stage": "adventure_illust_ready",
                "status": "ok",
                "model": model_used,
                "duration": int((time.time() - t0) * 1000),
                "payload": {"message_id": message_id, "size": size},
                "responseStream": url[:200],
            },
        )
        yield (
            "illust_ready",
            {
                "message_id": message_id,
                "asset_id": asset_id,
                "url": url,
                "size": size,
                "aspect": aspect,
                "model_id": model_used,
            },
        )
    except Exception as exc:
        store.update_adventure_message_illust(message_id, user_id, tenant_id, illust_status="failed")
        yield (
            "api_log",
            {
                "id": f"illust_fail_{message_id}",
                "stage": "adventure_illust_failed",
                "status": "error",
                "duration": int((time.time() - t0) * 1000),
                "responseStream": str(exc)[:200],
            },
        )
        yield (
            "illust_failed",
            {"message_id": message_id, "reason": "api_error", "user_hint": "companion.adventureIllustFailed"},
        )
