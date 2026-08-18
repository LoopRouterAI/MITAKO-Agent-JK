import unittest
from unittest.mock import patch

from review_service import resource_guard


class ResourceGuardTest(unittest.TestCase):
    def test_two_gb_budget_caps_configured_parallelism_to_one(self):
        snapshot = resource_guard.ResourceSnapshot(
            total_bytes=2 * 1024**3,
            available_bytes=1 * 1024**3,
            process_bytes=0,
            source="test",
        )
        with patch.object(resource_guard, "memory_snapshot", return_value=snapshot):
            self.assertEqual(resource_guard.recommended_concurrency(4), 1)

    def test_gate_rejects_new_work_when_available_memory_is_below_reserve(self):
        snapshot = resource_guard.ResourceSnapshot(
            total_bytes=2 * 1024**3,
            available_bytes=128 * 1024**2,
            process_bytes=0,
            source="test",
        )
        gate = resource_guard.ResourceGate(capacity=1, min_available_bytes=512 * 1024**2)
        with patch.object(resource_guard, "memory_snapshot", return_value=snapshot):
            self.assertFalse(gate.try_acquire(timeout=0.01))
            self.assertEqual(gate.diagnostics()["active"], 0)

    def test_gate_releases_and_exposes_resource_diagnostics(self):
        snapshot = resource_guard.ResourceSnapshot(
            total_bytes=8 * 1024**3,
            available_bytes=4 * 1024**3,
            process_bytes=0,
            source="test",
        )
        gate = resource_guard.ResourceGate(capacity=1, min_available_bytes=512 * 1024**2)
        with patch.object(resource_guard, "memory_snapshot", return_value=snapshot):
            self.assertTrue(gate.try_acquire(timeout=0.01))
            self.assertEqual(gate.diagnostics()["active"], 1)
            gate.release()
            self.assertEqual(gate.diagnostics()["active"], 0)


if __name__ == "__main__":
    unittest.main()
