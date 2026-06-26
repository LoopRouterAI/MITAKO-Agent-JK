# -*- coding: utf-8 -*-
"""冒险富文本与 Prompt 构建单元测试"""
import pytest

from companion_richtext import parse_adventure_content, parse_inner_thought, strip_adventure_markers
from companion_adventure_context import build_context_bundle, detect_anachronism, estimate_tokens
from companion_adventure_visual import PromptBuilder


def test_parse_inner_thought():
    raw = "正文<inner>摘要|完整内心文本</inner>结尾"
    inner = parse_inner_thought(raw)
    assert inner["summary"] == "摘要"
    assert inner["full"] == "完整内心文本"


def test_strip_markers():
    raw = ">>场景<<\n【旁白】\n<inner>心|念</inner>\n<illust:scene />\n[1] 选A"
    display = strip_adventure_markers(raw)
    assert "<inner>" not in display
    assert "<illust" not in display
    assert ">>场景<<" in display


def test_parse_adventure_content_choices():
    raw = "叙事\n[1] 向左\n[2] 向右"
    parsed = parse_adventure_content(raw)
    assert len(parsed["choices"]) == 2


def test_ooc_detect():
    assert detect_anachronism("我要开加特林", {"era_label": "古代三国"}) == "modern_firearm"


def test_context_bundle_under_budget():
    history = [{"role": "user", "content": "x" * 500}, {"role": "assistant", "content": "y" * 500}] * 20
    msgs, tokens, _ = build_context_bundle("sys", {"era_label": "测试"}, "摘要", history, "继续")
    assert tokens < 128000
    assert len(msgs) >= 3


def test_prompt_builder_has_visual_world():
    bible = {"visual_style": "新海诚风", "address_agent": "小伴", "address_user": "主人"}
    prompt, size = PromptBuilder.turn_illust("scene", bible, "璃月港", {"mood": "雨"}, "小伴外貌")
    assert "VISUAL_WORLD" in prompt
    assert size == "2752x1536"


def test_estimate_tokens():
    assert estimate_tokens("中文测试") > 0
