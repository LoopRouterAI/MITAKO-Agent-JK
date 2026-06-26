# Feature Specification: 客服管理员运营后台（008）

**Feature Directory**: `specs/008-cs-admin-operations-platform`

**Created**: 2026-06-20

**Status**: Spec Ready — 待实现

**Depends on**: `007` UAT 基线、`009` 鉴权与观测基础（可并行 P1 模块）

**Input**: 甲方需要完整的人工客服**管理员后台**，而非 007 中仅用于演示的「转人工路由 JSON 页」。须覆盖坐席管理、队列监管、SLA 看板、转交审计、旁听质检、补偿审批与运营报表。参考 `specs/02-AI客服Agent系统设计.md` 观测/运营层与权限矩阵。

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 管理员登录与分级权限 (Priority: P1)

作为**甲方客服运营主管**，我需要通过账号登录 `/admin`，且不同角色只能访问其权限范围内的模块（如 BPO 外包经理不可改安全规则）。

**Why this priority**: 无鉴权的管理后台不能交付甲方；007 当前 `/admin` 公开可写属 P0 风险。

**Independent Test**: 未登录访问 `PUT /api/v1/admin/*` 返回 401；`operator` 角色无法访问「补偿审批」。

**Acceptance Scenarios**:

1. **Given** 有效管理员 token，**When** 打开 `/admin`，**Then** 进入 Dashboard，显示当前在线坐席数与排队数。
2. **Given** 无 token，**When** 调用 mutating admin API，**Then** 401/403，前端跳转登录页。
3. **Given** `bpo_manager` 角色，**When** 访问「路由规则」，**Then** 可编辑；**When** 访问「系统安全规则」，**Then** 只读或不可见。

---

### User Story 2 - 坐席与组织管理 (Priority: P1)

作为**运营管理员**，我需要维护坐席工号、姓名、所属团队（外包 A/B、甲方 VIP）、tier（standard/supervisor）、技能标签与启用状态，供 `/desk` 登录选择。

**Why this priority**: 当前 `_DEMO_AGENTS` 硬编码无法反映甲方 BPO 组织变更。

**Independent Test**: Admin 新增坐席 CS-2001 → `/desk` 工号下拉可见 → 可成功接单。

**Acceptance Scenarios**:

1. **Given** 管理员创建坐席，**When** 保存，**Then** 写入 `agent_profiles` 表且 desk API 返回该坐席。
2. **Given** 坐席被禁用，**When** desk 尝试以其 ID 接单，**Then** 拒绝并提示「账号已停用」。
3. **Given** 修改 tier 为 supervisor，**When** L5+规则会话入队，**Then** 该坐席可接「需主管」队列。

---

### User Story 3 - 队列与 SLA 监管大盘 (Priority: P1)

作为**值班主管**，我需要实时看到：排队会话数、平均等待、SLA 即将超时/已超时列表、需主管标识会话，并可对单会话执行「重新分配」或「强制转交」。

**Why this priority**: 甲方日常运营核心场景；007 仅有 desk 侧列表，无管理视角。

**Independent Test**: 模拟 3 个 queuing 会话 → Dashboard 显示 3 → 主管强制分配给指定坐席 → desk 可见 pending。

**Acceptance Scenarios**:

1. **Given** 存在 queuing 会话，**When** 打开队列监控，**Then** 列表含 session_id、等待时长、required_tier、情绪等级摘要。
2. **Given** connected 会话 SLA 首响超时，**When** 看板刷新，**Then** 标记为「首响超时」并链到审计记录。
3. **Given** 主管点击「重新分配」，**When** 选择目标坐席，**Then** 写入 `TransferEvent(manual_reassign)` 且用户端状态一致。

---

### User Story 4 - 转交审计与会话回放 (Priority: P2)

作为**质检主管**，我需要按 session / 坐席 / 时间范围查看 accept、colleague、timeout、escalate 全链路审计，并可查看会话消息 transcript（含 AI 历史摘要）。

**Why this priority**: 商业交付必备合规与纠纷追溯能力。

**Independent Test**: 完成 A→B 转同事 → Audit 页可见两条 event + 完整消息数。

**Acceptance Scenarios**:

1. **Given** 会话发生过 escalate，**When** 审计页筛选 `escalate`，**Then** 显示 from/to/note/timestamp。
2. **Given** 选中 session，**When** 打开回放，**Then** 展示 user/human/system/observer 消息时间线。

---

### User Story 5 - @虾饺 旁听质检 (Priority: P2)

作为**质检员**，我需要抽检人工接入后的 `@虾饺` 旁听回复，系统自动标记「疑似越权承诺」供人工复核。

**Why this priority**: 007 FR-009/SC-005 要求策略约束；缺 audit UI 无法运营抽检。

**Independent Test**: 注入含「全额退现金」的 observer 回复 → QC 队列出现 flagged 项。

**Acceptance Scenarios**:

1. **Given** observer 回复命中策略词表，**When** 写入消息，**Then** `observer_audits.flagged=true` 且 QC 列表可见。
2. **Given** 质检员标记「误报」，**When** 提交复核，**Then** 状态变为 reviewed 并记录操作人。

---

### User Story 6 - 补偿审批队列 (Priority: P2)

作为**主管**，我需要审批 AI 或坐席发起的 10–100 元补偿申请；>100 元需多级审批（Demo 可二级）。

**Why this priority**: `specs/02` §8.1 权限矩阵明确要求；当前系统无审批流。

**Independent Test**: 创建 50 元补偿申请 → 主管批准 → 用户侧可见补偿结果（或工单状态更新）。

**Acceptance Scenarios**:

1. **Given** 待审批申请，**When** 主管批准，**Then** 状态 approved 并通知来源会话。
2. **Given** >100 元申请，**When** 一线主管批准，**Then** 仍 pending 直至 `super_admin` 二级批准。

---

### User Story 7 - 运营报表 (Priority: P3)

作为**甲方管理层**，我需要查看日/周：会话总量、AI 解决率、转人工率、平均排队时长、SLA 达标率、旁听越权率。

**Independent Test**: 选择日期范围 → 导出 CSV 或页面图表展示。

---

### Edge Cases

- 管理员与 desk 同时修改同坐席：乐观锁或 updated_at 冲突提示。
- 强制重新分配时用户正在输入：消息不丢失，新负责人继承 transcript。
- 禁用当前 connected 坐席：需先转交或提示主管处理。
- 路由规则 mid-flight 变更：与 007 一致，不影响已在队会话除非显式重分配。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `/admin` MUST 提供登录态与 RBAC（至少：`super_admin` | `supervisor` | `bpo_manager` | `qc_viewer`）。
- **FR-002**: 所有 `POST/PUT/DELETE /api/v1/admin/*` MUST 校验 token；只读 GET 可配置为登录后可见。
- **FR-003**: 坐席档案 MUST 持久化于 SQLite（或共用 handoff.db 新表），`/desk/agents` MUST 读 DB。
- **FR-004**: Dashboard MUST 展示 queuing/connected/escalated 计数与 SLA 告警列表。
- **FR-005**: 管理员 MUST 可对会话执行 manual_reassign / force_close（审计必填 note）。
- **FR-006**: 审计 UI MUST 覆盖 `handoff_transfer_events` 全 event_type。
- **FR-007**: Observer 消息 MUST 写入 `observer_audits` 并支持 flagged + 人工复核。
- **FR-008**: 补偿审批 MUST 实现至少一级主管审批；>100 元二级（可配置阈值）。
- **FR-009**: 路由规则编辑 MUST 保留 007 行为（新会话生效）；UI 需规则优先级与生效预览。
- **FR-010**: 所有管理员可见文案 MUST i18n（`admin.*` namespace）。

### Key Entities

- **AdminUser**: id, username, role, team_scope, password_hash/token, last_login
- **AgentProfile**: agent_id, name, team, tier, skills[], enabled, created_at
- **QueueSnapshot**: 聚合视图（非持久表）
- **ObserverAudit**: message_id, session_id, content_hash, flagged, policy_hits[], reviewer_id, status
- **ApprovalRequest**: id, session_id, amount, type, status, approver_chain[], created_at

## Success Criteria *(mandatory)*

- **SC-001**: 100% mutating admin API 在未授权时返回 401/403。
- **SC-002**: 坐席 CRUD 到 desk 可见 ≤ 5s（或立即 reload）。
- **SC-003**: 主管可在 3 次点击内完成「查看排队 → 强制分配」。
- **SC-004**: 审计页可还原任一会话完整 TransferEvent 链（与 DB 100% 一致）。
- **SC-005**: Admin E2E 自动化 ≥ 15 项 PASS。

## Assumptions

- 首版鉴权可用 JWT + SQLite admin_users（甲方 SSO 为 009/008 Phase 2 扩展点）。
- 报表先用 SQL 聚合 + 前端图表；复杂 BI 接 Grafana 为 P3 可选项。
- Chatwoot 对接仍走 009 `HandoffBackend` 抽象，008 不直接绑 Chatwoot。

## Out of Scope (008 v1)

- 完整 WFM 排班引擎
- 录音合规、屏幕录制
- 私域社群运营模块

## 与 007 现状关系

| 007 已有 | 008 扩展 |
|----------|----------|
| `HandoffAdmin.jsx` 路由+SLA | 迁入「路由策略」子模块，外加 6+ 模块 |
| `handoff_transfer_events` 表 | 审计 UI + 导出 |
| `handoff_routing.json` | DB 或 JSON 双写（plan 阶段定） |
| 无 admin 用户 | `admin_users` + JWT |
