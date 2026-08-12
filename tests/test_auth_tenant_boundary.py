# -*- coding: utf-8 -*-
from __future__ import annotations

from inspect import Parameter, signature
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from auth.jwt_utils import create_handoff_user_token, create_token
from auth.roles import Role
from main import AuthLoginRequest, app
from private_domain import store as private_store


def test_admin_login_requires_non_blank_tenant_id() -> None:
    with pytest.raises(ValidationError):
        AuthLoginRequest(username="admin", password="secret")

    with pytest.raises(ValidationError):
        AuthLoginRequest(username="admin", password="secret", tenant_id="   ")


def test_token_factories_require_explicit_tenant_id() -> None:
    assert signature(create_token).parameters["tenant_id"].default is Parameter.empty
    assert signature(create_handoff_user_token).parameters["tenant_id"].default is Parameter.empty


def _review_task(task_id: str, tenant_id: str) -> dict:
    return {
        "task_id": task_id,
        "user_id": f"user-{tenant_id}",
        "session_id": f"session-{tenant_id}",
        "tenant_id": tenant_id,
        "scenario": "product_damage",
        "file_name": "evidence.mp4",
        "stored_name": f"{task_id}.mp4",
        "mime_type": "video/mp4",
        "size": 128,
        "status": "COMPLETED",
        "boundary": "tenant-test",
        "context": {"private_note": tenant_id},
        "result": {"tenant": tenant_id},
    }


def test_private_domain_admin_cannot_read_or_clear_another_tenant() -> None:
    secret = "tenant-boundary-test-secret-0123456789abcdef"
    with TemporaryDirectory() as temp_dir, patch.object(
        private_store, "DB_PATH", Path(temp_dir) / "private_domain.db"
    ), patch.dict(
        "os.environ",
        {
            "MITAKO_JWT_SECRET": secret,
            "MITAKO_PROTECTED_API_AUTH_REQUIRED": "1",
            "MITAKO_DEV_AUTH_BYPASS": "0",
        },
        clear=False,
    ):
        private_store.init_db()
        private_store.create_review_task(_review_task("TASK-A", "tenant-a"))
        private_store.create_review_task(_review_task("TASK-B", "tenant-b"))
        token = create_token(
            sub="supervisor-a",
            role=Role.SUPERVISOR.value,
            tenant_id="tenant-a",
        )
        headers = {"Authorization": f"Bearer {token}"}
        client = TestClient(app)

        forbidden = client.get(
            "/api/v1/private-domain/review-tasks/TASK-B",
            headers=headers,
        )
        assert forbidden.status_code == 403

        dashboard = client.get("/api/v1/private-domain/dashboard", headers=headers)
        assert dashboard.status_code == 200
        assert [item["task_id"] for item in dashboard.json()["review_tasks"]] == ["TASK-A"]

        cleared = client.post("/api/v1/private-domain/demo/clear", headers=headers)
        assert cleared.status_code == 200
        assert private_store.get_review_task("TASK-A") is None
        assert private_store.get_review_task("TASK-B", tenant_id="tenant-b") is not None
