# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from poc.visual_review_poc import workbench_server
from poc.visual_review_poc.minor_material_pipeline import aggregate_minor_material_results
from review_service import router, service, store
from review_service.advisory_assessment import attach_advisory_assessment
from review_service.schemas import ReviewCaseMetadata
from scripts.check_dynamic_material_capacity_http import capacity_checks_from_public_job, release_gate_result
from scripts.check_review_service_batch import public_submission_evidence


PNG_BODY = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _upload(index: int) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(PNG_BODY),
        filename=f"material_{index:03d}.png",
        headers=Headers({"content-type": "image/png"}),
    )


def _case(image_count: int) -> dict:
    return {
        "case_id": "capacity-incomplete",
        "scenario": "minor_material",
        "structured_business_context": {
            "business_scenario": "minor_refund",
            "frontdesk_evidence_package": {
                "asset_manifest": {
                    "assets": [{"mime_type": "image/png"} for _ in range(image_count)]
                }
            },
        },
        "supplemental_images": [
            {"image_index": index, "api_path": __file__, "api_mime_type": "image/png"}
            for index in range(1, image_count + 1)
        ],
        "frames": [],
        "videos": [],
    }


def _observation(index: int) -> dict:
    return {
        "image_index": index,
        "asset_ref": f"supplemental_image_{index}",
        "document_types": ["other"],
        "subject_role": "not_applicable",
        "document_side": "page",
        "readability": "clear",
        "quality_issues": [],
    }


class DynamicAssetCapacityTest(unittest.IsolatedAsyncioTestCase):
    def test_live_batch_evidence_uses_public_case_and_asset_fields(self) -> None:
        evidence = public_submission_evidence(
            {
                "client_case_id": "CASE-PUBLIC-BATCH",
                "assets": [
                    {"asset_id": "A-1", "mime_type": "image/png", "size": 7},
                    {"asset_id": "A-2", "mime_type": "video/mp4", "size": 11},
                ],
            },
            {"client_case_id": "CASE-PUBLIC-BATCH", "file_count": 2, "bytes": 18},
        )

        self.assertEqual(evidence, {"source_case_preserved": True, "submitted_assets_preserved": True})

    def test_capacity_evidence_uses_public_counts_without_private_ingestion_metadata(self) -> None:
        checks = capacity_checks_from_public_job(
            {"status": "SUCCEEDED", "assets": [{} for _ in range(62)]},
            {
                "accepted_image_count": 62,
                "processed_image_count": 62,
                "coverage_complete": True,
            },
            62,
        )

        self.assertTrue(checks["expanded_capacity"])
        self.assertTrue(release_gate_result(checks, {})["release_gate_ok"])

    def test_release_gate_accepts_only_complete_processing_or_explicit_system_retry(self) -> None:
        capacity_checks = {
            "all_assets_saved": True,
            "expanded_capacity": True,
            "all_images_accepted": True,
            "job_succeeded": False,
            "all_images_processed": False,
            "coverage_complete": False,
        }
        safe_failure = release_gate_result(
            capacity_checks,
            {"processing_status": "technical_processing_incomplete", "system_action": "system_retry"},
        )
        unsafe_failure = release_gate_result(capacity_checks, {"processing_status": "completed"})

        self.assertTrue(safe_failure["release_gate_ok"])
        self.assertTrue(safe_failure["safe_external_failure"])
        self.assertFalse(safe_failure["model_processing_ok"])
        self.assertFalse(unsafe_failure["release_gate_ok"])

    async def test_sixty_two_assets_within_safe_limit_are_accepted_by_both_entries(self) -> None:
        metadata = ReviewCaseMetadata(client_case_id="CASE-62", scenario="minor_refund")
        with tempfile.TemporaryDirectory() as formal_dir, tempfile.TemporaryDirectory() as workbench_dir:
            with (
                patch.dict(os.environ, {"REVIEW_MAX_ASSETS": "80"}),
                patch.object(service, "upload_root", return_value=Path(formal_dir)),
            ):
                formal_assets = await service._save_uploads(
                    "RJ-CAPACITY-62",
                    metadata,
                    [_upload(index) for index in range(1, 63)],
                )
            with (
                patch.object(workbench_server, "MAX_FOLDER_FILES", 80),
                patch.object(workbench_server, "UPLOAD_DIR", Path(workbench_dir)),
            ):
                _, workbench_summary = workbench_server._save_folder_uploads(
                    [_upload(index) for index in range(1, 63)]
                )

        self.assertEqual(len(formal_assets), 62)
        self.assertEqual(workbench_summary["received_count"], 62)
        self.assertEqual(workbench_summary["accepted_count"], 62)
        self.assertEqual(workbench_summary["image_count"], 62)

    def test_incomplete_processing_is_system_retry_not_customer_material_gap(self) -> None:
        case = _case(62)
        rows = [
            (
                list(range(start, min(start + 4, 41))),
                {
                    "parsed": {
                        "material_observations": [
                            _observation(index) for index in range(start, min(start + 4, 41))
                        ]
                    }
                },
            )
            for start in range(1, 41, 4)
        ]
        parsed = aggregate_minor_material_results(case, rows, [], [], [])
        output = {
            "summary": {
                "predicted_label": parsed["predicted_label"],
                "confidence": parsed["confidence"],
            },
            "agent_brief": {"conclusion": parsed["overall_audit"]["conclusion"]},
            "agent_report": {"parsed": parsed},
        }
        assessed = attach_advisory_assessment(
            output,
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )
        advisory = assessed["advisory_assessment"]

        checks = {
            "技术处理状态": (parsed.get("processing_status"), "technical_processing_incomplete"),
            "系统动作": (parsed.get("system_action"), "system_retry"),
            "不得伪装成用户缺件": (parsed.get("material_gaps"), []),
            "工作流进入系统重试": (advisory["workflow_recommendation"], "system_retry"),
        }
        for name, (actual, expected) in checks.items():
            with self.subTest(contract=name):
                self.assertEqual(actual, expected)
        with self.subTest(contract="人工路由说明技术失败"):
            self.assertIn(
                "technical_processing_incomplete",
                advisory["human_review"]["reason_codes"],
            )
        with self.subTest(contract="不得生成用户材料缺口信号"):
            self.assertNotIn("material_gap", [item["code"] for item in advisory["signals"]])
        escalation = service._recommended_escalation(
            {"metadata": {"sampling_policy": {"preset": "adaptive"}}},
            assessed,
            {"summary": {}},
        )
        self.assertEqual(escalation["actions"][0]["type"], "retry_review_case")
        self.assertTrue(escalation["actions"][0]["full_case_retry"])
        self.assertTrue(escalation["actions"][0]["may_repeat_model_cost"])

    async def test_over_limit_errors_are_consistent_machine_readable_and_include_counts(self) -> None:
        metadata = ReviewCaseMetadata(client_case_id="CASE-81", scenario="minor_refund")
        with patch.dict(os.environ, {"REVIEW_MAX_ASSETS": "80"}):
            with self.assertRaises(ValueError) as formal_error:
                await service._save_uploads(
                    "RJ-CAPACITY-81",
                    metadata,
                    [_upload(index) for index in range(1, 82)],
                )

        with patch.object(workbench_server, "MAX_FOLDER_FILES", 80):
            with self.assertRaises(HTTPException) as workbench_error:
                workbench_server._save_folder_uploads([_upload(index) for index in range(1, 82)])

        formal_payload = str(formal_error.exception)
        workbench_payload = json.dumps(workbench_error.exception.detail, ensure_ascii=False)
        for source, payload in (("formal_api", formal_payload), ("workbench", workbench_payload)):
            with self.subTest(source=source, field="error_code"):
                self.assertIn("too_many_review_assets", payload)
            with self.subTest(source=source, field="received_count"):
                self.assertIn("81", payload)
            with self.subTest(source=source, field="safe_limit"):
                self.assertIn("80", payload)

        self.assertEqual(
            router._structured_error_detail(formal_payload),
            workbench_error.exception.detail,
        )

    def test_system_retry_success_can_retry_but_normal_success_cannot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            store, "DB_PATH", Path(temp_dir) / "review.sqlite3"
        ):
            base = {
                "tenant_id": "mitako",
                "client_case_id": "CASE-RETRY",
                "idempotency_key": "",
                "scenario": "minor_refund",
                "metadata": {},
                "assets": [],
            }
            retry_job = store.create_job({**base, "job_id": "RJ-SYSTEM-RETRY"}, "hash-a")
            store.finish_job(
                retry_job["job_id"],
                status="SUCCEEDED",
                result={"review": {"advisory_assessment": {"workflow_recommendation": "system_retry"}}},
                diagnostics={},
            )
            normal_job = store.create_job({**base, "job_id": "RJ-NORMAL"}, "hash-b")
            store.finish_job(
                normal_job["job_id"],
                status="SUCCEEDED",
                result={"review": {"advisory_assessment": {"workflow_recommendation": "continue_by_customer_policy"}}},
                diagnostics={},
            )

            retried = store.queue_retry(retry_job["job_id"])
            rejected = store.queue_retry(normal_job["job_id"])

        self.assertEqual(retried["status"], "RETRYING")
        self.assertIsNone(rejected)

    def test_zero_token_native_technical_failure_can_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            store, "DB_PATH", Path(temp_dir) / "review.sqlite3"
        ):
            job = store.create_job({
                "job_id": "RJ-NATIVE-TECHNICAL-RETRY",
                "tenant_id": "mitako",
                "client_case_id": "CASE-NATIVE-TECHNICAL-RETRY",
                "idempotency_key": "",
                "scenario": "product_damage",
                "metadata": {},
                "assets": [],
            }, "hash-native-technical-retry")
            store.finish_job(
                job["job_id"],
                status="SUCCEEDED",
                result={
                    "review": {
                        "advisory_assessment": {
                            "workflow_recommendation": "human_review",
                        },
                        "agent_report": {
                            "inference_estimate": {
                                "total_tokens": 0,
                                "native_video": {
                                    "technical_status": "failed",
                                    "status_code": 400,
                                },
                            }
                        },
                    }
                },
                diagnostics={},
            )

            retried = store.queue_retry(job["job_id"])

        self.assertEqual(retried["status"], "RETRYING")

    def test_stale_worker_cannot_overwrite_newer_review_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            store, "DB_PATH", Path(temp_dir) / "review.sqlite3"
        ):
            job = store.create_job(
                {
                    "job_id": "RJ-FENCING",
                    "tenant_id": "mitako",
                    "client_case_id": "CASE-FENCING",
                    "idempotency_key": "",
                    "scenario": "product_damage",
                    "metadata": {},
                    "assets": [],
                },
                "hash-fencing",
            )
            self.assertTrue(store.claim_job(job["job_id"], 60))
            stale_attempt = int((store.get_job(job["job_id"]) or {})["attempts"])
            first_request_id = str((store.get_job(job["job_id"]) or {})["workbench_request_id"])
            with store._connect() as conn:
                conn.execute(
                    "UPDATE review_jobs SET lease_until=0 WHERE job_id=?",
                    (job["job_id"],),
                )
            self.assertIn(job["job_id"], store.recover_incomplete())
            self.assertTrue(store.claim_job(job["job_id"], 60))
            current_attempt = int((store.get_job(job["job_id"]) or {})["attempts"])
            recovered_request_id = str((store.get_job(job["job_id"]) or {})["workbench_request_id"])

            stale_result = store.finish_job(
                job["job_id"],
                status="SUCCEEDED",
                result={"worker": "stale"},
                diagnostics={},
                expected_attempts=stale_attempt,
            )
            accepted_result = store.finish_job(
                job["job_id"],
                status="SUCCEEDED",
                result={"worker": "current"},
                diagnostics={},
                expected_attempts=current_attempt,
            )

        self.assertEqual(stale_result["status"], "RUNNING")
        self.assertEqual(accepted_result["result"], {"worker": "current"})
        self.assertEqual(first_request_id, "RJ-FENCING-workbench-1")
        self.assertEqual(recovered_request_id, first_request_id)

    def test_queue_snapshot_includes_failed_model_usage_for_the_same_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            store, "DB_PATH", Path(temp_dir) / "review.sqlite3"
        ):
            def finish(job_id: str, tenant_id: str, status: str, tokens: int, usd: float) -> None:
                store.create_job(
                    {
                        "job_id": job_id,
                        "tenant_id": tenant_id,
                        "client_case_id": job_id,
                        "idempotency_key": "",
                        "scenario": "product_damage",
                        "metadata": {},
                        "assets": [],
                    },
                    f"hash-{job_id}",
                )
                store.finish_job(
                    job_id,
                    status=status,
                    result={
                        "review": {
                            "agent_report": {
                                "inference_estimate": {
                                    "total_tokens": tokens,
                                    "estimated_usd": usd,
                                }
                            }
                        }
                    },
                    diagnostics={},
                )

            finish("RJ-METRIC-OK", "mitako", "SUCCEEDED", 100, 0.10)
            finish("RJ-METRIC-FAILED", "mitako", "FAILED", 25, 0.02)
            finish("RJ-METRIC-OTHER", "other-tenant", "FAILED", 900, 9.0)
            snapshot = store.snapshot("mitako")

        self.assertEqual(snapshot["inference_total_tokens"], 125)
        self.assertEqual(snapshot["inference_estimated_usd"], 0.12)

    def test_business_retry_preserves_prior_attempt_usage_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            store, "DB_PATH", Path(temp_dir) / "review.sqlite3"
        ):
            job = store.create_job(
                {
                    "job_id": "RJ-RETRY-USAGE",
                    "tenant_id": "mitako",
                    "client_case_id": "CASE-RETRY-USAGE",
                    "idempotency_key": "",
                    "scenario": "product_damage",
                    "metadata": {"batch_id": "BATCH-RETRY-USAGE"},
                    "assets": [],
                },
                "hash-retry-usage",
            )
            store.finish_job(
                job["job_id"],
                status="FAILED",
                result={
                    "review": {
                        "agent_report": {
                            "inference_estimate": {
                                "total_tokens": 25,
                                "estimated_usd": 0.02,
                            }
                        }
                    }
                },
                diagnostics={},
            )

            self.assertIsNotNone(store.queue_retry(job["job_id"]))
            queued_snapshot = store.snapshot("mitako")
            self.assertEqual(queued_snapshot["inference_total_tokens"], 25)
            self.assertEqual(queued_snapshot["inference_estimated_usd"], 0.02)
            self.assertTrue(store.claim_job(job["job_id"], 60))
            current_attempt = int((store.get_job(job["job_id"]) or {})["attempts"])
            store.finish_job(
                job["job_id"],
                status="SUCCEEDED",
                result={
                    "review": {
                        "agent_report": {
                            "inference_estimate": {
                                "total_tokens": 100,
                                "estimated_usd": 0.10,
                            }
                        }
                    }
                },
                diagnostics={},
                expected_attempts=current_attempt,
            )

            snapshot = store.snapshot("mitako")
            batch = store.batch_snapshot("mitako", "BATCH-RETRY-USAGE")

        self.assertEqual(snapshot["inference_total_tokens"], 125)
        self.assertEqual(snapshot["inference_estimated_usd"], 0.12)
        self.assertEqual(batch[0]["total_tokens"], 125)
        self.assertAlmostEqual(batch[0]["estimated_usd"], 0.12)

    def test_retry_and_lease_recovery_preserve_attempt_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            store, "DB_PATH", Path(temp_dir) / "review.sqlite3"
        ):
            job = store.create_job(
                {
                    "job_id": "RJ-ATTEMPT-HISTORY",
                    "tenant_id": "mitako",
                    "client_case_id": "CASE-ATTEMPT-HISTORY",
                    "idempotency_key": "",
                    "scenario": "product_damage",
                    "metadata": {},
                    "assets": [],
                },
                "hash-attempt-history",
            )
            self.assertTrue(store.claim_job(job["job_id"], 60))
            first_attempt = int((store.get_job(job["job_id"]) or {})["attempts"])
            store.finish_job(
                job["job_id"],
                status="FAILED",
                result={"review": {"agent_report": {"inference_estimate": {"total_tokens": 7}}}},
                diagnostics={"error_type": "workbench_http_error", "status_code": 503},
                expected_attempts=first_attempt,
            )
            self.assertIsNotNone(store.queue_retry(job["job_id"]))
            self.assertTrue(store.claim_job(job["job_id"], 60))
            with store._connect() as conn:
                conn.execute(
                    "UPDATE review_jobs SET lease_until=0 WHERE job_id=?",
                    (job["job_id"],),
                )
            self.assertIn(job["job_id"], store.recover_incomplete())

            history = store.list_attempts(job["job_id"])

        self.assertEqual([item["status"] for item in history], ["FAILED", "LEASE_EXPIRED"])
        self.assertEqual(history[0]["diagnostics"]["status_code"], 503)
        self.assertEqual(history[1]["diagnostics"]["error_type"], "lease_expired")
        self.assertEqual(history[0]["attempt"], 1)
        self.assertEqual(history[1]["attempt"], 2)

    def test_technical_retry_stops_after_three_execution_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            store, "DB_PATH", Path(temp_dir) / "review.sqlite3"
        ):
            job = store.create_job(
                {
                    "job_id": "RJ-RETRY-LIMIT",
                    "tenant_id": "mitako",
                    "client_case_id": "CASE-RETRY-LIMIT",
                    "idempotency_key": "",
                    "scenario": "product_damage",
                    "metadata": {},
                    "assets": [],
                },
                "hash-retry-limit",
            )
            for expected_attempt in range(1, 4):
                self.assertTrue(store.claim_job(job["job_id"], 60))
                current = store.get_job(job["job_id"]) or {}
                self.assertEqual(current["attempts"], expected_attempt)
                store.finish_job(
                    job["job_id"],
                    status="FAILED",
                    result={},
                    diagnostics={"error_type": "temporary_failure"},
                    expected_attempts=expected_attempt,
                )
                retry = store.queue_retry(job["job_id"])
                if expected_attempt < 3:
                    self.assertIsNotNone(retry)
                else:
                    self.assertIsNone(retry)


if __name__ == "__main__":
    unittest.main()
