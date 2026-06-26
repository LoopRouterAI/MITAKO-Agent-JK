# MITAKO 虾淘 AI 客服 Constitution

## Core Principles

### I. SOP 优先，体验服从流程
所有 UI 交互必须映射真实客服 SOP：工单边界核验 → 系统预判 → 卡片/话术 → 挂起/转交。禁止展示与 SOP 矛盾的「已自动完成」类文案，统一使用「申请制」温和表达。

### II. 情绪价值与业务准确并重
先共情后事实；结构化卡片（物流、补偿、核实进度、转人工）与流式文本并行；L4+ 情绪自动强化视觉反馈并触发转人工路径。

### III. 移动端优先与无障碍
触摸目标 ≥44px；竖屏单列布局；Agent 监控面板可折叠；禁止 `scrollIntoView`；支持 `prefers-reduced-motion`。

### IV. 模块化与可维护
单文件 ≤1000 行；OpenUI 卡片独立组件；SSE 逻辑抽离 Hook；用户可见文案走 i18n，禁止硬编码。

### V. 品牌一致，拒绝 AI 俗套
沿用 MITAKO 多巴胺配色（Lime `#C8FF1A`、Purple `#7B61FF`、Sky `#42C8FF`、Orange `#FF8B38`）；UI 层减少 emoji 装饰，用 Lucide 图标；禁止紫粉渐变模板风。

## Technology Constraints

- 前端：React 18 + Vite + Tailwind CDN + `@openuidev/react-lang`
- 不改动用户已配置的模型名与 API 接口名（如 `agnes-2.0-flash`、`/api/v1/chat`）
- 调试面板保留但默认折叠，面向演示时可展开

## Governance

Constitution 优先于单次迭代偏好；重大 UX 变更需对照 `specs/006-ui-ux-refactor/` 验收清单。

**Version**: 1.0.0 | **Ratified**: 2026-06-17 | **Last Amended**: 2026-06-17
