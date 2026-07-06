# 生产环境安全检查清单

## 必设环境变量

| 变量 | 生产建议 | 说明 |
|---|---|---|
| `MITAKO_AUTH_REQUIRED` | `1` | 开启后台页面登录保护 |
| `MITAKO_PROTECTED_API_AUTH_REQUIRED` | `1` | 开启后台、坐席和受保护 API 鉴权 |
| `MITAKO_JWT_SECRET` | 随机强密钥，至少 32 字符 | 禁止使用公开示例密钥 |
| `MITAKO_SSO_DEMO` | `0` | 关闭本地演示 SSO |
| `ALLOW_PORT_FALLBACK` | `0` | 固定端口，避免运维和回归环境混乱 |
| `REDIS_HOST` | 生产 Redis | 用于实时广播、SSO state、SLA 锁等能力 |
| `MITAKO_BUSINESS_DEMO_API_ENABLED` | 生产为 `0` | 禁止将本地业务样例接口误当生产接口 |

## 鉴权模型

| 端点 | 角色 / Token |
|---|---|
| `/api/v1/admin/*` 变更 | `ADMIN_MUTATE_ROLES` |
| `/api/v1/desk/*` 读取 | `DESK_ACCESS_ROLES` |
| `/api/v1/desk/*` 写入 | `DESK_MUTATE_ROLES` |
| `/api/v1/handoff/request` | 客户端可发起，返回短时 `handoff_token` |
| `/api/v1/handoff/status/*` | `handoff_token` |
| `/api/v1/handoff/ws/*` | `handoff_token` 或坐席 JWT |
| `/api/v1/handoff/reset` | 管理员角色 |

## 多租户与数据边界

- 登录必须校验 `tenant_id` 与账号归属一致。
- `handoff_sessions.tenant_id` 必须隔离坐席队列、报表、审计和运维快照。
- 视觉审核材料必须按租户、工单、任务隔离存储，禁止跨租户读取。
- 生产日志不得写入用户隐私原文、完整视频地址、接口密钥或模型渠道凭证。

## 审批职责分离

- 退款、补发、拒赔、库存修改、财务动作必须由甲方业务系统或人工坐席执行。
- AI 审核结论仅作为“证据摘要 + 置信度 + 复核建议”，不得直接自动裁决。
- `decide_compensation_approval` 需保证审批人与申请人不同。

## 上线前命令

```bat
python scripts/seed_auth.py
npm run build
python scripts/dual_system_smoke_test.py
python tests/e2e/run_enterprise_production_e2e.py
python scripts/check_visual_workbench_smoke.py
```

旧版陪伴、角色扮演、文字冒险服务线已经封存，不再作为生产安全边界的一部分。
