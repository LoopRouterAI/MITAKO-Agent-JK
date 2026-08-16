# REST API 概览

Base URL：`http://<host>:8000`
鉴权：生产或联调模式建议使用 `Authorization: Bearer <JWT>`。

## 鉴权

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/auth/status` | 鉴权、受保护 API、SSO 状态 |
| POST | `/api/v1/auth/login` | 账号密码登录，参数为 `{username,password,tenant_id?}` |
| GET | `/api/v1/auth/tenants` | 租户列表 |
| GET | `/api/v1/auth/sso/{tenant}/authorize` | 企业 SSO 跳转 |
| POST | `/api/v1/auth/sso/callback` | 企业 SSO 回调 `{tenant_id,code,state}` |

## 用户端客服

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/v1/chat` | 可选客户 token | SSE AI客服对话 |
| POST | `/api/v1/handoff/request` | 可选客户 token | 转VIP客服，返回 `handoff_token` |
| GET | `/api/v1/handoff/status/{session_id}` | `handoff_token` | 查询排队、接入和关闭状态 |
| GET | `/api/v1/handoff/messages/{session_id}` | `handoff_token` | 查询VIP客服消息增量 |
| WS | `/api/v1/handoff/ws/{session_id}` | `handoff_token` 或坐席 JWT | 实时同步 |

## VIP客服工作台

| 方法 | 路径 | 角色 |
|---|---|---|
| GET | `/api/v1/desk/sessions` | `DESK_ACCESS_ROLES` |
| GET | `/api/v1/desk/session/{id}` | `DESK_ACCESS_ROLES` |
| POST | `/api/v1/desk/session/{id}/accept` | `DESK_MUTATE_ROLES` |
| POST | `/api/v1/desk/session/{id}/reply` | `DESK_MUTATE_ROLES` |
| POST | `/api/v1/desk/session/{id}/transfer` | `DESK_MUTATE_ROLES` |
| POST | `/api/v1/desk/session/{id}/escalate` | `DESK_MUTATE_ROLES` |

## 运营后台

| 方法 | 路径 | 角色 |
|---|---|---|
| GET/POST | `/api/v1/admin/agents` | `ADMIN_MUTATE_ROLES` |
| GET | `/api/v1/admin/queue/snapshot` | `ADMIN_MUTATE_ROLES` |
| GET/POST | `/api/v1/admin/approvals` | `ADMIN_MUTATE_ROLES` |
| GET | `/api/v1/admin/reports/summary` | `ADMIN_MUTATE_ROLES` |
| GET | `/api/v1/admin/reports/export.csv` | `ADMIN_MUTATE_ROLES` |
| PUT | `/api/v1/admin/handoff/routing` | `ADMIN_MUTATE_ROLES` |
| GET | `/api/v1/ops/snapshot` | `ADMIN_MUTATE_ROLES` |

## 视觉审核工作台

视觉审核 POC 当前由独立工作台服务承载，默认本地地址为 `http://127.0.0.1:7861/`。它面向三类独立审核入口：开箱视频审核、商品有伤审核、未成年人资料审核。真实接入甲方业务系统时，建议通过“创建审核任务、上传材料、查询状态、回写人工结论”的对接契约完成，详见：

- [审核服务 API 契约与自动化验收](../review_service_api_contract_20260710.md)
- [OpenAPI 定义](../delivery/openapi.yaml)
- [测试与验收指南](../delivery/testing-guide.md)
- [甲方对接物料与接口清单](../delivery/customer-integration-materials-checklist.md)

## 观测

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/metrics` | 服务运行状态 JSON |

## 历史封存

`/api/v2/companion/*`、`/companion`、`/companion-desk` 已从当前主系统移除，历史源码封存在 `archive/companion_roleplay_mode_20260705/`。
