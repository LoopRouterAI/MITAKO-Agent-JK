# Feature Specification: Companion 专属 Agent 独立产品线（005）

**Feature Directory**: `specs/005-companion-agent-platform`

**Created**: 2026-06-19（系统级沉淀更新：2026-06-20）

**Status**: Spec Ready — **待 Phase C 实施**（在 009+008 之后）

**Depends on**: 009 鉴权模式可复用；与 007/008 **数据完全隔离**

**Input**: 在 MITAKO 客服体系之外，建设第二套「陪伴式对话」多系统：情绪价值、专属人格、消费助理；代码/会话/DB 与客服 Demo 隔离。人工协同走独立 `/companion-desk`。

> 原 `.specify/specs/005-*` 内容已升格至本目录并补充 gap-analysis、plan、tasks。

---

## 产品定位对比

| 维度 | MITAKO 客服 (`/`) | Companion (`/companion`) |
|------|---------------------|--------------------------|
| 核心使命 | SOP 客服、查单、转人工 | 情绪陪伴 + 生活/消费助理 |
| 用户关系 | 平台客服 ↔ 会员 | 专属 Agent ↔ 主人 |
| 人格 | 固定「虾饺」 | 用户命名、性格模板 |
| 数据 | `handoff.db` + mock 订单 | **`companion.db`** |
| 人工协同 | `/desk` | **`/companion-desk`** |
| API | `/api/v1/*` | **`/api/v2/companion/*`** |

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 专属身份与 Onboarding (Priority: P1)

高级付费用户首次进入 Companion，完成 Agent 命名（敏感词过滤）、称谓、性格模板、头像风格；配置持久化到 `companion.db`。

**Acceptance Scenarios**:

1. **Given** 新用户，**When** 完成 Onboarding，**Then** persona 持久化且对话使用设定称谓。
2. **Given** 侮辱性名称，**When** 保存，**Then** 拒绝并 i18n 提示。

---

### User Story 2 - 情绪陪伴对话 (Priority: P1)

20+ 轮 SSE 对话稳定；无 SOP 卡片强插；安全策略拦截违法/色情/自伤内容。

**Acceptance Scenarios**:

1. **Given** 情绪倾诉，**When** Agent 回复，**Then** 先共情后建议，非 FAQ 甩锅。
2. **Given** 越界请求，**When** 识别，**Then** 温和拒绝。

---

### User Story 3 - 消费助理 (Priority: P2)

盯单、查价 mock、wishlist 工单；状态变更触发 Agent 主动提醒。

---

### User Story 4 - 兼职客服子模式 (Priority: P3)

真实售后诉求时切换「客服模式」UI，可走 companion 专属转人工（不进 `/desk`）。

---

### User Story 5 - 双系统隔离 (Priority: P1)

`/` 与 `/companion` 同浏览器多标签：session、DB、SSE 互不影响。

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Companion MUST 使用独立 SQLite `data/companion.db`。
- **FR-002**: API MUST 挂载 `/api/v2/companion/*`，不得写 `/api/v1/handoff/*`。
- **FR-003**: 前端 MUST 独立 hook（禁止 import `useChatSSE.js`）。
- **FR-004**: Onboarding + persona CRUD MUST 完整实现（非占位页）。
- **FR-005**: `POST /api/v2/companion/chat` SSE MUST 支持 20 轮稳定对话。
- **FR-006**: 敏感词/安全策略 MUST 服务端校验。
- **FR-007**: `/companion-desk` MUST 为独立运营台（Phase D），不与 `/desk` 共享队列。
- **FR-008**: 全用户可见文案 MUST i18n（`companion.*`）。
- **FR-009**: E2E `run_companion_smoke.py` MUST ≥12 PASS。

## Success Criteria

- **SC-001**: 双标签隔离测试 100% 无串 session。
- **SC-002**: Onboarding 完成率 >80%（内部）。
- **SC-003**: 20 轮对话无空白/重复 bubble。
- **SC-004**: 与 handoff.db 零表共享。

## Out of Scope (005 v1)

- 真实支付/会员等级 API
- APNs/FCM 推送（可用「下次上线提醒」模拟）
- 私域社群
- 与 MITAKO 订单库实时同步（先用 companion mock）

## 当前实现状态（2026-06-20）

见 [`gap-analysis.md`](./gap-analysis.md)：仅 URL/构建脚手架，**不具备商业演示能力**。
