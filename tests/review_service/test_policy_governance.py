import tempfile
import unittest
import gc
import os
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from review_service import policy_governance
from auth.jwt_utils import create_token
from auth.roles import Role


class ReviewPolicyGovernanceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_path = policy_governance._DB_PATH
        self.original_ready = policy_governance._ready
        policy_governance._DB_PATH = str(Path(self.temp_dir.name) / "admin.db")
        policy_governance._ready = False

    def tearDown(self):
        policy_governance._ready = False
        policy_governance._DB_PATH = self.original_path
        gc.collect()
        policy_governance._ready = self.original_ready
        self.temp_dir.cleanup()

    def test_default_policy_is_safe_and_public(self):
        policy = policy_governance.get_active_policy("tenant-a")
        self.assertEqual(policy["version"], 0)
        self.assertEqual(policy["review_intensity"], "strong")
        self.assertEqual(policy["video_max_source_mb"], 100)
        self.assertFalse(policy["one_fps_frame_fallback"])
        self.assertNotIn("prompt", policy_governance.public_policy(policy))

    def test_publish_and_rollback_keep_audit_history(self):
        published = policy_governance.publish_policy(
            tenant_id="tenant-a",
            policy={"review_intensity": "forensic", "video_max_source_mb": 120},
            reason="根据大视频复核反馈调整预算",
            actor="supervisor-1",
            actor_role="supervisor",
            expected_active_version=0,
        )
        self.assertEqual(published["version"], 1)
        self.assertEqual(published["video_max_source_mb"], 120)
        rolled = policy_governance.rollback_policy(
            tenant_id="tenant-a",
            target_version=0,
            reason="回到已验证的默认媒体预算",
            actor="supervisor-1",
            actor_role="supervisor",
            expected_active_version=1,
        )
        self.assertEqual(rolled["version"], 2)
        self.assertEqual(rolled["video_max_source_mb"], 100)
        self.assertEqual([item["version"] for item in policy_governance.list_versions("tenant-a")], [2, 1])

    def test_reason_and_bounds_are_enforced(self):
        with self.assertRaises(ValueError):
            policy_governance.publish_policy(
                tenant_id="tenant-a", policy={}, reason="太短", actor="u", actor_role="supervisor"
            )
        with self.assertRaises(ValueError):
            policy_governance.normalize_policy({"video_min_short_edge": 2000})

    def test_policy_api_is_tenant_bound_and_supports_publish_history_rollback(self):
        from review_service.policy_governance_router import router

        app = FastAPI()
        app.include_router(router)
        with patch.dict(os.environ, {
            "MITAKO_JWT_SECRET": "policy-governance-test-secret-at-least-32-bytes",
            "MITAKO_PROTECTED_API_AUTH_REQUIRED": "1",
            "MITAKO_DEV_AUTH_BYPASS": "0",
        }):
            token = create_token(sub="supervisor-a", role=Role.SUPERVISOR.value, tenant_id="tenant-a")
            other = create_token(sub="supervisor-b", role=Role.SUPERVISOR.value, tenant_id="tenant-b")
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/v1/admin/review-policies", headers=headers).status_code == 200
            published = client.post(
                "/api/v1/admin/review-policies/versions",
                headers=headers,
                json={"policy": {"review_intensity": "forensic", "max_frames": 48}, "reason": "根据疑难视频复核调整策略", "expected_active_version": 0},
            )
            assert published.status_code == 200
            assert published.json()["policy"]["version"] == 1
            state = client.get("/api/v1/admin/review-policies", headers=headers).json()
            assert state["policy"]["review_intensity"] == "forensic"
            assert state["versions"][0]["actor"] == "supervisor-a"
            rolled = client.post(
                "/api/v1/admin/review-policies/rollback",
                headers=headers,
                json={"target_version": 0, "reason": "复核结束恢复默认成本档", "expected_active_version": 1},
            )
            assert rolled.status_code == 200
            assert rolled.json()["policy"]["version"] == 2
            assert client.get(
                "/api/v1/admin/review-policies",
                headers={"Authorization": f"Bearer {other}"},
            ).json()["policy"]["version"] == 0
            assert client.post(
                "/api/v1/admin/review-policies/versions",
                headers=headers,
                json={"policy": {}, "reason": "太短", "expected_active_version": 2},
            ).status_code == 422


if __name__ == "__main__":
    unittest.main()
