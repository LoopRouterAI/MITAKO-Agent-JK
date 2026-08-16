# -*- coding: utf-8 -*-
from scripts.run_final_commercial_acceptance import (
    BLIND_MANIFEST_PATH,
    CURRENT_ARTIFACT_TAG,
    DEFAULT_CHECKPOINT_PATH,
    DEFAULT_MODEL_PROFILE,
    FORBIDDEN_INPUT_NAMES,
    REQUIRED_CASES_PER_SCENE,
    SCENARIOS,
    UNSEEN_AUDIT_SCOPES,
    UNSEEN_AUDIT_VERSION,
    FORMALLY_UNRUN_AUDIT_SCOPES,
    FORMALLY_UNRUN_AUDIT_VERSION,
    build_blind_review_checks,
    _model_profile,
    _scene_facts_present,
    case_summary,
    case_input_names,
    case_ids_sha256,
    compute_case_input_bundle_sha256,
    export,
    load_blind_manifest,
    load_submission_checkpoint,
    resolve_blind_cases,
    save_submission_checkpoint,
    source_case,
    submit,
    wait_all,
)
import httpx
import hashlib
import json
import pytest
from unittest.mock import patch


def test_submit_uses_stable_execution_id_without_changing_sealed_case_hash(tmp_path) -> None:
    media = tmp_path / "asset.mp4"
    media.write_bytes(b"video")
    case = {
        "case_id": "602271",
        "scenario": "product_damage",
        "input_bundle_sha256": "a" * 64,
    }
    captured = []

    class _Response:
        status_code = 202
        text = ""

        @staticmethod
        def json() -> dict:
            return {"job": {"job_id": "RJ-NEW-BATCH"}}

    class _Client:
        def post(self, *args, **kwargs):
            captured.append(kwargs)
            return _Response()

    prepared = (
        {"scenario": "product_damage"},
        [media],
        [{"neutral_name": "asset_001.mp4", "mime_type": "video/mp4"}],
    )
    with patch("scripts.run_final_commercial_acceptance.source_case", return_value=prepared):
        submit(_Client(), "http://127.0.0.1:8015", "token", case, 1, "20260814.1")
        submit(_Client(), "http://127.0.0.1:8015", "token", case, 1, "20260814.1")
        submit(_Client(), "http://127.0.0.1:8015", "token", case, 1, "20260815.1")

    keys = [item["headers"]["Idempotency-Key"] for item in captured]
    assert keys[0] == keys[1]
    assert keys[0] != keys[2]
    assert case["input_bundle_sha256"] == "a" * 64


def test_export_rejects_failed_jobs_before_requesting_any_html() -> None:
    class _Client:
        def get(self, *args, **kwargs):
            raise AssertionError("失败批次不得请求报告 HTML")

    rows = [{
        "case": {"case_id": "316353", "scenario": "missing_item"},
        "job_id": "RJ-FAILED",
        "job": {"job_id": "RJ-FAILED", "status": "FAILED"},
    }]
    with pytest.raises(RuntimeError, match="316353:FAILED"):
        export(_Client(), "http://127.0.0.1:8015", "token", rows)


def test_export_rejects_technical_processing_incomplete_before_requesting_html() -> None:
    class _Client:
        def get(self, *args, **kwargs):
            raise AssertionError("技术处理未完成时不得请求报告 HTML")

    rows = [{
        "case": {"case_id": "611941", "scenario": "product_damage"},
        "job_id": "RJ-TECHNICAL-INCOMPLETE",
        "job": {
            "job_id": "RJ-TECHNICAL-INCOMPLETE",
            "status": "SUCCEEDED",
            "result": {"review": {"agent_report": {"parsed": {
                "processing_status": "technical_processing_incomplete",
                "system_action": "system_retry",
            }}}},
        },
    }]
    with pytest.raises(RuntimeError, match="technical_processing_incomplete"):
        export(_Client(), "http://127.0.0.1:8015", "token", rows)


def _row(scenario: str, case_index: int) -> dict:
    scene_contract = {
        "product_damage": {
            "opening_video_evidence": {
                "present": True,
                "sop_compliant": True,
                "validated_requirements": [
                    "opening_action", "sealed_start", "waybill_visible",
                    "continuous", "all_items_shown",
                ],
            },
            "damage_presence": "confirmed",
            "claim_support": "supported",
            "severity": {
                "level": "moderate",
                "confidence": 0.91,
                "structural_failure": False,
            },
            "severe_alert_eligible": False,
        },
        "wrong_item": {
            "evidence_sufficiency": "sufficient",
            "observed_items_present": True,
            "package_observations_present": True,
            "identity_definition_fields_present": True,
            "same_package_evidence_present": True,
        },
        "missing_item": {
            "evidence_route": "static_three_images",
            "resolution_basis": "none",
            "warehouse_check": {"state": "pending", "outcome": None},
            "user_materials_complete": True,
        },
        "minor_refund": {
            "five_material_checklist_present": True,
            "payment_capability_risk": {
                "low_age": False,
                "under_nine": False,
                "age_confidence": "high",
                "process_evidence_status": "matched",
                "requires_more_material": False,
                "requires_review": False,
            },
        },
    }[scenario]
    return {
        "case_id": f"{scenario}-{case_index}",
        "scenario": scenario,
        "status": "SUCCEEDED",
        "processing_status": "completed",
        "system_action": "none",
        "predicted_label": "review",
        "material_readiness": {
            "scenario": scenario,
            "status": "complete",
            "confidence": 0.91,
            "reason": "本场景材料齐全。",
            "checklist": [{
                "requirement_id": (
                    "initial_opening_video" if scenario == "product_damage" else "evidence"
                ),
                "label": "场景必要证据",
                "required": True,
                "status": "present",
                "source": "model",
                "confidence": 0.91,
                "evidence_refs": [{"asset_ref": "native_video_1", "timestamp": "00:01"}],
                "reason": "证据可回看。",
            }],
            "missing_items": [],
            "warnings": [],
        },
        "scene_facts_present": True,
        "scene_contract": scene_contract,
        "evidence_ref_count": 1,
        "report_json": f"tests/reports/review_0816_blind_{scenario}_{case_index}.json",
        "report_html": f"tests/reports/review_0816_blind_{scenario}_{case_index}.html",
        "report_same_job": True,
        "model_profile": DEFAULT_MODEL_PROFILE,
    }


def test_final_gate_requires_two_random_cases_for_all_four_scenarios() -> None:
    assert CURRENT_ARTIFACT_TAG == "0816"
    assert DEFAULT_CHECKPOINT_PATH.name == "review_0816_formally_unrun_blind_checkpoint.json"
    assert SCENARIOS == {
        "product_damage", "wrong_item", "missing_item", "minor_refund"
    }
    assert REQUIRED_CASES_PER_SCENE == 2


def test_wrong_item_incomplete_materials_do_not_require_invented_observed_identity() -> None:
    row = _row("wrong_item", 1)
    row["predicted_label"] = "review"
    row["scene_contract"].update({
        "evidence_sufficiency": "insufficient",
        "observed_items_present": False,
        "identity_definition_fields_present": False,
    })

    assert build_blind_review_checks([
        row,
        _row("wrong_item", 2),
        *[_row(scene, index) for scene in SCENARIOS - {"wrong_item"} for index in (1, 2)],
    ])["all_current_business_contracts_valid"] is True


def test_blind_case_summary_does_not_require_or_export_manual_answers() -> None:
    row = {
        "case": {"case_id": "BLIND-1", "scenario": "product_damage"},
        "job": {
            "job_id": "RJ-BLIND-1",
            "status": "SUCCEEDED",
            "result": {
                "review": {
                    "summary": {"predicted_label": "review", "confidence": 0.7},
                    "agent_report": {"parsed": {}},
                },
                "material_readiness": {
                    "scenario": "product_damage",
                    "status": "indeterminate",
                    "confidence": 0.7,
                    "reason": "当前证据仍有未确认项。",
                    "checklist": [],
                    "missing_items": [],
                    "warnings": [],
                },
            },
        },
        "internal_job": {"result": {"review": {}}},
        "report_requested_job_id": "RJ-BLIND-1",
    }

    summary = case_summary(row, "blind.json", "blind.html")

    assert "manual_baseline" not in summary
    assert summary["case_id"] == "BLIND-1"
    assert summary["predicted_label"] == "review"


def test_existing_technical_manifest_is_sealed_but_not_strictly_unseen() -> None:
    legacy_path = BLIND_MANIFEST_PATH.with_name("four_scene_blind_manifest_20260815.json")
    payload = json.loads(legacy_path.read_text(encoding="utf-8-sig"))
    cases = payload["cases"]
    configured = {
        scenario: [item["case_id"] for item in cases if item["scenario"] == scenario]
        for scenario in sorted(SCENARIOS)
    }

    assert configured == {
        "minor_refund": ["141869", "262009"],
        "missing_item": ["317898", "572191"],
        "product_damage": ["590108", "603703"],
        "wrong_item": ["72006", "159686"],
    }
    assert "56790" not in {item["case_id"] for item in cases}
    forbidden = {"expected_label", "manual_baseline", "manual_source", "sample_dir"}
    assert all(forbidden.isdisjoint(item) for item in cases)
    assert payload["label_state"] == "sealed"
    assert payload["unseen_audit"]["status"] == "not_proven"
    with pytest.raises(RuntimeError, match="盲验输入审计"):
        load_blind_manifest(legacy_path)


def test_current_manifest_uses_formally_unrun_cases_without_human_answers() -> None:
    payload = load_blind_manifest(BLIND_MANIFEST_PATH)

    assert payload["unseen_audit"]["version"] == FORMALLY_UNRUN_AUDIT_VERSION
    assert {
        scenario: [item["case_id"] for item in payload["cases"] if item["scenario"] == scenario]
        for scenario in sorted(SCENARIOS)
    } == {
        "minor_refund": ["554611", "511007"],
        "missing_item": ["289433", "319303"],
            "product_damage": ["611941", "592717"],
        "wrong_item": ["515028", "310508"],
    }
    assert "310714" in payload["selection_note"]
    assert "人工基准相互冲突" in payload["selection_note"]
    forbidden = {"expected_label", "manual_baseline", "manual_source", "sample_dir"}
    assert all(forbidden.isdisjoint(item) for item in payload["cases"])


def test_resolve_blind_cases_ignores_same_id_directory_without_review_media(tmp_path) -> None:
    sample_dir = tmp_path / "samples" / "515028"
    sample_dir.mkdir(parents=True)
    (sample_dir / "001_evidence.jpg").write_bytes(b"\xff\xd8\xffevidence")
    order_index = tmp_path / "order_index" / "515028"
    order_index.mkdir(parents=True)
    (order_index / "order.json").write_text("{}", encoding="utf-8")
    payload = {
        "cases": [{
            "scenario": "wrong_item",
            "case_id": "515028",
            "input_bundle_sha256": compute_case_input_bundle_sha256(sample_dir),
        }],
    }

    resolved = resolve_blind_cases(payload, sample_root=tmp_path)

    assert len(resolved) == 1
    assert resolved[0]["sample_dir"] == sample_dir


def test_blind_manifest_requires_verified_unseen_audit_contract(tmp_path) -> None:
    payload = json.loads(BLIND_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    case_ids = [str(item["case_id"]) for item in payload["cases"]]
    payload["unseen_audit"] = {
        "version": UNSEEN_AUDIT_VERSION,
        "status": "verified_before_freeze",
        "audited_at": "2026-08-16 10:50:00 +08:00",
        "checked_scopes": sorted(UNSEEN_AUDIT_SCOPES),
        "case_ids_sha256": case_ids_sha256(case_ids),
        "matches": [],
    }
    path = tmp_path / "blind.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert load_blind_manifest(path)["unseen_audit"]["status"] == "verified_before_freeze"

    payload["unseen_audit"]["case_ids_sha256"] = hashlib.sha256(b"tampered").hexdigest()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="盲验输入审计"):
        load_blind_manifest(path)


def test_blind_manifest_accepts_user_approved_formally_unrun_audit(tmp_path) -> None:
    payload = json.loads(BLIND_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    case_ids = [str(item["case_id"]) for item in payload["cases"]]
    payload["unseen_audit"] = {
        "version": FORMALLY_UNRUN_AUDIT_VERSION,
        "status": "verified_before_freeze",
        "audited_at": "2026-08-16 18:30:00 +08:00",
        "checked_scopes": sorted(FORMALLY_UNRUN_AUDIT_SCOPES),
        "case_ids_sha256": case_ids_sha256(case_ids),
        "matches": [],
    }
    path = tmp_path / "formally-unrun.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert load_blind_manifest(path)["unseen_audit"]["version"] == FORMALLY_UNRUN_AUDIT_VERSION

    payload["unseen_audit"]["matches"] = [{"case_id": case_ids[0], "scope": "review_service_jobs"}]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="盲验输入审计"):
        load_blind_manifest(path)

    payload["unseen_audit"]["checked_scopes"] = [{}]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="盲验输入审计"):
        load_blind_manifest(path)


def test_case_input_names_exclude_human_answers_and_directory_labels() -> None:
    names = case_input_names([
        "001_evidence.mp4",
        "002_closeup.jpg",
        "content.txt",
        "order_info_snapshot.json",
        "reply.json",
        "annotation.json",
        "manifest.json",
        "sample_labels.json",
    ])

    assert names == ["001_evidence.mp4", "002_closeup.jpg"]
    assert FORBIDDEN_INPUT_NAMES.isdisjoint(names)


def test_source_case_uses_only_safe_ticket_identifiers_for_package_candidate(tmp_path) -> None:
    (tmp_path / "content.txt").write_text("漏发，要求补发", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps({
            "id": 319912,
            "order_no": "PT_202503159907401_6",
            "status": "已完成",
            "human_conclusion": "确认漏发",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "order_info_snapshot.json").write_text(
        json.dumps({
            "goods_list": [{
                "id": 1,
                "number": "SKU-1",
                "name": "纸类商品",
                "intro": "标准款",
                "goods_num": 1,
            }],
            "tracking_company": "测试快递",
            "tracking_number": "TRACK-1",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "evidence.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
    case = {
        "case_id": "319912",
        "scenario": "missing_item",
        "expected_label": "positive",
        "sample_dir": tmp_path,
    }

    metadata, _, _ = source_case(case)

    assert metadata["ticket_id"].startswith("BLIND-")
    assert "319912" not in json.dumps(metadata, ensure_ascii=False)
    assert metadata["order_no"] == "PT_202503159907401_6"
    package = metadata["fulfillment_baseline"]["packages"][0]
    assert package["package_ref"] == "ORDER-PACKAGE-001"
    assert package["tracking_no"] == "TRACK-1"
    assert package["order_reference"] == "PT_202503159907401_6"
    assert package["expected_item_refs"] == ["ORDER-LINE-001"]
    assert "确认漏发" not in json.dumps(metadata, ensure_ascii=False)


def test_source_case_rebuilds_clean_request_without_human_answers(tmp_path) -> None:
    (tmp_path / "001_evidence.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (tmp_path / "content.txt").write_text(
        "未成年人退款，监护人联系方式：13780720938",
        encoding="utf-8",
    )
    (tmp_path / "reply.json").write_text(
        json.dumps([
            {"from": "user", "text": "联系电话 13780720938，请撤销本次投诉"},
            {"from": "admin", "text": "人工终审：审核通过"},
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "annotation.json").write_text('{"label":"positive"}', encoding="utf-8")
    (tmp_path / "order_info_snapshot.json").write_text(
        '{"goods_list":[{"id":"1","number":"SKU-1","name":"测试商品","goods_num":1}]}',
        encoding="utf-8",
    )
    case = {
        "case_id": "clean-input",
        "scenario": "minor_refund",
        "sample_dir": tmp_path,
    }

    metadata, paths, manifest = source_case(case)

    assert [path.name for path in paths] == ["001_evidence.mp4"]
    assert metadata["customer_claim"] == "未成年人退款，监护人联系方式：[已脱敏]"
    assert metadata["conversation_history"] == [{
        "role": "user",
        "text": "联系电话 [敏感信息已遮盖]，请撤销本次投诉",
        "created_at": "",
    }]
    assert metadata["fulfillment_baseline"]["expected_items"][0]["sku"] == "SKU-1"
    serialized = str(metadata)
    assert "clean-input" not in serialized
    assert str(tmp_path) not in serialized
    assert "审核通过" not in serialized
    assert "positive" not in serialized
    assert manifest == [{
        "neutral_name": "asset_001.mp4",
        "mime_type": "video/mp4",
        "bytes": 12,
        "sha256": "4f0049d5f748a652f76c19e597432e2cbcc2a6b4108fb09d1846e7b25eae2df1",
    }]


def test_frozen_input_hash_covers_user_messages_but_not_human_answers(tmp_path) -> None:
    (tmp_path / "001_evidence.jpg").write_bytes(b"\xff\xd8\xffevidence")
    (tmp_path / "content.txt").write_text("用户原始诉求", encoding="utf-8")
    (tmp_path / "manifest.json").write_text('{"id":"CASE-1"}', encoding="utf-8")
    (tmp_path / "order_info_snapshot.json").write_text('{"goods_list":[]}', encoding="utf-8")
    (tmp_path / "reply.json").write_text(
        json.dumps([
            {"from": "user", "text": "用户补充说明"},
            {"from": "admin", "text": "人工结论：通过"},
        ], ensure_ascii=False),
        encoding="utf-8",
    )

    before = compute_case_input_bundle_sha256(tmp_path)
    (tmp_path / "reply.json").write_text(
        json.dumps([
            {"from": "user", "text": "用户补充说明"},
            {"from": "admin", "text": "人工结论：不通过"},
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    assert compute_case_input_bundle_sha256(tmp_path) == before

    (tmp_path / "reply.json").write_text(
        json.dumps([
            {"from": "user", "text": "用户改为撤销投诉"},
            {"from": "admin", "text": "人工结论：不通过"},
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    assert compute_case_input_bundle_sha256(tmp_path) != before

    (tmp_path / "content.txt").write_text("变更后的用户诉求", encoding="utf-8")
    assert compute_case_input_bundle_sha256(tmp_path) != before


def test_submission_checkpoint_round_trips_without_sample_paths(tmp_path) -> None:
    path = tmp_path / "checkpoint.json"
    rows = [{
        "case": {"case_id": "602271", "scenario": "product_damage", "sample_dir": tmp_path},
        "run_number": 1,
        "job_id": "RJ-CHECKPOINT-1",
        "manifest": [{"neutral_name": "asset_001.jpg", "sha256": "a" * 64}],
    }]

    save_submission_checkpoint(path, rows)
    serialized = path.read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert load_submission_checkpoint(path) == [{
        "case_id": "602271",
        "scenario": "product_damage",
        "run_number": 1,
        "job_id": "RJ-CHECKPOINT-1",
        "manifest": [{"neutral_name": "asset_001.jpg", "sha256": "a" * 64}],
    }]


def test_source_case_uses_detected_media_type_for_neutral_upload_name(tmp_path) -> None:
    png_body = b"\x89PNG\r\n\x1a\n" + b"verified-image"
    (tmp_path / "021_legacy.jpg").write_bytes(png_body)
    case = {
        "case_id": "mismatched-extension",
        "scenario": "minor_refund",
        "sample_dir": tmp_path,
    }

    _, paths, manifest = source_case(case)

    assert [path.name for path in paths] == ["021_legacy.jpg"]
    assert manifest[0]["neutral_name"] == "asset_001.png"
    assert manifest[0]["mime_type"] == "image/png"


def test_source_case_binds_trusted_product_composition_to_real_order_sku(tmp_path) -> None:
    (tmp_path / "001_received.jpg").write_bytes(b"\xff\xd8\xffreceived-item")
    (tmp_path / "content.txt").write_text("摆件里没有另一张柄图", encoding="utf-8")
    (tmp_path / "order_info_snapshot.json").write_text(
        '{"goods_list":[{"id":"1","number":"SKU-AXIS",'
        '"name":"纪念摆件 光轴摆件","goods_num":1}]}',
        encoding="utf-8",
    )
    case = {
        "case_id": "composition-resolution",
        "scenario": "missing_item",
        "sample_dir": tmp_path,
        "trusted_product_composition_resolution": {
            "claimed_item": "摆件内另一张柄图",
            "source": "product_master",
            "resolution_ref": "PRODUCT-COMPOSITION-CASE-1",
            "reason": "订单 SKU 本体就是光轴摆件，不包含另一件独立应发的柄图。",
            "required_received_skus": ["SKU-AXIS"],
        },
    }

    metadata, _, _ = source_case(case)

    baseline = metadata["fulfillment_baseline"]
    resolution = baseline["claim_expected_item_resolution"]
    assert resolution["baseline_version"] == baseline["baseline_version"]
    assert resolution["required_received_item_refs"] == ["ORDER-LINE-001"]
    assert resolution["is_expected"] is False


def test_source_case_rejects_product_composition_for_unknown_order_sku(tmp_path) -> None:
    (tmp_path / "001_received.jpg").write_bytes(b"\xff\xd8\xffreceived-item")
    (tmp_path / "order_info_snapshot.json").write_text(
        '{"goods_list":[{"id":"1","number":"SKU-REAL",'
        '"name":"纪念摆件 光轴摆件","goods_num":1}]}',
        encoding="utf-8",
    )
    case = {
        "case_id": "composition-resolution-invalid",
        "scenario": "missing_item",
        "sample_dir": tmp_path,
        "trusted_product_composition_resolution": {
            "claimed_item": "摆件内另一张柄图",
            "source": "product_master",
            "resolution_ref": "PRODUCT-COMPOSITION-CASE-2",
            "reason": "订单商品构成已核验。",
            "required_received_skus": ["SKU-NOT-IN-ORDER"],
        },
    }

    try:
        source_case(case)
    except RuntimeError as exc:
        assert "商品构成核验引用了订单中不存在的 SKU" in str(exc)
    else:
        raise AssertionError("未知 SKU 不得进入可信商品构成结论")


def test_wait_all_recovers_from_a_transient_poll_connection_reset() -> None:
    class Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {"job": {"job_id": "RJ-RESUME-1", "status": "SUCCEEDED"}}

    class Client:
        attempts = 0

        def get(self, *_args, **_kwargs):
            self.attempts += 1
            if self.attempts == 1:
                request = httpx.Request("GET", "http://127.0.0.1/jobs/RJ-RESUME-1")
                raise httpx.ReadError("connection reset", request=request)
            return Response()

    rows = [{"job_id": "RJ-RESUME-1", "case": {"case_id": "resume-case"}}]
    with patch("scripts.run_final_commercial_acceptance.time.sleep"), patch(
        "scripts.run_final_commercial_acceptance.store.get_job",
        return_value={"job_id": "RJ-RESUME-1", "status": "SUCCEEDED"},
    ):
        wait_all(Client(), "http://127.0.0.1:8000", "token", rows, timeout=5)

    assert rows[0]["job"]["status"] == "SUCCEEDED"
    assert rows[0]["internal_job"]["job_id"] == "RJ-RESUME-1"


def test_wait_all_recovers_from_a_transient_server_error() -> None:
    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.request = httpx.Request("GET", "http://127.0.0.1/jobs/RJ-RESUME-500")

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "temporary server error",
                    request=self.request,
                    response=httpx.Response(self.status_code, request=self.request),
                )

        @staticmethod
        def json() -> dict:
            return {"job": {"job_id": "RJ-RESUME-500", "status": "SUCCEEDED"}}

    class Client:
        attempts = 0

        def get(self, *_args, **_kwargs):
            self.attempts += 1
            return Response(500 if self.attempts == 1 else 200)

    rows = [{"job_id": "RJ-RESUME-500", "case": {"case_id": "resume-server-error"}}]
    with patch("scripts.run_final_commercial_acceptance.time.sleep"), patch(
        "scripts.run_final_commercial_acceptance.store.get_job",
        return_value={"job_id": "RJ-RESUME-500", "status": "SUCCEEDED"},
    ):
        wait_all(Client(), "http://127.0.0.1:8000", "token", rows, timeout=5)

    assert rows[0]["job"]["status"] == "SUCCEEDED"
    assert rows[0]["internal_job"]["job_id"] == "RJ-RESUME-500"


def test_final_gate_accepts_complete_current_contract_evidence() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]

    checks = build_blind_review_checks(rows)

    assert all(checks.values())


def test_final_gate_rejects_outer_success_when_technical_processing_is_incomplete() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    rows[0]["processing_status"] = "technical_processing_incomplete"
    rows[0]["system_action"] = "system_retry"

    assert build_blind_review_checks(rows)["all_jobs_succeeded"] is False


def test_final_gate_rejects_material_readiness_shell_without_required_fields() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    rows[0]["material_readiness"] = {
        "scenario": rows[0]["scenario"],
        "status": "complete",
        "checklist": [{"requirement_id": "evidence", "status": "present"}],
    }

    assert build_blind_review_checks(rows)["all_material_readiness_contracts_valid"] is False


def test_final_gate_rejects_old_generic_scene_shell_without_current_business_facts() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    rows[0].pop("scene_contract")

    assert build_blind_review_checks(rows)["all_current_business_contracts_valid"] is False


def test_final_gate_rejects_normal_damage_missing_opening_that_is_directly_negative() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    row = next(item for item in rows if item["scenario"] == "product_damage")
    row["predicted_label"] = "negative"
    row["material_readiness"]["status"] = "incomplete"
    row["material_readiness"]["checklist"][0]["status"] = "missing"
    row["scene_contract"]["opening_video_evidence"]["present"] = False
    row["scene_contract"]["opening_video_evidence"]["sop_compliant"] = False
    row["scene_contract"]["severe_alert_eligible"] = False

    assert build_blind_review_checks(rows)["all_current_business_contracts_valid"] is False


def test_final_gate_accepts_high_confidence_severe_structural_damage_without_opening() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    row = next(item for item in rows if item["scenario"] == "product_damage")
    row["predicted_label"] = "positive"
    row["material_readiness"]["status"] = "incomplete"
    row["material_readiness"]["checklist"][0]["status"] = "missing"
    row["scene_contract"].update({
        "opening_video_evidence": {},
        "damage_presence": "confirmed",
        "claim_support": "insufficient",
        "severity": {"level": "severe", "confidence": 0.91, "structural_failure": True},
        "severe_alert_eligible": True,
    })

    assert build_blind_review_checks(rows)["all_current_business_contracts_valid"] is True


def test_final_gate_rejects_under_ten_process_gap_that_is_silently_positive() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    row = next(item for item in rows if item["scenario"] == "minor_refund")
    row["predicted_label"] = "positive"
    row["scene_contract"]["payment_capability_risk"].update({
        "low_age": True,
        "under_nine": False,
        "process_evidence_status": "unresolved",
        "requires_more_material": False,
    })

    assert build_blind_review_checks(rows)["all_current_business_contracts_valid"] is False


def test_final_gate_accepts_image_or_warehouse_routes_without_forcing_video() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    for row in rows:
        if row["scenario"] in {"wrong_item", "missing_item", "minor_refund"}:
            row["evidence_preview"] = {"video": False, "image": True, "warehouse": False}

    assert build_blind_review_checks(rows)["all_current_business_contracts_valid"] is True


def test_final_gate_rejects_old_reports_and_missing_traceable_evidence() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    rows[0]["report_json"] = "tests/reports/review_0809_old.json"
    rows[1]["evidence_ref_count"] = 0

    checks = build_blind_review_checks(rows)

    assert checks["current_artifacts_only"] is False
    assert checks["all_required_facts_have_traceable_evidence"] is False


def test_final_gate_does_not_invent_evidence_when_wrong_item_has_no_adopted_fact() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    row = next(item for item in rows if item["scenario"] == "wrong_item")
    row["predicted_label"] = "review"
    row["material_readiness"]["status"] = "incomplete"
    row["evidence_ref_count"] = 0
    row["scene_contract"].update({
        "evidence_sufficiency": "insufficient",
        "observed_items_present": False,
        "identity_definition_fields_present": False,
        "same_package_evidence_present": False,
    })

    assert build_blind_review_checks(rows)["all_required_facts_have_traceable_evidence"] is True


def test_final_gate_rejects_gemini36_as_default_profile() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    rows[0]["model_profile"] = "baidu-gemini-3.6-flash-high-high-native-fps1"

    assert build_blind_review_checks(rows)["default_model_profile_consistent"] is False


def test_final_gate_rejects_unproven_high_high_or_max_output_override() -> None:
    rows = [_row(scenario, index) for scenario in sorted(SCENARIOS) for index in (1, 2)]
    rows[0]["model_profile"] = "baidu-gemini-3.5-flash-lite-unknown-unknown-native-fps1"
    rows[1]["model_profile"] = "baidu-gemini-3.5-flash-lite-high-high-native-fps1-max65536"

    assert build_blind_review_checks(rows)["default_model_profile_consistent"] is False


def test_product_damage_scene_facts_use_nested_damage_assessment_contract() -> None:
    assessment = {
        "predicted_label": "positive",
        "opening_video_evidence": {"present": True, "sop_compliant": True},
        "damage_observability": {"status": "confirmed"},
        "damage_causality_assessment": {
            "damage_presence": "confirmed",
            "damage_timing": "pre_opening_visible",
            "claim_support": "supported",
            "business_defect_qualification": {"status": "confirmed"},
            "severity_assessment": {
                "level": "moderate",
                "confidence": 0.9,
                "structural_failure": False,
            },
        },
    }

    assert _scene_facts_present("product_damage", assessment) is True


def test_model_profile_uses_executed_native_fps_but_rejects_frame_fallback() -> None:
    review = {
        "agent_report": {
            "inference_estimate": {
                "request_profile": {
                    "provider": "gemini_native",
                    "model": "gemini-3.5-flash-lite",
                    "thinking_level": "high",
                    "media_resolution": "high",
                    "max_output_tokens": "provider_default",
                    "native_video_count": 1,
                    "sampling_fps": None,
                }
            }
        },
        "media_preflight_execution": {
            "video": {
                "native_review_status": "completed",
                "native_sampling_fps": 1.0,
            },
            "frame_fallback": {"used": False},
        },
    }

    assert _model_profile(review) == DEFAULT_MODEL_PROFILE
    review["media_preflight_execution"]["frame_fallback"]["used"] = True
    assert _model_profile(review) != DEFAULT_MODEL_PROFILE
