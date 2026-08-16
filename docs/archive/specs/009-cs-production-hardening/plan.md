# Implementation Plan: 009 生产化加固

**Branch**: `009-cs-production-hardening` | **Date**: 2026-06-20 | **Spec**: [spec.md](./spec.md)

## Summary

在保持 007 51/51 E2E 不退化前提下，交付 JWT 鉴权、WS 心跳与 desk 实时、Celery+Redis SLA、多实例 pub/sub、用户端转交提示、状态机/i18n 补全、observer audit 表、HandoffBackend 抽象与 metrics。

## Technical Context

**Language/Version**: Python 3.11+ / Node 18+ / React 18  
**Primary Dependencies**: FastAPI, Celery, Redis, httpx, Playwright  
**Storage**: SQLite `handoff.db` + 新表 `observer_audits`；Redis 用于锁与 pub/sub  
**Testing**: pytest + `tests/e2e/run_production_hardening_e2e.py` + 原 `run_full_pipeline_e2e.py`  
**Target Platform**: Windows 11 本地 + 甲方可拷贝部署  
**Constraints**: 不改动用户配置的模型名/API 路径；Constitution i18n/移动端优先

## Constitution Check

| 原则 | 符合方式 |
|------|----------|
| SOP 优先 | 转交/升级系统消息走 i18n，不用 mock 假接入 |
| 模块化 | `auth/`、`handoff_backend/`、`sla_worker/` 独立模块 |
| i18n | FR-009 全量 sweep |
| 不改动模型名 | 仅 middleware/worker，不动 `/api/v1/chat` body |

## Project Structure

```text
MITAKO_Agent/
├── auth/
│   ├── jwt_utils.py
│   ├── middleware.py
│   └── roles.py
├── handoff_backend/
│   ├── protocol.py
│   └── sqlite_backend.py
├── sla_worker/
│   ├── celery_app.py
│   └── tasks.py
├── handoff_ws.py          # Redis pub/sub 扩展
├── handoff_store.py       # observer_audits 表
├── main.py                # metrics、auth 挂载
├── src/desk/              # useDeskHandoffSync.js
├── src/hooks/useHandoffSync.js  # reconnect 退避
└── tests/e2e/run_production_hardening_e2e.py
```

## Phase 0 — Research（见 research 决策摘要）

| 决策 | 选择 | 理由 |
|------|------|------|
| 鉴权 | JWT HS256 + env secret | Windows 友好，008 可扩 SSO |
| 任务队列 | Celery + Redis | SLA 幂等业界标准 |
| WS 多实例 | Redis pub/sub channel `handoff:events` | 最小改动 HandoffHub |
| desk 同步 | 复用 useHandoffSync 模式 | 与用户端一致 |

## Phase 1 — Contracts

见 `contracts/production-api.md`（auth、metrics、closed、system-message）

## Implementation Phases

1. **P1-A**: auth middleware + desk/admin token 登录 API  
2. **P1-B**: WS ping/pong + client reconnect + desk WS  
3. **P1-C**: Celery SLA + Redis lock + 关闭 main.py 内 timer  
4. **P2**: escalate 用户提示、closed、observer_audits、i18n sweep  
5. **P2**: HandoffBackend + /metrics  
6. **P2**: E2E 20 项 + 回归 51 项

## Risks

- Redis/Celery Windows 部署：提供 `docker-compose.yml` 可选 + 文档 fallback 单进程模式（仅 dev）
- JWT 破坏性变更：desk/admin 前端同步发版
