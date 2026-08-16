# MITAKO Agent 交付路线图（系统级）

**版本**: 1.1  
**日期**: 2026-06-20  
**状态**: **V1 平台工程验收期**  
**文档入口**: [docs/delivery/README.md](../docs/delivery/README.md)

---

## 验收分期

| 阶段 | 名称 | 状态 | 文档 |
|------|------|------|------|
| **V1** | 平台工程 + 对接文档 + 模拟终端 | ✅ 可组织验收 | [acceptance-checklist-v1.md](../docs/delivery/acceptance-checklist-v1.md) |
| V2 | Live 联调（真实 IdP / Chatwoot staging） | 待 staging | integration 指南 |
| V3 | SOP 业务执行（RAG + 虾淘 API） | 规划 | [sop-coverage-gap.md](../docs/product/sop-coverage-gap.md) |

> **V1 不含** SOP 逐步自动执行；但 **交付物、API 文档、对接指南、甲方模拟终端** 已齐。

---

## 1. 双产品线

| 产品线 | 入口 | 规格 | E2E | 交付说明 |
|--------|------|------|-----|----------|
| **A · 客服+人机协同** | `/` `/desk` `/admin` | 007–010 | 70/70 + 17 admin | [system-a](../docs/delivery/system-a-cs-platform.md) |
| **B · Companion** | `/companion` `/companion-desk` | 005 | 9/9 | [system-b](../docs/delivery/system-b-companion.md) |

---

## 2. 已完成能力（010）

- 鉴权加固、多租户、SSO OIDC、Chatwoot hybrid、Ops 快照
- `tools/partner_lab/` 甲方模拟终端（IdP / Chatwoot / 业务 API）
- `scripts/run_all_e2e.bat` 全量回归

---

## 3. 规格目录 → 文档沉淀

| ID | 状态 | 运行文档 |
|----|------|----------|
| 007 | UAT ✅ | delivery/system-a + CodeWiki |
| 008 | MVP+ ✅ | delivery/system-a §admin |
| 009 | ✅ | production-checklist + changelog |
| 005 | Phase A–D ✅ | delivery/system-b |
| 010 | ✅ | integration/* + integration-lab |

**建议归档**（不删）：`007/code-review.md`、`007/full-pipeline-e2e-report.md` → `docs/archive/specs/`

---

## 4. Program 退出标准（V1）

- [x] 五端 SPA + 鉴权 + SLA/WS
- [x] E2E 全绿（见 `run_all_e2e.bat`）
- [x] 对接文档 + API 概览 + 模拟终端自联调
- [ ] 甲方 V1 签字（checklist）
- [ ] V2 Live IdP/Chatwoot
- [ ] V3 SOP RAG

---

## 5. 测试命令

```bat
scripts\run_all_e2e.bat
tools\partner_lab\启动甲方模拟终端-Windows.bat
python scripts\seed_lab_tenant.py
python tools\partner_lab\self_integration_test.py
```

详见 [docs/delivery/testing-guide.md](../docs/delivery/testing-guide.md)
