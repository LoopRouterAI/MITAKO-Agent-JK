# 012 任务与验收矩阵

**日期**: 2026-06-29
**边界**: 本期只做甲方业务 Mock Agent 演示版，不接入甲方真实后台、客户接口、企微、飞书、仓库、财务或商品库。

## P0 已落地

| 任务 | 状态 | 验收方式 |
|---|---|---|
| P0 转人工短路 | 已完成 | 命中 `12315/起诉/改地址/高情绪` 后直接进入 `transfer_human`，不执行 `generate_reply`、`check_compensation` |
| P0 转人工仍写业务审计 | 已完成 | `mock_transfer_blocked` 记录 Mock-only SOP 留痕 |
| 安全审核后再下发文本 | 已完成 | `call_llm` 不直接对客服主流程发 `text_chunk`，由 `send_reply` 在 `safety_review=pass` 后发送 |
| block 不循环 | 已完成 | `safety_review=block` 路由到 `transfer_human` |
| LLM 失败兜底 | 已完成 | LLM API key 缺失、超时或配额失败时标记 `should_transfer=True` |
| handoff REST token | 已完成 | `status/connect/messages/user-message` 校验 `handoff_token` 的 session/user/tenant |
| desk 坐席身份绑定 | 已完成 | `reply/accept/transfer` 使用登录 token 的 `agent_id`，请求体冒充返回 403 |
| 重复转人工不降级 | 已完成 | 已接入会话重复 `/handoff/request` 返回现有状态，不覆盖 assigned agent |
| admin 审计租户隔离 | 已完成 | admin audit events 和 transcript 按 `tenant_id` 过滤 |
| 本地 SOP 来源召回 | 已完成 | `search_knowledge_base` 读取 `docs/_extracted_sop/*.txt`，上下文带 `本地SOP` 来源 |
| 服务端权威 transcript | 已完成 | `/api/v1/chat` 写服务端消息表，handoff 简报优先用服务端历史 |

## P1 核心已落地

| 任务 | 状态 | 验收方式 |
|---|---|---|
| 最小 SOP 状态机 | 已完成 | 覆盖申请退款、物流异常、商品有伤、漏发/发错、未成年人退款、账号换绑 |
| SOP checklist | 已完成 | `sop_state.checklist` 输出核对用户与订单、SOP 分支、禁止动作、证据材料、人工审批、下一步 |
| Mock 业务审计 | 已完成 | `business_audit_events` 记录 SOP 分支、多模态 fixture、Mock 售后/仓库/质检/私域事件 |
| 多 fixture 幂等 | 已完成 | 同一会话同一订单多个 fixture 不互相去重，重复同请求才 dedupe |
| 仓库任务准备态 | 已完成 | 物流/漏发场景输出 `warehouse_task.task_center`，包含 owner、SLA、next_step |
| 质检/SOP 更新准备态 | 已完成 | 业务动作生成 `mock_qc_sop_proposal` |
| 私域运营准备态 | 已完成 | 业务动作生成 `mock_private_domain_task`，标明待真实企微/社群/App Push 替换 |
| 人工台可见业务准备态 | 已完成 | `/desk` 右侧显示风险条、SOP checklist、Mock 业务动作、首要下一步 |
| 后台可读审计时间线 | 已完成 | `/admin` 审计页聚合 message、handoff、business events，并保留原始 JSON |
| OpenUI 业务动作卡注册 | 已完成 | `BusinessActionCard` 注册到 `mitakoOpenUILibrary` 和 `CARD_RENDERERS` |

## 当前验收命令

```powershell
.\venv\Scripts\python.exe -m py_compile agent.py agent_llm.py main.py handoff_service.py handoff_store.py business_mock_service.py admin_service.py mock_api.py tests/e2e/run_mock_business_guard_e2e.py
.\venv\Scripts\python.exe tests/e2e/run_mock_business_guard_e2e.py
npm run build
```

## P1 后续可增强

| 任务 | 后置原因 |
|---|---|
| 每份 SOP 逐段结构化 | 当前已做最小状态机，完整逐段拆解需要更多脱敏样本和甲方确认 |
| Mock 后台完整生命周期 | 当前已有审计与任务中心形态，完整挂起/答疑/关闭/审批需继续扩展 |
| 未成年人退款材料链 | 当前已有分支和 fixture 入口，完整关系链需补脱敏材料包 |
| 盲测样本集 | 当前 E2E 是守护门禁，后续应按每类 SOP 增加至少 10 条样本 |

## P2 后置

| 任务 | 后置原因 |
|---|---|
| 企微/飞书私域闭环 | 本期只能 Mock，不写真企业 IM |
| 仓库 Agent 完整任务中心 | 需要更多甲方仓储字段、责任人规则和 SLA 规则 |
| 真实 OCR/视频识别准确率 | 当前只能用 fixture 证明流程，不承诺识别质量 |
| 真实甲方接口替换 | 需要甲方提供 API、鉴权、回调、数据字典和灰度环境 |
