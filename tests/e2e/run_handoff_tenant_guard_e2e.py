# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.insert(0, os.path.dirname(__file__))

from e2e_lib import discover_base
from auth import store as auth_store
from auth.roles import Role
import admin_store


def seed_guard_accounts() -> None:
    auth_store.upsert_user(
        "guard_a_admin",
        "pass",
        Role.SUPER_ADMIN.value,
        display_name="Guard A Admin",
        tenant_id="guard_a",
    )
    auth_store.upsert_user(
        "guard_a_desk",
        "pass",
        Role.DESK_AGENT.value,
        agent_id="CS-0816",
        display_name="Guard A Desk",
        tenant_id="guard_a",
    )
    auth_store.upsert_user(
        "guard_b_desk",
        "pass",
        Role.DESK_AGENT.value,
        agent_id="CS-GB",
        display_name="Guard B Desk",
        tenant_id="guard_b",
    )
    auth_store.upsert_user(
        "guard_b_shadow_desk",
        "pass",
        Role.DESK_AGENT.value,
        agent_id="CS-0816",
        display_name="Guard B Shadow Desk",
        tenant_id="guard_b",
    )
    admin_store.upsert_agent({
        "agent_id": "CS-GA",
        "name": "Guard A Desk",
        "title": "Guard A",
        "tier": "standard",
        "team": "guard",
        "skills": [],
        "enabled": True,
        "tenant_id": "guard_a",
    })
    admin_store.upsert_agent({
        "agent_id": "CS-GB",
        "name": "Guard B Desk",
        "title": "Guard B",
        "tier": "standard",
        "team": "guard",
        "skills": [],
        "enabled": True,
        "tenant_id": "guard_b",
    })


async def main_async() -> int:
    seed_guard_accounts()
    tenant_a = "guard_a"
    tenant_b = "guard_b"
    sid = f"guard_cross_{int(time.time())}"

    import handoff_store

    handoff_store.upsert_session({
        "session_id": sid,
        "user_id": "tenant_b_user",
        "tenant_id": tenant_b,
        "status": "queuing",
        "required_tier": "standard",
        "brief": {"user_id": "tenant_b_user", "tenant_id": tenant_b, "summary": "guard"},
        "position": 1,
        "ahead": 0,
        "eta_minutes": 1,
    })

    async with httpx.AsyncClient(timeout=20.0) as client:
        base = await discover_base(client, None)

        async def login(username: str, tenant_id: str) -> dict[str, str]:
            r = await client.post(
                f"{base}/api/v1/auth/login",
                json={"username": username, "password": "pass", "tenant_id": tenant_id},
            )
            token = r.json().get("token", "")
            assert token, r.text
            return {"Authorization": f"Bearer {token}"}

        a_admin = await login("guard_a_admin", tenant_a)
        a_desk = await login("guard_a_desk", tenant_a)
        b_desk = await login("guard_b_desk", tenant_b)
        b_shadow_desk = await login("guard_b_shadow_desk", tenant_b)

        agents_a = (await client.get(f"{base}/api/v1/desk/agents", headers=a_desk)).json()
        agents_b = (await client.get(f"{base}/api/v1/desk/agents", headers=b_desk)).json()
        assert agents_a.get("ok") is True and agents_b.get("ok") is True, (agents_a, agents_b)
        assert "Guard A Desk" in {a.get("name") for a in agents_a.get("agents", [])}, agents_a
        assert "Guard B Desk" not in {a.get("name") for a in agents_a.get("agents", [])}, agents_a
        assert "Guard B Desk" in {a.get("name") for a in agents_b.get("agents", [])}, agents_b
        assert "Guard A Desk" not in {a.get("name") for a in agents_b.get("agents", [])}, agents_b

        from handoff_service import enqueue_handoff

        try:
            enqueue_handoff(
                sid,
                {"user_id": "tenant_a_user", "tenant_id": tenant_a, "summary": "cross tenant overwrite"},
                tenant_id=tenant_a,
            )
        except PermissionError:
            pass
        else:
            raise AssertionError("cross-tenant enqueue unexpectedly succeeded")

        checks = []
        checks.append((await client.post(f"{base}/api/v1/desk/session/{sid}/accept", headers=a_desk, json={"agent_id": "CS-0816"})).json())
        checks.append((await client.post(f"{base}/api/v1/desk/session/{sid}/escalate", headers=a_desk, json={"note": "x"})).json())
        checks.append((await client.post(f"{base}/api/v1/handoff/close", headers=a_desk, params={"session_id": sid})).json())
        checks.append((await client.post(f"{base}/api/v1/handoff/reset", headers=a_admin, params={"session_id": sid})).json())
        assert all(c.get("ok") is not True and c.get("error") == "tenant_forbidden" for c in checks), checks

        mismatch_agent = (await client.post(f"{base}/api/v1/desk/session/{sid}/accept", headers=b_desk, json={"agent_id": "CS-0816"})).json()
        assert mismatch_agent.get("ok") is not True and mismatch_agent.get("detail") == "agent_id_mismatch", mismatch_agent

        missing_agent = (await client.post(f"{base}/api/v1/desk/session/{sid}/accept", headers=b_shadow_desk, json={"agent_id": "CS-0816"})).json()
        assert missing_agent.get("ok") is not True and missing_agent.get("error") == "agent_not_found", missing_agent

        ok_accept = (await client.post(f"{base}/api/v1/desk/session/{sid}/accept", headers=b_desk, json={"agent_id": "CS-GB"})).json()
        assert ok_accept.get("ok") is True, ok_accept
        transfer = (await client.post(f"{base}/api/v1/desk/session/{sid}/transfer", headers=a_desk, json={"from_agent_id": "CS-0816", "to_agent_id": "CS-0922", "note": "x"})).json()
        assert transfer.get("ok") is not True and transfer.get("error") == "tenant_forbidden", transfer
        still_there = handoff_store.get_session(sid)
        assert still_there and still_there.get("tenant_id") == tenant_b and still_there.get("status") == "connected", still_there

    print("handoff tenant guard ok")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
