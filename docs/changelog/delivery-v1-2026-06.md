# 变更记录：V1 交付文档与联调实验室（2026-06）

## 新增

- `docs/delivery/` — 双系统部署、测试、验收清单、integration-lab
- `docs/api/rest-api-overview.md` — REST 索引
- `tools/partner_lab/` — 甲方模拟终端（IdP :9101 / Chatwoot :9102 / 业务 :9103）
- `scripts/run_all_e2e.bat` — 全量 E2E
- `scripts/seed_lab_tenant.py` — bpo-east 联调 OIDC 配置

## 测试记录（本轮）

| 套件 | 结果 |
|------|------|
| full_pipeline | 54/54 |
| admin | 17/17 |
| companion | 9/9 |
| enterprise | 6/6 |
| auth_strict | 9/9 |
| self_integration_test | 10/10（SSO Live OK；Chatwoot Live 需 MOCK=0 重启后验） |

## Spec 同步

- `specs/00-delivery-roadmap.md` → V1 验收期 + 文档入口
