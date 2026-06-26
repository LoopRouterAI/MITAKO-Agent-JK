# V1 平台工程验收清单

**版本**：V1 · 2026-06  
**范围**：系统 A（客服+desk+admin）+ 系统 B（Companion）+ 企业基建（鉴权/SSO/Chatwoot/Ops）  
**不含**：SOP 逐步自动执行（见 [sop-coverage-gap.md](../product/sop-coverage-gap.md)）

---

## 一、交付物

| # | 交付物 | 路径/说明 | 甲方确认 |
|---|--------|-----------|----------|
| D1 | 可运行应用（五端 SPA） | `一键启动-Windows.bat` | ☐ |
| D2 | 部署指南 | `docs/delivery/deployment-guide.md` | ☐ |
| D3 | 双系统说明 | `system-a-*.md` / `system-b-*.md` | ☐ |
| D4 | API 概览 | `docs/api/rest-api-overview.md` | ☐ |
| D5 | SSO 对接指南 | `docs/integration/sso-oidc-guide.md` | ☐ |
| D6 | Chatwoot 全包指南 | `docs/integration/chatwoot-guide.md` | ☐ |
| D7 | 联调实验室 | `tools/partner_lab/` + `integration-lab.md` | ☐ |
| D8 | E2E 报告 | `tests/reports/` 最新 HTML | ☐ |
| D9 | 生产检查清单 | `docs/security/production-checklist.md` | ☐ |
| D10 | SOP 原文 + 差距说明 | `_extracted_sop/` + `sop-coverage-gap.md` | ☐ |

---

## 二、自动化测试（我方执行，甲方抽检）

执行：`scripts\双系统测试-自动化-Windows.bat` 或 `scripts\双系统测试-全链路-Windows.bat`

| # | 项 | 通过标准 | 确认 |
|---|-----|----------|------|
| T1 | 全链路 E2E | 70/70 | ☐ |
| T2 | Admin E2E | 17/17 | ☐ |
| T3 | Companion E2E | 9/9 | ☐ |
| T4 | Enterprise E2E | 6/6 | ☐ |
| T5 | Auth Strict | 9/9（AUTH=1） | ☐ |
| T6 | 自联调脚本 | `self_integration_test.py` 全 PASS | ☐ |
| T7 | 双系统冒烟 | `dual_system_smoke_test.py` 全 PASS | ☐ |

---

## 三、手工 UAT（甲方）

前置：`scripts\双系统测试-手工UAT-Windows.bat` · 步骤见 [testing-guide.md](./testing-guide.md) §4–§5

| # | 场景 | 确认 |
|---|------|------|
| U1 | 用户转人工 → desk 接单 → 双端同步 | ☐ |
| U2 | Admin 审批（supervisor 批准） | ☐ |
| U3 | Companion 全链路 + 不进 desk | ☐ |
| U4 | SSO 联调（Mock IdP 或真实 IdP） | ☐ |
| U5 | Chatwoot 同步（Mock :9102 或 staging） | ☐ |

---

## 四、签字

| 角色 | 姓名 | 日期 |
|------|------|------|
| 我方项目经理 | | |
| 甲方 IT | | |
| 甲方业务负责人 | | |

**备注**：V1 签字表示平台工程与对接文档验收；SOP 自动执行单列为 V2/V3 里程碑。
