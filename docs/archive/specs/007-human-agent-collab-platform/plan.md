# Implementation Plan: 007 人机协同客服平台

**Branch**: `007-human-agent-collab-platform` | **Date**: 2026-06-19 | **Spec**: [spec.md](./spec.md)

## Summary

将 AI→人工移交从「演示级假接入」升级为**商业可交付**的人机协同客服子系统：SQLite 持久化、可配置路由（默认外包一线）、工作台确认接单、双端消息真同步、同事转交/升级/SLA 自动转交、@虾饺 旁听策略、双端 RichText 一致、排队与虾饺退下过渡 UX。

## Technical Context

**Language/Version**: Python 3.11+ / React 18 / Vite 5  
**Primary Dependencies**: FastAPI, sqlite3, LangGraph Agent（旁听轻量 LLM 调用）  
**Storage**: SQLite `data/handoff.db` + `config/handoff_routing.json`  
**Testing**: quickstart 场景 + 现有 `tests/e2e` 扩展点  
**Target Platform**: Win11 单机 / 内网部署  
**Performance Goals**: 人工回复用户可见 p95 ≤3s（轮询 1.5s）  
**Constraints**: 不改用户模型名/API 名；i18n 全覆盖；单文件 ≤1000 行  
**Scale/Scope**: 多客服协作、单会话 transcript、路由可配置

## Constitution Check

| 原则 | 合规 |
|------|------|
| SOP 优先 | 接单须确认简报；补偿仍申请制 |
| 情绪价值 | L4+ 提示申请人工，非强制主管 |
| 移动端/a11y | 动画 reduced-motion 降级；touch ≥44px |
| 模块化/i18n | handoff_store/routing/observer 拆分；文案 zh-CN |
| 品牌 | MITAKO 配色；Lucide 图标 |

## Project Structure

```text
MITAKO_Agent/
├── config/handoff_routing.json
├── data/handoff.db                    # 运行时生成
├── handoff_store.py                   # SQLite CRUD
├── handoff_routing.py                 # 路由规则
├── handoff_observer.py                # @虾饺 旁听
├── handoff_service.py                 # 业务编排
├── main.py                            # 新 API + SLA 后台任务
└── src/
    ├── components/shared/RichTextContent.jsx
    ├── components/chat/XiaoJiaoObserverTransition.jsx
    ├── hooks/useHandoffSync.js
    ├── hooks/useChatSSE.js            # 移除 mock，接入 sync
    └── desk/HumanAgentDesk.jsx
```

## Phase Delivery

| Phase | 交付 |
|-------|------|
| P1 | Store + 路由默认 standard + 双端消息同步 + 接单 UX + RichText |
| P2 | 转同事 / 升级 / SLA + @虾饺 旁听 + 退下动画 |
| P3 | 路由 Admin、WebSocket、SSO（后续 spec） |

## Complexity Tracking

| 项 | 理由 |
|----|------|
| SQLite 新层 | 商业持久化与审计，内存队列不足 |
| 独立 observer 模块 | 防越权承诺，与主 Agent 隔离 |
