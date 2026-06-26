# Feature Spec：Companion 可观测平台重构（011）

**状态**：V1.1 重构 · 2026-06  
**替代**：005 中「Companion 人工运营台 / companion-desk 接单」设计

---

## 1. 问题陈述

Companion 用户端 UI/交互显著落后于系统 A（客服 Agent）：深色全屏、无手机模拟框、无右侧调试 Monitor，且对话 SSE 解析不稳定导致「无回复」。  
后台 `/companion-desk` 被误实现为**人工陪伴运营台**，与产品定位不符。

---

## 2. 目标（What / Why）

### 2.1 用户端 `/companion`

- 粉色 + 大面积白色的多巴胺配色，视觉语言与系统 A 一致  
- **PhoneFrame** 手机竖屏对话体验  
- 右侧 **AgentMonitor**：LangGraph 节点 trace、API 请求/响应日志、情绪与安全 capsule  
- 每轮对话必须有可见 Agent 回复（含无 API Key 时的 fallback）

### 2.2 后台 `/companion-desk`（观测台，非人工台）

- 查看**全局** Companion 对话 trace  
- 筛选：安全审核触发、情绪不满、情绪积极、长对话  
- 单条 trace 详情：会话上下文 + LangGraph 节点 + LLM api_log  
- **不提供**人工接入、人工回复

### 2.3 编排与可观测

- **LangGraph**：`safety_scan → emotion_analyze → generate_reply`  
- 每轮持久化 `companion_turn_traces`  
- **LangSmith**（可选）：`LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY`

---

## 3. 用户故事与验收

| ID | 故事 | 验收 |
|----|------|------|
| U1 | 用户 Onboarding 后在手机框内聊天 | 发送消息后 3s 内看到 Agent 气泡 |
| U2 | 研发在右侧看到 graph 节点与 API 日志 | thinking + api_log SSE 事件可见 |
| U3 | 运营在观测台看安全/情绪分布 | summary KPI + filter 列表 |
| U4 | Companion handoff 不进主站 desk | `/desk` 列表不含 companion handoff session |
| U5 | 无 LLM Key 仍有陪伴 fallback | 回复非空且写入 trace |

---

## 4. 非目标

- 不在 Companion 后台做人工陪伴/人工回复  
- 不在 V1.1 实现完整 LangSmith UI 嵌入（仅 env 对接 + 本地 trace 展示）  
- 不合并 Companion 与主站 SOP / handoff.db

---

## 5. 技术要点（Plan 摘要）

| 层 | 方案 |
|----|------|
| 编排 | `companion_graph.py` LangGraph |
| 存储 | `companion_turn_traces` SQLite |
| API | `/api/v2/companion/chat` SSE 扩展；`/observability/*` |
| 前端 | `CompanionApp` + `CompanionObservabilityApp` |
| 废弃 | `desk/sessions` accept/reply → HTTP 410 |

---

## 6. 关联文档

- [system-b-companion.md](../delivery/system-b-companion.md)（待同步）  
- [CodeWiki.md](../CodeWiki.md)  
- 原 005 spec：`.specify/specs/005-companion-agent-platform/`
