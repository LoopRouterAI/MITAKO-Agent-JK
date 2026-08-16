# Tasks: 007 人机协同客服平台

## Phase 1 — 核心链路 (P1)

- [x] T001 spec/research/plan/contracts/quickstart
- [x] T002 `config/handoff_routing.json` + `handoff_routing.py`
- [x] T003 `handoff_store.py` SQLite schema + CRUD
- [x] T004 重构 `handoff_service.py`：默认 standard、接入 store
- [x] T005 main.py：messages/user-message/routing API
- [x] T006 `RichTextContent.jsx` + desk/MessageList 复用
- [x] T007 `useHandoffSync` + useChatSSE 移除 mock
- [x] T008 i18n 排队/成功/旁听文案
- [x] T009 transfer/escalate 状态机 + desk UI
- [x] T010 SLA 后台任务 auto_transfer
- [x] T011 `handoff_observer.py` + @虾饺 API
- [x] T012 `XiaoJiaoObserverTransition` + HandoffQueueCard 文案
- [x] T013 npm run build + 重启后端
- [x] T014 quickstart 场景 A–E 自动化验收（`run_handoff_acceptance.py`，报告见 `tests/reports/`）
- [x] T021 全链路 E2E（代码/通信/链路/浏览器 × 三角色，`run_full_pipeline_e2e.py` **51/51**）

## Phase 3 — WebSocket + 管理后台 (P3)

- [x] T015 `handoff_ws.py` + main WS 路由 + service emit
- [x] T016 `useHandoffSync.js` WS 优先 + poll 兜底
- [x] T017 `/admin` + `HandoffAdmin.jsx` + PUT routing API
- [x] T018 E2E P3-1 / W1 场景
- [ ] T019 desk 端 WS 同步（可选，当前 poll 3–4s）
- [ ] T020 生产鉴权 + WS 心跳（见 code-review.md P1）
