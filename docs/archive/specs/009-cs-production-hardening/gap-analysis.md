# Gap Analysis：007 弱项 + 商业生产共性缺口（009）

**基准**: `007/spec.md` FR-001~012、SC-001~005、`full-pipeline-e2e-report.md`、`code-review.md`  
**目标**: 将 007 从 **UAT/Demo+** 提升至 **可上生产的最小闭环**

---

## 007 FR 弱项 → 009 任务映射

| FR/SC | 007 评级 | 问题 | 009 升级项 |
|-------|----------|------|------------|
| FR-001 | UAT | `accepted_pending`/`closed` 弱 | 补全状态迁移 + closed 归档 API |
| FR-004 | UAT | 动画无 Playwright 回归 | 视觉 E2E + reduced-motion 用例 |
| FR-006 | UAT | 「对口部门」≈ escalate only | 用户端升级提示 + 可选 department 标签 |
| FR-007 | Demo+ | 进程内 `process_sla_timeouts` | Celery Beat + Redis 锁 + 幂等 |
| FR-009 | UAT | observer 无 audit | `observer_audits` 表 + 008 QC 消费 |
| FR-011 | UAT | 用户端 escalate 提示薄 | i18n 系统消息 + WS 推送 |
| FR-012 | Demo+ | admin/desk 硬编码 | 全量 i18n  sweep |
| SC-003 | UAT | desk poll 3–4s | desk 接入 WS（T019） |
| P3 desk WS | 未做 | poll 兜底 | `useHandoffSync` 复用到 desk |

---

## 商业生产共性缺口 → 009 任务映射

| 缺口 | 现状 | 009 交付 |
|------|------|----------|
| 鉴权 | admin/desk 公开 | JWT middleware + desk token + admin login |
| WS 稳定性 | 无 heartbeat | ping/pong 30s + reconnect 退避 |
| 多实例 | 内存 Hub | Redis pub/sub `HandoffHub` |
| SLA worker | main.py 定时 | Celery + 配置化 |
| 观测 | 无 | structlog + `/metrics` + 关键 span |
| IM 抽象 | 直连 handoff_store | `HandoffBackend` protocol + 默认 SQLite impl |
| LLM E2E | 未纳入 51 项 | 可选 gated job `run_full_chain.py` |

---

## 009 不包含

- 008 完整 admin UI（009 只交付 auth/observability 基础供 008 使用）
- Companion（005）
- 私域社群

---

## 退出标准

- 原 51 项 E2E **仍全绿**
- 新增 `tests/e2e/run_production_hardening_e2e.py` ≥ 20 项 PASS
- `code-review.md` P1 项全部关闭
