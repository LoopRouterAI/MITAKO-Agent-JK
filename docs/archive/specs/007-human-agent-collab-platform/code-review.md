# Code Review：007 人机协同 + P3（2026-06-19）

## 摘要

P1/P2/P3 核心链路已落地：SQLite 持久化、双端真同步、WS 推送、管理后台、E2E 自动化。**无 P0 阻塞项**；P2 项为生产加固建议。

## 已修复 / 已验证项（相对初版 review）

| 项 | 状态 |
|----|------|
| 用户端 setTimeout 假人工回复 | ✅ 已移除，走 API + WS/poll |
| desk 回复不到用户端 | ✅ append + broadcast + ingest |
| L5 硬编码主管 | ✅ 默认 standard + 可配置 rules |
| 双端 RichText 不一致 | ✅ RichTextContent 共享 |
| 缺 E2E | ✅ run_handoff_acceptance.py 12/12 通过 |
| handoff_store 递归初始化 | ✅ `_ensure_db` 直接建表，避免与 `_connect` 互调栈溢出 |

## 剩余建议（按优先级）

### P1 — 生产前建议

1. **管理后台无鉴权** — `/admin` 与 `PUT routing` 应加 token/内网 ACL。
2. **WebSocket 无心跳** — 长连接需 ping/pong 与 reconnect 退避策略。
3. **escalate 后用户态** — 用户端应展示「已升级」系统提示（部分依赖 poll status）。

### P2 — 增强

4. **process_sla_timeouts** 生产环境应用 Celery/独立 worker，避免多 worker 重复转交。
5. **observer LLM 失败** 仅有规则 fallback，应记录 audit 供质检。
6. **Playwright UI E2E** 覆盖动画与 desk 富文本视觉回归。

### P3 — 架构

7. Chatwoot/IM 适配层抽象 `HandoffBackend` interface。
8. 多实例部署需 Redis pub/sub 替代内存 `HandoffHub._rooms`。

## 测试门禁

执行：`python tests/e2e/run_handoff_acceptance.py`  
文档：`specs/007-human-agent-collab-platform/e2e-acceptance.md`

## 结论

**可进入商业演示/UAT 阶段**；上线生产前需完成 P1 鉴权与 WS 稳定性。
