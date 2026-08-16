# 全链路 E2E 验收报告

**执行时间**: 2026-06-20 17:21:49  
**环境**: `http://127.0.0.1:8000`  
**脚本**: `tests/e2e/run_full_pipeline_e2e.py`  
**HTML 报告**: `tests/reports/full_pipeline_20260620_172149.html`

## 总览

| 维度 | 通过 | 总计 | 说明 |
|------|------|------|------|
| **合计** | **51** | **51** | 100% |
| 代码层 CODE | 10 | 10 | 构建产物、模块导入、SQLite、路由配置 |
| 通信层 COMM | 10 | 10 | REST、页面、WS 双事件、增量 poll |
| 链路层 CHAIN | 6 | 6 | 排队→接入→旁听→升级→富文本 |
| 角色层 ROLE | 17 | 17 | 客户 6 + 客服 7 + 管理员 4 |
| **浏览器层 BROWSER** | **8** | **8** | Playwright 三角色真实 UI 操作 + 截图 |

## 本次修复

- **`handoff_service.build_handoff_brief`**：空对话历史（`confirmHandoff` 默认 payload）时 `user_msgs[-1]` 触发 `IndexError` → 500；已改为空历史时使用 `transfer_reason` 生成摘要。
- **`e2e_lib.discover_base`**：增加 `handoff/request` 探针，避免连到旧进程（8001/8002 半崩溃实例）。
- **E2E 桥接**：`/?e2e=1` 暴露 `window.__MITAKO_E2E__.confirmHandoff()`，Playwright 直接调用真实排队逻辑。

## 浏览器层用例（Playwright）

| 角色 | 用例 | 验证点 |
|------|------|--------|
| 客户 | B-customer-queue-banner | 排队 banner 文案 |
| 客户 | B-customer-api-queuing | API 状态 `queuing` |
| 客服 | B-desk-brief-visible | 移交简报可见 |
| 客服 | B-desk-accept-click | 确认阅读并接受转接 |
| 客户 | B-customer-connected-banner | 已接入 / 旁听 banner |
| 客服 | B-desk-send-reply | 发送含 `#优先发货特权#` 回复 |
| 客户 | B-customer-see-desk-reply | 客户端可见人工消息 |
| 管理员 | B-admin-save-routing | `/admin` 修改 SLA 并保存 |

截图目录：`tests/reports/screenshots/`（01–06 共 6 张，嵌入 HTML 报告画廊）

## 测试矩阵（API 层）

### 代码层（不依赖 UI）

- dist 三端 HTML 存在且非空
- `handoff_store/service/routing/ws/observer` 可导入
- SQLite `handoff_sessions` 表可创建（无 `_ensure_db` 递归）
- 路由 JSON 含 `rules` / `sla` / `default_required_tier=standard`

### 通信层

- REST：`routing`、`agents`、`sessions`、未知 session status
- 静态页：`/`、`/desk`、`/admin` 返回 200
- 未接单时 `connect` 拒绝假接入
- WebSocket：accept 广播 `status` + desk reply 广播 `message`
- `messages?since=` 增量拉取

### 链路层（跨角色编排）

1. 排队态 → 接单后 `connect` 成功 + welcome
2. `@虾饺` 旁听回复（无退赔承诺）
3. 一线 `escalate` → 主管 `CS-1024` 接单
4. 简报保留 `#优先发货特权#`

### 角色：客户 / 客服 / 管理员

- 见 `run_full_pipeline_e2e.py` ROLE 段 17 项

## 结论

**商业 UAT 门禁通过。** 代码 / 通信 / 链路 / 三角色 API + **Playwright 真实浏览器** 全覆盖，无失败项。

## 复现命令

```powershell
cd MITAKO_Agent
npm run build
.\venv\Scripts\python.exe main.py
# 自动探测健康端口（优先 8000）；也可显式指定：
# $env:E2E_BASE_URL="http://127.0.0.1:8000"
.\venv\Scripts\python.exe tests/e2e/run_full_pipeline_e2e.py
# 需 Playwright：pip install playwright && playwright install chromium
```

## 未覆盖（后续迭代）

- SSE `/api/v1/chat` 全 LLM 链（需 API Key，见 `run_full_chain.py`）
- Admin / Desk 鉴权
- desk 端 WebSocket（当前 poll 兜底）
- 移动端触摸 / 动画专项
