# E2E 测试覆盖与运行说明

## 一键全量

```bat
scripts\run_all_e2e.bat
```

或：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_all_e2e.ps1
```

首次运行浏览器层测试前需要：

```bat
venv\Scripts\playwright install chromium
```

## 套件一览

| 脚本 | 覆盖 | 前置 |
|---|---|---|
| `run_full_pipeline_e2e.py` | 客服全链路 + Browser | 服务 `:8000` |
| `run_admin_operations_e2e.py` | Admin、审批、报表、队列 | `seed_auth` |
| `run_enterprise_production_e2e.py` | SSO、外部协作、运维 | 服务 `:8000` |
| `run_auth_strict_e2e.py` | 严格 401 与鉴权 | `MITAKO_AUTH_REQUIRED=1` |
| `run_handoff_tenant_guard_e2e.py` | 租户隔离与转人工保护 | 严格鉴权 |
| `scripts/check_visual_workbench_smoke.py` | 视觉审核工作台三类样例 | 工作台依赖可导入 |

旧版 Companion 专项 E2E 已随服务线封存到 `archive/companion_roleplay_mode_20260705/`，不再作为当前回归范围。

## 联调实验室

```bat
tools\partner_lab\启动甲方模拟终端-Windows.bat
python scripts\seed_lab_tenant.py
python tools\partner_lab\self_integration_test.py
```

## 报告

报告输出到 `tests/reports/`。手工场景详见 [测试指南](../../测试指南.md)。
