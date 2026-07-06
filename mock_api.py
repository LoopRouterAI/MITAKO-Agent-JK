# -*- coding: utf-8 -*-
"""兼容旧内部导入；客户服务路由实现已迁移到 business_api。"""
from business_api import *  # noqa: F401,F403
from business_api import business_router as mock_router  # noqa: F401
