# MITAKO Agent Code Wiki

本页给研发快速定位当前 AI客服系统、VIP客服工作台、运营后台与视觉审核工作台的代码边界。旧版 Companion、陪伴、文字冒险与角色扮演代码已经封存在 `../archive/companion_roleplay_mode_20260705/`。

## 产品入口

| URL | 入口 | 说明 |
|---|---|---|
| `/` | `index.html` | 用户端 AI客服 |
| `/desk` | `desk.html` | VIP客服工作台 |
| `/admin` | `admin.html` | 运营后台 |
| `http://127.0.0.1:7861/` | `poc/visual_review_poc/workbench_server.py` | 三大视觉审核工作台 |

## AI 客服调用链

```text
用户输入
  -> src/hooks/useChatSSE.js
  -> POST /api/v1/chat
  -> agent.py 状态机
  -> SOP / 订单 / 物流 / 售后适配层
  -> 安全清洗与客服话术
  -> 前端 MessageList + 业务卡片
```

客服 Agent 保留 MBTI 服务人格，但定位是“专业、同理、有边界的服务型助手”。它可以安抚、解释、整理材料、建议转VIP客服；不能提供陪伴、角色扮演、恋爱或无人最终裁决。

## 转VIP客服调用链

```text
用户确认转VIP客服或 Agent 触发升级
  -> POST /api/v1/handoff/request
  -> handoff_service.build_handoff_brief
  -> handoff_store 写入 handoff.db
  -> /desk 坐席接单、回复、转交、升级
  -> handoff_ws 广播状态与消息
  -> 用户端轮询或 WebSocket 同步
```

## 运营后台

```text
/admin
  -> src/admin/*
  -> /api/v1/admin/agents
  -> /api/v1/admin/queue/snapshot
  -> /api/v1/admin/approvals
  -> /api/v1/admin/reports/*
  -> admin_store.py
```

## 视觉审核工作台

```text
客服上传材料或选择样例
  -> poc/visual_review_poc/workbench.html
  -> workbench_server.py
  -> 抽帧 / 证据包 / 审核 prompt
  -> 多模态审核调用
  -> report_renderer.py 生成客服可读 HTML 报告
```

三类审核入口应保持独立：开箱视频审核、商品有伤审核、未成年人资料审核。报告优先展示结论、置信度、证据链、缺失材料和人工复核建议。

## 生产基础设施

| 模块 | 职责 |
|---|---|
| `auth/` | JWT、角色门控、SSO OIDC |
| `handoff_store.py` | 会话、消息、审计 SQLite 存储 |
| `handoff_service.py` | 人工接手与服务记录编排 |
| `handoff_ws.py` | WebSocket Hub 与实时同步 |
| `admin_store.py` | 坐席、审批、报表数据 |
| `business_api.py` | 验证环境业务适配接口 |
| `business_readiness_service.py` | 业务准备度、SOP 分支与边界判断 |
| `poc/visual_review_poc/` | 视觉审核工作台与 E2E 工具 |

## 鉴权矩阵

| 路径 | 要求 |
|---|---|
| `/api/v1/admin/*` 变更 | `ADMIN_MUTATE_ROLES` |
| `/api/v1/desk/*` 读取 | `DESK_ACCESS_ROLES` |
| `/api/v1/desk/*` 写入 | `DESK_MUTATE_ROLES` |
| `/api/v1/handoff/ws/*` | `handoff_token` 或坐席 JWT |
| `/api/v1/handoff/reset` | 管理员 |

## E2E 回归

```powershell
cd MITAKO_Agent
npm run build
python scripts/dual_system_smoke_test.py
python tests/e2e/run_admin_operations_e2e.py
python tests/e2e/run_enterprise_production_e2e.py
python tests/e2e/run_auth_strict_e2e.py
python scripts/check_visual_workbench_smoke.py
```

最后更新：2026-07-05。
