# Feature Specification: 010 企业级生产补齐

**Scope**: 私域社群（spec 03）除外的一切商业生产级能力

## 必须交付

1. **真实 IM/工单**：Chatwoot REST 适配（`HANDOFF_BACKEND=hybrid|chatwoot`），未配置时 SQLite 兜底
2. **多租户 SSO**：`tenants` 表 + OIDC 授权/回调 + JWT `tenant_id`
3. **7×24 运维面板**：Redis/Celery/Chatwoot/队列/WS 健康快照 + Admin 大屏 Tab
4. **严格鉴权 E2E**：`MITAKO_AUTH_REQUIRED=1` 401 门禁
5. **分布式 SLA**：Celery worker 可观测 + E2E mock

## 退出标准

- `run_enterprise_production_e2e.py` 全绿
- `run_production_hardening_e2e.py` 68/68 仍全绿
- `run_auth_strict_e2e.py` 在 auth=1 时全绿
