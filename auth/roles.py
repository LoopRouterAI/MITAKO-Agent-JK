# -*- coding: utf-8 -*-
"""角色定义 — admin / desk / companion 分级权限"""
from __future__ import annotations

from enum import Enum
from typing import FrozenSet


class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    SUPERVISOR = "supervisor"
    BPO_MANAGER = "bpo_manager"
    QC_VIEWER = "qc_viewer"
    DESK_AGENT = "desk_agent"
    COMPANION_OPS = "companion_ops"
    HANDOFF_USER = "handoff_user"
    COMPANION_USER = "companion_user"


# mutating admin API 允许的运营角色
ADMIN_MUTATE_ROLES: FrozenSet[str] = frozenset({
    Role.SUPER_ADMIN.value,
    Role.SUPERVISOR.value,
    Role.BPO_MANAGER.value,
})

# desk 接单/回复/转交
DESK_MUTATE_ROLES: FrozenSet[str] = frozenset({
    Role.SUPER_ADMIN.value,
    Role.SUPERVISOR.value,
    Role.DESK_AGENT.value,
})

# desk 读队列/会话（含 QC、BPO 监控）
DESK_ACCESS_ROLES: FrozenSet[str] = DESK_MUTATE_ROLES | frozenset({
    Role.BPO_MANAGER.value,
    Role.QC_VIEWER.value,
})

# Companion 独立运营台
COMPANION_DESK_ROLES: FrozenSet[str] = frozenset({
    Role.SUPER_ADMIN.value,
    Role.SUPERVISOR.value,
    Role.COMPANION_OPS.value,
})

ALL_ROLES: FrozenSet[str] = frozenset(r.value for r in Role)
