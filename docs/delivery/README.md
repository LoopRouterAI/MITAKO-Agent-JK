# MITAKO 双系统交付与测试指南（索引）

> **V1 平台工程验收** · 2026-06 · 业务 SOP 执行见 [product/sop-coverage-gap.md](../product/sop-coverage-gap.md)

## 两套产品

| 系统 | 用户价值 | 前台 | 后台/运营 | 交付文档 |
|------|----------|------|-----------|----------|
| **A · 智能客服 + 人机协同** | SOP 对话、转人工、坐席协同 | `/` | `/desk` `/admin` | [system-a-cs-platform.md](./system-a-cs-platform.md) |
| **B · Companion 陪伴** | 情绪价值、消费助理、独立运营 | `/companion` | `/companion-desk` | [system-b-companion.md](./system-b-companion.md) |

## 从这里开始（根目录）

| 文档 | 读者 |
|------|------|
| **[../开发上手.md](../开发上手.md)** | 研发必读 |
| **[../测试指南.md](../测试指南.md)** | 测试必读 |
| **[../打包说明.md](../打包说明.md)** | 维护方打包 |

## 合作方必读（部署 / 对接 / 测试）

| 文档 | 读者 | 内容 |
|------|------|------|
| [deployment-guide.md](./deployment-guide.md) | 我方运维 + 甲方 IT | 环境、构建、启动、生产 env |
| [testing-guide.md](./testing-guide.md) | 双方 QA | **双系统测试脚本 + 手工 UAT 指南** |
| [engineer-onboarding.md](./engineer-onboarding.md) | **我方研发** | 克隆 → 启动 → E2E → 联调 |
| [integration-lab.md](./integration-lab.md) | 集成工程师 | **甲方模拟终端**自联调 |
| [../api/rest-api-overview.md](../api/rest-api-overview.md) | 开发 | REST API 索引 |
| [../integration/sso-oidc-guide.md](../integration/sso-oidc-guide.md) | 甲方 IdP | SSO 配合项 |
| [../integration/chatwoot-guide.md](../integration/chatwoot-guide.md) | 甲方业务 | IM 全包交付与 UAT |
| [acceptance-checklist-v1.md](./acceptance-checklist-v1.md) | 项目经理 | V1 签字验收清单 |

## 测试脚本（Windows）

| 脚本 | 说明 |
|------|------|
| `scripts/双系统测试-Windows.bat` | **主菜单** |
| `scripts/双系统测试-手工UAT-Windows.bat` | 启动 + 五端 + 冒烟 |
| `scripts/双系统测试-自动化-Windows.bat` | 全量 E2E |
| `scripts/双系统测试-全链路-Windows.bat` | E2E + 联调实验室 |
| `scripts/dual_system_smoke_test.py` | API 冒烟 |

指南：[testing-guide.md](./testing-guide.md)

## 甲方模拟终端（解耦）

目录：`tools/partner_lab/` — **不 import** MITAKO 业务代码，仅 HTTP 契约。

```
启动甲方模拟终端-Windows.bat           → 仅 Mock :9101/:9102/:9103
联调-MITAKO对接模拟终端-Windows.bat    → Mock + Live MITAKO + 自测（发版前必跑）
scripts/seed_lab_tenant.py             → 写入 bpo-east 联调 OIDC
```

## 最近 E2E 报告

`tests/reports/` — 全量见 [../testing/e2e-coverage.md](../testing/e2e-coverage.md)
