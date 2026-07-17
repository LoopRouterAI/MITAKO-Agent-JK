# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FORBIDDEN_PUBLIC_TERMS = re.compile(
    r"Gemini|GPT|endpoint|DeepSeek|Mock|外包|端点|模型渠道|模型服务限流|status_code|error_type",
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
    "status_code",
    "error_type",
    "path",
    "api_path",
    "uri",
    "inference_estimate",
    "estimated_usd",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "model_calls",
    "channels",
}


def contains_forbidden_public_key(value) -> bool:
    if isinstance(value, dict):
        return any(str(key) in FORBIDDEN_PUBLIC_KEYS or contains_forbidden_public_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_forbidden_public_key(item) for item in value)
    return False


def assert_public_payload_clean(value) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    assert not FORBIDDEN_PUBLIC_TERMS.search(text), text
    assert "file:///" not in text.lower() and "file://" not in text.lower(), text
    assert str(ROOT) not in text, text
    if not isinstance(value, str):
        assert not contains_forbidden_public_key(value), value


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
    import poc.visual_review_poc.workbench_server as workbench_server

    client = TestClient(workbench_server.app)
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

    with tempfile.TemporaryDirectory() as temp_dir:
        single_failure = workbench_server._agent_report_response(
            {
                "case_id": "SMOKE-FAILURE",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
                "structured_business_context": {},
            },
            Path(temp_dir),
            {"status": "failed", "status_code": 429, "error_type": "soft", "error": "review_timeout"},
            "smoke_failure",
        )
    assert single_failure["summary"]["cases"] == 1, single_failure
    assert single_failure["summary"]["total_reviews"] == 1, single_failure
    assert single_failure["summary"]["successful_reviews"] == 0, single_failure
    assert single_failure["diagnostics"]["failure_stage"] == "系统复核", single_failure
    assert "status_code" not in single_failure["diagnostics"], single_failure
    assert "error_type" not in single_failure["diagnostics"], single_failure
    single_failure_html = client.get(single_failure["report"]["html_url"])
    assert single_failure_html.status_code == 200, single_failure_html.text
    assert "本轮失败诊断" in single_failure_html.text, single_failure_html.text
    assert "审核未完成" in single_failure_html.text, single_failure_html.text
    assert "系统复核服务繁忙" in single_failure_html.text, single_failure_html.text
    assert_public_payload_clean(single_failure)
    assert_public_payload_clean(single_failure_html.text)

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
    assert data["summary"]["ready_for_accuracy"] is None, data
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
    assert not_ready["summary"]["ready_for_accuracy"] is None, not_ready
    ready = client.post(
        "/api/evaluate-samples",
        files={"file": ("ready.csv", "\n".join(rows_ready).encode("utf-8"), "text/csv")},
    ).json()
    assert ready["summary"]["ready_for_accuracy"] is None, ready
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

    image_path = next((ROOT / "docs" / "三大审核场景的小量样本" / "sample_003").glob("*.jpg"))
    original_call_model = workbench_server.call_model_chunked

    def fake_success(cfg, case, timeout, retries):
        assert not case.get("videos"), case
        assert case.get("supplemental_images"), case
        return {
            "status": "success",
            "latency_seconds": 0.1,
            "usage": {},
            "cost": {},
            "parsed": {
                "predicted_label": "positive",
                "system_yes_no": "YES",
                "confidence": 0.91,
                "overall_audit": {
                    "conclusion": "图片可见商品有伤",
                    "confidence": 0.91,
                    "core_reason": "商品局部瑕疵清晰可见。",
                    "business_follow_up_suggestion": "提交人工复核。",
                },
                "visual_qc_conclusion": {"verdict": "positive", "confidence": 0.91, "core_reason": "瑕疵清晰。"},
                "adopted_evidence": [{"source_type": "image", "image_index": 1, "file": image_path.name, "fact": "瑕疵可见", "confidence": 0.91}],
            },
        }

    def fake_failed(cfg, case, timeout, retries):
        return {"status": "failed", "status_code": 429, "error_type": "soft", "latency_seconds": 0.2}

    def fake_unstructured(cfg, case, timeout, retries):
        return {"status": "success", "latency_seconds": 0.1, "usage": {}, "cost": {}, "parsed": {"raw_text": "not json"}}

    try:
        workbench_server.call_model_chunked = fake_success
        image_only = client.post(
            "/api/review-folder",
            data={"scenario": "product_damage", "customer_claim": "用户反馈商品有划痕"},
            files=[
                ("files", ("content.txt", "用户反馈商品有划痕".encode("utf-8"), "text/plain")),
                ("files", (image_path.name, image_path.read_bytes(), "image/jpeg")),
            ],
        )
        assert image_only.status_code == 200, image_only.text
        image_data = image_only.json()
        assert image_data["ok"] is True, image_data
        assert image_data["review"]["summary"]["successful_reviews"] == 1, image_data
        assert "补充图片 1 张" in image_data["review"]["frame_strategy"], image_data

        workbench_server.call_model_chunked = fake_failed
        failed = client.post(
            "/api/review-folder",
            data={"scenario": "product_damage", "customer_claim": "用户反馈商品有划痕"},
            files=[
                ("files", ("content.txt", "用户反馈商品有划痕".encode("utf-8"), "text/plain")),
                ("files", (image_path.name, image_path.read_bytes(), "image/jpeg")),
            ],
        )
        assert failed.status_code == 200, failed.text
        failed_data = failed.json()
        assert failed_data["ok"] is False, failed_data
        assert failed_data["review"]["summary"]["successful_reviews"] == 0, failed_data
        assert failed_data["review"]["diagnostics"]["failure_stage"] == "系统复核", failed_data
        assert failed_data["review"]["diagnostics"]["failure_reason"] == "系统复核服务繁忙，本轮重试后仍未完成审核。", failed_data
        assert "status_code" not in failed_data["review"]["diagnostics"], failed_data
        assert "error_type" not in failed_data["review"]["diagnostics"], failed_data
        assert "审核未完成" in failed_data["review"]["agent_brief"]["conclusion"], failed_data
        assert "证据不足" not in failed_data["review"]["agent_brief"]["conclusion"], failed_data
        failed_html = client.get(failed_data["review"]["report"]["html_url"])
        assert failed_html.status_code == 200, failed_html.text
        for text in ("本轮失败诊断", "审核未完成", "系统复核服务繁忙"):
            assert text in failed_html.text, text
        assert_public_payload_clean(failed_data["review"])
        assert_public_payload_clean(failed_html.text)

        video_path = ROOT / "docs" / "三大审核场景的小量样本" / "sample_004" / "minor_material_review.mp4"
        video_failed = client.post(
            "/api/review-folder",
            data={"scenario": "video_unboxing", "customer_claim": "用户反馈开箱视频疑似发错货"},
            files=[
                ("files", ("content.txt", "用户反馈开箱视频疑似发错货".encode("utf-8"), "text/plain")),
                ("files", (video_path.name, video_path.read_bytes(), "video/mp4")),
            ],
        )
        assert video_failed.status_code == 200, video_failed.text
        video_failed_data = video_failed.json()
        assert video_failed_data["ok"] is False, video_failed_data
        assert video_failed_data["review"]["diagnostics"]["videos_received"] == 1, video_failed_data
        video_failed_html = client.get(video_failed_data["review"]["report"]["html_url"])
        assert video_failed_html.status_code == 200, video_failed_html.text
        for text in ("本轮失败诊断", "审核未完成", "系统复核服务繁忙"):
            assert text in video_failed_html.text, text
        assert_public_payload_clean(video_failed_data["review"])
        assert_public_payload_clean(video_failed_html.text)

        hidden_files = client.post(
            "/api/review-folder",
            data={"scenario": "video_unboxing", "customer_claim": "用户反馈开箱视频疑似发错货"},
            files=[
                ("files", ("__MACOSX/._030_008.mp4", b"\x00\x05\x16\x07resource-fork", "video/mp4")),
                ("files", ("._annotation.json", b"appledouble", "application/json")),
                ("files", (".hidden.mp4", b"not-a-video", "video/mp4")),
                ("files", ("fake.mp4", b"not-a-video", "video/mp4")),
                ("files", (video_path.name, video_path.read_bytes(), "video/mp4")),
            ],
        )
        assert hidden_files.status_code == 200, hidden_files.text
        hidden_data = hidden_files.json()
        assert hidden_data["ingestion"]["received_count"] == 5, hidden_data
        assert hidden_data["ingestion"]["accepted_count"] == 1, hidden_data
        assert hidden_data["ingestion"]["video_count"] == 1, hidden_data
        assert hidden_data["ingestion"]["skipped_count"] == 4, hidden_data
        reason_codes = {item["reason_code"] for item in hidden_data["ingestion"]["skipped_files"]}
        assert {"system_directory", "appledouble_file", "hidden_file", "invalid_media_content"} == reason_codes, hidden_data
        assert hidden_data["review"]["diagnostics"]["videos_received"] == 1, hidden_data
        assert_public_payload_clean(hidden_data["review"])

        workbench_server.call_model_chunked = fake_unstructured
        unstructured = client.post(
            "/api/review-folder",
            data={"scenario": "product_damage", "customer_claim": "用户反馈商品有划痕"},
            files=[
                ("files", ("content.txt", "用户反馈商品有划痕".encode("utf-8"), "text/plain")),
                ("files", (image_path.name, image_path.read_bytes(), "image/jpeg")),
            ],
        )
        assert unstructured.status_code == 200, unstructured.text
        unstructured_data = unstructured.json()
        assert unstructured_data["ok"] is False, unstructured_data
        assert unstructured_data["review"]["summary"]["review_status"] == "failed", unstructured_data
        assert unstructured_data["review"]["diagnostics"]["failure_stage"] == "系统复核", unstructured_data
        assert_public_payload_clean(unstructured_data["review"])
    finally:
        workbench_server.call_model_chunked = original_call_model


def test_model_transport_contract() -> None:
    import poc.visual_review_poc.model_selection_e2e as model_selection

    image_path = next((ROOT / "docs" / "三大审核场景的小量样本" / "sample_003").glob("*.jpg"))
    case = {
        "case_id": "image_only_contract",
        "scenario": "product_damage",
        "scenario_label": "商品有伤审核",
        "customer_claim": "用户反馈商品有划痕",
        "order_context": {},
        "structured_business_context": {},
        "evidence_assets": [],
        "videos": [],
        "frames": [],
        "supplemental_images": [
            {
                "image_index": 1,
                "file": image_path.name,
                "api_path": str(image_path),
                "api_mime_type": "image/jpeg",
                "fields": [],
            }
        ],
    }
    original_post = model_selection.post_with_retries
    original_key = os.environ.get("VISION_REVIEW_API_KEY")
    captured = {}

    def fake_post(endpoint, headers, payload, timeout, retries):
        captured["payload"] = payload
        return {
            "ok": True,
            "status_code": 200,
            "latency_seconds": 0.01,
            "attempt": 1,
            "data": {
                "candidates": [{"content": {"parts": [{"text": json.dumps({"predicted_label": "positive", "system_yes_no": "YES", "confidence": 0.9}, ensure_ascii=False)}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
            },
        }

    try:
        os.environ["VISION_REVIEW_API_KEY"] = "fake-key-for-contract-test"
        model_selection.post_with_retries = fake_post
        result = model_selection.call_model(model_selection.MODEL_CONFIGS["gemini35"], case, timeout=1, retries=0)
        assert result["status"] == "success", result
        parts = captured["payload"]["contents"][0]["parts"]
        inline_items = [item for item in parts if "inline_data" in item]
        assert len(inline_items) == 1, parts
        assert inline_items[0]["inline_data"]["mime_type"] == "image/jpeg", inline_items
        assert not any("视频1 帧" in str(item.get("text") or "") for item in parts if isinstance(item, dict)), parts
    finally:
        model_selection.post_with_retries = original_post
        if original_key is None:
            os.environ.pop("VISION_REVIEW_API_KEY", None)
        else:
            os.environ["VISION_REVIEW_API_KEY"] = original_key


def test_retry_after_is_honored() -> None:
    import poc.visual_review_poc.model_selection_e2e as model_selection

    class FakeResponse:
        def __init__(self, status_code: int, text: str = "", headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

        def json(self):
            return {"ok": True}

    class FakeClient:
        calls = 0

        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, headers, json):
            FakeClient.calls += 1
            if FakeClient.calls == 1:
                return FakeResponse(429, "rate limit", {"Retry-After": "1"})
            return FakeResponse(200)

    original_client = model_selection.httpx.Client
    original_sleep = model_selection.time.sleep
    sleeps = []
    try:
        model_selection.httpx.Client = FakeClient
        model_selection.time.sleep = lambda seconds: sleeps.append(seconds)
        result = model_selection.post_with_retries("https://example.invalid", {}, {}, timeout=1, retries=1)
        assert result["ok"] is True, result
        assert result["attempt"] == 2, result
        assert sleeps == [1.0], sleeps
    finally:
        model_selection.httpx.Client = original_client
        model_selection.time.sleep = original_sleep


def test_workbench_html() -> None:
    html = (ROOT / "poc" / "visual_review_poc" / "workbench.html").read_text(encoding="utf-8")
    for scenario in ("video_unboxing", "product_damage", "minor_material"):
        assert f'data-scenario="{scenario}"' in html
    assert "scenario=all" not in html
    assert "sampleEvalForm" in html
    assert "folderInput" in html
    assert "function folderFileIssue(file)" in html
    assert "function uploadableFolderFiles()" in html
    assert "formData.delete('files')" in html
    assert "function ingestionLines(data)" in html
    assert "function mediaWarningLines(data)" in html
    assert "function clientFolderIngestionSummary()" in html
    assert "function configureBuiltInSampleControls()" in html
    assert "batchSampleBtn" in html
    assert "sample_004" in html
    for path in ("/video-unboxing", "/product-damage", "/minor-material"):
        assert path in html, path
    assert "人工结论样本评测" in html
    assert not FORBIDDEN_PUBLIC_TERMS.search(html)

    for fps in ("0.2", "0.5", "1", "2"):
        assert re.search(rf'<option\s+value="{re.escape(fps)}"[^>]*>', html), fps
    for label in ("每 5 秒 1 帧", "每 2 秒 1 帧", "每秒 1 帧", "每秒 2 帧"):
        assert label in html, label

    assert "function stopReportLinkEvent(event)" in html
    assert "event.stopPropagation();" in html
    assert "function prepareReportLink(link)" in html
    assert "link.target = '_blank';" in html
    assert "link.rel = 'noopener noreferrer';" in html
    assert "prepareReportLink(reportLink);" in html
    assert "prepareReportLink(document.createElement('a'))" in html
    assert "if (event.target.closest('a')) return;" in html

    labels_path = ROOT / "docs" / "三大审核场景的小量样本" / "sample_labels.json"
    assert labels_path.exists(), labels_path
    labels = json.loads(labels_path.read_text(encoding="utf-8-sig"))
    assert labels.get("note") == "人工结论只用于报告侧评测，不进入模型 Prompt。", labels
    scenarios = {item.get("scenario") for item in (labels.get("samples") or {}).values()}
    assert {"video_unboxing", "product_damage", "minor_material"}.issubset(scenarios), scenarios


def test_internal_package_visual_contract() -> None:
    script = (ROOT / "scripts" / "package_internal_release.ps1").read_text(encoding="utf-8-sig")
    for text in (
        "function Copy-SafeSampleLabels",
        'Copy-SafeSampleLabels',
        'docs\\三大审核场景的小量样本\\sample_labels.json',
        'usage_boundary = "report_evaluation_only"',
        'send_to_model = $false',
        'Packaged sample labels violate the report-only boundary.',
        'function Invoke-InternalValidation',
        '$PythonCandidates = @(',
        '.venv\Scripts\python.exe',
        'venv\Scripts\python.exe',
        'evidence = $evidenceHashes',
    ):
        assert text in script, text
    assert 'New-Item -ItemType Junction' not in script, "内部包不应再创建兼容 Junction"
    assert not re.search(r"七牛云.{0,24}(已接入|已打通|生产可用)", script), script


def test_sampling_density_runtime_contract() -> None:
    from poc.visual_review_poc.local_video_triage_demo import sample_video_frames

    sample_dir = ROOT / "docs" / "三大审核场景的小量样本" / "sample_002"
    video = next(path for path in sorted(sample_dir.iterdir()) if path.suffix.lower() in {".mp4", ".mov", ".m4v", ".webm", ".mkv"})
    tmp_root = ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="visual-fps-smoke-", dir=tmp_root) as workdir:
        for fps in (0.2, 0.5, 1.0, 2.0):
            result = sample_video_frames(
                video,
                fps=fps,
                max_frames=2000,
                probe_seconds=1.0,
                frame_width=320,
                run_dir=Path(workdir) / str(fps).replace(".", "_"),
                sampling_mode="dense",
            )
            duration = float(result.get("duration_seconds") or 0)
            actual = int(result.get("sampled_frames") or 0)
            expected = math.ceil(duration * fps) + 1
            assert result.get("fps_requested") == fps, result
            assert result.get("sampling_strategy") == "full_timeline_dense", result
            assert float(result.get("timeline_coverage_ratio") or 0) >= 0.9, result
            assert abs(actual - expected) <= 1, {"fps": fps, "actual": actual, "expected": expected, "duration": duration}


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
        "开箱视频",
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
                    "next_step": "输出证据摘要并转VIP客服复核。",
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
    from poc.visual_review_poc.workbench_server import _agent_report_response

    public_dir = ROOT / "poc" / "visual_review_poc" / "reports" / "public_summaries"
    before = {item.name for item in public_dir.glob("*.json")} if public_dir.exists() else set()

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
                "business_follow_up_reason": "VIP客服复核",
                "next_step": "请VIP客服补齐监护关系证明后复核。",
            },
        },
        "redaction_fixture",
    )
    agent_name = agent["report"]["html_url"].rsplit("/", 1)[-1]
    agent_json = ROOT / "poc" / "visual_review_poc" / "reports" / "public_summaries" / Path(agent_name).with_suffix(".json").name
    agent_data = json.loads(agent_json.read_text(encoding="utf-8"))
    assert not contains_forbidden_public_key(agent_data), agent_data

    for item in public_dir.glob("*.json"):
        if item.name in before:
            continue
        payload = json.loads(item.read_text(encoding="utf-8"))
        assert not contains_forbidden_public_key(payload), item
    return agent_json


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
        ("model_transport_contract", test_model_transport_contract),
        ("retry_after_is_honored", test_retry_after_is_honored),
        ("workbench_html", test_workbench_html),
        ("internal_package_visual_contract", test_internal_package_visual_contract),
        ("sampling_density_runtime_contract", test_sampling_density_runtime_contract),
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
