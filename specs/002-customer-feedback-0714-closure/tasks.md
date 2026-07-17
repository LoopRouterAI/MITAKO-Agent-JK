# Tasks: 0714 甲方反馈闭环整改

## Phase 1: 规格与测试基线

- [x] T001 建立 `specs/002-customer-feedback-0714-closure/spec.md` 和需求检查清单
- [x] T002 [P] 建立数据模型与接口边界文档 `specs/002-customer-feedback-0714-closure/data-model.md`、`contracts/`
- [x] T003 [P] 完善 0714 回归脚本 `scripts/check_customer_agent_0714_regression.py`
- [x] T004 记录修复前失败基线到 `tests/reports/customer_agent_0714_regression_before.json`

## Phase 2: 统一业务事实 (P1)

- [x] T005 [US1] 修复显式订单优先和归属校验 `agent.py`
- [x] T006 [US1] 修复用户切换期间旧 SSE、卡片、审核和人工状态污染 `src/hooks/useChatSSE.js`
- [x] T007 [US1] 统一案例与审核查询上下文 `main.py`
- [x] T008 [US1] 增加跨用户并发回归 `scripts/check_customer_agent_0714_regression.py`

## Phase 3: 业务意图与真实转接 (P1)

- [x] T009 [US2] 调整业务意图优先级并新增库存/抽赏分支 `agent.py`、`business_readiness_service.py`
- [x] T010 [US2] 移除附件默认转客服语义 `src/hooks/useChatSSE.js`
- [x] T011 [US2] 分离人工审核、业务审批和会话转接 `agent.py`、`handoff_service.py`
- [x] T012 [US2] 实现用户同意后的可验证转接状态 `main.py`、`src/hooks/useChatSSE.js`

## Phase 4: 审核闭环 (P1)

- [x] T013 [US3] 按案例查询并回写审核状态、置信度、失败阶段和报告 `main.py`
- [x] T013A [US3] 为聊天审核适配器补场景、订单、案例和上下文字段 `private_domain/`
- [x] T014 [US3] 修复视觉工作台报告链接事件冒泡 `poc/visual_review_poc/workbench.html`
- [x] T015 [US3] 修复内置 sample_003 稳定性并保留盲测隔离 `poc/visual_review_poc/`
- [x] T016 [US3] 将 `sample_labels.json` 纳入安全发布依赖 `scripts/package_internal_release.ps1`
- [x] T017 [US3] 验证可配置 0.2/0.5/1/2 FPS 与超大媒体边界 `scripts/check_visual_workbench_smoke.py`
- [x] T017A [US3] 收敛视觉媒体可访问目录并记录生产鉴权边界 `poc/visual_review_poc/workbench_server.py`

## Phase 5: 响应编排与工作台 (P2)

- [x] T018 [US4] 实现一轮一个主卡和一句话无卡 `main.py`
- [x] T019 [US4] 修复各 SOP 卡片类型、时效和追问增量 `business_readiness_service.py`
- [x] T020 [US5] 修复坐席简报和默认首句 `handoff_service.py`
- [x] T021 [US5] 增加本人/可接/全队列视图 `src/desk/HumanAgentDesk.jsx`
- [x] T022 [US5] 增加公开报告风险明细入口 `ops_service.py`、`src/admin/`
- [x] T023 [US5] 在后台明确演示数据未加载和数据来源 `src/admin/`

## Phase 6: 全量验收与交付

- [x] T024 运行 0709、0714、业务 E2E、私有化 API 和视觉 smoke
- [x] T025 运行前端构建与桌面/移动端浏览器验收
- [x] T026 生成 0714 甲方验收 HTML `docs/delivery/`
- [x] T027 更新甲方沟通文档、内部 Java 开发部署说明、README 和升级日志
- [x] T028 安全瘦身并生成内部源码包与甲方测试包
- [x] T029 在全新解压目录启动并重复自动化验收
- [x] T030 提交并推送 GitHub，记录 commit、包哈希和验收报告

## Phase 7: 0717 网页端视频读取事故闭环

- [x] T031 复现并定位网页目录上传误读 AppleDouble 伪视频的根因
- [x] T032 统一网页工作台与正式审核 API 的隐藏文件和媒体内容校验
- [x] T033 实现坏视频逐文件隔离、UUID 并发目录隔离和接收回执
- [x] T034 隐藏客户包中不可运行的内置样本入口并收紧公开报告字段
- [x] T035 新增媒体安全、20 路并发、坏视频隔离和工作台专项回归
- [x] T036 生成 0717 HTML、两类 ZIP，并完成独立解压冷启动验收
- [x] T037 提交并推送 GitHub，记录 ZIP 哈希和最终验收证据

## Phase 8: 0717 四样本审核工程闭环

- [x] T038 多角色对抗审查 617341/614176/618205/617911 的标签、诉求范围、时间轴、SRE 与盲测风险
- [x] T039 新增版本化 `claim_scope` 和默认保守的 `decision_policy`
- [x] T040 实现 617341 缺必需开箱视频的规则性分类建议，并保持业务动作禁止
- [x] T041 为 617911 增加同物关联、主张部位特写、完整视角、无冲突和零离镜判负门槛
- [x] T042 将商品有伤普通档提升为 1 FPS 三通道质量底线，Strong 统一为 2 FPS
- [x] T043 修复分段末帧误报视频结束、局部结论拼接和全局报告矛盾
- [x] T044 补齐 ffprobe 固定路径、Docker 依赖、readiness、Nginx 800MB 基线和真实 602MB 媒体探测
- [x] T045 增加内部工作台 429/502/503/504 有限重试及传输尝试审计
- [ ] T046 完成五任务正式 API 盲测、全量回归和浏览器报告验收
- [ ] T047 更新双方文档、生成两类 ZIP、独立解压验收并推送 GitHub
