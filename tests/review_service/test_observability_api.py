# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException


class ObservabilityApiTest(unittest.TestCase):
    def test_job_events_is_tenant_scoped_and_returns_redacted_events(self):
        from review_service import router

        async def run():
            with patch.object(router.store, "get_job", return_value={"job_id": "JOB-A", "tenant_id": "tenant-a"}), patch.object(
                router.observability_store,
                "list_events",
                return_value=[{"id": 1, "event": "visual_model_http_success", "visibility": "redacted", "data": {"request_target": "model_gateway"}}],
            ) as listed:
                response = await router.job_events(
                    "JOB-A",
                    detail="redacted",
                    limit=100,
                    since_id=0,
                    user={"tenant_id": "tenant-a", "role": "supervisor"},
                )
            listed.assert_called_once_with("tenant-a", job_id="JOB-A", visibility="redacted", limit=100, since_id=0)
            return response

        response = asyncio.run(run())
        self.assertEqual(response["visibility"], "redacted")
        self.assertEqual(response["events"][0]["data"]["request_target"], "model_gateway")

    def test_internal_events_are_super_admin_only(self):
        from review_service import router

        async def run():
            with patch.object(router.store, "get_job", return_value={"job_id": "JOB-A", "tenant_id": "tenant-a"}):
                with self.assertRaises(HTTPException) as error:
                    await router.job_events(
                        "JOB-A",
                        detail="internal",
                        limit=100,
                        since_id=0,
                        user={"tenant_id": "tenant-a", "role": "supervisor"},
                    )
            return error.exception

        self.assertEqual(asyncio.run(run()).status_code, 403)

    def test_public_job_exposes_only_redacted_observability_summary_and_url(self):
        from review_service import service

        job = {
            "job_id": "JOB-A",
            "tenant_id": "tenant-a",
            "client_case_id": "CASE-A",
            "scenario": "product_damage",
            "status": "SUCCEEDED",
            "assets": [],
            "result": {},
        }
        with patch.object(service.observability_store, "summarize_events", return_value={"event_count": 2, "visibility": "redacted"}):
            public = service.public_job(job)

        self.assertEqual(public["result"]["observability"]["event_count"], 2)
        self.assertIn("/api/v1/review/jobs/JOB-A/events", public["result"]["observability"]["events_url"])


if __name__ == "__main__":
    unittest.main()
