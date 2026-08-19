# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

import main


def test_version_endpoint_has_auditable_deployment_fields(monkeypatch) -> None:
    monkeypatch.setenv("MITAKO_BUILD_COMMIT", "abc1234")
    monkeypatch.setenv("VITE_BUILD_ID", "web-20260819.1")
    monkeypatch.setenv("MITAKO_CUSTOMER_POLICY_VERSION", "MITAKO-CUSTOMER-CHAT-20260818.1")
    monkeypatch.setenv("MITAKO_DEPLOYED_AT", "2026-08-19T09:30:00+08:00")

    body = TestClient(main.app).get("/api/v1/version").json()

    assert body == {
        "backend_commit": "abc1234",
        "frontend_build": "web-20260819.1",
        "customer_policy_version": "MITAKO-CUSTOMER-CHAT-20260818.1",
        "deployed_at": "2026-08-19T09:30:00+08:00",
    }


def test_version_endpoint_uses_unknown_without_running_git(monkeypatch) -> None:
    for key in (
        "MITAKO_BUILD_COMMIT",
        "VITE_BUILD_ID",
        "MITAKO_CUSTOMER_POLICY_VERSION",
        "MITAKO_DEPLOYED_AT",
    ):
        monkeypatch.delenv(key, raising=False)

    body = TestClient(main.app).get("/api/v1/version").json()

    assert set(body.values()) == {"unknown"}
