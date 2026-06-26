# MITAKO Agent — Code Wiki

> 架构摘要 · 供 Agent/开发者快速定位 · 与 `.codegraph/` 索引同步

## 产品端 URL

| URL | 入口 | 说明 |
|-----|------|------|
| `/` | index.html | 用户端客服（虾饺 SSE） |
| `/desk` | desk.html | 人工客服工作台（handoff.db） |
| `/admin` | admin.html | 管理员运营后台（坐席/队列/审批/报表） |
| `/companion` | companion.html | Companion 陪伴 + 消费助理 |
| `/companion-desk` | companion-desk.html | Companion 独立运营台（companion.db） |

## 核心调用链：AI 对话

```
用户输入 → useChatSSE.handleSend
  → POST /api/v1/chat (SSE)
  → agent.py LangGraph
  → unified_analysis / generate_reply / safety_review
  → 前端 MessageList + OpenUI 卡片
```

## 核心调用链：转人工（007 + 009）

```
用户 confirmHandoff / Agent transfer 事件
  → POST /api/v1/handoff/request
  → handoff_service.build_handoff_brief + enqueue_handoff
  → handoff_store (SQLite data/handoff.db)

工作台 accept
  → POST /api/v1/desk/session/{id}/accept
  → accept_handoff → append welcome message
  → handoff_ws.emit status/message (可选 Redis pub/sub)

用户端同步
  → attachHandoffTransport (WS + poll fallback)
  → ingestServerHandoffMessages → MessageList（handoff_i18n 系统消息）

desk 回复
  → POST .../reply → append_desk_message → WS broadcast
```

## Companion 独立链路（005）

```
/companion → useCompanionChat（禁止 useChatSSE）
  → /api/v2/companion/persona|messages|chat
  → companion.db
  → cs_parttime：companion_mode 关键词 → agent_mode 切换
  → 消费助理：watch / wishlist / products/search
  → handoff/request → companion_handoff_sessions（不进 /desk 队列）

/companion-desk → CompanionDeskApp
  → /api/v2/companion/desk/*
```

## 管理员后台（008）

```
/admin → AdminShell + JWT（MITAKO_AUTH_REQUIRED=1）
  → /api/v1/admin/agents|queue|audit|approvals|reports
  → admin.db（坐席档案 + approval_requests）
```

## 生产基建（009 + 010 安全加固）

| 模块 | 职责 |
|------|------|
| `auth/` | JWT + 角色门控 + SSO OIDC + companion_guard |
| `auth/sso_state.py` | OAuth state（Redis 优先） |
| `handoff_backend/` | HandoffBackend 协议，默认 SQLite |
| `handoff_ws.py` | WS Hub + Redis 多实例 + token 校验 |
| `sla_worker/` | Celery Beat SLA（SLA_WORKER_MODE=celery） |
| `logging_utils.py` | JSON 结构化日志 |
| `GET /metrics` | 队列 + WS 连接数 |

### 鉴权矩阵（2026-06）

| 路径 | 要求 |
|------|------|
| `/api/v1/desk/*` 读 | `DESK_ACCESS_ROLES` JWT |
| `/api/v1/desk/*` 写 | `DESK_MUTATE_ROLES` |
| `/api/v2/companion/*` C 端 | `companion_user` token（onboarding 签发） |
| `/api/v2/companion/desk/*` | `COMPANION_DESK_ROLES` + CompanionDeskShell |
| `/api/v1/handoff/ws/*` | `handoff_token` 或 desk JWT |
| `/api/v1/handoff/reset` | admin only |
| `/api/v1/admin/*` 变更 | `ADMIN_MUTATE_ROLES` |

### 多租户

- `handoff_sessions.tenant_id` 隔离 desk/报表/ops
- `admin_store`：`agent_profiles` / `approval_requests` 按 `tenant_id` 过滤
- `companion_store`：persona / 消息 / 心愿单 / Companion handoff 按 `tenant_id` 过滤
- 登录校验 `tenant_mismatch`
- SSO groups → 角色：`tenants.oidc_role_mapping_json`

## 关键模块

| 模块 | 职责 |
|------|------|
| `handoff_store.py` | SQLite 会话/消息/审计 |
| `handoff_routing.py` | JSON 路由规则 |
| `handoff_observer.py` | @虾饺 旁听 |
| `handoff_service.py` | 业务编排 |
| `companion_store.py` | Companion 独立 DB |
| `admin_store.py` | 坐席 + 补偿审批 |

## E2E 回归

详见 `docs/testing/e2e-coverage.md`。

```powershell
cd MITAKO_Agent
python scripts/seed_auth.py
$env:E2E_BASE_URL="http://127.0.0.1:8000"
python tests/e2e/run_admin_operations_e2e.py
python tests/e2e/run_companion_features_e2e.py
python tests/e2e/run_enterprise_production_e2e.py
python tests/e2e/run_auth_strict_e2e.py   # 需 MITAKO_AUTH_REQUIRED=1
```

## 联调实验室（partner_lab）

| 脚本 | 用途 |
|------|------|
| `tools/partner_lab/启动甲方模拟终端-Windows.bat` | Mock IdP :9101 / Chatwoot :9102 / 业务 :9103 |
| `tools/partner_lab/联调-MITAKO对接模拟终端-Windows.bat` | 全链路：Mock + `CHATWOOT_MOCK=0` MITAKO + `self_integration_test.py` |
| `scripts/seed_lab_tenant.py` | 租户 `bpo-east` → Mock IdP OIDC |

## 甲方对接文档

| 文档 | 内容 |
|------|------|
| [docs/README.md](./README.md) | 文档索引与 specs/docs 分工 |
| [docs/product/sop-coverage-gap.md](./product/sop-coverage-gap.md) | 甲方 SOP vs 实现差距 |
| `docs/integration/sso-oidc-guide.md` | IdP OIDC 配置与联调 |
| `docs/integration/chatwoot-guide.md` | Chatwoot **全包交付**（我方部署） |
| `docs/security/production-checklist.md` | 上线前检查 |
| `docs/changelog/security-hardening-2026-06.md` | 安全加固变更与排障 |

## 质量关注点

- 接单前不得 connected（SC-001）
- Companion 与 handoff 数据完全隔离
- 生产：`MITAKO_AUTH_REQUIRED=1` + 强 `MITAKO_JWT_SECRET` + `MITAKO_SSO_DEMO=0`
- 审批人 ≠ 申请人（职责分离）
- P3 可选：Grafana、私域社群（spec 03）

## 索引维护

```powershell
cd MITAKO_Agent
codegraph sync .
```

最后更新：2026-06-19（partner_lab 联调 BAT + engineer-onboarding + CodeGraph sync）
