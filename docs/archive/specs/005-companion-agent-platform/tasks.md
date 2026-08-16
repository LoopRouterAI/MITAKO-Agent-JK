# Tasks: 005 Companion 独立产品线

**Input**: [spec.md](./spec.md) · [plan.md](./plan.md) · [gap-analysis.md](./gap-analysis.md)

**Prerequisites**: 009 鉴权模式可复用；**建议** 008 Phase 1 完成后启动（降低并行冲突）

## Phase A — 核心对话（P1）

- [x] T201 创建 `companion_store.py` + `data/companion.db` schema
- [x] T202 创建 `companion_api.py` + `main.py` include
- [x] T203 `GET/PUT /api/v2/companion/persona/{user_id}`
- [x] T204 `companion_agent.py` + SSE `POST /chat`
- [x] T205 `useCompanionChat.js`
- [x] T206 `CompanionApp.jsx` 替换占位页
- [x] T207 `GET /api/v2/companion/messages`
- [x] T208 E2E 隔离脚本 COMP-ISO-*（`run_companion_features_e2e.py` COMP-desk-isolated）

## Phase B — Onboarding 与安全（P1）

- [x] T209 `OnboardingFlow.jsx`
- [x] T210 敏感词服务端拒绝（companion_store.validate_agent_name）
- [x] T211 i18n companion.* 基础文案
- [ ] T212–T213 E2E onboarding + 20 轮

## Phase C — 消费助理（P2）

- [x] T214 表 `watch_orders`, `wishlist`（companion.db）
- [x] T215 `POST /watch/orders` + `GET /watch/orders/{user_id}`
- [x] T216 查价 mock API `GET /products/search`
- [x] T217 UI：关注订单 / 需求提交卡片（CompanionAssistantPanel）

## Phase D — companion-desk + 兼职客服（P3）

- [x] T218 `companion-desk.html` → React SPA（CompanionDeskApp）
- [x] T219 `companion_handoff_*` 表 + `/api/v2/companion/desk/*`
- [x] T220 Agent `mode=cs_parttime` 子流程 + UI 角标 + 转 companion-desk
- [x] T221 E2E：companion 售后不进 `/desk` 队列（`run_admin_operations_e2e.py` COMP-*）

## Phase E — 验收

- [x] T222 冒烟 ≥12 PASS（并入 `run_admin_operations_e2e.py` + 全量 68/68）
- [ ] T223 更新 `Docs/CodeWiki.md` Companion 链路
- [ ] T224 `codegraph sync` + 更新 `00-delivery-roadmap.md` Phase C 状态

## 并行标记

T201–T207 可并行前端/后端（T205 依赖 T204 contract）
