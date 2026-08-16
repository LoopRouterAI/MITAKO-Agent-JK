# Tasks: 010 企业级生产补齐

## Phase A — 多租户 SSO ✅
- [x] T301 `auth/tenants.py` + JWT `tenant_id`
- [x] T302 `auth/sso.py` OIDC Demo + `/api/v1/auth/sso/*`
- [x] T303 AdminLogin 租户选择 + SSO 按钮

## Phase B — IM/工单 Chatwoot ✅
- [x] T311 `handoff_backend/chatwoot_client.py`
- [x] T312 `im_sync_service.py` hybrid 同步
- [x] T313 E2E CHATWOOT-mock-sync

## Phase C — 7×24 运维 ✅
- [x] T321 `ops_service.py` + `GET /api/v1/ops/snapshot`
- [x] T322 Admin `OpsMonitor.jsx` Tab
- [x] T323 E2E OPS-snapshot + B-admin-ops-monitor

## Phase D — 基建与回归 ✅
- [x] T331 `scripts/kill_mitako_ports.ps1` + APP_PORT 严格
- [x] T332 `run_enterprise_production_e2e.py` 16/16
- [x] T333 `run_production_hardening_e2e.py` 70/70

## 待生产实机验证（非阻塞 Demo）
- [ ] T401 真实 Chatwoot 实例 + `CHATWOOT_MOCK=0`
- [ ] T402 真实 OIDC IdP + `MITAKO_SSO_DEMO=0`
- [ ] T403 `docker-compose up` Celery SLA 7×24
- [ ] T404 `MITAKO_AUTH_REQUIRED=1` 全链路门禁
- [ ] T405 Grafana/告警 webhook 对接
