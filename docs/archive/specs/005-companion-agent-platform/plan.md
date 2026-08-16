# Implementation Plan: 005 Companion 独立产品线

**Branch**: `005-companion-agent-platform` | **Date**: 2026-06-20 | **Spec**: [spec.md](./spec.md)

## Summary

交付完整第二套多系统：独立 `companion.db`、`companion_api.py`（`/api/v2/companion/*`）、Companion Chat SPA、Onboarding、SSE 对话；Phase D 再建 `/companion-desk`。

## Technical Context

**Frontend**: `src/companion/` — `CompanionApp.jsx`, `useCompanionChat.js`, `OnboardingFlow.jsx`  
**Backend**: `companion_store.py`, `companion_api.py`, `companion_agent.py`（独立 prompt，非 agent.py 状态机）  
**Storage**: `data/companion.db`  
**Testing**: `tests/e2e/run_companion_smoke.py`

## Constitution Check + 扩展

- **双产品线隔离**（005 constitution 扩展）：禁止 import useChatSSE / handoff 模块  
- 情感表达允许 + RP 底线：服务端 safety 拦截  
- i18n：`companion.*`

## Project Structure

```text
companion_store.py
companion_api.py             # FastAPI router prefix /api/v2/companion
companion_agent.py           # 轻量 LLM 编排
companion_safety.py          # 敏感词 + 策略
data/companion.db
src/companion/
├── CompanionApp.jsx
├── OnboardingFlow.jsx
├── CompanionChatPanel.jsx
├── hooks/useCompanionChat.js
└── store/companionStore.js  # Zustand
main.py                      # include_router(companion_router)
```

## API（contracts/companion-api.md）

| Method | Path | 说明 |
|--------|------|------|
| GET/PUT | `/api/v2/companion/persona/{user_id}` | 人格 |
| POST | `/api/v2/companion/chat` | SSE |
| GET | `/api/v2/companion/messages` | 分页历史 |
| POST | `/api/v2/companion/watch/order` | 盯单 P2 |
| GET | `/api/v2/companion/digest` | 离线摘要 P2 |

## Phased Delivery

| Phase | 内容 | 工期估 |
|-------|------|--------|
| A | companion.db + persona + chat SSE + UI | 3–5d |
| B | Onboarding + safety + i18n | 2–3d |
| C | watch/查价/wishlist | 3–5d |
| D | companion-desk + 兼职客服 | 5d+ |

## 与 007/008 边界

- 不写入 `handoff.db`  
- companion 转人工（Phase D）使用 `companion_handoff_*` 表，不进入 `/desk` 队列
