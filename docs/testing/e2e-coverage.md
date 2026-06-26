# E2E 测试覆盖与运行说明

## 一键全量

```bat
双系统测试-自动化-Windows.bat
```

或：`scripts\run_all_e2e.bat`

首次 Browser 层需：`venv\Scripts\playwright install chromium`

## 套件一览

| 脚本 | 覆盖 | 前置 |
|------|------|------|
| `run_full_pipeline_e2e.py` | 系统 A 全链路 + Browser | 服务 :8000 |
| `run_admin_operations_e2e.py` | Admin 17 项 | seed_auth |
| `run_companion_features_e2e.py` | 系统 B 9 项 | companion token |
| `run_enterprise_production_e2e.py` | SSO/Chatwoot/Ops 6 项 | — |
| `run_auth_strict_e2e.py` | 严格 401 共 9 项 | `MITAKO_AUTH_REQUIRED=1` |

已合并/移除的旧脚本：`run_full_chain.py`、`run_handoff_acceptance.py`、`run_production_hardening_e2e.py`（由上述套件覆盖）。

## 联调实验室

```bat
tools\partner_lab\启动甲方模拟终端-Windows.bat
python scripts\seed_lab_tenant.py
python tools\partner_lab\self_integration_test.py
```

Chatwoot Live 项需 MITAKO 以 `CHATWOOT_MOCK=0` + `CHATWOOT_BASE_URL=http://127.0.0.1:9102` 重启。

## 报告

`tests/reports/*.html` · 手工场景见 [测试指南.md](../../测试指南.md)
