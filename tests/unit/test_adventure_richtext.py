# -*- coding: utf-8 -*-
from companion_richtext import (
    clean_choice_label,
    detect_legacy_markup,
    history_has_legacy_markup,
    normalize_adventure_reply,
    parse_adventure_content,
    sanitize_history_for_llm,
)


def test_angle_scene_normalized():
    out = normalize_adventure_reply("<>晨曦中的璃月港<>")
    assert ">>晨曦中的璃月港<<" in out
    assert "<>" not in out


def test_parse_say_dialogues():
    raw = (
        ">>序章<<\n"
        "【海风拂面】\n"
        '<say role="agent" name="红玉">你好，主人。</say>\n'
        "[1] 继续"
    )
    parsed = parse_adventure_content(raw)
    assert len(parsed["dialogues"]) == 1
    assert parsed["dialogues"][0]["name"] == "红玉"
    assert "红玉" in parsed["tts_plain"]
    assert "<say" not in parsed["display"]


def test_broken_gt_markers():
    raw = ">夜之城·霓虹浸染的第六街>\n>主人，这条街不对劲。>/SAY>>"
    out = normalize_adventure_reply(raw)
    assert ">>夜之城·霓虹浸染的第六街<<" in out
    assert "<say" in out
    assert ">/SAY>>" not in out
    assert out.count(">夜之城") == 0 or ">>" in out


def test_clean_choice_label():
    assert clean_choice_label("握#g:单手剑#准备") == "握单手剑准备"


def test_detect_legacy_markup():
    assert detect_legacy_markup("<>晨曦<>")
    assert detect_legacy_markup(">台词>/SAY>>")
    assert not detect_legacy_markup('>>序章<<\n<say role="agent" name="A">你好</say>')


def test_sanitize_history_for_llm():
    history = [
        {"role": "user", "content": "继续"},
        {"role": "assistant", "content": ">夜之城>\n>你好。>/SAY>>"},
    ]
    assert history_has_legacy_markup(history)
    clean = sanitize_history_for_llm(history)
    assert clean[1]["content"].startswith(">>夜之城<<")
    assert "<say" in clean[1]["content"]
    assert ">/SAY>>" not in clean[1]["content"]
