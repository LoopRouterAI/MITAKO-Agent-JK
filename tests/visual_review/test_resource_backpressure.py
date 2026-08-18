import unittest
from unittest.mock import patch

from fastapi import HTTPException

from poc.visual_review_poc import workbench_server
from review_service import resource_guard


class ResourceBackpressureTest(unittest.TestCase):
    def test_web_review_returns_structured_busy_error_when_case_slot_is_exhausted(self):
        gate = resource_guard.ResourceGate(capacity=1, min_available_bytes=1)
        self.assertTrue(gate.try_acquire(timeout=0.01))
        try:
            with patch.object(workbench_server, "CASE_GATE", gate), \
                 patch.object(workbench_server, "_resource_wait_seconds", return_value=0.01):
                with self.assertRaises(HTTPException) as raised:
                    workbench_server._run_with_case_slot(lambda: {"ok": True})
            self.assertEqual(raised.exception.status_code, 429)
            self.assertEqual(raised.exception.detail["error_type"], "review_resource_busy")
            self.assertEqual(raised.exception.headers["Retry-After"], "1")
        finally:
            gate.release()


if __name__ == "__main__":
    unittest.main()
