import threading
import unittest
from unittest.mock import patch

from review_service import service


class _Executor:
    def __init__(self):
        self.submitted = []

    def submit(self, fn, job_id):
        self.submitted.append((fn, job_id))
        return object()


class ReviewQueueBackpressureTest(unittest.TestCase):
    def test_scheduler_stops_admitting_jobs_at_capacity_and_fills_from_db_after_completion(self):
        executor = _Executor()
        scheduled = set()
        with patch.object(service, "EXECUTOR", executor), \
             patch.object(service, "run_job", return_value={}), \
             patch.object(service, "_SCHEDULE_SLOTS", threading.BoundedSemaphore(1)), \
             patch.object(service, "_SCHEDULED_JOBS", scheduled), \
             patch.object(service.store, "list_queued_job_ids", return_value=["RJ-QUEUED"]):
            self.assertTrue(service.enqueue("RJ-RUNNING"))
            self.assertFalse(service.enqueue("RJ-OVERFLOW"))
            service._run_scheduled_job("RJ-RUNNING")
            self.assertEqual([item[1] for item in executor.submitted], ["RJ-RUNNING", "RJ-QUEUED"])

    def test_queue_diagnostics_exposes_capacity_and_backpressure(self):
        with patch.object(service, "_SCHEDULE_CAPACITY", 2), \
             patch.object(service, "_SCHEDULED_JOBS", {"RJ-1", "RJ-2"}):
            diagnostics = service.queue_diagnostics()
        self.assertEqual(diagnostics["capacity"], 2)
        self.assertEqual(diagnostics["scheduled"], 2)
        self.assertTrue(diagnostics["backpressure"])

    def test_admission_closes_when_persisted_jobs_reach_capacity(self):
        with patch.object(service, "_SCHEDULE_CAPACITY", 2), \
             patch.object(service.store, "snapshot", return_value={"queued": 1, "running": 1}):
            self.assertFalse(service.queue_admission_available("tenant-a"))

    def test_workbench_resource_busy_requeues_without_marking_case_failed(self):
        job = {"job_id": "RJ-RESOURCE", "assets": [], "metadata": {}, "attempts": 1}
        with patch.object(service.store, "get_job", return_value=job), \
             patch.object(service.store, "claim_job", return_value=True), \
             patch.object(service, "_workbench_lease_seconds", return_value=60), \
             patch.object(service, "_media_forensics", return_value={}), \
             patch.object(service, "assess_input_readiness", return_value={}), \
             patch.object(service, "build_review_inventory", return_value={}), \
             patch.object(service, "_call_workbench", side_effect=service.WorkbenchRequestError(429, [])), \
             patch.object(service.store, "requeue_running_job", return_value={"job_id": "RJ-RESOURCE", "status": "QUEUED"}) as requeue:
            result = service.run_job("RJ-RESOURCE")
        self.assertEqual(result["status"], "QUEUED")
        requeue.assert_called_once()


if __name__ == "__main__":
    unittest.main()
