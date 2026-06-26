# Feature Specification: 007 生产化加固（009）

**Feature Directory**: `specs/009-cs-production-hardening`

**Created**: 2026-06-20

**Status**: Spec Ready — **当前 Spec-Kit 实施入口**

**Depends on**: `007` UAT 基线（51/51 E2E 已通过）

**Blocks**: `008` 鉴权基础、`005` 可选复用 JWT/Redis 模式

**Input**: 将 007 验收中评级为 Demo+/UAT 弱项的全部 FR/SC 升级至生产可交付；并完成鉴权、WS 稳定性、SLA worker、多实例、观测、IM 抽象等共性缺口。私域社群不在范围。

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 安全鉴权基座 (Priority: P1)

作为**甲方安全负责人**，我需要 `/admin` 与 `/desk` 的变更类 API 必须携带有效 token，防止未授权修改路由或冒充坐席。

**Independent Test**: 无 token `PUT routing` → 401；desk `accept` 无 token → 401。

**Acceptance Scenarios**:

1. **Given** 有效 JWT，**When** desk 接单，**Then** 200 且 audit 记录 agent_id。
2. **Given** token 过期，**When** 调用 API，**Then** 401 且前端引导重新登录。

---

### User Story 2 - WebSocket 生产级稳定 (Priority: P1)

作为**终端用户与坐席**，长连接在 30 分钟会话内不因静默断开；断线后自动重连并补拉增量消息。

**Acceptance Scenarios**:

1. **Given** WS 连接 60s 无业务消息，**When** ping/pong 正常，**Then** 连接保持。
2. **Given** 服务端重启，**When** 客户端重连，**Then** ≤5s 恢复且 `messages?since=` 无丢失。

---

### User Story 3 - desk 实时同步（消除 poll 延迟）(Priority: P1)

作为**人工客服**，工作台 MUST 通过 WebSocket 接收新用户消息与转交事件，p95 延迟 ≤1s。

**Acceptance Scenarios**:

1. **Given** desk 已 WS 连接，**When** 用户发消息，**Then** desk UI ≤1s 显示，无需点刷新。

---

### User Story 4 - SLA 分布式可靠执行 (Priority: P1)

作为**运营方**，SLA 超时转交在单进程/多 worker 部署下**恰好执行一次**，不重复转交。

**Acceptance Scenarios**:

1. **Given** 两个 worker 同时 tick，**When** 会话首响超时，**Then** 仅产生一条 timeout TransferEvent。

---

### User Story 5 - 用户端升级/转交感知 (Priority: P2)

作为**终端用户**，当会话被升级或转交时，我应在聊天区看到明确 i18n 系统提示（负责专员变更）。

**Acceptance Scenarios**:

1. **Given** escalate 完成，**When** 用户端 poll/WS，**Then** 出现「已为您升级至 XX 专员组」类消息。

---

### User Story 6 - 状态机与 i18n 补全 (Priority: P2)

补全 `closed` 归档、FR-012 硬编码清理、Playwright 动画降级用例。

---

### User Story 7 - 可观测与 IM 抽象 (Priority: P2)

结构化日志、Prometheus metrics、`HandoffBackend` 接口（默认 SQLite，预留 Chatwoot）。

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: JWT 鉴权 middleware 覆盖 `/api/v1/admin/*` mutating 与 `/api/v1/desk/*` mutating。
- **FR-002**: WS Hub MUST ping/pong + 客户端指数退避重连（max 30s）。
- **FR-003**: desk SPA MUST 使用 `useHandoffSync`（或 desk 专用 hook）WS 优先。
- **FR-004**: SLA MUST 由 Celery Beat 触发；Redis 分布式锁保证幂等。
- **FR-005**: Redis pub/sub MUST 广播 WS 事件以支持多 uvicorn worker。
- **FR-006**: escalate/transfer MUST 向用户端写入 i18n system message。
- **FR-007**: `closed` 状态 MUST 可归档会话且 desk 列表移除。
- **FR-008**: observer 回复 MUST 写入 `observer_audits`（供 008 QC）。
- **FR-009**: 用户/desk/admin 可见硬编码 MUST 迁入 i18n。
- **FR-010**: `HandoffBackend` Protocol + `SqliteHandoffBackend` 默认实现。
- **FR-011**: `/metrics` 暴露 handoff_queue_depth、sla_timeouts_total、ws_connections。
- **FR-012**: E2E `run_production_hardening_e2e.py` MUST ≥20 PASS 且原 51 项不退化。

## Success Criteria

- **SC-001**: 鉴权绕过测试 0 成功（安全扫描或 E2E）。
- **SC-002**: desk 消息 p95 ≤1s（WS 路径，本地压测 100 条）。
- **SC-003**: SLA 双 worker 重复转交率 0%。
- **SC-004**: 007 原 51/51 E2E 仍 PASS。
- **SC-005**: code-review P1 项全部关闭。

## Out of Scope

- 008 完整 admin UI（仅提供 auth 模块供其使用）
- Companion 005
- 私域社群
