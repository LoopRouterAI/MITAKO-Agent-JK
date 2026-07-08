# Chatwoot IM / 工单对接指南

> **交付模式：我方（MITAKO 全包）部署与运维 Chatwoot** · 甲方无需自建 GitHub 项目  
> 底层选型：[Chatwoot 开源版](https://github.com/chatwoot/chatwoot)（MIT License，可商用）

## 0. 角色分工（全包交付）

| 角色 | 职责 |
|------|------|
| **我方（MITAKO / 集成商）** | 部署 Chatwoot（Docker/K8s）、配置 Inbox、签发 API Token、维护 `CHATWOOT_*` 环境变量、与 MITAKO handoff 联调 |
| **甲方** | 提供业务侧配合：测试账号、工单分类口径、验收用例、客服编制与 SLA；**不需要**自行 clone/部署 Chatwoot 仓库 |
| **MITAKO Agent** | 以 `handoff.db` 为权威队列；`im_sync_service` 将会话/消息镜像到 Chatwoot |

对外 IM 域名示例：`https://im.<甲方品牌>.com`（由**我方**在甲方环境或我方托管环境中部署并交付，非 chatwoot.com 官方 SaaS）。

## 1. 架构说明

- **权威数据源**：MITAKO 本地 `handoff.db`（排队、消息、SLA）
- **IM 镜像**：`HANDOFF_BACKEND=hybrid` 时异步推送到 Chatwoot
- **Mock**：`CHATWOOT_MOCK=1` 仅开发/E2E
- **工厂**：`handoff_backend/factory.py` 按 `HANDOFF_BACKEND` 选择 `sqlite` / `hybrid`

## 2. 甲方验收需配合项（非自建）

1. 提供 **1 个测试 Inbox** 对应的业务场景（如「虾淘售后」渠道名）
2. 指派 **2～3 名坐席账号** 用于 UAT（可在 Chatwoot 或 MITAKO `/desk` 验收）
3. 确认 **消息同步方向**：用户转VIP客服 → Chatwoot 可见；坐席在 MITAKO 回复 → Chatwoot outgoing
4. 签署 **SLA 与数据归属**（会话日志存于我方部署实例，按合同约定导出）

## 3. 我方部署配置（内部文档，勿发给甲方填仓库）

```env
HANDOFF_BACKEND=hybrid
CHATWOOT_MOCK=0
CHATWOOT_BASE_URL=https://im.<交付域名>
CHATWOOT_API_TOKEN=<我方签发>
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_INBOX_ID=1
```

`/admin` → **7×24 运维** 可查看 `chatwoot` 健康检查。

## 4. 同步行为

| 事件 | MITAKO | Chatwoot |
|------|--------|----------|
| 用户转VIP客服 | `POST /handoff/request` | 创建 conversation |
| 用户/坐席消息 | append_message | incoming / outgoing |
| SLA 超时转交 | 本地处理 | 可扩展 webhook |

## 5. 联调与验收清单

1. 我方完成 Chatwoot 部署与 Token 配置
2. 发起转VIP客服 → Chatwoot 收件箱出现会话
3. MITAKO `/desk` 回复 → Chatwoot 侧可见 outgoing
4. 日志：`chatwoot_conversation_created` / `chatwoot_sync_failed`
5. 甲方 UAT 签字（见项目验收文档）

## 6. API 说明

- `POST /api/v1/accounts/{account_id}/conversations`
- `POST /api/v1/accounts/{account_id}/conversations/{id}/messages`

定制 payload 见 `handoff_backend/chatwoot_client.py`。

## 7. E2E

- Mock：`run_enterprise_production_e2e.py` → `CHATWOOT-mock-sync`
- Live：我方 staging 环境 + 甲方 UAT 账号，手动验收
