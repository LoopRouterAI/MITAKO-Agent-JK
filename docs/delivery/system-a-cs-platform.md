# 系统 A：智能客服 + 人机协同

## 1. 产品范围

| 端 | URL | 角色 | 能力 |
|----|-----|------|------|
| 用户端 | `/` | C 端会员 | AI 虾饺对话、情绪识别、转人工、@虾饺旁听 |
| 坐席台 | `/desk` | BPO/甲方客服 | 简报、接单、回复、转交、升级 |
| 运营台 | `/admin` | 主管/运营 | 坐席、队列、审批、报表、路由、运维 |

数据：`handoff.db` + `admin.db` + `auth.db`（多租户 `tenant_id`）

## 2. 我方部署（全包）

```bat
一键启动-Windows.bat
```

或手动：

```bat
npm run build
python scripts/seed_auth.py
set HANDOFF_BACKEND=hybrid
set CHATWOOT_MOCK=1
python main.py
```

生产见 [deployment-guide.md](./deployment-guide.md) 与 [../security/production-checklist.md](../security/production-checklist.md)。

## 3. 甲方配合项（非自建 IM/IdP 运维）

| 项 | 甲方做什么 | 文档 |
|----|------------|------|
| SSO 登录 | 提供 IdP Client/Secret、Groups 映射 | [sso-oidc-guide.md](../integration/sso-oidc-guide.md) |
| IM 会话镜像 | UAT 账号、验收同步方向 | [chatwoot-guide.md](../integration/chatwoot-guide.md)（**我方部署 Chatwoot**） |
| 业务订单/退款 | 后续提供 API 或对接 `tools/partner_lab/mock_business_api.py` 契约 | [integration-lab.md](./integration-lab.md) |
| SOP 话术验收 | 按 [sop-coverage-gap.md](../product/sop-coverage-gap.md) 场景 UAT | 文档阶段可验收「交付物齐全」 |

## 4. 默认测试账号

| 账号 | 密码 | 角色 | 入口 |
|------|------|------|------|
| admin | admin123 | super_admin | /admin |
| supervisor | super123 | supervisor | /admin 审批 |
| desk0816 | desk123 | desk_agent | /desk |
| bpo_mgr | bpo123 | bpo_manager | /admin |

## 5. 核心 API（详见 [rest-api-overview.md](../api/rest-api-overview.md)）

- 对话：`POST /api/v1/chat`（SSE）
- 转人工：`POST /api/v1/handoff/request`
- 坐席：`GET/POST /api/v1/desk/*`
- 运营：`GET/POST /api/v1/admin/*`
- 鉴权：`POST /api/v1/auth/login`

## 6. 验收要点（V1）

- [ ] 用户转人工 → desk 可见简报 → 接单 → 双端消息同步
- [ ] Admin 审批流（申请人 ≠ 审批人）
- [ ] `MITAKO_AUTH_REQUIRED=1` 时 desk/admin 无 token 返回 401
- [ ] E2E：`run_full_pipeline_e2e.py` 70/70
