# Data Model: 0714 反馈闭环

## ServiceCase

| 字段 | 说明 |
| --- | --- |
| `case_id` | 全局案例标识 |
| `user_id` | 当前用户 |
| `session_id` | 当前会话 |
| `case_type` | logistics / lottery / minor_refund / damage / inventory / general |
| `order_ids` | 已校验属于该用户的订单 |
| `review_task_ids` | 与案例相关的审核任务 |
| `handoff_id` | 当前人工会话，可为空 |
| `status` | collecting / processing / waiting_review / waiting_customer / resolved / closed |
| `provenance` | 数据来源标记 |

## ReviewTask

| 字段 | 说明 |
| --- | --- |
| `task_id` | 审核任务标识 |
| `case_id` / `user_id` / `order_id` | 业务归属 |
| `scenario` | product_damage / wrong_item / missing_item / minor_refund |
| `assets` | 多个图片、视频及逐资产状态 |
| `sampling_policy` | FPS、最大帧数、分辨率、实际抽帧结果 |
| `status` | queued / preprocessing / reviewing / completed / manual_review / failed |
| `decision` | 支持、不支持、需复核 |
| `confidence` | 0 到 1 |
| `failure_stage` | 预处理、模型、解析、报告或回写 |
| `usage_cost` | Token、时延、估算成本 |
| `report_url` | HTML 报告入口 |
| `not_sent_to_model` | 标签等禁止输入清单 |

## HandoffSession

| 字段 | 说明 |
| --- | --- |
| `handoff_id` | 转接标识 |
| `case_id` | 所属案例 |
| `state` | offered / consented / queued / connected / failed / closed |
| `reason` | 用户请求、高风险、法律或敏感操作 |
| `queue_id` / `agent_id` | 队列与坐席 |
| `audit_events` | 状态变化时间线 |

## CustomerResponsePlan

| 字段 | 说明 |
| --- | --- |
| `answer_goal` | 本轮必须回答的具体问题 |
| `primary_card` | 最多一张用户可见主卡 |
| `internal_events` | 不直接展示的后台动作 |
| `transfer_action` | 当前会话是否真实转接 |
| `brevity_mode` | normal / concise / one_sentence |

## DataProvenance

演示数据固定值：

```json
{
  "data_mode": "demo",
  "source_system": "mitako_fixture",
  "integration_status": "not_connected"
}
```

真实联调前不得使用 `connected`。

