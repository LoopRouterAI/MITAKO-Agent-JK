# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import io
import logging
import time
import unittest
from unittest.mock import patch


class VisualObservabilityTest(unittest.TestCase):
    def test_expired_case_deadline_blocks_http_attempt(self):
        from poc.visual_review_poc import model_selection_e2e

        with patch.object(model_selection_e2e.httpx, "Client") as client:
            result = model_selection_e2e.post_with_retries(
                "https://example.com/v1/models/demo:generateContent",
                {},
                {},
                timeout=180,
                retries=2,
                deadline_at=time.monotonic() - 1,
            )

        client.assert_not_called()
        self.assertEqual(result["error_type"], "deadline")
        self.assertEqual(result["attempt"], 0)

    def test_event_is_written_to_stderr_even_when_logger_filters_info(self):
        from poc.visual_review_poc.observability import log_visual_event

        stream = io.StringIO()
        logger = logging.getLogger("test.filtered.visual")
        logger.setLevel(logging.CRITICAL)
        with patch("sys.stderr", stream):
            log_visual_event(
                logger,
                "visual_model_http_success",
                endpoint="https://vod.bj.baidubce.com/v3/chat/gc",
                status_code=200,
                headers={"Authorization": "Bearer secret-value"},
            )

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["event"], "visual_model_http_success")
        self.assertEqual(payload["status_code"], 200)
        self.assertNotIn("secret-value", stream.getvalue())

    def test_event_payload_exposes_endpoint_shape_without_credentials(self):
        from poc.visual_review_poc.observability import visual_event_payload

        with patch.dict("os.environ", {"MITAKO_VISUAL_LOG_MODE": "internal"}, clear=False):
            payload = visual_event_payload(
                "visual_model_http_attempt",
                endpoint="https://vod.bj.baidubce.com/v3/chat/gc",
                model="gemini-3.5-flash",
                headers={"Authorization": "Bearer secret-value"},
                prompt="internal prompt",
            )
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["event"], "visual_model_http_attempt")
        self.assertEqual(payload["endpoint_host"], "vod.bj.baidubce.com")
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("internal prompt", serialized)
        self.assertNotIn("headers", payload)
        self.assertNotIn("prompt", payload)

    def test_default_event_payload_is_redacted(self):
        from poc.visual_review_poc.observability import visual_event_payload

        with patch.dict("os.environ", {"MITAKO_VISUAL_LOG_MODE": "redacted"}, clear=False):
            payload = visual_event_payload(
                "visual_model_http_attempt",
                endpoint="https://vod.bj.baidubce.com/v3/chat/gc",
                model="gemini-3.5-flash",
                channel="baidu",
            )

        self.assertEqual(payload["visibility"], "redacted")
        self.assertEqual(payload["request_target"], "model_gateway")
        self.assertNotIn("endpoint_host", payload)
        self.assertNotIn("endpoint_vendor_hint", payload)
        self.assertNotIn("model", payload)
        self.assertNotIn("channel", payload)

    def test_event_persists_and_context_is_replayed(self):
        from observability_store import list_events
        from poc.visual_review_poc.observability import log_visual_event, visual_event_context

        with patch.dict("os.environ", {"MITAKO_OBSERVABILITY_DB": str(self._tmp_db())}, clear=False):
            with visual_event_context(tenant_id="tenant-a", job_id="JOB-A", request_id="REQ-A"):
                log_visual_event(logging.getLogger("test.persist"), "visual_review_subprocess_finished", status="ok")
            events = list_events("tenant-a", job_id="JOB-A")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["request_id"], "REQ-A")
        self.assertEqual(events[0]["data"]["status"], "ok")

    def test_internal_mode_keeps_both_internal_and_redacted_views(self):
        from observability_store import list_events
        from poc.visual_review_poc.observability import log_visual_event

        with patch.dict(
            "os.environ",
            {"MITAKO_OBSERVABILITY_DB": str(self._tmp_db()), "MITAKO_VISUAL_LOG_MODE": "internal"},
            clear=False,
        ):
            log_visual_event(
                logging.getLogger("test.internal.persist"),
                "visual_model_http_success",
                endpoint="https://vod.bj.baidubce.com/v3/chat/gc",
                model="gemini-3.5-flash-lite",
            )
            redacted = list_events("", visibility="redacted")
            internal = list_events("", visibility="internal")

        self.assertEqual(len(redacted), 1)
        self.assertEqual(len(internal), 1)
        self.assertNotIn("endpoint_host", redacted[0]["data"])
        self.assertEqual(internal[0]["data"]["endpoint_vendor_hint"], "baidu")

    @staticmethod
    def _tmp_db():
        import tempfile
        import time

        return str(__import__("pathlib").Path(tempfile.gettempdir()) / f"mitako-observability-test-{time.time_ns()}.db")

    def test_http_retry_path_emits_sanitized_attempt_event(self):
        from poc.visual_review_poc import model_selection_e2e

        class Response:
            status_code = 200
            text = ""
            headers = {}

            @staticmethod
            def json():
                return {"ok": True}

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def post(*args, **kwargs):
                return Response()

        events = []
        with patch.object(model_selection_e2e.httpx, "Client", Client), patch.object(
            model_selection_e2e,
            "log_visual_event",
            side_effect=lambda logger, event, **fields: events.append((event, fields)),
        ):
            result = model_selection_e2e.post_with_retries(
                "https://example.com/v1/models/demo:generateContent",
                {"Authorization": "Bearer secret-value"},
                {"prompt": "internal prompt"},
                timeout=5,
                retries=0,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(events[0][0], "visual_model_http_attempt")
        self.assertNotIn("status_code", events[0][1])
        self.assertEqual(events[0][1]["attempt"], 1)
        self.assertEqual(events[-1][0], "visual_model_http_success")
        self.assertEqual(events[-1][1]["status_code"], 200)
        for _event, fields in events:
            self.assertNotIn("headers", fields)
            self.assertNotIn("payload", fields)

    def test_http_attempt_uses_and_releases_process_wide_provider_gate(self):
        from poc.visual_review_poc import model_selection_e2e

        class Gate:
            acquired = 0
            released = 0

            def acquire(self, **kwargs):
                self.acquired += 1
                return True

            def release(self):
                self.released += 1

        class Response:
            status_code = 200
            text = ""
            headers = {}

            @staticmethod
            def json():
                return {"ok": True}

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def post(*args, **kwargs):
                return Response()

        gate = Gate()
        with patch.object(model_selection_e2e, "_PROVIDER_REQUEST_GATE", gate), patch.object(
            model_selection_e2e.httpx, "Client", Client
        ):
            result = model_selection_e2e.post_with_retries(
                "https://example.com/v1/models/demo:generateContent",
                {},
                {},
                timeout=5,
                retries=0,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(gate.acquired, 1)
        self.assertEqual(gate.released, 1)

    def test_endpoint_path_is_not_logged_because_it_may_contain_credentials(self):
        from poc.visual_review_poc.observability import visual_event_payload

        payload = visual_event_payload(
            "visual_model_http_attempt",
            endpoint="https://gateway.example.com/tenant-secret-token/v1/models/demo:generateContent",
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("tenant-secret-token", serialized)
        self.assertNotIn("endpoint_path", payload)


if __name__ == "__main__":
    unittest.main()
