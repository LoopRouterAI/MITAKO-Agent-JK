# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import ast
from inspect import Parameter, signature
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from auth.jwt_utils import create_handoff_user_token, create_token
from auth.middleware import resolve_handoff_ws_user
from auth.roles import Role
import handoff_store
import main
from handoff_ws import HandoffHub
from handoff_service import build_public_handoff_brief
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


def test_handoff_offer_cannot_be_consumed_by_another_tenant() -> None:
    secret = "handoff-offer-tenant-secret-0123456789abcdef"
    with TemporaryDirectory() as temp_dir, patch.object(
        handoff_store, "_DB_DIR", temp_dir
    ), patch.object(
        handoff_store, "_DB_PATH", str(Path(temp_dir) / "handoff.db")
    ), patch.object(
        handoff_store, "_db_ready", False
    ), patch.dict(
        "os.environ",
        {
            "MITAKO_JWT_SECRET": secret,
            "MITAKO_PROTECTED_API_AUTH_REQUIRED": "1",
            "MITAKO_DEV_AUTH_BYPASS": "0",
        },
        clear=False,
    ):
        session_id = "shared-session"
        user_id = "shared-user"
        token_a = create_token(
            sub=user_id,
            role=Role.CUSTOMER_USER.value,
            tenant_id="tenant-a",
            extra={"session_id": session_id},
        )
        token_b = create_token(
            sub=user_id,
            role=Role.CUSTOMER_USER.value,
            tenant_id="tenant-b",
            extra={"session_id": session_id},
        )
        client = TestClient(app)
        created = client.post(
            "/api/v1/handoff/offer",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"user_id": user_id, "session_id": session_id, "tenant_id": "tenant-a"},
        )
        assert created.status_code == 200
        offer_id = created.json()["offer"]["offer_id"]

        consumed = client.post(
            "/api/v1/handoff/request",
            headers={"Authorization": f"Bearer {token_b}"},
            json={
                "user_id": user_id,
                "session_id": session_id,
                "tenant_id": "tenant-b",
                "offer_id": offer_id,
            },
        )

        assert consumed.status_code == 409
        assert handoff_store.update_handoff_offer(
            offer_id,
            "declined",
            session_id,
            user_id,
            tenant_id="tenant-a",
        )["tenant_id"] == "tenant-a"


def test_queued_handoff_copy_does_not_claim_human_is_connected() -> None:
    assert build_public_handoff_brief({})["reason"] == "已进入人工队列，正在等待客服接入。"
    source = Path("src/hooks/useChatSSE.js").read_text(encoding="utf-8")
    assert "已为您转接VIP客服继续处理。" not in source


def test_nondefault_customer_session_ids_are_tenant_qualified() -> None:
    with patch.dict(
        "os.environ",
        {
            "MITAKO_DEMO_CUSTOMERS": "shared-user,c,b_c",
            "MITAKO_DEMO_CUSTOMER_TENANTS": "tenant-a,tenant-b,a_b,a,a!b",
        },
        clear=False,
    ):
        assert main._customer_session_is_allowed(
            "shared-user",
            "session:tenant-a:shared-user",
            "tenant-a",
        )
        assert main._customer_session_is_allowed(
            "shared-user",
            "session:tenant-b:shared-user",
            "tenant-b",
        )
        assert not main._customer_session_is_allowed(
            "shared-user",
            "session_shared-user",
            "tenant-a",
        )
        assert main._customer_session_is_allowed("c", "session:a_b:c", "a_b")
        assert main._customer_session_is_allowed("b_c", "session:a:b_c", "a")
        assert main._customer_session_is_allowed("c", "session:a%21b:c", "a!b")
        assert not main._customer_session_is_allowed("c", "session_a_b_c", "a_b")

    hook = Path("src/hooks/useChatSSE.js").read_text(encoding="utf-8")
    app_source = Path("src/App.jsx").read_text(encoding="utf-8")
    assert "function encodeSessionPart(value)" in hook
    assert ".replace(/[!'()*]/g" in hook
    assert "session:${encodeSessionPart(tenant)}:${encodeSessionPart(user)}" in hook
    assert "tenantId," in app_source


def test_tenant_qualified_customer_sessions_do_not_collide_in_sqlite() -> None:
    session_a = main._customer_session_id("c", "a_b")
    session_b = main._customer_session_id("b_c", "a")
    assert session_a != session_b

    with TemporaryDirectory() as temp_dir, patch.object(
        handoff_store, "_DB_DIR", temp_dir
    ), patch.object(
        handoff_store, "_DB_PATH", str(Path(temp_dir) / "handoff.db")
    ), patch.object(
        handoff_store, "_db_ready", False
    ):
        first = handoff_store.ensure_chat_session(session_a, "c", "a_b")
        second = handoff_store.ensure_chat_session(session_b, "b_c", "a")

        assert first["tenant_id"] == "a_b"
        assert second["tenant_id"] == "a"
        assert handoff_store.get_session(session_a)["user_id"] == "c"
        assert handoff_store.get_session(session_b)["user_id"] == "b_c"


def test_customer_ui_preserves_escalated_and_transferring_states() -> None:
    hook = Path("src/hooks/useChatSSE.js").read_text(encoding="utf-8")
    cards = Path("src/components/cards/openUILibrary.jsx").read_text(encoding="utf-8")

    assert "WAITING_HANDOFF_STATES" in hook
    assert "queueMeta?.status" in hook
    assert "const restored = await restoreHandoffState();" in hook
    assert "if (active && !restored) await resetChat();" in hook
    assert "authValue: serviceAuthRef.current || customerAuthRef.current" in hook
    assert "syncWaitingHandoffState(statusData);" in hook
    assert "syncWaitingHandoffState(data);" in hook
    assert "transferEscalated" in cards
    assert "transferTransferring" in cards


def test_customer_session_token_restores_own_handoff_state_only() -> None:
    secret = "handoff-restore-tenant-secret-0123456789abcdef"
    with TemporaryDirectory() as temp_dir, patch.object(
        handoff_store, "_DB_DIR", temp_dir
    ), patch.object(
        handoff_store, "_DB_PATH", str(Path(temp_dir) / "handoff.db")
    ), patch.object(
        handoff_store, "_db_ready", False
    ), patch.dict(
        "os.environ",
        {
            "MITAKO_JWT_SECRET": secret,
            "MITAKO_PROTECTED_API_AUTH_REQUIRED": "1",
            "MITAKO_DEV_AUTH_BYPASS": "0",
        },
        clear=False,
    ):
        handoff_store.upsert_session(
            {
                "session_id": "session_tenant-a_shared-user",
                "user_id": "shared-user",
                "tenant_id": "tenant-a",
                "status": "escalated",
                "brief": {"user_id": "shared-user", "tenant_id": "tenant-a"},
            }
        )
        own_token = create_token(
            sub="shared-user",
            role=Role.CUSTOMER_USER.value,
            tenant_id="tenant-a",
            extra={"session_id": "session_tenant-a_shared-user"},
        )
        other_tenant_token = create_token(
            sub="shared-user",
            role=Role.CUSTOMER_USER.value,
            tenant_id="tenant-b",
            extra={"session_id": "session_tenant-a_shared-user"},
        )
        client = TestClient(app)

        restored = client.get(
            "/api/v1/handoff/status/session_tenant-a_shared-user",
            headers={"Authorization": f"Bearer {own_token}"},
        )
        forbidden = client.get(
            "/api/v1/handoff/status/session_tenant-a_shared-user",
            headers={"Authorization": f"Bearer {other_tenant_token}"},
        )

        assert restored.status_code == 200
        assert restored.json()["status"] == "escalated"
        assert forbidden.status_code == 403


def test_customer_session_token_can_resume_own_handoff_websocket_only() -> None:
    secret = "handoff-websocket-tenant-secret-0123456789abcdef"

    class FakeWebSocket:
        query_params = {}

        def __init__(self, token: str) -> None:
            self.headers = {"sec-websocket-protocol": f"handoff.{token}"}

    with patch.dict(
        "os.environ",
        {
            "MITAKO_JWT_SECRET": secret,
            "MITAKO_PROTECTED_API_AUTH_REQUIRED": "1",
            "MITAKO_DEV_AUTH_BYPASS": "0",
        },
        clear=False,
    ):
        own_token = create_token(
            sub="shared-user",
            role=Role.CUSTOMER_USER.value,
            tenant_id="tenant-a",
            extra={"session_id": "session_tenant-a_shared-user"},
        )
        other_tenant_token = create_token(
            sub="shared-user",
            role=Role.CUSTOMER_USER.value,
            tenant_id="tenant-b",
            extra={"session_id": "session_tenant-a_shared-user"},
        )

        assert resolve_handoff_ws_user(
            FakeWebSocket(own_token),
            "session_tenant-a_shared-user",
            "shared-user",
            "tenant-a",
        )
        assert resolve_handoff_ws_user(
            FakeWebSocket(other_tenant_token),
            "session_tenant-a_shared-user",
            "shared-user",
            "tenant-a",
        ) is None


def test_handoff_hub_echoes_the_authenticated_websocket_subprotocol() -> None:
    class FakeWebSocket:
        headers = {"sec-websocket-protocol": "handoff.signed-token"}

        def __init__(self) -> None:
            self.accepted_subprotocol = None

        async def accept(self, *, subprotocol=None) -> None:
            self.accepted_subprotocol = subprotocol

    websocket = FakeWebSocket()
    asyncio.run(HandoffHub().connect("SESSION-WS", websocket))

    assert websocket.accepted_subprotocol == "handoff.signed-token"


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
        private_store.create_review_task(
            _review_task("TASK-A", "tenant-a"), tenant_id="tenant-a"
        )
        private_store.create_review_task(
            _review_task("TASK-B", "tenant-b"), tenant_id="tenant-b"
        )
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
        assert forbidden.status_code == 404

        dashboard = client.get("/api/v1/private-domain/dashboard", headers=headers)
        assert dashboard.status_code == 200
        assert [item["task_id"] for item in dashboard.json()["review_tasks"]] == ["TASK-A"]

        cleared = client.post("/api/v1/private-domain/demo/clear", headers=headers)
        assert cleared.status_code == 200
        assert private_store.get_review_task("TASK-A", tenant_id="tenant-a") is None
        assert private_store.get_review_task("TASK-B", tenant_id="tenant-b") is not None


def test_private_domain_review_task_store_requires_explicit_tenant() -> None:
    assert signature(private_store.get_review_task).parameters["tenant_id"].default is Parameter.empty
    assert signature(private_store.list_review_tasks).parameters["tenant_id"].default is Parameter.empty
    assert signature(private_store.update_review_task_result).parameters["tenant_id"].default is Parameter.empty
    with pytest.raises(ValueError, match="tenant_id_required"):
        private_store.list_review_tasks(tenant_id="   ")


def test_customer_agent_release_regression_passes_explicit_tenant_to_private_review_store() -> None:
    script = Path("scripts/check_customer_agent_0714_regression.py").read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(script))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "private_domain_store"
        and node.func.attr in {"get_review_task", "create_review_task"}
    ]

    assert len(calls) == 2
    assert all(any(keyword.arg == "tenant_id" for keyword in call.keywords) for call in calls)


def test_private_domain_allows_same_business_ids_in_different_tenants() -> None:
    with TemporaryDirectory() as temp_dir, patch.object(
        private_store, "DB_PATH", Path(temp_dir) / "private_domain.db"
    ):
        private_store.upsert_group(
            {"group_id": "GROUP-SHARED", "group_name": "A"}, tenant_id="tenant-a"
        )
        private_store.upsert_group(
            {"group_id": "GROUP-SHARED", "group_name": "B"}, tenant_id="tenant-b"
        )
        private_store.save_product_event(
            {"event_id": "EVENT-SHARED", "item_id": "SKU-A", "ip_name": "IP-A"},
            tenant_id="tenant-a",
        )
        private_store.save_product_event(
            {"event_id": "EVENT-SHARED", "item_id": "SKU-B", "ip_name": "IP-B"},
            tenant_id="tenant-b",
        )
        private_store.create_customer_service_task(
            {
                "task_id": "CS-SHARED",
                "user_id": "user-a",
                "group_id": "GROUP-SHARED",
                "risk_level": 1,
                "issue_type": "shipping",
                "message_summary": "A",
                "evidence_messages": [],
                "priority": "normal",
                "required_action": "review",
            },
            tenant_id="tenant-a",
        )
        private_store.create_customer_service_task(
            {
                "task_id": "CS-SHARED",
                "user_id": "user-b",
                "group_id": "GROUP-SHARED",
                "risk_level": 1,
                "issue_type": "shipping",
                "message_summary": "B",
                "evidence_messages": [],
                "priority": "normal",
                "required_action": "review",
            },
            tenant_id="tenant-b",
        )
        private_store.create_review_task(
            _review_task("REVIEW-SHARED", "tenant-a"), tenant_id="tenant-a"
        )
        private_store.create_review_task(
            _review_task("REVIEW-SHARED", "tenant-b"), tenant_id="tenant-b"
        )

        assert private_store.get_group("GROUP-SHARED", tenant_id="tenant-a")["group_name"] == "A"
        assert private_store.get_group("GROUP-SHARED", tenant_id="tenant-b")["group_name"] == "B"
        assert private_store.get_customer_service_task("CS-SHARED", tenant_id="tenant-a")["user_id"] == "user-a"
        assert private_store.get_customer_service_task("CS-SHARED", tenant_id="tenant-b")["user_id"] == "user-b"
        assert private_store.get_review_task("REVIEW-SHARED", tenant_id="tenant-a")["user_id"] == "user-tenant-a"
        assert private_store.get_review_task("REVIEW-SHARED", tenant_id="tenant-b")["user_id"] == "user-tenant-b"


def test_private_domain_migrates_pre_tenant_group_table_without_data_loss() -> None:
    with TemporaryDirectory() as temp_dir, patch.object(
        private_store, "DB_PATH", Path(temp_dir) / "private_domain.db"
    ):
        connection = sqlite3.connect(private_store.DB_PATH)
        try:
            connection.execute(
                """
                CREATE TABLE private_groups (
                  group_id TEXT PRIMARY KEY,
                  group_name TEXT NOT NULL,
                  owner_id TEXT NOT NULL DEFAULT '',
                  member_count INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'normal',
                  risk_level INTEGER NOT NULL DEFAULT 0,
                  fatigue_score INTEGER NOT NULL DEFAULT 0,
                  health_score INTEGER NOT NULL DEFAULT 100,
                  marketing_disabled_until REAL NOT NULL DEFAULT 0,
                  tags TEXT NOT NULL DEFAULT '{}',
                  metrics TEXT NOT NULL DEFAULT '{}',
                  updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO private_groups(group_id, group_name, updated_at)
                VALUES ('LEGACY-GROUP', 'Legacy', 1)
                """
            )
            connection.commit()
        finally:
            connection.close()

        private_store.init_db()

        assert private_store.get_group("LEGACY-GROUP", tenant_id="mitako")["group_name"] == "Legacy"
        connection = sqlite3.connect(private_store.DB_PATH)
        try:
            primary_key = [
                row[1]
                for row in sorted(
                    (row for row in connection.execute("PRAGMA table_info(private_groups)") if row[5]),
                    key=lambda row: row[5],
                )
            ]
        finally:
            connection.close()
        assert primary_key == ["tenant_id", "group_id"]
