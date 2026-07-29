# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.routing import APIRoute

from poc.visual_review_poc import workbench_server
from review_service import router, service


def successful_workbench_review() -> dict:
    return {
        "ok": True,
        "source_status": "folder_ready",
        "review": {
            "review_label": "商品有伤审核",
            "summary": {"predicted_label": "positive", "confidence": 0.91, "review_status": "completed"},
            "agent_brief": {"conclusion": "当前证据支持商品存在可见损伤。"},
            "agent_report": {
                "parsed": {
                    "predicted_label": "positive",
                    "confidence": 0.91,
                    "overall_audit": {"conclusion": "当前证据支持商品存在可见损伤。"},
                }
            },
        },
    }


class ReportOutputOptionsTest(unittest.TestCase):
    def test_job_json_rewrites_media_to_authenticated_job_route(self):
        media_id = "d" * 32
        job = {
            "job_id": "RJ-JSON-MEDIA",
            "result": {"review": {"agent_report": {"media_gallery": {
                "frames": [{"url": f"/media-item/{media_id}?expires=99&sig=old"}],
            }}}},
        }

        public = service.public_job(job)

        self.assertEqual(
            public["result"]["review"]["agent_report"]["media_gallery"]["frames"][0]["url"],
            f"/api/v1/review/jobs/{job['job_id']}/media/{media_id}",
        )

    def test_batch_json_rewrites_media_to_authenticated_job_route(self):
        media_id = "e" * 32
        job = {
            "job_id": "RJ-BATCH-MEDIA",
            "status": "SUCCEEDED",
            "result": {"review": {"agent_report": {"media_gallery": {
                "frames": [{"url": f"/media-item/{media_id}"}],
            }}}},
        }
        with patch.object(service.store, "list_batch", return_value=[job]), patch.object(
            service.store,
            "batch_snapshot",
            return_value=[{"status": "SUCCEEDED", "count": 1, "total_tokens": 0, "estimated_usd": 0}],
        ):
            result = service.batch_status("mitako", "BATCH-1")

        self.assertEqual(
            result["jobs"][0]["result"]["review"]["agent_report"]["media_gallery"]["frames"][0]["url"],
            f"/api/v1/review/jobs/{job['job_id']}/media/{media_id}",
        )

    def test_media_route_openapi_declares_binary_content_not_json(self):
        route = next(
            item for item in router.router.routes
            if isinstance(item, APIRoute) and item.path == "/api/v1/review/jobs/{job_id}/media/{media_id}"
        )
        responses = route.responses[200]["content"]

        self.assertIn("image/jpeg", responses)
        self.assertIn("video/mp4", responses)
        self.assertIn("application/octet-stream", responses)
        self.assertNotIn("application/json", responses)
        for definition in responses.values():
            self.assertEqual(definition["schema"], {"type": "string", "format": "binary"})
        self.assertEqual(route.responses[206]["content"], responses)

    def test_formal_report_uses_job_scoped_media_urls_instead_of_internal_workbench_host(self):
        media_id = "a" * 32
        job = {
            "job_id": "RV-MEDIA-PROXY",
            "tenant_id": "mitako",
            "status": "SUCCEEDED",
            "completed_at": 1,
            "metadata": {"output_options": {"include_html_report": True}},
            "result": {"review": {
                "summary": {"review_status": "completed"},
                "agent_report": {
                    "scenario": "product_damage",
                    "scenario_label": "商品有伤审核",
                    "parsed": {"predicted_label": "review"},
                    "media_gallery": {
                        "frames": [{
                            "url": f"http://127.0.0.1:7861/media-item/{media_id}?expires=99&sig=old",
                            "timestamp": "00:01.00",
                        }],
                    },
                },
            }},
        }

        html = service.render_job_report(job)

        self.assertIn(f"/api/v1/review/jobs/{job['job_id']}/media/{media_id}", html)
        self.assertNotIn("127.0.0.1:7861", html)

    def test_job_media_resolution_is_limited_to_media_referenced_by_that_job(self):
        media_id = "b" * 32
        job = {
            "result": {"review": {"agent_report": {"media_gallery": {
                "frames": [{"url": f"/media-item/{media_id}?expires=99&sig=old"}],
            }}}},
        }

        with patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "shared-secret"}):
            resolved = service.resolve_job_media_url(job, media_id)

        self.assertTrue(resolved.startswith("http://127.0.0.1:"))
        self.assertIn(f"/media-item/{media_id}", resolved)
        with self.assertRaises(ValueError):
            service.resolve_job_media_url(job, "c" * 32)

    def test_report_explains_internal_processing_retry_without_asking_customer_for_material(self):
        job = {
            "job_id": "RV-SYSTEM-RETRY",
            "status": "SUCCEEDED",
            "completed_at": 1,
            "result": {"review": {
                "summary": {"review_status": "completed"},
                "agent_report": {"scenario_label": "未成年人资料审核", "parsed": {}},
                "advisory_assessment": {
                    "workflow_recommendation": "system_retry",
                    "assessment": {"conclusion": "本轮技术处理未完成"},
                    "human_review": {"level": "not_required"},
                    "signals": [{
                        "code": "technical_processing_incomplete",
                        "effect": "当前请求已完成逐张恢复；仍未覆盖时可受控重跑整案，可能重复模型成本。",
                    }],
                },
            }},
        }

        html = service.render_job_report(job)

        self.assertIn("受控重跑整案", html)
        self.assertIn("可能重复模型成本", html)
        self.assertIn("技术处理未完成", html)

    def test_workbench_json_only_does_not_write_html_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_dir = root / "case"
            sample_dir.mkdir()
            case = {
                "case_id": "CASE-JSON-ONLY",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
                "structured_business_context": {
                    "business_scenario": "product_damage",
                    "review_routing_policy": {"out_of_frame_resubmit_seconds": 3.0},
                },
            }
            result = {
                "status": "success",
                "parsed": {
                    "predicted_label": "positive",
                    "confidence": 0.91,
                    "overall_audit": {"conclusion": "当前证据支持商品存在可见损伤。"},
                },
            }
            with patch.object(workbench_server, "PUBLIC_SUMMARY_DIR", root / "summaries"), patch.object(
                workbench_server, "score_result", return_value={}
            ):
                before = set(workbench_server.ALLOWED_REPORTS)
                response = workbench_server._agent_report_response(
                    case,
                    sample_dir,
                    result,
                    "json_only",
                    include_html_report=False,
                )

            self.assertEqual(response["report"]["status"], "not_requested")
            self.assertIsNone(response["report"]["html_url"])
            self.assertEqual(set(workbench_server.ALLOWED_REPORTS), before)
            self.assertFalse((root / "summaries").exists())
            self.assertEqual(response["advisory_assessment"]["human_review"]["level"], "not_required")

    def test_formal_job_json_only_keeps_structured_result_without_report_url(self):
        job = {
            "job_id": "RV-JSON-ONLY",
            "tenant_id": "mitako",
            "client_case_id": "CASE-JSON-ONLY",
            "scenario": "product_damage",
            "metadata": {
                "scenario": "product_damage",
                "output_options": {"include_html_report": False},
                "review_routing_policy": {},
            },
            "assets": [],
        }

        def finish(job_id, *, status, result, diagnostics):
            return {**job, "status": status, "result": result, "diagnostics": diagnostics}

        with patch.object(service.store, "claim_job", return_value=True), patch.object(
            service.store, "get_job", return_value=job
        ), patch.object(service.store, "finish_job", side_effect=finish), patch.object(
            service, "_media_forensics", return_value={"summary": {"risk_signal_count": 0}}
        ), patch.object(
            service, "assess_input_readiness", return_value={"full_review_ready": True, "missing_required": []}
        ), patch.object(service, "_call_workbench", return_value=successful_workbench_review()):
            completed = service.run_job(job["job_id"])

        review = completed["result"]["review"]
        self.assertEqual(review["report"]["status"], "not_requested")
        self.assertIsNone(review["report"]["html_url"])
        self.assertEqual(review["advisory_assessment"]["human_review"]["level"], "not_required")

    def test_report_route_rejects_job_that_did_not_request_html(self):
        job = {
            "job_id": "RV-JSON-ONLY",
            "tenant_id": "mitako",
            "status": "SUCCEEDED",
            "metadata": {"output_options": {"include_html_report": False}},
            "result": {},
        }
        with patch.object(router.store, "get_job", return_value=job):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(router.job_report(job["job_id"], user={"tenant_id": "mitako"}))

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "review_report_not_requested")

    def test_report_route_rejects_job_that_is_not_ready(self):
        job = {
            "job_id": "RV-PENDING",
            "tenant_id": "mitako",
            "status": "RUNNING",
            "metadata": {"output_options": {"include_html_report": True}},
            "result": {},
        }
        with patch.object(router.store, "get_job", return_value=job):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(router.job_report(job["job_id"], user={"tenant_id": "mitako"}))

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "review_report_not_ready")

    def test_formal_job_failure_still_returns_primary_advisory_contract(self):
        job = {
            "job_id": "RV-FAILED-CONTRACT",
            "tenant_id": "mitako",
            "client_case_id": "CASE-FAILED-CONTRACT",
            "scenario": "product_damage",
            "metadata": {
                "scenario": "product_damage",
                "output_options": {"include_html_report": True},
            },
            "assets": [],
        }

        def finish(job_id, *, status, result, diagnostics):
            return {**job, "status": status, "result": result, "diagnostics": diagnostics}

        with patch.object(service.store, "claim_job", return_value=True), patch.object(
            service.store, "get_job", return_value=job
        ), patch.object(service.store, "finish_job", side_effect=finish), patch.object(
            service, "_media_forensics", return_value={"summary": {"risk_signal_count": 0}}
        ), patch.object(service, "_call_workbench", side_effect=RuntimeError("upstream unavailable")):
            completed = service.run_job(job["job_id"])

        review = completed["result"]["review"]
        self.assertEqual(review["advisory_assessment"]["human_review"]["level"], "required")
        self.assertEqual(review["advisory_assessment"]["workflow_recommendation"], "human_review")
        self.assertEqual(review["report"]["status"], "unavailable")
        self.assertIsNone(review["report"]["html_url"])


if __name__ == "__main__":
    unittest.main()
