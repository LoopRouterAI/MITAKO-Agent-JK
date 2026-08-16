# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.jwt_utils import create_token
from auth.roles import Role


def _isolated_module(tmp_path: Path):
    assert importlib.util.find_spec("configs.model_governance") is not None, "模型治理模块尚未实现"
    module = importlib.import_module("configs.model_governance")
    return patch.multiple(
        module,
        _DB_PATH=str(tmp_path / "admin.db"),
        _db_ready=False,
    ), module


def test_default_model_governance_snapshot_is_safe_and_deterministic(tmp_path: Path) -> None:
    context, governance = _isolated_module(tmp_path)
    with context:
        state = governance.get_model_state("tenant-a")

    assert state["tenant_id"] == "tenant-a"
    assert state["version"] == 0
    assert state["default_model"] == "gemini35lite"
    assert [item["key"] for item in state["models"]] == ["gemini35lite", "gemini37"]
    assert all(item["enabled"] is True for item in state["models"])
    assert state["models"][0]["is_default"] is True
    assert state["models"][1]["automatic_fallback"] is False
    assert "endpoint" not in str(state).lower()
    assert "api_key" not in str(state).lower()


def test_publish_and_rollback_keep_append_only_tenant_history(tmp_path: Path) -> None:
    context, governance = _isolated_module(tmp_path)
    with context:
        first = governance.publish_config(
            tenant_id="tenant-a",
            default_model="gemini37",
            enabled_models=["gemini35lite", "gemini37"],
            reason="根据主管确认，临时切换高质量模型核验视觉疑难案例。",
            actor="admin-a",
            actor_role="super_admin",
            expected_active_version=0,
        )
        second = governance.publish_config(
            tenant_id="tenant-a",
            default_model="gemini37",
            enabled_models=["gemini37"],
            reason="短期停用默认成本档，验证禁用配置会真实传递到运行时。",
            actor="admin-a",
            actor_role="super_admin",
            expected_active_version=1,
        )
        rolled_back = governance.rollback_config(
            tenant_id="tenant-a",
            target_version=1,
            reason="验证完成后恢复包含 Lite 兜底的上一版配置并保留审计历史。",
            actor="admin-b",
            actor_role="super_admin",
            expected_active_version=2,
        )
        versions = governance.list_versions("tenant-a")
        isolated = governance.get_model_state("tenant-b")

    assert first["version"] == 1
    assert second["version"] == 2
    assert rolled_back["version"] == 3
    assert rolled_back["source_version"] == 1
    assert rolled_back["action"] == "rollback"
    assert rolled_back["enabled_models"] == ["gemini35lite", "gemini37"]
    assert [item["version"] for item in versions] == [3, 2, 1]
    assert versions[0]["actor"] == "admin-b"
    assert isolated["version"] == 0


def test_model_config_rejects_stale_or_unsafe_changes(tmp_path: Path) -> None:
    context, governance = _isolated_module(tmp_path)
    with context:
        governance.publish_config(
            tenant_id="tenant-a",
            default_model="gemini35lite",
            enabled_models=["gemini35lite", "gemini37"],
            reason="建立并发编辑与配置边界验证所需的第一个正式版本。",
            actor="admin-a",
            actor_role="super_admin",
            expected_active_version=0,
        )
        with pytest.raises(governance.VersionConflictError):
            governance.publish_config(
                tenant_id="tenant-a",
                default_model="gemini37",
                enabled_models=["gemini35lite", "gemini37"],
                reason="过期页面提交不得静默覆盖已经生效的模型配置版本。",
                actor="admin-b",
                actor_role="super_admin",
                expected_active_version=0,
            )
        invalid_rows = (
            ("gemini35lite", [], "至少启用"),
            ("gemini37", ["gemini35lite"], "默认模型必须处于启用状态"),
            ("unknown", ["gemini35lite", "unknown"], "未知审核模型"),
        )
        for default_model, enabled_models, message in invalid_rows:
            with pytest.raises(ValueError, match=message):
                governance.publish_config(
                    tenant_id="tenant-a",
                    default_model=default_model,
                    enabled_models=enabled_models,
                    reason="验证不安全的模型启停组合无法进入正式运行配置。",
                    actor="admin-a",
                    actor_role="super_admin",
                    expected_active_version=1,
                )
        with pytest.raises(ValueError, match="修改原因"):
            governance.publish_config(
                tenant_id="tenant-a",
                default_model="gemini35lite",
                enabled_models=["gemini35lite"],
                reason="太短",
                actor="admin-a",
                actor_role="super_admin",
                expected_active_version=1,
            )


def test_runtime_routes_only_enabled_models_and_never_uses_37_as_automatic_fallback(tmp_path: Path) -> None:
    context, governance = _isolated_module(tmp_path)
    with context:
        assert governance.runtime_model_keys("tenant-a", "auto") == ["gemini35lite"]
        assert governance.runtime_model_keys("tenant-a", "gemini37") == ["gemini37"]

        governance.publish_config(
            tenant_id="tenant-a",
            default_model="gemini37",
            enabled_models=["gemini35lite", "gemini37"],
            reason="管理员显式选择高质量模型，并保留 Lite 作为失败时的成本可控兜底。",
            actor="admin-a",
            actor_role="super_admin",
            expected_active_version=0,
        )
        assert governance.runtime_model_keys("tenant-a", "auto") == ["gemini37", "gemini35lite"]

        governance.publish_config(
            tenant_id="tenant-a",
            default_model="gemini35lite",
            enabled_models=["gemini35lite"],
            reason="高质量模型验证结束，恢复 Lite 默认并明确禁用高成本候选模型。",
            actor="admin-a",
            actor_role="super_admin",
            expected_active_version=1,
        )
        assert governance.runtime_model_keys("tenant-a", "auto") == ["gemini35lite"]
        assert governance.runtime_model_keys("tenant-a", "gemini37") == []
        assert governance.runtime_model_keys("tenant-a", "unknown") == []


def test_model_governance_api_is_super_admin_only_tenant_bound_and_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MITAKO_JWT_SECRET", "model-governance-test-secret-at-least-32-bytes")
    monkeypatch.setenv("MITAKO_PROTECTED_API_AUTH_REQUIRED", "1")
    monkeypatch.setenv("MITAKO_DEV_AUTH_BYPASS", "0")
    context, governance = _isolated_module(tmp_path)
    with context:
        from review_service.model_governance_router import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        supervisor = create_token(sub="supervisor", role=Role.SUPERVISOR.value, tenant_id="tenant-a")
        super_admin = create_token(sub="root", role=Role.SUPER_ADMIN.value, tenant_id="tenant-a")
        missing_tenant = create_token(sub="legacy-root", role=Role.SUPER_ADMIN.value, tenant_id="")

        assert client.get(
            "/api/v1/admin/review-models",
            headers={"Authorization": f"Bearer {supervisor}"},
        ).status_code == 403
        assert client.get(
            "/api/v1/admin/review-models",
            headers={"Authorization": f"Bearer {missing_tenant}"},
        ).status_code == 403

        published = client.post(
            "/api/v1/admin/review-models/versions",
            headers={"Authorization": f"Bearer {super_admin}"},
            json={
                "default_model": "gemini37",
                "enabled_models": ["gemini35lite", "gemini37"],
                "reason": "依据主管确认，显式切换高质量模型复核视觉疑难案件。",
                "expected_active_version": 0,
            },
        )
        assert published.status_code == 200
        state = client.get(
            "/api/v1/admin/review-models",
            headers={"Authorization": f"Bearer {super_admin}"},
        )

    assert state.status_code == 200
    body = state.json()
    assert body["state"]["default_model"] == "gemini37"
    assert body["versions"][0]["actor"] == "root"
    assert "api_key" not in str(body).lower()
    assert "base_url" not in str(body).lower()


def test_baidu_model_smoke_returns_only_sanitized_operational_fields() -> None:
    from review_service import model_governance_router

    captured = {}

    class FakeResponse:
        status_code = 200
        headers = {"x-bce-request-id": "bce-smoke-1"}

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "candidates": [{"content": {"parts": [{"text": "OK-secret-raw-output"}]}}],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
            }

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, endpoint, *, headers, json):
            captured.update({"endpoint": endpoint, "headers": headers, "payload": json})
            return FakeResponse()

    with patch.object(
        model_governance_router,
        "gemini_channel_options",
        return_value=[{
            "channel": "baidu",
            "model": "gemini-3.7-flash",
            "endpoint": "https://secret.baidu.example/v1/models/gemini-3.7-flash:generateContent",
            "headers": {"Authorization": "Bearer secret-key"},
        }],
    ), patch.object(model_governance_router.httpx, "Client", FakeClient):
        result = model_governance_router._run_baidu_smoke("gemini37")

    assert result == {
        "ok": True,
        "model": "gemini-3.7-flash",
        "status_code": 200,
        "request_id": "bce-smoke-1",
        "usage": {"promptTokenCount": 3, "candidatesTokenCount": 1},
        "latency_seconds": result["latency_seconds"],
    }
    assert result["latency_seconds"] >= 0
    assert "maxOutputTokens" not in str(captured["payload"])
    assert "secret" not in str(result).lower()


def test_jkadmin_exposes_model_governance_only_to_super_admin() -> None:
    root = Path(__file__).resolve().parents[1]
    shell = (root / "src" / "admin" / "AdminShell.jsx").read_text(encoding="utf-8")
    page_path = root / "src" / "admin" / "pages" / "ReviewModels.jsx"
    assert page_path.exists(), "JKAdmin 模型治理页面尚未实现"
    page = page_path.read_text(encoding="utf-8")
    locale = (root / "src" / "i18n" / "zh-CN.js").read_text(encoding="utf-8")

    assert "ReviewModels" in shell
    assert "roles: ['super_admin']" in shell
    assert "<ReviewModels" in shell
    assert "/api/v1/admin/review-models" in page
    assert "/versions" in page
    assert "/rollback" in page
    assert "/smoke" in page
    assert "minLength={10}" in page
    assert "modelGovernanceTitle" in locale
    assert "百度云冒烟" not in locale
    assert "渠道未返回编号" not in locale
    assert "请求 {requestId}" not in locale
    assert "测试可用性" in locale
    assert "admin.navSelect" in shell
    assert "md:hidden" in shell
    assert "hidden md:flex" in shell
    assert "· {version.default_model}" not in page
    assert "modelLabel(version.default_model" in page


def test_mobile_admin_and_desk_controls_keep_touch_targets() -> None:
    root = Path(__file__).resolve().parents[1]
    admin = (root / "src" / "admin" / "AdminShell.jsx").read_text(encoding="utf-8")
    desk = (root / "src" / "desk" / "HumanAgentDesk.jsx").read_text(encoding="utf-8")

    assert "min-h-[44px]" in admin.split("admin.openDesk", 1)[0][-300:]
    assert "min-h-[44px]" in desk.split("desk.agentIdentity", 1)[1][:700]
    assert "min-h-[44px]" in desk.split("desk.openCustomerApp", 1)[0][-300:]
    assert 'aria-pressed={mobileView === id}' in desk
    assert 'flex-1 min-h-[280px] md:min-h-0 overflow-y-auto' in desk
    assert desk.count('min-h-[44px] rounded-[8px] border border-slate-200 px-3 text-xs') >= 3
    assert 'md:hidden' in admin and 'value={tab}' in admin and 'onChange={event => setTab(event.target.value)}' in admin
