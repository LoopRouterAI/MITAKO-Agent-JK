# Tasks: 008 客服管理员运营后台

**Input**: [spec.md](./spec.md) · [plan.md](./plan.md) · [gap-analysis.md](./gap-analysis.md)

**Prerequisites**: 009 Phase 1 鉴权（T001–T005）✅

## Phase 1 — 骨架与坐席（P1 MVP）✅

- [x] T101 `admin_store.py` + 自动 seed DEMO 坐席
- [x] T102 handoff 读 DB（无需单独 migrate 脚本）
- [x] T103–T104 `/api/v1/admin/agents` CRUD + `admin_service.py`
- [x] T105 `AdminShell.jsx` + `AdminApp.jsx` + `AdminLogin.jsx`
- [x] T106 `pages/AgentManagement.jsx`
- [x] T107 `pages/RoutingRules.jsx` 嵌入 HandoffAdmin
- [ ] T108 E2E：坐席 CRUD → desk 可见

## Phase 2 — 队列监管（P1）✅

- [x] T109–T110 queue snapshot + reassign API
- [x] T111–T112 QueueMonitor + Dashboard
- [ ] T113 E2E ADMIN-Q*

## Phase 3 — 审计与回放（P2）✅

- [x] T114–T116 audit events + transcript + AuditLog UI
- [ ] T117 E2E ADMIN-U*

## Phase 4 — 质检与审批（P2）

- [x] T118 ObserverQC 页
- [x] T119–T120 补偿审批 `approval_requests` + Approvals.jsx
- [x] T121 E2E ADMIN-QC/AP（`run_admin_operations_e2e.py`）

## Phase 5 — 报表（P3）

- [x] T122–T123 Reports + CSV 导出
- [x] T124 i18n admin.* 审批/报表文案
- [x] T125 `run_admin_operations_e2e.py` ≥15 PASS
