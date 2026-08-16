# -*- coding: utf-8 -*-
"""旧导入路径兼容层。

正式业务状态机统一由 business_readiness_service 提供，避免 POC 与主服务维护两套规则。
"""
from business_readiness_service import (
    build_sop_checklist,
    classify_sop_branch,
    get_multimodal_fixture,
    record_transfer_blocked,
    run_business_flow,
)

__all__ = [
    "build_sop_checklist",
    "classify_sop_branch",
    "get_multimodal_fixture",
    "record_transfer_blocked",
    "run_business_flow",
]
