# Implementation Plan: UI/UX Refactor v3.0

## Tech Stack

- React 18 + Vite 5（不变）
- Tailwind CDN + CSS custom properties（`src/styles/tokens.css`）
- `@openuidev/react-lang` + `zod/v4`（不变）
- `lucide-react` 图标（UI chrome）
- 自研 i18n 轻量字典（无 extra deps）

## Architecture

```
src/
├── App.jsx                 # 布局编排 (~150行)
├── i18n/
│   ├── index.js
│   └── zh-CN.js
├── styles/tokens.css
├── constants/
│   ├── memeMap.js
│   └── userOrders.js
├── utils/
│   ├── formatText.js
│   └── copyToClipboard.js
├── hooks/
│   └── useChatSSE.js       # SSE + 状态机
├── components/
│   ├── layout/AppShell.jsx
│   ├── layout/AppHeader.jsx
│   ├── chat/ChatPanel.jsx
│   ├── chat/MessageList.jsx
│   ├── chat/ChatInput.jsx
│   ├── chat/OrderQuickBar.jsx
│   ├── monitor/AgentMonitor.jsx
│   ├── monitor/ApiLogPanel.jsx
│   ├── monitor/NodeTracePanel.jsx
│   └── cards/              # OpenUI 四卡
```

## Visual System

| Token | Value | Usage |
|-------|-------|-------|
| `--mitako-lime` | #C8FF1A | 品牌强调、在线态 |
| `--mitako-purple` | #7B61FF | 主 CTA、用户气泡 |
| `--mitako-sky` | #42C8FF | 监控/科技点缀 |
| `--mitako-orange` | #FF8B38 | 警告、异常订单 |
| `--surface-glass` | rgba(255,255,255,0.82) | 面板背景 |
| `--radius-panel` | 1.25rem | 容器 |
| `--radius-bubble` | 1rem | 气泡 |
| spacing base | 4px grid | 8/12/16/20/24 |

Typography: Outfit display + Noto Sans SC body + JetBrains Mono logs

## Migration Strategy

1. 抽离 constants/utils（零行为变更）
2. 抽离 cards 组件
3. 抽离 useChatSSE hook
4. 组装新布局组件
5. 视觉 token + 移动端抽屉
6. 删除旧 App.jsx 内联定义

## Risks

- OpenUI peer deps：保持 `--legacy-peer-deps` 安装方式
- SSE ref 闭包：沿用现有 `useRef` 模式
