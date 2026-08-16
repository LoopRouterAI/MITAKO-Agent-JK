# Contract: 审核回写与人工转接

## 审核任务

- `POST /api/v1/review/tasks`: 单任务、多资产提交。
- `POST /api/v1/review/batches`: 批量提交。
- `GET /api/v1/review/tasks/{task_id}`: 状态、置信度、失败阶段、成本与报告。
- `GET /api/v1/review/tasks?case_id=...`: 按案例查询并供客服回写。

每个任务必须区分 `review_policy.requires_human` 与 `conversation_handoff.state`。

## 人工转接

- `POST /api/v1/handoff/offer`: AI 提议人工，不入队。
- `POST /api/v1/handoff/consent`: 用户同意后创建转接。
- `GET /api/v1/handoff/{handoff_id}`: 查询 queued/connected/failed/closed。

只有服务返回 `queued` 或 `connected` 后，用户端才能显示已经进入人工接待流程。

