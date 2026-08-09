# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.jwt_utils import create_token
from auth.roles import Role


@pytest.fixture()
def isolated_store(tmp_path: Path):
    from prompts import governance_store

    with (
        patch.object(governance_store, "_DB_PATH", str(tmp_path / "prompt-rules.db")),
        patch.object(governance_store, "_db_ready", False),
    ):
        yield governance_store


def test_publish_and_rollback_are_append_only_with_full_audit(isolated_store) -> None:
    first = isolated_store.publish_version(
        tenant_id="mitako",
        prompt_key="visual.product_damage",
        mode="supplement",
        content="加速视频只作为风险信号，不应仅凭加速直接判定材料不合格。",
        reason="根据甲方人工审核指南补充合理加速的判断边界。",
        actor="supervisor-a",
        actor_role=Role.SUPERVISOR.value,
    )
    second = isolated_store.publish_version(
        tenant_id="mitako",
        prompt_key="visual.product_damage",
        mode="replace",
        content="只有加速影响默认一帧每秒审核形成结论时，才升级为阻断性证据风险。",
        reason="修正仅凭视频加速就要求补件的过严审核逻辑。",
        actor="supervisor-a",
        actor_role=Role.SUPERVISOR.value,
    )
    rolled_back = isolated_store.rollback_version(
        tenant_id="mitako",
        prompt_key="visual.product_damage",
        target_version=1,
        reason="复盘发现第一版更符合当前人工审核口径，恢复其内容并保留历史。",
        actor="supervisor-b",
        actor_role=Role.SUPERVISOR.value,
    )

    versions = isolated_store.list_versions("mitako", "visual.product_damage")
    assert [item["version"] for item in versions] == [3, 2, 1]
    assert rolled_back["version"] == 3
    assert rolled_back["source_version"] == 1
    assert rolled_back["content"] == first["content"]
    assert isolated_store.get_active_version("mitako", "visual.product_damage")["version"] == 3
    assert second["is_active"] is True

    audit = isolated_store.list_audit("mitako", "visual.product_damage")
    assert [item["action"] for item in audit] == ["rollback", "publish", "publish"]
    assert audit[0]["actor"] == "supervisor-b"
    assert audit[0]["reason"].startswith("复盘发现")
    assert all(item["created_at"] for item in audit)


def test_stale_editor_cannot_overwrite_active_version(isolated_store) -> None:
    first = isolated_store.publish_version(
        tenant_id="mitako",
        prompt_key="visual.wrong_item",
        mode="supplement",
        content="清晰照片证据链可以支持发错货的明确初审结论。",
        reason="建立主管并发编辑冲突测试所需的第一个生效版本。",
        actor="supervisor-a",
        actor_role=Role.SUPERVISOR.value,
        expected_active_version=0,
    )
    assert first["version"] == 1
    with pytest.raises(isolated_store.VersionConflictError):
        isolated_store.publish_version(
            tenant_id="mitako",
            prompt_key="visual.wrong_item",
            mode="replace",
            content="另一个主管基于过期页面提交的规则不得覆盖当前版本。",
            reason="验证过期编辑器提交时服务端拒绝静默覆盖最新规则。",
            actor="supervisor-b",
            actor_role=Role.SUPERVISOR.value,
            expected_active_version=0,
        )
    assert isolated_store.get_active_version("mitako", "visual.wrong_item")["version"] == 1


def test_validation_and_tenant_isolation(isolated_store) -> None:
    with pytest.raises(ValueError, match="修改原因"):
        isolated_store.publish_version(
            tenant_id="mitako",
            prompt_key="visual.missing_item",
            mode="supplement",
            content="结构化仓库终核可以覆盖历史待核实备注。",
            reason="太短",
            actor="supervisor-a",
            actor_role=Role.SUPERVISOR.value,
        )
    with pytest.raises(ValueError, match="更新方式"):
        isolated_store.publish_version(
            tenant_id="mitako",
            prompt_key="visual.missing_item",
            mode="unsafe",
            content="结构化仓库终核可以覆盖历史待核实备注。",
            reason="明确补充仓库核实结果的证据优先级和适用条件。",
            actor="supervisor-a",
            actor_role=Role.SUPERVISOR.value,
        )

    isolated_store.publish_version(
        tenant_id="tenant-a",
        prompt_key="visual.missing_item",
        mode="supplement",
        content="工单568689已有仓库终核且商品与用户初始材料一致，应判定未漏发。",
        reason="依据人工补充结论沉淀租户A的漏发货终核规则。",
        actor="supervisor-a",
        actor_role=Role.SUPERVISOR.value,
    )
    assert isolated_store.get_active_version("tenant-b", "visual.missing_item") is None


def test_business_rule_resolution_keeps_immutable_boundary(isolated_store) -> None:
    from prompts.governance import capture_rule_snapshot, resolve_business_rules
    from prompts.visual_review.core import build_system_prompt

    isolated_store.publish_version(
        tenant_id="mitako",
        prompt_key="visual.minor_refund",
        mode="replace",
        content="未满九周岁且年龄识别置信度高时，标记独立支付能力风险并要求高级客服重点复核。",
        reason="补充甲方关于低龄未成年人支付能力风险的最新人工口径。",
        actor="supervisor-a",
        actor_role=Role.SUPERVISOR.value,
    )
    resolved = resolve_business_rules(
        prompt_key="visual.minor_refund",
        default_rules="默认五类材料审核规则。",
        tenant_id="mitako",
    )
    assert "默认五类材料审核规则" not in resolved
    assert "未满九周岁" in resolved
    assert "不能仅凭年龄" in resolved

    immutable = "禁止自动退款、自动拒赔或输出最终业务裁决。"
    full_prompt = immutable + "\n" + resolved
    assert immutable in full_prompt
    visual_prompt = build_system_prompt("minor_refund", tenant_id="mitako")
    assert "未满九周岁" in visual_prompt
    assert "最终边界" in visual_prompt
    assert "不得覆盖禁止自动退款" in visual_prompt

    snapshot = capture_rule_snapshot("visual.minor_refund", "mitako")
    isolated_store.publish_version(
        tenant_id="mitako",
        prompt_key="visual.minor_refund",
        mode="replace",
        content="新版本要求把支付来源核验结果写入证据清单。",
        reason="验证同一案件冻结规则版本后不会混入审核期间发布的新口径。",
        actor="supervisor-a",
        actor_role=Role.SUPERVISOR.value,
    )
    frozen = resolve_business_rules(
        prompt_key="visual.minor_refund",
        default_rules="默认五类材料审核规则。",
        tenant_id="mitako",
        snapshot=snapshot,
    )
    assert "独立支付能力风险" in frozen
    assert "写入证据清单" not in frozen


def test_visual_prompt_snapshot_is_tenant_isolated(isolated_store) -> None:
    from prompts import governance
    from prompts.visual_review.core import build_system_prompt, freeze_rule_snapshot
    from prompts.visual_review.review_model_prompt import build_selection_prompt

    for tenant, marker in (("tenant-a", "租户A专属仓库终核规则"), ("tenant-b", "租户B专属仓库终核规则")):
        isolated_store.publish_version(
            tenant_id=tenant,
            prompt_key="visual.missing_item",
            mode="supplement",
            content=f"{marker}：只有带核验编号的结构化记录可以覆盖待核实备注。",
            reason=f"验证{tenant}的视觉审核规则不会串入其他租户。",
            actor="supervisor-a",
            actor_role=Role.SUPERVISOR.value,
        )

    snapshot = governance.capture_rule_snapshot("visual.missing_item", "tenant-a")
    prompt = build_system_prompt("missing_item", tenant_id="tenant-a", rule_snapshot=snapshot)
    assert "租户A专属仓库终核规则" in prompt
    assert "租户B专属仓库终核规则" not in prompt

    case = {
        "case_id": "CASE-TENANT-A",
        "scenario": "video_unboxing",
        "customer_claim": "用户称订单少了一件商品。",
        "structured_business_context": {"business_scenario": "missing_item"},
        "frames": [],
        "supplemental_images": [],
        "_rule_tenant_id": "tenant-a",
    }
    with patch.object(governance, "get_active_version", wraps=governance.get_active_version) as read_active:
        freeze_rule_snapshot(case)
        for _ in range(8):
            freeze_rule_snapshot(dict(case))
    assert read_active.call_count == 1
    assert "租户A专属仓库终核规则" not in build_selection_prompt(case)


def test_observer_rules_end_with_immutable_boundary(isolated_store) -> None:
    from prompts.customer_service import get_observer_system_prompt

    isolated_store.publish_version(
        tenant_id="mitako",
        prompt_key="customer.observer",
        mode="replace",
        content="旁听回复需要优先概括用户当前最关心的处理节点。",
        reason="验证旁听模式的可编辑规则始终位于不可变权限边界之前。",
        actor="supervisor-a",
        actor_role=Role.SUPERVISOR.value,
    )
    prompt = get_observer_system_prompt("mitako")
    assert prompt.index("优先概括") < prompt.index("旁听模式不可变边界")
    assert "不得声称已执行退款、补发、催促、联系或转交" in prompt


def test_prompt_governance_api_rejects_non_supervisor_role(isolated_store, monkeypatch) -> None:
    monkeypatch.setenv("MITAKO_JWT_SECRET", "prompt-governance-test-secret-at-least-32-bytes")
    monkeypatch.setenv("MITAKO_PROTECTED_API_AUTH_REQUIRED", "1")
    monkeypatch.setenv("MITAKO_DEV_AUTH_BYPASS", "0")

    from prompts.router import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    manager_token = create_token(sub="manager", role=Role.BPO_MANAGER.value, tenant_id="mitako")
    supervisor_token = create_token(sub="supervisor", role=Role.SUPERVISOR.value, tenant_id="mitako")

    denied = client.get(
        "/api/v1/admin/business-rules",
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    allowed = client.get(
        "/api/v1/admin/business-rules",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["ok"] is True
    assert all("default_rules" not in item for item in allowed.json()["rules"])

    isolated_store.publish_version(
        tenant_id="mitako",
        prompt_key="visual.product_damage",
        mode="supplement",
        content="当前版本用于验证后台并发提交的冲突响应。",
        reason="建立 API 版本冲突测试所需的当前生效规则。",
        actor="supervisor",
        actor_role=Role.SUPERVISOR.value,
    )
    conflict = client.post(
        "/api/v1/admin/business-rules/visual.product_damage/versions",
        headers={"Authorization": f"Bearer {supervisor_token}"},
        json={
            "mode": "replace",
            "content": "基于过期版本号的规则提交不得覆盖当前规则。",
            "reason": "验证并发编辑冲突通过 409 明确返回给后台界面。",
            "expected_active_version": 0,
        },
    )
    assert conflict.status_code == 409

    missing_tenant_token = create_token(
        sub="legacy-supervisor",
        role=Role.SUPERVISOR.value,
        tenant_id="",
    )
    missing_tenant = client.post(
        "/api/v1/admin/business-rules/visual.missing_item/versions",
        headers={"Authorization": f"Bearer {missing_tenant_token}"},
        json={
            "mode": "supplement",
            "content": "缺失租户声明时不得默认写入任何客户的业务规则。",
            "reason": "验证旧版令牌无法误写默认租户的规则数据。",
            "expected_active_version": 0,
        },
    )
    assert missing_tenant.status_code == 403
    assert isolated_store.get_active_version("mitako", "visual.missing_item") is None


def test_formal_review_transmits_trusted_rule_tenant() -> None:
    from review_service.service import _review_fields
    from poc.visual_review_poc.workbench_server import _resolve_rule_tenant_id

    fields = _review_fields({
        "tenant_id": "tenant-b",
        "scenario": "missing_item",
        "client_case_id": "CASE-1",
        "metadata": {},
        "assets": [],
    })
    assert fields["rule_tenant_id"] == "tenant-b"
    assert _resolve_rule_tenant_id("tenant-b", internal_request=True) == "tenant-b"
    assert _resolve_rule_tenant_id("tenant-b", internal_request=False) == "mitako"


def test_old_governance_schema_is_migrated(tmp_path: Path) -> None:
    from prompts import governance_store

    database = tmp_path / "old-rules.db"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            """
            CREATE TABLE business_rule_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                prompt_key TEXT NOT NULL,
                version INTEGER NOT NULL,
                mode TEXT NOT NULL,
                content TEXT NOT NULL,
                reason TEXT NOT NULL,
                actor TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE TABLE business_rule_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                prompt_key TEXT NOT NULL,
                action TEXT NOT NULL,
                from_version INTEGER,
                to_version INTEGER NOT NULL,
                reason TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            """
        )

    with (
        patch.object(governance_store, "_DB_PATH", str(database)),
        patch.object(governance_store, "_db_ready", False),
    ):
        published = governance_store.publish_version(
            tenant_id="mitako",
            prompt_key="visual.product_damage",
            mode="supplement",
            content="旧数据库升级后仍能发布新的商品有伤业务规则。",
            reason="验证已有部署数据库可以无损升级到规则治理新结构。",
            actor="supervisor-a",
            actor_role=Role.SUPERVISOR.value,
        )
    assert published["actor_role"] == Role.SUPERVISOR.value
    assert "source_version" in published


def test_legacy_modules_are_thin_compatibility_exports() -> None:
    root = Path(__file__).resolve().parents[1]
    legacy_files = (
        "minor_material_model_prompt.py",
        "continuity_model_prompt.py",
        "damage_causality_model_prompt.py",
        "review_model_prompt.py",
    )
    for name in legacy_files:
        text = (root / "poc" / "visual_review_poc" / name).read_text(encoding="utf-8")
        assert "prompts.visual_review" in text
        assert len(text.splitlines()) < 30

    for name in ("gemini_adapter.py", "e2e_real_api_report.py", "e2e_youtube_report.py"):
        text = (root / "poc" / "visual_review_poc" / name).read_text(encoding="utf-8")
        assert "prompts.visual_review.diagnostics" in text
        assert "未成年人资料即使看起来完整，也必须" not in text

    admin_shell = (root / "src" / "admin" / "AdminShell.jsx").read_text(encoding="utf-8")
    page = (root / "src" / "admin" / "pages" / "BusinessRules.jsx").read_text(encoding="utf-8")
    assert "roles: ['super_admin', 'supervisor']" in admin_shell
    assert "target_version" in page and "rollbackReason" in page
    assert "expected_active_version" in page
    assert "rollback.prompt_key" in page
    assert "showModal" in page and "aria-pressed" in page


def test_missing_item_rules_do_not_force_review_for_split_orders_or_photo_evidence(isolated_store) -> None:
    from prompts.visual_review.core import build_system_prompt

    prompt = build_system_prompt("missing_item", tenant_id="mitako")

    assert "订单已拆单时不能判为漏发" not in prompt
    assert "无视频时只能" not in prompt
    assert "全部分包" in prompt
    assert "清晰照片" in prompt
