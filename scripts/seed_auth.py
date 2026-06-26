# -*- coding: utf-8 -*-
"""初始化演示/生产账号 — python scripts/seed_auth.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auth.roles import Role
from auth.store import upsert_user, list_users
import auth.tenants  # noqa: F401 — 初始化 tenants 表


DEFAULT_USERS = [
    ("admin", "admin123", Role.SUPER_ADMIN.value, "", "系统管理员"),
    ("supervisor", "super123", Role.SUPERVISOR.value, "CS-1024", "客诉主管"),
    ("bpo_mgr", "bpo123", Role.BPO_MANAGER.value, "", "外包经理"),
    ("desk0816", "desk123", Role.DESK_AGENT.value, "CS-0816", "一线坐席岚星"),
    ("comp_ops", "comp123", Role.COMPANION_OPS.value, "", "Companion 运营"),
]


def main() -> None:
    for username, password, role, agent_id, display_name in DEFAULT_USERS:
        upsert_user(username, password, role, agent_id=agent_id, display_name=display_name)
        print(f"  upserted {username} ({role})")
    print("\n当前账号：")
    for u in list_users():
        print(f"  - {u['username']} role={u['role']} agent={u.get('agent_id') or '-'}")


if __name__ == "__main__":
    main()
