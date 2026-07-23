# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

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
