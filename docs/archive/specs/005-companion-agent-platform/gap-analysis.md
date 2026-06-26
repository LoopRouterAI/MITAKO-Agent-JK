# Gap Analysis：005 Companion 陪伴第二系统

**基准**: `.specify/specs/005-companion-agent-platform/spec.md` + `plan.md`  
**当前代码**: `CompanionShell.jsx` 占位页；无 `companion_api.py`；无 `companion.db`  
**完成度**: **~5%（Phase A 脚手架）**

---

## 组件完成度

| 组件 | 规划 | 现状 | 差距 |
|------|------|------|------|
| `/companion` UI | Chat + Onboarding + presence dock | 静态说明页 + 链接 | **P0** |
| `/companion-desk` | 独立运营/人工台 | HTML 占位 | **P0** |
| `/api/v2/companion/*` | persona/chat/watch/digest | **不存在** | **P0** |
| `companion.db` | persona/messages/watches | **不存在** | **P0** |
| 独立 SSE hook | 不 import useChatSSE | 无 | **P0** |
| 与客服隔离 | 无共享 session/DB | URL 隔离 only | **P0** |
| Onboarding + 敏感词 | Phase B | 无 | **P1** |
| 消费助理 | Phase C | 无 | **P2** |
| 兼职客服模式 | Phase D | 无 | **P3** |

---

## 与客服体系边界（必须遵守 Constitution 扩展）

- **禁止** Companion import `useChatSSE.js` 或写 `handoff.db`
- **允许** 共享：`i18n/index.js`、`RichTextContent`（拷贝或 packages 级）
- **人工协同**：Companion 转人工走 **companion-desk + companion handoff 表**，不进入 `/desk` 队列

---

## 009/008 依赖

- Companion **不依赖** 008 admin 完成，但 companion-desk 运营台可参考 008 鉴权模式
- 009 的 JWT/Redis 模式可复用到 companion API

---

## 退出标准（005 Program）

- `/` 与 `/companion` 同开标签页：sessionStorage、DB、SSE 互不影响
- Onboarding 完成率内部测试 > 80%
- 20 轮 companion 对话 E2E 无空白气泡
- `tests/e2e/run_companion_smoke.py` ≥ 12 项 PASS
