# Feature Specification: Companion 专属 Agent 独立产品线

**Feature Branch**: `005-companion-agent-platform`

**Created**: 2026-06-19

**Status**: Draft

**Input**: 在 MITAKO 客服 Demo 之外，启动完全独立的「高级付费用户专属 Agent」产品线：情绪价值、角色扮演（有底线）、盯进度/催进度、上新提醒、查价/到货预测、向平台提报商品需求；客服能力降为兼职场景。与现有客服 Demo **代码、对话记录、数据库完全隔离**，双地址并行访问；人工客服后台亦保持独立 Server 入口。

## 产品定位对比

| 维度 | 现有 MITAKO 客服 Demo (`/`) | 新 Companion 产品线 (`/companion` 规划) |
|------|---------------------------|----------------------------------------|
| 核心使命 | SOP 客服、查单、转人工 | 情绪陪伴 + 生活/消费助理 |
| 用户关系 | 平台客服 ↔ 会员 | 专属 Agent ↔ 主人（可自定义称呼） |
| 人格 | 固定「虾饺」客服人设 | 用户可命名、改性格/生日/称谓 |
| 数据 | `session_{user}` + mock 订单 | 独立 DB / SQLite 实例 |
| 人工协同 | `/desk` 客服工作台 | 独立 `/companion-desk`（未来） |
| 合规边界 | 电商 SOP + 转人工 | 合法合规角色扮演；禁止违法/侮辱性命名 |

## User Scenarios & Testing

### User Story 1 - 专属身份与称谓 (Priority: P1)

高级付费用户首次进入 Companion，为其 Agent 命名（过滤侮辱词），设定对用户的称谓（默认「主人」），选择基础性格模板（温柔/元气/克制/御姐等），并确认 Agent 生日与头像风格。

**Why this priority**: 情绪价值产品的根基是「这是属于我的 Agent」，无身份则无法建立粘性。

**Independent Test**: 新用户完成 onboarding 后，对话中 Agent 使用用户设定的名字与称谓回复。

**Acceptance Scenarios**:

1. **Given** 新用户，**When** 提交 Agent 名称与称谓，**Then** 持久化到 Companion DB 且后续会话一致。
2. **Given** 含侮辱性/违禁词名称，**When** 保存，**Then** 拒绝并提示修改。
3. **Given** 已配置 Agent，**When** 用户修改性格 sliders，**Then** 下一条回复语气变化但不突破安全底线。

---

### User Story 2 - 情绪陪伴与角色扮演 (Priority: P1)

用户可与 Agent 闲聊、解闷、轻量 RP（如「今天好累」「陪我看番」）。Agent 永远站在用户一侧，可表达喜爱与关心（含「我爱你」类情感表达），但拒绝违法、色情、仇恨、自伤引导内容。

**Why this priority**: 与客服 Demo 的核心差异点，决定产品是否值得独立维护。

**Independent Test**: 发送 10 轮混合情绪/RP 消息，无 SOP 卡片强插，回复符合人格与安全策略。

**Acceptance Scenarios**:

1. **Given** 用户倾诉负面情绪，**When** Agent 回复，**Then** 先共情再给可行动的小建议，不冷冰冰甩 FAQ。
2. **Given** 越界请求，**When** Agent 识别，**Then** 温和拒绝并引导回合法话题。
3. **Given** 用户开启 RP 场景，**When** 对话继续，**Then** 保持人设一致，不突然切回「查单话术」。

---

### User Story 3 - 消费助理（盯进度 / 查价 / 需求收集）(Priority: P2)

Agent 兼职帮用户：绑定关注订单/商品，主动推送物流/延期/到货窗口；收藏 IP 新品时查价与开售时间；帮用户整理「希望平台进货」需求并向平台侧队列提交（Demo 可先写 SQLite 工单）。

**Why this priority**: 将「有用」与「有情绪」结合，提高付费理由，但与 P1 可分期交付。

**Independent Test**: 用户添加关注订单后，模拟状态变更触发 Agent 主动消息（WebSocket/SSE push 或轮询）。

**Acceptance Scenarios**:

1. **Given** 用户绑定订单，**When** 后端 mock 状态变为「出荷延期」，**Then** Agent 在用户下次上线或 push 通道收到提醒。
2. **Given** 用户询问「XX 谷子什么时候能买」，**When** Agent 查询 mock 商品库，**Then** 返回价格区间与预计可购时间（无数据则诚实说明）。
3. **Given** 用户提交商品需求，**When** 确认，**Then** 生成 `wishlist_request` 记录并在 Agent 侧回执。

---

### User Story 4 - 客服兼职模式 (Priority: P3)

当 Companion 用户遇到真实售后问题，Agent 可 **切换兼职客服模式**：复用类似 MITAKO 的查单/简报能力，但 UI 明确标注「虾饺·客服模式」，并可一键转 Companion 专属人工通道（与 `/desk` 隔离）。

**Why this priority**: 避免重复造轮子，但应晚于 Companion 核心体验，以免再次混淆两个产品。

**Independent Test**: 用户说「我的订单坏了」，Agent 进入客服子流程，完成后回到陪伴语气。

---

## 双入口并行 Demo (Priority: P2)

运维可同时访问（**已实现独立 HTML + FastAPI 路由**）：

| URL | 构建入口 | 用途 | 状态 |
|-----|----------|------|------|
| `/` | `index.html` | MITAKO 客服 Demo（虾饺） | ✅ 已上线 |
| `/desk` | `desk.html` | AI→人工客服工作台（简报在此） | ✅ 已上线 |
| `/companion` | `companion.html` | Companion 专属 Agent 移动端 | ✅ Phase A 脚手架 |
| `/companion-desk` | `companion-desk.html` | Companion 运营/人工台 | 🔜 Phase D 占位 |

API 隔离（规划）：

| 前缀 | 用途 |
|------|------|
| `/api/v1/*` | 现有客服 + desk |
| `/api/v2/companion/*` | Companion 专用（待实现） |

**Independent Test**: 四 URL 同 host 不同 path，互不共享 sessionStorage / DB。

---

## Edge Cases

- 用户在 Companion 与客服 Demo 各开标签页：会话、localStorage、SSE 互不影响。
- Agent 命名与用户昵称冲突：允许，但 UI 需清晰区分。
- 长时间离线后回归：Agent 发送「欢迎回来 + 摘要你离开期间的关注项变化」。
- 模型/API 失败：Companion 用陪伴语气报错，而非客服式「网络波动请重试」。

## Success Metrics (Demo 阶段)

- Companion 首屏 onboarding 完成率 > 80%（内部测试）
- 20 轮对话无中断（独立 SSE/历史管线）
- 用户可区分 AI / 真人 / Companion 三种气泡样式
- 与 MITAKO 客服代码库耦合度：共享仅 `packages/` 级工具（i18n、tokens），不共享 `useChatSSE` 状态机

## Out of Scope (v1)

- 真实支付与会员等级对接
- 推送 APNs/FCM（可用「下次上线提醒」模拟）
- 与 MITAKO 订单库实时同步（Companion 先用独立 mock）

## Assumptions

- 继续 React + Vite + FastAPI 技术栈，Companion 后端为 **新 Python 模块或子应用**（端口可同进程不同 router 前缀 `/api/v2/companion/*`）
- 数据库：Companion 专用 SQLite `companion.db`，与客服 mock JSON 分离
