# Feature Specification: 人机协同客服平台（移交 · 协作 · 旁听）

**Feature Directory**: `specs/007-human-agent-collab-platform`

**Created**: 2026-06-19

**Status**: UAT Ready (P1/P2/P3 implemented, E2E 51/51 passed 2026-06-20)

**Follow-on（系统级，待完成）**:

- `009-cs-production-hardening` — 007 弱项 + 生产共性缺口（**当前 Spec-Kit 实施入口**）
- `008-cs-admin-operations-platform` — 甲方完整管理员后台（非演示级路由页）
- `005-companion-agent-platform` — 陪伴式第二系统（脚手架 → 全栈）

**Roadmap**: [`specs/00-delivery-roadmap.md`](../00-delivery-roadmap.md)

**Input**: 用户要求重构 AI→人工移交体系：默认外包一线接单、可配置路由；专业客服协作（同事接管/超时转交/升级对口部门）；客户端排队与接入 UX；虾饺旁听与 @虾饺 协助；两端富文本能力一致。

> **说明**：007 的 `/admin` 仅交付「转人工路由/SLA 配置」最小页，**不等于**甲方管理员运营后台 — 见 008 gap-analysis。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 用户排队等待真实人工接入 (Priority: P1)

作为**终端用户**，当我申请或触发转人工后，我希望看到「正在帮您联系人工客服，当前人工坐席繁忙，正在帮您排队中」，并且**只有**后台客服确认阅读并接受转接后，才显示「已成功联系到人工客服」，并播放虾饺退下转旁听的过渡动画。

**Why this priority**: 这是转人工链路的核心信任契约；假接入或文案不符会直接破坏演示可信度。

**Independent Test**: 用户端发起转人工 → 仅见排队态 → 工作台未接单前状态不变 → 工作台确认接单 → 用户端变为已接入并播放过渡动画。

**Acceptance Scenarios**:

1. **Given** 用户已进入排队，**When** 工作台尚未点击「确认阅读并接受转接」，**Then** 用户端持续显示排队/繁忙文案，不得显示「已成功联系」。
2. **Given** 工作台客服已确认接单，**When** 用户端轮询或推送收到 `connected`，**Then** 排队卡更新为成功态，并触发虾饺退下旁听动画（支持 `prefers-reduced-motion` 降级为静态过渡）。
3. **Given** 用户排队中，**When** 用户继续发消息，**Then** 仍可与虾饺对话（查单/安抚），且排队状态不被错误清除。

---

### User Story 2 - 外包一线默认接单与可配置路由 (Priority: P1)

作为**运营管理员**，我希望默认所有会话由外包/普通客服接单；高情绪或 VIP 等场景可通过后台路由规则（可选）定向到总部或专业组，但**默认不**因情绪 Level≥5 自动锁定主管。

**Why this priority**: 与真实 BPO 外包模式一致，避免当前「高情绪只能主管接单」的错误默认。

**Independent Test**: 默认配置下 L5 会话可由一线 CS-0816 成功接单；开启「高情绪→主管队列」配置后，同场景走路由规则。

**Acceptance Scenarios**:

1. **Given** 系统默认路由配置，**When** 情绪 Level 5 会话进入队列，**Then** 任意 `standard` 客服均可接单。
2. **Given** 管理员启用「emotion_level ≥ 5 → supervisor_queue」规则，**When** 符合条件会话入队，**Then** 仅 supervisor 可接单，且队列标识「需主管」。
3. **Given** 路由规则变更，**When** 已在排队会话，**Then** 不因规则变更 mid-flight 强制踢出（除非运营显式「重新分配」）。

---

### User Story 3 - 多客服无缝协作与转交 (Priority: P1)

作为**人工客服**，我希望在同一会话中支持：手动转给同事、超时未回复由系统转下一位、客户要求升级时转部门/对口专员；多位客服可衔接同一客户，且移交简报与对话上下文完整传递。

**Why this priority**: 专业客服平台的基础能力，当前实现仅有「升级主管」单点且会断开已接入态。

**Independent Test**: A 接单 → A 转 B → B 继续回复；A 超时 → 系统自动 assign C；升级后用户端可见负责客服变更（可选轻提示）。

**Acceptance Scenarios**:

1. **Given** 客服 A 已接入，**When** A 发起「转交同事」并选择 B，**Then** B 收到待接管通知，确认后成为当前负责人，A 只读或退出；用户消息路由至 B。
2. **Given** 客服已接入且 SLA 超时（如 3 分钟未首响 / 5 分钟未回复），**When** 系统触发自动转交，**Then** 下一位可用同事被分配，原客服收到系统提示，简报追加「超时转交」记录。
3. **Given** 客户明确要求升级投诉，**When** 一线发起「升级对口部门」，**Then** 会话进入升级队列，目标部门客服可接单；用户端可显示「已为您升级至 XX 专员组」（文案可配置）。

---

### User Story 4 - 虾饺旁听与 @虾饺 协助 (Priority: P2)

作为**终端用户**，在人工接入后我仍可通过 `@虾饺` 请求 AI 以**中立、略倾向用户**的方式协助沟通——例如帮催进度、翻译诉求，但**不**帮着讨赔偿或越权承诺。

**Why this priority**: 差异化体验与真实协同场景，依赖 P1 双端消息同步完成后才有意义。

**Independent Test**: 人工已接入 → 用户发送 `@虾饺 帮我和专员说一下我很着急` → 虾饺生成旁听回复（帮催不帮讨）→ 人工客服工作台可见该条 AI 协助消息。

**Acceptance Scenarios**:

1. **Given** 人工已接入且虾饺处于旁听模式，**When** 用户 @虾饺，**Then** 触发旁听 Agent，回复遵守「帮催不帮讨」策略，且不与人工回复冲突抢占主通道。
2. **Given** 用户未 @虾饺，**When** 仅与人工对话，**Then** 虾饺不主动插话（除系统级进度提示）。
3. **Given** 虾饺旁听回复涉及补偿/退款，**When** 超出 AI 权限，**Then** 仅复述事实与进度，引导由人工专员定案。

---

### User Story 5 - 双端富文本与特殊用语一致渲染 (Priority: P2)

作为**人工客服**，我在工作台看到的 AI 历史、简报与用户消息中的 `#优先发货特权#`、`#500平台积分#`、`<meme:*>` 等，应与用户端 Chat 一致的视觉语义，避免 plain text 造成误读。

**Why this priority**: 两端能力不同步是当前可复现缺陷，影响简报专业度。

**Independent Test**: 含 `#优先发货特权#` 的会话移交后，用户端与 `/desk` 对话区/简报区渲染样式一致。

**Acceptance Scenarios**:

1. **Given** 消息含 `#词块#`，**When** 在 desk 会话区或简报摘录展示，**Then** 使用与用户端相同的 tag 高亮组件。
2. **Given** 人工在工作台回复含 `#词块#`，**When** 同步至用户端，**Then** 用户端同样正确渲染。

---

### Edge Cases

- 客服 A 接单后页面关闭：会话是否回到队列？默认保留 A 占用直至超时转交。
- 用户端与 desk 同时刷新：以服务端会话状态为准，避免双写冲突。
- 升级/转交过程中用户发消息：消息不丢失，进入缓冲并在新负责人接入后投递。
- 多标签 `@虾饺` 与 `@引用订单` 同句：解析优先级与歧义处理需定义。
- 演示环境内存队列重启：需明确为 Demo 限制或引入持久化（plan 阶段决策）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 区分会话状态：`queuing` | `accepted_pending`（可选）| `connected` | `transferring` | `escalated` | `closed`。
- **FR-002**: 用户端 MUST 仅在 `connected` 且服务端确认 `accepted_by` 后展示「已成功联系到人工客服」。
- **FR-003**: 排队态 MUST 使用统一文案：「正在帮您联系人工客服，当前人工坐席繁忙，正在帮您排队中」（i18n key，可带前方人数/预计等待）。
- **FR-004**: 接入成功 MUST 播放虾饺退下旁听过渡（动画 + 文案），并切换 presence 为「人工主答 + 虾饺旁听」。
- **FR-005**: 默认路由 MUST 允许所有 `standard` 客服接单；高情绪强制主管 MUST 为**可关闭**的后台配置项，默认关闭。
- **FR-006**: 工作台 MUST 支持：确认接单、手动转同事、升级部门/主管、查看完整移交简报（含真实意图/画像/建议方向/情绪触发词）。
- **FR-007**: 系统 MUST 支持 SLA 超时自动转交下一位同事（阈值可配置）。
- **FR-008**: 用户消息 MUST 与 desk 回复双向同步（不得使用前端 setTimeout 模拟人工回复）。
- **FR-009**: 人工接入后 MUST 支持 `@虾饺` 旁听请求，策略为中立翻译 + 帮催进度，禁止代用户索取超额赔偿。
- **FR-010**: 用户端与 desk MUST 共享同一套富文本渲染能力（`#词块#`、meme、action 剥离等）。
- **FR-011**: 多位客服衔接同一会话时 MUST 保留完整 transcript + 转交/升级审计记录。
- **FR-012**: 所有用户可见文案 MUST 走 i18n，禁止硬编码（含 desk 与排队 placeholder）。

### Key Entities

- **HandoffSession**: 会话 ID、状态、队列位置、当前负责人、历史负责人链、SLA 计时、路由标签。
- **HandoffBrief**: 移交简报（摘要、真实意图、对话回顾、画像、心理分析、建议方向、情绪触发词、专业移交原因）。
- **RoutingRule**: 条件（情绪/意图/VIP/金额）→ 目标队列/部门/技能组；启用开关与优先级。
- **AgentProfile**: 工号、姓名、团队、tier、技能标签、在线状态。
- **TransferEvent**: 类型（accept | colleague | timeout | escalate | department）、from_agent、to_agent、note、timestamp。
- **ObserverTurn**: 用户 @虾饺 触发的旁听消息，含策略约束标记。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% 的「已接入」展示均对应工作台一次成功的「确认阅读并接受转接」操作（零自动假接入）。
- **SC-002**: 默认配置下，L5 演示会话可由一线客服在 3 步内完成接单（选身份 → 读简报 → 确认）。
- **SC-003**: 人工回复从 desk 发出到用户端可见 ≤ 3s（Demo 轮询）或 ≤ 1s（若引入 SSE/WebSocket）。
- **SC-004**: 含 `#优先发货特权#` 的简报/消息在 user + desk 双端渲染一致率 100%。
- **SC-005**: `@虾饺` 旁听回复在抽检中 0 次出现「代用户索要超额赔偿/退现金承诺」类越权话术（策略层 + 抽检）。

## Assumptions

- 演示阶段可继续使用内存队列，但 FR-008 双端同步必须在 Demo 可验证，不能依赖前端 mock。
- 路由规则后台 UI 可在 P1 用配置文件/JSON，完整 Admin 控制台可放 P3。
- Chatwoot 或同类 IM 后端对接放在 plan 阶段，spec 只约束行为契约。
- 动画资源可使用现有虾饺形象 Lottie/CSS，具体资产在 plan 阶段选定。
- Constitution 中「L4+ 强化转人工路径」解释为**提示用户可申请**，而非强制主管队列。

## Out of Scope (v1 Spec)

- Companion 产品线人工台（见 005-companion-agent-platform）。
- 完整 WFM 排班、质检评分、录音合规。
- 生产级 SSO/RBAC（Demo 可用工号选择器，plan 阶段补安全）。
