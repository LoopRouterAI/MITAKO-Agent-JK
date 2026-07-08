# Tasks: 商业级客服 POC 专业化升级

**Input**: Design documents from `specs/001-customer-poc-professional-upgrade/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

## Phase 1: Setup

**Purpose**: 固化本轮需求与工程边界。

- [ ] T001 写入本轮计划、研究、数据模型、接口契约和 quickstart 到 `specs/001-customer-poc-professional-upgrade/`
- [ ] T002 [P] 在 `docs/product/` 或本 feature 目录沉淀本轮经验，说明为什么移除旧陪伴/角色扮演入口、为什么不伪装真实甲方接口

---

## Phase 2: Foundational

**Purpose**: 修复会影响商业 POC 信任和安全的基础问题。

- [ ] T003 修复 `/api/v1/handoff/reset` 权限边界，修改 `main.py`
- [ ] T004 [P] 修复全局滚动和强制黑边/硬阴影覆盖，修改 `src/index.css` 与 `src/styles/tokens.css`
- [ ] T005 [P] 统一客服角色、升级处理、移动端操作等低理解成本文案，修改 `src/i18n/zh-CN.js`
- [ ] T006 增强队列快照等待时长、最长等待、平均等待和失败反馈数据，修改 `admin_service.py` 与 `handoff_store.py`

---

## Phase 3: User Story 3 - 用户端客服看起来专业且不误导 (Priority: P1)

**Goal**: 只读卡片不再像按钮，可操作卡片有明确按钮。

**Independent Test**: 用户端触发服务处理进度卡，观察者能分辨它是只读状态摘要。

- [ ] T007 [US3] 重构 `BusinessActionCard` 的状态摘要布局，修改 `src/components/cards/openUILibrary.jsx`
- [ ] T008 [US3] 检查用户端聊天关键卡片在移动端不溢出，必要时修改 `src/components/chat/MessageList.jsx`

---

## Phase 4: User Story 2 - 一线客服能高效接单、查询、转交和结案 (Priority: P1)

**Goal**: VIP客服在桌面和移动端都能完成接手、回复、转交/升级、结案。

**Independent Test**: 选择任意演示会话，2 次点击内进入接手/回复或转交/升级/结案路径。

- [ ] T009 [US2] 给人工台增加刷新状态、错误提示和更真实的队列摘要，修改 `src/desk/HumanAgentDesk.jsx`
- [ ] T010 [US2] 将接手从标题行按钮改成确认面板/弹窗语义，修改 `src/desk/HumanAgentDesk.jsx`
- [ ] T011 [US2] 增加结案入口并调用 `POST /api/v1/handoff/close`，修改 `src/desk/HumanAgentDesk.jsx`
- [ ] T012 [US2] 优化人工台移动端布局为可滚动分段视图，修改 `src/desk/HumanAgentDesk.jsx` 与 `src/index.css`
- [ ] T013 [US2] 为发送、删除、转交等图标按钮补充可访问标签和确认，修改 `src/desk/HumanAgentDesk.jsx`

---

## Phase 5: User Story 1 - 客服主管能一眼判断系统是否有价值 (Priority: P1)

**Goal**: 后台首页、队列、报表、运维大盘能表达客服业务指标和系统健康。

**Independent Test**: 打开管理中心后 3 分钟内能说清队列压力、人工介入压力和系统健康状态。

- [ ] T014 [US1] 优化后台 Shell 风格和演示数据状态入口，修改 `src/admin/AdminShell.jsx`
- [ ] T015 [US1] 升级监管大盘为关键指标卡和队列压力摘要，修改 `src/admin/pages/Dashboard.jsx`
- [ ] T016 [US1] 优化队列监控：等待时长、排队顺序、目标客服未选提示、转交失败反馈，修改 `src/admin/pages/QueueMonitor.jsx`
- [ ] T017 [US1] 升级运营报表为 Leader 可读指标视图，修改 `src/admin/pages/Reports.jsx`
- [ ] T018 [US1] 升级 7x24 运维为健康 BI，修改 `src/admin/pages/OpsMonitor.jsx` 与 `ops_service.py`
- [ ] T019 [US1] 让补偿审批区分普通申请和主管审批语义，修改 `src/admin/pages/Approvals.jsx`
- [ ] T020 [US1] 让服务质检展示待复盘、需跟进、已通过状态或可解释空状态，修改 `src/admin/pages/ObserverQC.jsx`

---

## Phase 6: User Story 4 - 视觉审核工作台能融入客服工单流程 (Priority: P2)

**Goal**: 三大审核任务可直达，并说明未来接口接入和手动补件边界。

**Independent Test**: 三个 `scenario` 子入口能直接进入对应审核任务。

- [ ] T021 [US4] 补充 `workbench.html?scenario=...` 直达逻辑、ARIA 状态和客服友好说明，修改 `poc/visual_review_poc/workbench.html`
- [ ] T022 [US4] 检查 `workbench_server.py` 的错误提示是否面向客服可理解，必要时调整文案

---

## Phase 7: User Story 5 - 团队能持续迭代而不被旧设计污染 (Priority: P2)

**Goal**: 新研发能通过当前文档理解边界、验收和踩坑经验。

**Independent Test**: 只读本 feature 文档和文档首页，能解释当前 POC 边界。

- [ ] T023 [US5] 更新内部/甲方文档入口，指向当前有效交付说明，修改 `我方内部开发文档/index.html` 与 `甲方沟通交付文档/index.html`（如存在）
- [ ] T024 [US5] 整理过旧视觉审核/模型选型报告入口，避免误导当前客服 POC 验收

---

## Phase 8: Verification

**Purpose**: 回归构建、核心 smoke 和对抗式代码审查。

- [ ] T025 运行 `npm run build`
- [ ] T026 运行 `python scripts/check_visual_workbench_smoke.py`
- [ ] T027 运行或人工检查 `http://127.0.0.1:8000/desk` 的 390px 移动端布局
- [ ] T028 启动 3 个子 Agent 做改版后对抗式代码审查
- [ ] T029 根据审查结果修复 P0/P1 问题并记录剩余风险

## Dependencies & Execution Order

- Phase 1 -> Phase 2 -> US3/US2/US1 -> US4/US5 -> Verification。
- T003 是 P0 安全项，必须优先。
- US3、US2、US1 修改文件基本不同，可并行，但最终需统一风格。

## MVP Scope

本轮必须完成 T003、T004、T007、T009-T012、T015-T018、T021、T025-T027。其余进入同轮可交付增强。
