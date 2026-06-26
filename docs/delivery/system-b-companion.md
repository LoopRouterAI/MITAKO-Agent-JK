# 系统 B：Companion 陪伴 Agent

## 1. 产品范围

| 端 | URL | 角色 | 能力 |
|----|-----|------|------|
| 用户端 | `/companion` | 付费用户 | Onboarding、手机框对话、LangGraph、右侧 Monitor |
| **观测台** | `/companion-desk` | 运营/质检 | **全局 trace**、安全/情绪筛选（**非人工陪伴**） |

数据：`companion.db` + `companion_turn_traces`（与 `handoff.db` **完全隔离**）

## 2. 部署

与系统 A **同一 `main.py` 进程**：

```bat
npm run build
python main.py
```

## 3. 编排与可观测

- **LangGraph**：`companion_graph.py`（安全 → 情绪 → 回复）
- **LangSmith**（可选）：`.env` 设置 `LANGCHAIN_TRACING_V2=true`
- 每轮对话写入 `companion_turn_traces`，观测台可读

## 4. 测试账号

| 账号 | 密码 | 入口 |
|------|------|------|
| comp_ops | comp123 | `/companion-desk` 观测台 |

C 端：打开 `/companion` 完成 Onboarding。

## 5. 核心 API

- `POST /api/v2/companion/chat` — SSE（thinking / emotion / safety / api_log / message）
- `GET /api/v2/companion/observability/summary` — KPI
- `GET /api/v2/companion/observability/traces` — 列表（filter=safety|negative|positive|long）
- `GET /api/v2/companion/observability/traces/{turn_id}` — 详情

## 6. 验收要点

- [ ] 用户端：粉色多巴胺 + PhoneFrame + 右侧 Monitor + **有回复**
- [ ] 观测台：安全/情绪/长对话筛选
- [ ] Companion 不进 `/desk` 队列
- [ ] E2E：`run_companion_features_e2e.py`

## 7. 规格

详见 [docs/specs/011-companion-observability-redesign/spec.md](../specs/011-companion-observability-redesign/spec.md)
