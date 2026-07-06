# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FORBIDDEN_PUBLIC_TERMS = re.compile(
    r"Gemini|GPT|Token|endpoint|API Yi|Banana|DeepSeek|Mock|外包|端点|成本",
    re.IGNORECASE,
)
FORBIDDEN_PUBLIC_KEYS = {
    "model",
    "display_model",
    "model_key",
    "model_name",
    "provider",
    "channel",
    "usage",
    "tokens",
    "token_usage",
    "usage_metadata",
    "cost",
    "pricing",
    "raw_response",
    "raw",
    "raw_text",
    "system_prompt",
    "user_prompt",
    "thoughtSignature",
    "thought_signature",
    "thoughtsTokenCount",
}


def contains_forbidden_public_key(value) -> bool:
    if isinstance(value, dict):
        return any(str(key) in FORBIDDEN_PUBLIC_KEYS or contains_forbidden_public_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_forbidden_public_key(item) for item in value)
    return False


def parse_stdout_json(stdout: str) -> dict:
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(stdout[index:])
            return data
        except json.JSONDecodeError:
            continue
    raise AssertionError("未找到审核脚本 JSON 输出")


def test_workbench_api() -> None:
    from fastapi.testclient import TestClient
    from poc.visual_review_poc.workbench_server import app

    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json().get("ok") is True
    for path in ("/video-unboxing", "/product-damage", "/minor-material"):
        routed = client.get(path)
        assert routed.status_code == 200, (path, routed.status_code)
        assert "MITAKO 视觉审核工作台" in routed.text, path

    rejected = client.post(
        "/api/review",
        data={"source_type": "upload", "scenario": "all", "review_model": "standard"},
    )
    assert rejected.status_code == 400

    csv_text = "\n".join([
        "task,human_label,predicted_label,user_text,video,order_item,sku,human_reason",
        "video_unboxing,pass,pass,开箱完整,a.mp4,商品A,SKU1,视频完整",
        "video_unboxing,fail,pass,视频剪辑,b.mp4,商品A,SKU1,视频不完整",
        "product_damage,pass,pass,划痕清晰,c.mp4,商品B,SKU2,瑕疵可见",
        "minor_material,fail,fail,资料缺失,d.mp4,商品C,SKU3,缺少关系证明",
    ])
    evaluated = client.post(
        "/api/evaluate-samples",
        files={"file": ("samples.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert evaluated.status_code == 200, evaluated.text
    data = evaluated.json()
    assert data["summary"]["total"] == 4, data
    assert data["summary"]["evaluable"] == 4, data
    assert data["summary"]["correct"] == 3, data
    assert data["summary"]["accuracy"] == 0.75, data
    assert data["summary"]["target_evaluable"] == 4, data
    assert data["summary"]["target_accuracy"] == 0.75, data
    assert data["summary"]["ready_for_accuracy"] is False, data
    assert not FORBIDDEN_PUBLIC_TERMS.search(json.dumps(data, ensure_ascii=False)), data

    json_payload = {
        "samples": [
            {"场景": "开箱视频", "人工结论": "合规", "辅助结论": "合规", "用户诉求": "开箱完整", "素材": "a.mp4", "商品名": "商品A", "规格": "SKU1", "人工原因": "视频连续"},
            {"场景": "商品有伤", "人工结论": "不支持", "辅助结论": "不支持", "用户诉求": "看不清", "素材": "b.jpg", "商品名": "商品B", "规格": "SKU2", "人工原因": "未见损伤"},
        ]
    }
    evaluated_json = client.post(
        "/api/evaluate-samples",
        files={"file": ("samples.json", json.dumps(json_payload, ensure_ascii=False).encode("utf-8"), "application/json")},
    )
    assert evaluated_json.status_code == 200, evaluated_json.text
    assert evaluated_json.json()["summary"]["evaluable"] == 2, evaluated_json.json()

    unmapped_csv = "\n".join([
        "task,human_label,predicted_label,user_text,video,order_item,sku,human_reason",
        "video_unboxing,赔付,赔付,用户要求赔付,a.mp4,商品A,SKU1,人工备注",
    ])
    unmapped = client.post(
        "/api/evaluate-samples",
        files={"file": ("unmapped.csv", unmapped_csv.encode("utf-8"), "text/csv")},
    )
    assert unmapped.status_code == 200, unmapped.text
    unmapped_data = unmapped.json()
    assert unmapped_data["summary"]["evaluable"] == 0, unmapped_data
    assert unmapped_data["unmapped_labels"]["人工结论"], unmapped_data
    assert unmapped_data["unmapped_labels"]["辅助结论"], unmapped_data

    mixed_csv = "\n".join([
        "task,human_label,predicted_label,user_text,video,order_item,sku,human_reason",
        "wrong_item,pass,pass,发错货,a.mp4,商品A,SKU1,人工确认发错",
        "unknown,pass,pass,其他,b.mp4,商品B,SKU2,其他原因",
        "product_damage,pass,fail,划痕,c.mp4,商品C,SKU3,人工确认有伤",
    ])
    mixed = client.post(
        "/api/evaluate-samples",
        files={"file": ("mixed.csv", mixed_csv.encode("utf-8"), "text/csv")},
    ).json()
    assert mixed["summary"]["evaluable"] == 3, mixed
    assert mixed["summary"]["accuracy"] == 0.6667, mixed
    assert mixed["summary"]["target_evaluable"] == 1, mixed
    assert mixed["summary"]["target_accuracy"] == 0.0, mixed
    assert mixed["summary"]["non_target_total"] == 2, mixed

    rows_without_prediction = ["task,human_label,user_text,video,order_item,sku,human_reason"]
    rows_ready = ["task,human_label,predicted_label,user_text,video,order_item,sku,human_reason"]
    for task in ("video_unboxing", "product_damage", "minor_material"):
        for index in range(50):
            rows_without_prediction.append(f"{task},pass,正向样本,{task}_{index}.mp4,商品,SKU,人工正向")
            rows_without_prediction.append(f"{task},fail,负向样本,{task}_n_{index}.mp4,商品,SKU,人工负向")
            rows_ready.append(f"{task},pass,pass,正向样本,{task}_{index}.mp4,商品,SKU,人工正向")
            rows_ready.append(f"{task},fail,fail,负向样本,{task}_n_{index}.mp4,商品,SKU,人工负向")
    not_ready = client.post(
        "/api/evaluate-samples",
        files={"file": ("not_ready.csv", "\n".join(rows_without_prediction).encode("utf-8"), "text/csv")},
    ).json()
    assert not_ready["summary"]["ready_for_accuracy"] is False, not_ready
    ready = client.post(
        "/api/evaluate-samples",
        files={"file": ("ready.csv", "\n".join(rows_ready).encode("utf-8"), "text/csv")},
    ).json()
    assert ready["summary"]["ready_for_accuracy"] is True, ready
    assert ready["summary"]["evaluable"] == 300, ready
    assert ready["summary"]["target_evaluable"] == 300, ready
    assert ready["summary"]["accuracy"] == 1.0, ready
    assert ready["summary"]["target_accuracy"] == 1.0, ready

    bad_csv = client.post(
        "/api/evaluate-samples",
        files={"file": ("bad.csv", b"task,human_label\nvideo_unboxing,pass,extra\n", "text/csv")},
    )
    assert bad_csv.status_code == 400

    bad_json = client.post(
        "/api/evaluate-samples",
        files={"file": ("bad.json", b'{"samples":[1]}', "application/json")},
    )
    assert bad_json.status_code == 400


def test_workbench_html() -> None:
    html = (ROOT / "poc" / "visual_review_poc" / "workbench.html").read_text(encoding="utf-8")
    for scenario in ("video_unboxing", "product_damage", "minor_material"):
        assert f'data-scenario="{scenario}"' in html
    assert "scenario=all" not in html
    assert "sampleEvalForm" in html
    assert "folderInput" in html
    assert "batchSampleBtn" in html
    assert "sample_004" in html
    for path in ("/video-unboxing", "/product-damage", "/minor-material"):
        assert path in html, path
    assert "人工结论样本评测" in html
    assert not FORBIDDEN_PUBLIC_TERMS.search(html)

    labels = json.loads((ROOT / "docs" / "三大审核场景的小量样本" / "sample_labels.json").read_text(encoding="utf-8"))
    scenarios = {item.get("scenario") for item in (labels.get("samples") or {}).values()}
    assert {"video_unboxing", "product_damage", "minor_material"}.issubset(scenarios), scenarios


def test_url_guard() -> None:
    from poc.visual_review_poc.url_video_fetcher import self_check

    self_check()


def test_review_prompt_policy() -> None:
    from poc.visual_review_poc.local_video_triage_demo import (
        build_system_prompt,
        build_user_prompt,
        evaluate,
        find_supplemental_images,
        load_case,
        load_report_label,
        render_html,
    )

    sample_video = ROOT / "docs" / "三大审核场景的小量样本" / "sample_001" / "005_cWKxEnRn.mp4"
    case = load_case(sample_video, 1)
    frames = [
        {"frame_index": 1, "timestamp": "00:00.00", "timestamp_seconds": 0.0, "file": "frame_001_0.00s.jpg", "path": str(sample_video)},
        {"frame_index": 2, "timestamp": "00:01.00", "timestamp_seconds": 1.0, "file": "frame_002_1.00s.jpg", "path": str(sample_video)},
    ]
    frame_sample = {
        "fps_requested": 1.0,
        "native_fps": 30.0,
        "duration_seconds": 2.0,
        "probe_seconds": 0.0,
        "sampled_frames": 2,
    }
    system_prompt = build_system_prompt()
    prompt = build_user_prompt(case, frame_sample, frames)
    for text in (
        "二次元电商售后",
        "开箱视频/发错货",
        "首席视觉质检员",
        "换手、遮挡、剪辑",
        "business_action_allowed 必须为 false",
    ):
        assert text in system_prompt, text
    for text in (
        "predicted_label",
        "confidence_reason",
        "expected_order_item",
        "actual_received_item",
        "frame_findings",
        "supporting_evidence",
        "challenging_evidence",
        "continuity_assessment",
        "size_sku_assessment",
        "issue_timestamps",
        "conclusion_argument",
        "business_action_allowed",
        "human_required",
    ):
        assert text in prompt, text

    forbidden_prompt_terms = (
        "sample_labels.json",
        "human_conclusion",
        "expected_predicted_label",
        "人工确认",
        "确实发错",
        "没有发错",
        "正样本",
        "负样本",
    )
    full_prompt = system_prompt + "\n" + prompt
    for text in forbidden_prompt_terms:
        assert text not in full_prompt, text

    images = find_supplemental_images(sample_video, 2, {})
    assert images and images[0]["file"], images

    label = load_report_label("sample_001")
    assert label["available"] is True, label
    miss = evaluate({"predicted_label": "review"}, label)
    assert miss["hit"] is False, miss
    hit = evaluate({"predicted_label": label["expected_predicted_label"]}, label)
    assert hit["hit"] is True, hit
    report = {
        "gemini": {
            "status": "success",
            "winner": {
                "model": "gemini-3.5-flash",
                "latency_seconds": 1.2,
                "usage": {"total_tokens": 100},
                "raw_text": "{\"predicted_label\":\"negative\"}",
                "parsed": {
                    "decision": "manual_review",
                    "predicted_label": "negative",
                    "confidence": 0.8,
                    "next_step": "输出证据摘要并转人工复核。",
                    "confidence_reason": "示例解析结果。",
                },
            },
        },
        "evaluation": hit,
        "frames": [],
        "supplemental_images": [],
        "system_prompt": system_prompt,
        "user_prompt": prompt,
        "report_label": label,
    }
    html = render_html(report)
    for text in ("recommended_primary_model", "recommended_double_blind_pool", "model_selection_basis", "双盲候选池", "主审"):
        assert text not in html, text


def test_public_report_redaction() -> Path:
    from poc.visual_review_poc.workbench_server import _agent_report_response, _public_result

    result = _public_result(True, "高精度审核", {"summary": {"available": True, "hit": False}})
    report_name = result["report"]["html_url"].rsplit("/", 1)[-1]
    html_path = ROOT / "poc" / "visual_review_poc" / "reports" / "public_summaries" / Path(report_name).with_suffix(".json").name
    assert html_path.exists(), html_path
    data = json.loads(html_path.read_text(encoding="utf-8"))
    assert not FORBIDDEN_PUBLIC_TERMS.search(json.dumps(data, ensure_ascii=False)), data
    assert not contains_forbidden_public_key(data), data

    sample_dir = ROOT / "docs" / "三大审核场景的小量样本" / "sample_004"
    agent = _agent_report_response(
        {
            "case_id": "redaction_fixture",
            "scenario": "minor_material",
            "scenario_label": "资料审核",
            "videos": [{"video_index": 1, "file": "minor_material_review.mp4"}],
            "frames": [],
            "supplemental_images": [],
        },
        sample_dir,
        {
            "status": "success",
            "model": "internal-model-name",
            "display_model": "internal-display-name",
            "provider": "internal-provider",
            "usage": {"total_tokens": 100},
            "token_usage": {"input_tokens": 10},
            "cost": {"amount": 1},
            "raw_response": {"thoughtSignature": "secret"},
            "raw_text": "secret",
            "system_prompt": "secret",
            "user_prompt": "secret",
            "latency_seconds": 1.1,
            "parsed": {
                "predicted_label": "review",
                "system_yes_no": "REVIEW",
                "confidence": 0.72,
                "overall_audit": {"conclusion": "资料需人工复核", "confidence": 0.72, "core_reason": "脱敏工程样本材料不足。"},
                "visual_qc_conclusion": {"verdict": "review", "confidence": 0.72, "core_reason": "资料关系证明仍需核验。"},
                "video_audit_conclusion": {"continuity_score": 1, "continuity_reason": "静态录屏样本", "swap_risk_level": "low", "edit_or_cut_risk": "low"},
                "adopted_evidence": [],
                "frame_findings": [],
                "business_follow_up_reason": "人工复核",
                "next_step": "请人工客服补齐监护关系证明后复核。",
            },
        },
        "redaction_fixture",
    )
    agent_name = agent["report"]["html_url"].rsplit("/", 1)[-1]
    agent_json = ROOT / "poc" / "visual_review_poc" / "reports" / "public_summaries" / Path(agent_name).with_suffix(".json").name
    agent_data = json.loads(agent_json.read_text(encoding="utf-8"))
    assert not contains_forbidden_public_key(agent_data), agent_data

    public_dir = ROOT / "poc" / "visual_review_poc" / "reports" / "public_summaries"
    for item in public_dir.glob("*.json"):
        payload = json.loads(item.read_text(encoding="utf-8"))
        assert not contains_forbidden_public_key(payload), item
    return html_path


def test_public_report_root_has_no_technical_reports() -> None:
    report_root = ROOT / "poc" / "visual_review_poc" / "reports"
    leaked = [
        item.name
        for item in report_root.glob("*")
        if item.is_file() and item.suffix.lower() in {".html", ".json"}
    ]
    assert not leaked, leaked


def main() -> int:
    report_dir = ROOT / "tests" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    checks = []
    for name, fn in (
        ("workbench_api", test_workbench_api),
        ("workbench_html", test_workbench_html),
        ("url_guard", test_url_guard),
        ("review_prompt_policy", test_review_prompt_policy),
        ("public_report_redaction", test_public_report_redaction),
        ("public_report_root_has_no_technical_reports", test_public_report_root_has_no_technical_reports),
    ):
        started = time.time()
        result = fn()
        checks.append({"name": name, "ok": True, "seconds": round(time.time() - started, 2), "result": str(result or "")})

    path = report_dir / f"visual_workbench_smoke_{time.strftime('%Y%m%d_%H%M%S')}.md"
    lines = ["# 视觉审核工作台 Smoke", "", f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for item in checks:
        lines.append(f"- [通过] {item['name']} ({item['seconds']}s) {item['result']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"visual workbench smoke passed: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
