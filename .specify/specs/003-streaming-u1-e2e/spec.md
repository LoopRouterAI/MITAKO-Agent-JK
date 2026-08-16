# Feature Specification: 流式客服体验 + SenseNova U1 生图

## 背景
MITAKO 商业演示需真实调用 DeepSeek V4 Flash（SenseNova），默认 SSE 流式 + 打字机效果，并接入 U1 Fast 信息图能力。

## 用户故事
1. 作为吃谷用户，我希望看到虾饺在「核实中」时有二次元 Loading 文案，缓解等待焦虑。
2. 作为演示者，我希望回复以流式打字机呈现，而非整段弹出。
3. 作为运营，我希望系统记住 DeepSeek 500/5h、U1 1500/5h 配额并在超额时拒绝。

## 功能需求

### FR-1 流式对话（默认开启）
- 后端 `call_llm` 必须 `stream: true`
- 前端通过 SSE `chunk` 事件 + `requestAnimationFrame` 渲染
- 首包前展示 `XiaoJiaoLoadingBubble` 轮播文案

### FR-2 思考模式
- 客服场景 `reasoning_effort=none`（.env 可覆盖）

### FR-3 SenseNova U1 Fast
- Model ID: `sensenova-u1-fast`
- Endpoint: `POST /v1/images/generations`
- 共用 `SENSENOVA_API_KEY`
- 配额：1500 次 / 5 小时（滑动窗口持久化）

### FR-4 无 LLM Mock
- 所有客服回复必须走真实 API；无 Key 或失败时返回明确错误

## API 契约
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/chat | SSE 对话流 |
| GET | /api/v1/models | LLM + image_models + streaming_default |
| POST | /api/v1/images/generate | U1 生图 |

## 验收标准
- [ ] 发送消息后 API 日志 payload 含 `stream: true`
- [ ] 首 token 前可见 Loading 气泡
- [ ] 回复逐字/逐块显示且带光标
- [ ] E2E 报告 HTML 全绿或标注真实 API 失败原因
- [ ] 移动端 375px 宽度无横向滚动、输入区 ≥44px 触控目标

## 非目标
- 不在 Agent 状态机内自动触发 U1 生图（仅 API 就绪，后续业务接入）
