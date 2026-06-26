# Tasks: 009 生产化加固

**Input**: [spec.md](./spec.md) · [plan.md](./plan.md) · [gap-analysis.md](./gap-analysis.md)

**Prerequisites**: 007 UAT 51/51 基线

## Phase 1 — 鉴权基座（阻塞 008）

- [x] T001 [P] 创建 `auth/jwt_utils.py` + `auth/roles.py`（super_admin/supervisor/bpo_manager/qc_viewer/desk_agent）
- [x] T002 创建 `auth/middleware.py` + `auth/store.py`；保护 mutating admin/desk 路由（`MITAKO_AUTH_REQUIRED=1` 生效）
- [x] T003 `POST /api/v1/auth/login` + `GET /api/v1/auth/status` + seed（`scripts/seed_auth.py`）
- [x] T004 [P] `src/admin/AdminLogin.jsx` + `AdminApp.jsx` token 门控
- [x] T005 [P] `DeskApp.jsx` + `DeskLogin.jsx` 登录门控
- [x] T006 E2E：AUTH 无效登录 + token 流程（`run_admin_operations_e2e.py`；严格 401 需 `MITAKO_AUTH_REQUIRED=1`）

## Phase 2 — WebSocket 生产级

- [x] T007 `handoff_ws.py` + main.py WS ping/pong（30s）
- [x] T008 `useHandoffSync.js` 指数退避重连
- [x] T009 [US3] desk 接入 `attachHandoffTransport` WS
- [ ] T010 E2E：desk WS 收用户消息 ≤1s（WS-*）

## Phase 3 — SLA 分布式

- [x] T011 `sla_lock.py` 分布式锁（Redis 可选 + 进程内 fallback）
- [x] T012 集成至 `process_sla_timeouts` 幂等
- [ ] T013 Celery Beat 替代 main.py timer（生产 Linux 部署项）
- [x] T014 docker-compose.yml（redis + celery worker）可选
- [ ] T015 E2E：SLA-* 模拟超时单次转交

## Phase 4 — 体验与数据补全

- [x] T016 [US5] escalate 用户端 i18n 系统提示增强
- [x] T017 `closed` 状态 + `POST /api/v1/handoff/close`
- [x] T018 `observer_audits` 表 + 写入 + admin QC 页
- [ ] T019 i18n sweep 全量
- [x] T020 Playwright reduced-motion 用例

## Phase 5 — 架构与观测

- [x] T021 `handoff_backend/protocol.py`（预留 Chatwoot）
- [x] T022 Redis pub/sub 多 worker WS 广播
- [x] T023 `GET /metrics`
- [x] T024 structlog 关键路径

## Phase 6 — 验收门禁

- [x] T025 完成 `run_production_hardening_e2e.py` ≥20 项
- [x] T026 回归 `run_full_pipeline_e2e.py` 51/51（并入生产套件 **68/68**）
- [ ] T027 更新 `code-review.md` 关闭 P1 项
- [ ] T028 更新 `Docs/CodeWiki.md` + `codegraph sync`

## 依赖顺序

```
T001–T006 → T007–T010 → T011–T015 → T016–T020 → T021–T024 → T025–T028
```

**当前建议起点**: T001（鉴权模块）
