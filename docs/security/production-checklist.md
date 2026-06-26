# 生产环境安全检查清单

## 必设环境变量

| 变量 | 生产值 | 说明 |
|------|--------|------|
| `MITAKO_AUTH_REQUIRED` | `1` | 开启 admin/desk/companion-desk JWT 门控 |
| `MITAKO_JWT_SECRET` | 随机 ≥32 字符 | **禁止**默认 `mitako-dev-change-me-in-production` |
| `MITAKO_SSO_DEMO` | `0` | 关闭 Demo SSO |
| `MITAKO_COMPANION_AUTH_REQUIRED` | `1` 或留空跟随 AUTH | Companion C 端 token |
| `ALLOW_PORT_FALLBACK` | `0` | 固定端口，避免 E2E/运维混乱 |
| `REDIS_HOST` | 生产 Redis | WS 广播 + SSO state + SLA 锁 |

## 鉴权模型（2026-06 加固后）

| 端点族 | 角色 / Token |
|--------|----------------|
| `/api/v1/admin/*` 变更 | `ADMIN_MUTATE_ROLES` |
| `/api/v1/desk/*` 读 | `DESK_ACCESS_ROLES` |
| `/api/v1/desk/*` 写 | `DESK_MUTATE_ROLES` |
| `/api/v2/companion/*` C 端 | `companion_user` JWT（onboarding 签发） |
| `/api/v2/companion/desk/*` | `COMPANION_DESK_ROLES` |
| `/api/v1/handoff/reset` | 仅 admin |
| `/api/v1/handoff/ws/*` | `handoff_user` 会话 token 或 desk JWT |
| `/api/v1/handoff/request` | 公开（返回 `handoff_token` 供 WS） |

## 多租户

- 登录校验 `tenant_id` 与账号归属一致（`tenant_mismatch`）
- `handoff_sessions.tenant_id` 隔离 desk/报表/运维快照
- SSO groups → 角色见 `docs/integration/sso-oidc-guide.md`

## 审批职责分离

- `decide_compensation_approval`：审批人 ≠ 申请人

## 上线前命令

```bat
python scripts/seed_auth.py
npm run build
set MITAKO_AUTH_REQUIRED=1
python tests/e2e/run_enterprise_production_e2e.py
```
