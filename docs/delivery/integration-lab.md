# 甲方联调实验室（模拟终端）

> 设计原则：**与 MITAKO 业务代码解耦** — 独立 HTTP 服务，仅通过 REST 契约对接。  
> 用途：我方自联调 → 甲方对照契约实现真实 IdP / Chatwoot / 业务 API。

## 1. 架构

```
┌─────────────────┐     HTTP      ┌──────────────────┐
│ MITAKO :8000    │ ◄───────────► │ Mock IdP :9101   │
│ (我方产品)      │               │ (甲方 SSO 模拟)  │
└────────┬────────┘               └──────────────────┘
         │
         ├──────────────────────► Mock Chatwoot :9102
         │
         └─ (后续) ─────────────► Mock 业务 API :9103
```

## 2. 启动模拟终端

```bat
tools\partner_lab\启动甲方模拟终端-Windows.bat
```

或分别启动：

```bat
python tools/partner_lab/mock_idp_server.py      REM :9101
python tools/partner_lab/mock_chatwoot_server.py REM :9102
python tools/partner_lab/mock_business_api.py    REM :9103
```

## 3. 配置 MITAKO 对接模拟器

### 3.1 SSO（Mock IdP）

```bat
python scripts/seed_lab_tenant.py
set MITAKO_SSO_DEMO=0
python main.py
```

浏览器：http://127.0.0.1:8000/admin → 选租户 `bpo-east` → SSO 登录  
Mock IdP 会 302 回 `/admin?sso=1&code=lab_oidc_code&state=...`

### 3.2 Chatwoot（Mock Live）

```bat
set CHATWOOT_MOCK=0
set CHATWOOT_BASE_URL=http://127.0.0.1:9102
set CHATWOOT_API_TOKEN=lab-token
set HANDOFF_BACKEND=hybrid
python main.py
```

发起转人工后查看：http://127.0.0.1:9102/events

### 3.3 业务 API（契约演练）

Mock 服务已提供：

- `GET /api/v1/orders/{id}`
- `POST /api/v1/refund/card`

MITAKO 主站尚未硬绑定此 URL；甲方按同契约实现即可。联调脚本会先测 Mock 本身。

## 4. 自联调一键验证

**推荐：一条 BAT 完成 Mock + MITAKO 联调环境 + 自测**

```bat
tools\partner_lab\联调-MITAKO对接模拟终端-Windows.bat
```

等价于：启动三个 Mock → `seed_lab_tenant.py` → 释放 8000 → 以 `CHATWOOT_MOCK=0` / `CHATWOOT_BASE_URL=http://127.0.0.1:9102` 重启 MITAKO → 运行 `self_integration_test.py`。

仅 MITAKO 已手动启动时：

```bat
python tools/partner_lab/self_integration_test.py
```

期望：`结果 N/N` 全 PASS（若 Chatwoot 仍为 mock 模式，Live 项会以 skip 计 PASS，**发版前必须用联调 BAT 验 Live**）。

## 5. 甲方真实对接时

| 模拟端 | 甲方替换为 | 文档 |
|--------|------------|------|
| :9101 IdP | 企业 OIDC | [sso-oidc-guide.md](../integration/sso-oidc-guide.md) |
| :9102 Chatwoot | 我方部署的真实 Chatwoot | [chatwoot-guide.md](../integration/chatwoot-guide.md) |
| :9103 业务 API | 虾淘订单/退款 OpenAPI | 待甲方提供后增补 `docs/api/business-api.md` |

**契约不变**：HTTP 路径与 JSON 字段与模拟器一致即可无缝切换。

## 6. 故障排查

| 现象 | 处理 |
|------|------|
| SSO callback 失败 | 是否 `seed_lab_tenant.py` + Redis 可用 |
| Chatwoot events 空 | 确认 `CHATWOOT_MOCK=0` 且 BASE 指向 :9102 |
| 9101 连接拒绝 | 先启动 `启动甲方模拟终端-Windows.bat` |
