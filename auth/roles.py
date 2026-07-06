# -*- coding: utf-8 -*-
"""角色定义 — 客服后台、坐席台与客户会话分级权限"""
from __future__ import annotations

from enum import Enum
from typing import FrozenSet


class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    SUPERVISOR = "supervisor"
    BPO_MANAGER = "bpo_manager"
    QC_VIEWER = "qc_viewer"
    DESK_AGENT = "desk_agent"
    HANDOFF_USER = "handoff_user"
    CUSTOMER_USER = "customer_user"


# mutating admin API 允许的运营角色
ADMIN_MUTATE_ROLES: FrozenSet[str] = frozenset({
    Role.SUPER_ADMIN.value,
    Role.SUPERVISOR.value,
    Role.BPO_MANAGER.value,
})

# 补偿审批职责分离：一线客服发起，主管/超级管理员裁决；管理角色不能绕过服务单代发起。
APPROVAL_CREATE_ROLES: FrozenSet[str] = frozenset({
    Role.DESK_AGENT.value,
})

APPROVAL_DECIDE_ROLES: FrozenSet[str] = frozenset({
    Role.SUPER_ADMIN.value,
    Role.SUPERVISOR.value,
})

APPROVAL_ACCESS_ROLES: FrozenSet[str] = APPROVAL_CREATE_ROLES | APPROVAL_DECIDE_ROLES

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

ALL_ROLES: FrozenSet[str] = frozenset(r.value for r in Role)
