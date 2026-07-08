# Iteration Notes: 2026-07-05 商业级客服 POC 专业化升级

## 为什么需求变化

项目已经从“证明 Agent 能聊天”变成“证明能为甲方客服系统提效”。甲方关注的不只是模型能力，还包括客服队列、人工接手、视觉审核、移动端、后台管理、系统健康和对接边界。

## 本轮解决什么问题

- 修复用户端只读业务卡片像按钮的问题。
- 修复VIP客服工作台流程混层、移动端裁切、结案缺失、刷新反馈不足的问题。
- 修复后台队列、报表、运维大盘不够业务化的问题。
- 修复未授权 reset 会话的 P0 安全问题。
- 让视觉审核工作台从能力展示页向“客服工单工具”靠拢。

## 踩坑记录

- 不要用全局选择器强行给所有白底 `div/section` 加黑边和硬阴影；这会让信息块看起来像按钮。
- 不能为了演示方便保留无鉴权清空接口；演示工具也要符合租户和权限边界。
- 不能把“升级处理”“一线客服”等内部词直接丢给业务人员，需要解释为“普通客服”“高级客服/专项客服”。
- 视觉审核报告与 E2E 模型选型报告不同，前者服务VIP客服决策，必须先给结论、置信度、证据和下一步。

## 本轮不做

- 不接入甲方生产订单、仓库、物流、清关、退款或私域接口。
- 不恢复 Companion/陪伴/角色扮演/文字冒险能力。
- 不引入完整第三方监控平台或大型 BI 系统。

## 二次对抗审查后的修正

- 演示数据生命周期从“只插入/删除 demo 会话”升级为“清理历史联调会话、演示会话、关联质检和补偿审批”，避免甲方第一次打开后台看到 300 多小时排队的旧脏数据。
- 后台演示数据增加租户命名空间，避免不同租户加载 `demo_poc_*` 时抢同一个全局 session_id。
- 转派规则从前端提示升级为后端强约束：需要高级客服/专项客服的会话不能转给普通客服，SLA 自动转派也必须遵守同样规则。
- 结案接口增加状态约束，只允许已接手且正在服务的会话结案，避免排队中或转派中的单子被直接关闭。
- 运营报表把已结案人工会话纳入人工介入量，避免“结案越多，转VIP客服率越低”的错误指标。
- `/api/v1/handoff/reset` 收紧为管理员或显式开发旁路专用，客户 handoff token 和普通坐席 token 不能物理删除审计链。
- 业务 Mock API 默认关闭；本地演示必须显式设置 `MITAKO_BUSINESS_DEMO_API_ENABLED=1`，且主要读接口返回 `demo_only=true` 与 `real_partner_integration=false`。
- 视觉审核工作台降低过亮绿色、统一基础圆角、补上传控件焦点态，并在移动端隐藏占屏 hero，让客服更快进入三大审核入口。
- VIP客服工作台补输入控件可访问名称、转派目标过滤、后台清空演示数据确认、坐席删除确认。

## 本轮验收记录

- `npm run build` 通过。
- `python -m py_compile main.py admin_service.py admin_store.py handoff_service.py handoff_store.py ops_service.py auth/middleware.py auth/sso.py business_api.py poc/visual_review_poc/workbench_server.py` 通过。
- `scripts/check_admin_ui_smoke.py` 通过。
- `scripts/dual_system_smoke_test.py` 通过，三端页面和坐席/后台 API 8/8 通过。
- `scripts/check_visual_workbench_smoke.py` 通过，最新报告在 `tests/reports/visual_workbench_smoke_20260705_175648.md`。
- `tests/e2e/run_handoff_tenant_guard_e2e.py` 通过。
- `tests/e2e/run_mock_business_guard_e2e.py` 通过。
- `scripts/check_data_isolation.py` 与 `scripts/check_auth_migration_dry_run.py` 已在临时 `tests/tmp` 数据目录通过。
- 浏览器复核：用户前台、人工台、后台、视觉审核工作台均无控制台错误，后台和人工台只展示三条演示样本，视觉工作台移动端 375px 无横向溢出。
