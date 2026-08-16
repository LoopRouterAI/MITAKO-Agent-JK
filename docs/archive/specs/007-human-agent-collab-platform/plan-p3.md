# P3 商业交付规划：WebSocket + 管理后台

**状态**: 已实现（v1）

## 已交付

### WebSocket 实时推送
- 端点：`WS /api/v1/handoff/ws/{session_id}`
- 事件：`status`（接单/转交/升级）、`message`（human/observer/system）
- 前端：`attachHandoffTransport` — WS 优先，1.5s 轮询兜底
- 模块：`handoff_ws.py` + `handoff_service._emit_*`

### 路由管理后台
- URL：`/admin`（`admin.html` + `HandoffAdmin.jsx`）
- API：`GET /api/v1/handoff/routing`、`PUT /api/v1/admin/handoff/routing`
- 能力：规则开关、SLA 阈值、自动转交开关
- 持久化：`config/handoff_routing.json`

## 后续 P3+（未纳入本迭代）

| 项 | 说明 |
|----|------|
| SSO/RBAC | 管理后台与 desk 工号鉴权 |
| 部门/技能组路由 | rules.condition.skills |
| Chatwoot 适配器 | 替换 handoff_store 为外部 IM |
| WFM 排班 | 在线状态 + 负载均衡 |
| E2E Playwright | UI 级自动化 |

## 性能目标

- WS 推送 p95 ≤ 500ms（本机）
- 轮询兜底 p95 ≤ 3s（SC-003）
