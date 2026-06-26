# Feature Spec: 客服前端体验重构 v3.0

> **Branch**: `006-ui-ux-refactor`  
> **Status**: Approved for implementation  
> **输入来源**: 客服 SOP 培训文档、历史工单 JSON、现有 `specs/05-OpenUI重构与流式组件规范.md`

## Design Read

**Reading this as**: 二次元电商 B2C 客服工作台 for 15–28 岁谷圈用户，warm humanist + MITAKO 潮玩品牌语言，leaning toward 编辑感玻璃拟态 + 单 accent 荧光绿体系。

**Dials**: DESIGN_VARIANCE 7 · MOTION 6 · VISUAL_DENSITY 5

## Problem Statement

| 差距域 | SOP/工单要求 | 当前代码问题 |
|--------|-------------|-------------|
| 流程可视化 | 出荷转囤三分支、210天补偿、卡片退款 | QueryStatusCard 步骤与 SOP 命名不一致 |
| 话术温度 | 「申请制」、禁止模板复读 | 部分 Mock 仍偏系统口吻 |
| 信息架构 | 用户侧简洁 / 坐席侧可展开调试 | 双栏等权，移动端拥挤 |
| 代码健康 | 可迭代 OpenUI 卡片库 | `App.jsx` 1444 行上帝文件 |
| 视觉 craft | 品牌多巴胺 + 精致留白 | emoji 过载、层次弱、缺少设计 token |

## User Stories

### US1 — 用户快速查单跟催（P0）
作为延期出荷用户，我希望一键引用订单并看到**出荷→清关→入库→发货**进度轴，以便理解等待原因而非空等。

**Acceptance**
- 异常订单条常驻输入区上方
- `OrderProgressCard` 延迟态 pulse + 原因字段
- 首响 <3s 感知（QueryStatusCard 即时出现）

### US2 — 安抚与补偿透明（P0）
作为 L3+ 焦虑用户，我希望看到「**正在为您申请**」而非「已赠送」，以便信任平台在处理。

**Acceptance**
- CompensationCard 文案统一申请制
- 虚拟包与免邮券两种 type 分支清晰

### US3 — 高风险转人工（P0）
作为提及 12315/黑猫的用户，我希望看到转接进度并最终锁定输入，符合 SOP 转交规则。

**Acceptance**
- TransferStatusCard calling → connected 动画
- 人工 Banner + 切回 AI 入口

### US4 — 演示/调试模式（P1）
作为实施工程师，我希望 Agent 监控面板可折叠，默认面向用户隐藏 API 日志。

**Acceptance**
- 桌面：右栏可收起
- 移动：底部 Sheet 打开监控

### US5 — 多语言就绪（P2）
作为后续国际化准备，所有 UI  chrome 文案走 i18n 字典。

## Functional Requirements

- FR-001: 拆分 `App.jsx` 为 cards / chat / monitor / hooks / i18n
- FR-002: CSS 设计 token（颜色、间距、圆角、阴影）集中管理
- FR-003: QueryStatusCard 步骤对齐 SOP：倾听 → 查单/物流 → 申请权益 → 整理回复
- FR-004: 移动端 `min-height: 100dvh` 布局，监控面板抽屉化
- FR-005: 滚动使用 `scrollTop`，禁用 `scrollIntoView`
- FR-006: 保留现有 SSE 事件协议与 OpenUI 卡片 schema

## Out of Scope

- 后端 agent.py 逻辑变更
- 真实订单 API 对接
- Chatwoot 集成

## Review Checklist

- [ ] SOP 四段式回复结构在 UI 有对应反馈（核实卡 + 文本流）
- [ ] 品牌色仅来自 token，无 rogue hue
- [ ] 构建 `npm run build` 通过
- [ ] 移动端竖屏可操作（发送、引用订单、切换用户）
