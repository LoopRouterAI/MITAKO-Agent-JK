# Data Model: 007 人机协同客服平台

## HandoffSession

| Field | Type | Notes |
|-------|------|-------|
| session_id | string PK | 与 chat session 一致 |
| user_id | string | |
| status | enum | queuing \| transferring \| connected \| escalated \| closed |
| required_tier | enum | standard \| supervisor（路由规则计算，默认 standard） |
| brief_json | JSON | 完整移交简报 |
| assigned_agent_json | JSON? | 当前负责人 |
| pending_agent_json | JSON? | 转交待确认同事 |
| suggested_agent_json | JSON | 队列推荐 |
| queue_position | int | |
| queue_ahead | int | |
| queue_eta_minutes | int | |
| enqueued_at | float | unix |
| accepted_at | float? | |
| accepted_by | string? | agent_id |
| last_agent_reply_at | float? | SLA |
| last_user_message_at | float? | |
| escalation_note | string? | |
| created_at / updated_at | float | |

## HandoffMessage

| Field | Type | Notes |
|-------|------|-------|
| id | integer PK | 自增 |
| session_id | string FK | |
| role | enum | user \| human \| observer \| system |
| content | text | 原始文本（含 #tag#） |
| agent_id | string? | human 消息 |
| meta_json | JSON? | event, transfer_id 等 |
| created_at | float | |

## TransferEvent

| Field | Type | Notes |
|-------|------|-------|
| id | integer PK | |
| session_id | string | |
| event_type | enum | accept \| colleague \| timeout \| escalate \| department |
| from_agent_id | string? | |
| to_agent_id | string? | |
| note | text | |
| created_at | float | |

## RoutingConfig (JSON file)

- `default_required_tier`: standard
- `rules[]`: { id, enabled, condition, required_tier }
- `sla`: { first_response_seconds, reply_timeout_seconds, auto_transfer_enabled }

## State Transitions

```
queuing --accept(standard)--> connected
connected --transfer_colleague--> transferring --accept(B)--> connected
connected --escalate--> escalated --accept(supervisor)--> connected
connected --sla_timeout--> transferring (auto next agent)
any active --close--> closed
```
