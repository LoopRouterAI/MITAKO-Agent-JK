# REST API 概览

> Base URL：`http://<host>:8000` · 鉴权：`Authorization: Bearer <JWT>`（`MITAKO_AUTH_REQUIRED=1` 时）

## 鉴权

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/auth/status` | 鉴权/SSO 状态 |
| POST | `/api/v1/auth/login` | 账号密码 `{username,password,tenant_id?}` |
| GET | `/api/v1/auth/tenants` | 租户列表 |
| GET | `/api/v1/auth/sso/{tenant}/authorize` | SSO 跳转 |
| POST | `/api/v1/auth/sso/callback` | SSO 回调 `{tenant_id,code,state}` |

## 系统 A — 用户对话

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/api/v1/chat` | 否 | SSE 对话 |
| POST | `/api/v1/handoff/request` | 否 | 转人工，返回 `handoff_token` |
| GET | `/api/v1/handoff/status/{session_id}` | 否 | 排队状态 |
| GET | `/api/v1/handoff/messages/{session_id}` | 否 | 消息增量 |
| WS | `/api/v1/handoff/ws/{session_id}?token=` | token | 实时同步 |

## 系统 A — 坐席 `/desk`

| 方法 | 路径 | 角色 |
|------|------|------|
| GET | `/api/v1/desk/sessions` | desk_* |
| GET | `/api/v1/desk/session/{id}` | desk_* |
| POST | `/api/v1/desk/session/{id}/accept` | desk mutate |
| POST | `/api/v1/desk/session/{id}/reply` | desk mutate |
| POST | `/api/v1/desk/session/{id}/transfer` | desk mutate |
| POST | `/api/v1/desk/session/{id}/escalate` | desk mutate |

## 系统 A — 运营 `/admin`

| 方法 | 路径 | 角色 |
|------|------|------|
| GET/POST | `/api/v1/admin/agents` | admin mutate |
| GET | `/api/v1/admin/queue/snapshot` | admin |
| GET/POST | `/api/v1/admin/approvals` | admin |
| GET | `/api/v1/admin/reports/summary` | admin |
| GET | `/api/v1/admin/reports/export.csv` | admin |
| PUT | `/api/v1/admin/handoff/routing` | admin |
| GET | `/api/v1/ops/snapshot` | admin |

## 系统 B — Companion `/api/v2/companion`

| 方法 | 路径 | 鉴权 |
|------|------|------|
| GET/PUT | `/persona/{user_id}` | companion_user |
| GET | `/messages/{user_id}` | companion_user |
| POST | `/chat` | companion_user SSE |
| GET | `/products/search` | companion_user |
| POST | `/watch/orders` | companion_user |
| POST | `/wishlist` | companion_user |
| POST | `/handoff/request` | companion_user |
| GET | `/desk/sessions` | companion_ops |
| POST | `/desk/sessions/{id}/accept` | companion_ops |
| POST | `/desk/sessions/{id}/reply` | companion_ops |

## 观测

| GET | `/metrics` | Prometheus 风格 JSON |

## 契约详情

- 007 合约：`docs/archive/specs/007-human-agent-collab-platform/contracts/handoff-api.md`
- 联调 Mock：`tools/partner_lab/` 与 [integration-lab.md](../delivery/integration-lab.md)
