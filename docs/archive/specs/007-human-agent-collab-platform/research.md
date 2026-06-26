# Research: 007 人机协同客服平台

## Decision: SQLite 作为移交会话持久层

**Rationale**: 商业项目需重启不丢会话、支持审计与 transcript；Win11 本地可零依赖部署，与项目现有 Chroma/SQLite 习惯一致。

**Alternatives considered**: 纯内存（已否决，不符合商业交付）；PostgreSQL（过重，当前单机交付阶段）。

## Decision: 路由规则外置 JSON + 默认 standard

**Rationale**: FR-005 要求默认外包一线接单；高情绪→主管为 opt-in 规则，运营可改 JSON 无需改代码。

**Alternatives considered**: 硬编码 emotion≥5（已否决）；完整 Admin UI（P3）。

## Decision: 长轮询同步（1.5s）+ 消息 since 游标

**Rationale**: 现有栈为 FastAPI + React，无 WebSocket 基础设施；商业 Demo 验收 SC-003 要求 ≤3s，轮询可满足；后续 plan 可升级 SSE `/handoff/stream`。

**Alternatives considered**: WebSocket（Phase 2）；用户端 setTimeout mock（已否决）。

## Decision: @虾饺 旁听独立 API + 策略 Prompt

**Rationale**: 与主 Agent 图解耦，避免转人工后误触发 SOP/补偿节点；策略层显式「帮催不帮讨」。

**Alternatives considered**: 复用 LangGraph 全链路（风险高，易越权承诺）。

## Decision: 共享 RichTextContent 组件

**Rationale**: `#词块#` / meme 渲染逻辑已在 `formatText.js`，抽 React 组件供 MessageList 与 desk 复用，保证 SC-004。

**Alternatives considered**: desk 复制 CSS（已否决，双端漂移）。

## Decision: 虾饺退下过渡用 CSS 动画 + reduced-motion 降级

**Rationale**: Constitution III 要求 prefers-reduced-motion；不引入 Lottie 新依赖，用现有品牌色与 avatar。

**Alternatives considered**: 视频/GIF（体积与 a11y 差）。
