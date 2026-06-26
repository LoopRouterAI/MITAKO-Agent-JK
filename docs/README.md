# MITAKO Agent 文档索引

> **主力维护区**：`docs/` — 运行、对接、交付、变更  
> **规格区（已归档）**：`docs/archive/specs/` · 交付摘要见 `docs/delivery/`

## 从这里开始

| 文档 | 读者 |
|------|------|
| **[../开发上手.md](../开发上手.md)** | 我方研发（根目录必读） |
| **[../测试指南.md](../测试指南.md)** | 测试 / 验收（根目录必读） |
| [delivery/deployment-guide.md](./delivery/deployment-guide.md) | 部署 |
| [delivery/integration-lab.md](./delivery/integration-lab.md) | **甲方模拟终端自联调** |
| [delivery/acceptance-checklist-v1.md](./delivery/acceptance-checklist-v1.md) | V1 验收签字清单 |
| [delivery/system-a-cs-platform.md](./delivery/system-a-cs-platform.md) | 系统 A |
| [delivery/system-b-companion.md](./delivery/system-b-companion.md) | 系统 B |
| [api/rest-api-overview.md](./api/rest-api-overview.md) | REST API |

## 架构与对接

| 文档 | 内容 |
|------|------|
| [CodeWiki.md](./CodeWiki.md) | 架构、调用链、鉴权 |
| [integration/sso-oidc-guide.md](./integration/sso-oidc-guide.md) | SSO（甲方 IdP 配合） |
| [integration/chatwoot-guide.md](./integration/chatwoot-guide.md) | Chatwoot（我方全包） |
| [security/production-checklist.md](./security/production-checklist.md) | 生产上线 |
| [testing/e2e-coverage.md](./testing/e2e-coverage.md) | E2E 套件 |
| [product/sop-coverage-gap.md](./product/sop-coverage-gap.md) | SOP 差距（V2+） |
| [changelog/](./changelog/) | 变更记录 |

## 甲方 SOP 原文

[`_extracted_sop/`](./_extracted_sop/) — 11 份抽取文本

## 维护约定

1. 可验收交付 → `docs/changelog/` + 更新 `delivery/acceptance-checklist-v1.md` 若范围变
2. 对接契约变更 → 同步 `tools/partner_lab/` 模拟器 + `integration-lab.md`
3. Spec 阶段完成 → 摘要写入 `docs/delivery/`，spec 位于 `docs/archive/specs/`

## 一键命令

```bat
scripts\双系统测试-Windows.bat          REM 主菜单（推荐）
scripts\双系统测试-全链路-Windows.bat   REM 发版前：E2E + 联调
一键启动-Windows.bat
```
