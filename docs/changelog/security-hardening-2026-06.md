# 变更记录：安全加固与企业生产（2026-06）

## 背景

代码审查发现：desk/companion 读接口无鉴权、SSO Demo 默认开启、Companion IDOR、多租户未隔离等问题。本次迭代以 **生产默认安全** 为目标，Demo 仅通过显式 env 开启。

## 主要变更

### P0 鉴权

- `DESK_ACCESS_ROLES` 保护 `/api/v1/desk/*` 读接口
- `COMPANION_DESK_ROLES` + `CompanionDeskShell` 登录门控
- Companion C 端 `companion_user` JWT（onboarding 签发，`companionClient.js`）
- `/api/v1/handoff/reset` 仅 admin
- WebSocket 需 `handoff_token` 或 desk JWT
- `handoff/request` 响应增加 `handoff_token`

### P1 多租户 / SSO

- `handoff_sessions.tenant_id` 列 + 查询过滤
- 登录 `tenant_mismatch` 校验
- OIDC `exchange_code_async` 真实 token/userinfo 交换
- SSO state → Redis（`auth/sso_state.py`）
- `MITAKO_SSO_DEMO` 默认 **0**；Demo 走 `/api/v1/auth/sso/demo/complete`
- Admin SSO 跳转 IdP；回调 `/admin?sso=1`

### P2 其他

- SLA 锁与 WS 一致：仅 `REDIS_HOST` 配置时使用 Redis
- 审批：审批人 ≠ 申请人
- `im_sync_service` 移除不可达 dead code
- `admin_store` / `companion_store` 增加 `tenant_id` 列与查询隔离
- `handoff_backend/factory.py` 按 `HANDOFF_BACKEND` 返回 `sqlite` 或 `hybrid` 后端

## 可能影响的行为

| 变更 | 若出问题排查 |
|------|----------------|
| desk 读接口 401 | 前端是否 `authFetch`；`MITAKO_AUTH_REQUIRED` |
| Companion 401 | 是否保存 `companion_token`；onboarding 后再调 API |
| WS 连接失败 | 是否传递 `handoff_token` query |
| SSO 生产失败 | 见 `docs/integration/sso-oidc-guide.md` |
| E2E reset 失败 | 需 admin token 调 reset |
| 审批 E2E 失败 | 需 supervisor 账号批准（非同一 requester） |

### 后续修补（同批次）

- `auth/middleware.py`：鉴权关闭时仍解析 Bearer，修复审批 E2E「审批人=申请人」假失败
- `auth/sso.py`：非 Demo 模式拒绝 `demo_ok` code（`demo_disabled`）
- `useCompanionChat.js`：修正 `companionClient` 导入路径
- `run_companion_features_e2e.py` / `run_enterprise_production_e2e.py`：补全 `main()` 入口

- 架构：`docs/CodeWiki.md`
- SSO 对接：`docs/integration/sso-oidc-guide.md`
- Chatwoot：`docs/integration/chatwoot-guide.md`
- 生产清单：`docs/security/production-checklist.md`
- E2E：`docs/testing/e2e-coverage.md`
