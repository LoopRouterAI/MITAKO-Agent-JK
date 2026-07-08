# Implementation Plan: 商业级客服 POC 专业化升级

**Branch**: `001-customer-poc-professional-upgrade` | **Date**: 2026-07-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-customer-poc-professional-upgrade/spec.md`

## Summary

本轮目标是把现有客服 Agent POC 从“能展示能力”提升到“甲方客服负责人、VIP客服、研发对接人都能理解价值和边界”的商业级演示系统。技术策略是保留现有 React + FastAPI + SQLite 架构，不引入重型新依赖；先修复安全与流程闭环，再统一前后台 UI 风格，最后补齐演示数据生命周期、移动端人工台和运营/运维 BI。

本轮明确不做甲方真实业务接口改造，也不伪造已接入状态。订单、物流、仓库、清关、投诉、退款、视觉审核等外部业务能力通过 Mock 数据、接口契约和对接文档表达。

## Technical Context

**Language/Version**: Python 3.x + JavaScript/React 18 + Vite

**Primary Dependencies**: FastAPI、SQLite、React、Tailwind/Lucide、现有视觉审核 POC 服务

**Storage**: SQLite 本地数据库：`handoff.db`、`admin.db`、`auth.db`；视觉审核 POC 使用本地文件与报告目录

**Testing**: `npm run build`、现有 Python smoke/e2e 脚本、人工浏览器回归

**Target Platform**: Windows 11 本地演示优先，兼容 Ubuntu 研发部署

**Project Type**: 前台客服 Web、VIP客服工作台、运营后台、视觉审核 POC 的一体化 Web 应用

**Performance Goals**: POC 演示页面首屏可用；后台指标刷新不阻塞操作；移动端人工台主流程无横向溢出

**Constraints**:

- 不暴露模型供应商、Key、内部 Prompt、外包、调试参数给甲方或用户。
- 不新增重型状态库或 BI 系统，先复用现有接口和数据库。
- 不恢复 Companion/角色扮演/文字冒险模式；保留“专业、同理、有边界”的客服人格。
- 不把演示数据包装成真实甲方数据。
- 所有面向客服的操作文案优先中文、明确、低理解成本。

**Scale/Scope**: 本轮覆盖用户端、人工台、管理中心、视觉审核工作台、文档体系和关键后端安全/数据闭环。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- SOP 优先：通过接手确认、转交/升级/结案、服务记录详情和视觉审核报告回写设计，保持所有 UI 都指向真实客服流程。
- 情绪价值与业务准确并重：保留客服 Agent 的专业同理风格，但不提供陪伴或角色扮演入口。
- 移动端优先与无障碍：修复全局滚动锁死，人工台移动端以队列、会话、档案/操作分段展示；按钮补充明确反馈与可访问标签。
- 模块化与可维护：不引入上帝文件；本轮优先改现有页面和服务，公共样式通过 token 和显式类控制，避免全局强覆盖。
- 品牌一致：对标视觉审核工作台的明亮工具风格，降低粗黑边、硬投影和过亮绿色占比。

**Gate Result**: PASS。没有需要绕过的 constitution 约束。

## Project Structure

### Documentation (this feature)

```text
specs/001-customer-poc-professional-upgrade/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
├── contracts/
│   ├── admin-demo-lifecycle.md
│   ├── handoff-workflow.md
│   └── visual-review-workbench.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
main.py                         # FastAPI 路由与权限边界
admin_service.py                # 队列、转派、报表、审批后台编排
admin_store.py                  # 坐席与审批 SQLite 数据
handoff_service.py              # 人工接手、转交、结案、用户消息
handoff_store.py                # 会话、消息、审计、质检事件 SQLite 数据
ops_service.py                  # 运维健康快照
src/
├── App.jsx                     # 用户端客服入口
├── index.css                   # 全局样式和 MITAKO 视觉层
├── styles/tokens.css           # 设计 token
├── components/cards/           # OpenUI 业务卡片
├── components/chat/            # 用户端聊天与状态面板
├── desk/HumanAgentDesk.jsx     # VIP客服工作台
├── admin/AdminShell.jsx        # 后台导航与布局
└── admin/pages/                # 管理中心页面
poc/visual_review_poc/
├── workbench.html              # 视觉审核工作台
└── workbench_server.py         # 视觉审核 POC API
tests/e2e/
scripts/
```

**Structure Decision**: 继续采用单仓库一体化 POC。前后端不拆成新包，避免商业演示前引入迁移风险。

## Phase Plan

### Phase 0 - Research

输出 `research.md`。目标是把用户反馈、子 Agent 审查、参考工作台风格和外部健康面板思路收敛成可落地决策。

### Phase 1 - Design

输出 `data-model.md`、`contracts/`、`quickstart.md`。重点明确演示数据状态、会话状态、转交/升级/结案、视觉审核工单入口和运维健康指标的契约。

### Phase 2 - Implementation

按 `tasks.md` 先做 P0/P1：

1. 修复 `/api/v1/handoff/reset` 未授权清空风险。
2. 修复全局样式导致非交互卡片像按钮、移动端滚动被裁切的问题。
3. 重构用户端只读业务卡片。
4. 优化VIP客服工作台：刷新反馈、接手确认、结案、转交/升级专用区、移动端分段体验。
5. 优化后台首页、队列监控、报表、运维大盘的指标表达与错误反馈。
6. 为视觉审核工作台补三大任务直达入口语义和更低理解成本的入口参数。

### Phase 3 - Verification

1. `npm run build`
2. 后端权限与核心接口 smoke
3. 视觉工作台 smoke
4. 桌面与 390px 移动端人工检查
5. 子 Agent 对抗式复审

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 无 | 本轮不引入新架构或重型依赖 | 现有系统足以支撑商业 POC 首轮可信度升级 |
