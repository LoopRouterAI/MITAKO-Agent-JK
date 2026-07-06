# 甲方需求满足度报告

**日期**: 2026-06-29
**范围**: MITAKO 客服 Agent + 私域/仓储协同 Mock 准备态
**结论**: 当前代码已经升级为“可验收 Mock 准备态”的客服 Agent 系统，但不是甲方真实系统对接完成版。除真实甲方后台、企微、飞书、仓储、财务、订单接口之外，本轮已把关键非真实对接缺口落到本地状态机、审计、人工台和 E2E 验收里。

## 1. 已满足或已准备好的能力

| 甲方需求 | 当前满足方式 | 代码位置 | 验收方式 |
|---|---|---|---|
| 客服能按 SOP 分流售后诉求 | 本地 SOP 状态机覆盖申请退款、物流异常、商品有伤、漏发/发错、未成年人退款、账号换绑 | `business_mock_service.py` | `test_sop_branch_matrix_minimal` |
| 高风险动作不能自动执行 | `allowed_actions/blocked_actions` 明确禁止自动退款、自动补发、自动改绑；高风险只生成人工确认任务 | `business_mock_service.py`, `agent.py` | `test_business_flow_fixture_idempotency_and_audit` |
| 直接投诉/12315/起诉要快速转人工 | P0 命中后短路到 `transfer_human`，不继续补偿或生成普通回复，同时写 `mock_transfer_blocked` 审计 | `agent.py`, `business_mock_service.py` | `test_p0_transfer_short_circuit` |
| 人工客服接手时要看到上下文 | `/api/v1/chat` 写服务端 transcript，`/handoff/request` 优先使用服务端历史，防客户端伪造 history | `main.py`, `handoff_store.py` | `test_server_transcript_beats_spoofed_client_history_for_handoff` |
| 坐席台要看到 SOP 核验项 | 移交 brief 携带 `sop_state.checklist`；`/desk` 右侧展示风险条、SOP checklist、Mock 业务动作、首要下一步 | `handoff_service.py`, `src/desk/HumanAgentDesk.jsx` | `test_desk_detail_returns_business_readiness` + `npm run build` |
| Mock 业务动作要可审计 | 新增 `business_audit_events`，记录 SOP 分支、多模态 fixture、Mock 售后卡、仓库任务、质检/SOP 提案、私域任务 | `handoff_store.py`, `business_mock_service.py` | `test_business_flow_fixture_idempotency_and_audit` |
| 仓库/跨部门协同准备态 | 物流、漏发/发错场景输出 `warehouse_task` 和 `task_center`，包含责任角色、SLA、下一步 | `business_mock_service.py` | `test_desk_detail_returns_business_readiness` |
| 质检/SOP 更新准备态 | 高风险或 Mock 动作会生成 `mock_qc_sop_proposal`，供后台审计与后续人工复核 | `business_mock_service.py`, `src/admin/pages/AuditLog.jsx` | `test_business_flow_fixture_idempotency_and_audit` |
| 私域运营准备态 | 业务流生成 `mock_private_domain_task`，明确企微/社群/App Push 为待甲方授权替换的触达点 | `business_mock_service.py` | `test_business_flow_fixture_idempotency_and_audit` |
| 后台审计可读 | 审计页聚合 handoff + business events，并新增可读时间线，保留原始 JSON | `admin_service.py`, `src/admin/pages/AuditLog.jsx` | `test_admin_audit_returns_business_events` |
| 多租户边界 | admin 审计和 transcript 按 `tenant_id` 过滤；跨租户 transcript 返回 `tenant_forbidden` | `admin_service.py`, `main.py` | `test_admin_audit_is_tenant_scoped` |
| 重复转人工不降级 | 已接入/排队/转派/关闭会话重复 `/handoff/request` 返回现有队列，不覆盖 assigned agent | `handoff_service.py`, `main.py` | `test_repeated_handoff_request_does_not_downgrade_connected_session` |
| 多 fixture 不误去重 | 幂等键加入 fixture seed，同会话同订单多个证据 fixture 可分别审计 | `business_mock_service.py` | `test_multiple_fixtures_are_not_deduped` |

## 2. 现在仍然不是“真实对接完成”的部分

以下能力当前只做到 Mock 或准备态，不能对外宣称已接入甲方真实生产系统：

- 甲方订单、工单、售后卡片、仓储、财务、商品库真实 API。
- 企业微信、飞书、社群、私域触达真实写入。
- 真实 OCR、开箱视频识别、证件关系链自动终审。
- 真实退款、补发、换货、账号改绑、地址修改等高风险动作。
- 甲方真实 SOP 版本发布、回滚、审批流。

当前系统对这些能力的处理原则是：生成本地 Mock 任务、人工确认建议、审计记录和替换适配器边界，不执行真实业务写入。

## 3. 仍需后续增强但不阻塞当前 Mock 验收的项

| 项目 | 当前状态 | 后续目标 |
|---|---|---|
| 每份 SOP 逐段状态机 | 已有 6 类最小状态机 | 按每份 SOP 拆到退款 A/B/C、物流未发/已发/拒签/丢件等细分状态 |
| 未成年人退款材料链 | 已有分支、人工确认、材料 fixture 入口 | 增加身份证、户口本/出生证明、承诺书、支付流水、手机号实名等脱敏材料包 |
| Mock 后台生命周期 | 已有审计事件和任务中心形态 | 增加可查询、挂起、答疑、关闭、主管审批等完整生命周期 |
| 盲测样本集 | 已有守护 E2E | 每类 SOP 至少 10 条脱敏样本，输出通过率和错分支报告 |
| 私域运营 Agent | 已有私域任务草稿 | 增加 Mock 群消息、标签、意向等级、触达频率、每日摘要 |
| 仓库 Agent | 已有仓库任务中心形态 | 增加责任人反馈、超时提醒、关闭与用户跟进草稿 |

## 4. 本轮验收结果

已通过：

```powershell
.\venv\Scripts\python.exe -m py_compile agent.py agent_llm.py main.py handoff_service.py handoff_store.py business_mock_service.py admin_service.py mock_api.py tests/e2e/run_mock_business_guard_e2e.py
.\venv\Scripts\python.exe tests/e2e/run_mock_business_guard_e2e.py
npm run build
```

`tests/e2e/run_mock_business_guard_e2e.py` 输出 `mock business guard checks passed`。唯一提示是 Starlette TestClient 的依赖弃用警告，不影响本次业务逻辑。

## 5. 当前判断

如果验收目标是“在不对接甲方真实系统的情况下，证明客服 Agent 能按甲方 SOP 做本地 Mock 分流、人工交接、业务动作准备、审计追踪和风险边界”，当前代码已经满足。

如果验收目标是“直接接入甲方生产后台并自动完成退款、补发、仓库、企微、飞书等真实动作”，当前代码不满足，且不应在未获得甲方 API、鉴权、字段字典、审批规则和灰度环境前继续伪装为真实对接。
