# E2E 验收计划：007 人机协同客服平台

**版本**: 1.0 | **类型**: 商业交付门禁 | **执行**: `python tests/e2e/run_handoff_acceptance.py`

## 1. 验收目标

证明 MITAKO 转人工子系统满足 **SC-001 ~ SC-005**（见 spec.md），覆盖 API 级 E2E 与 UI 冒烟清单。

## 2. 环境门禁（G0）

| ID | 检查项 | 通过标准 |
|----|--------|----------|
| G0-1 | 后端存活 | `GET /api/v1/handoff/routing` → 200 |
| G0-2 | 前端构建 | `dist/index.html` + `dist/desk.html` + `dist/admin.html` 存在 |
| G0-3 | SQLite | `data/handoff.db` 可读写（首次自动创建） |
| G0-4 | 默认路由 | `high_emotion_supervisor.enabled === false` |

## 3. 自动化场景（A–E + P3）

| 场景 | ID | 自动化用例 | 断言 |
|------|-----|------------|------|
| A 排队与真实接入 | A1 | request → status=queuing | 无 connected |
| | A2 | accept(CS-0816) | status=connected |
| | A3 | messages 含 welcome | role=human |
| | A4 | desk reply → poll | 用户端 messages 可见 |
| B L5 一线接单 | B1 | emotion=5 + accept standard | ok=true |
| C 转同事 | C1 | transfer → transferring | pending_agent 设置 |
| | C2 | accept(CS-0922) | assigned 变更 |
| D @虾饺旁听 | D1 | user-message @虾饺 | 含 observer 消息 |
| | D2 | 策略检查 | 不含「退现金」「全额退款」 |
| E 富文本 | E1 | brief 含 `#优先发货特权#` | summary 保留 tag |
| P3 WebSocket | W1 | WS 连接 + accept 广播 | 收到 type=status |
| P3 Admin | P3-1 | PUT routing + GET 一致 | config 持久化 |

## 4. UI 冒烟（人工，自动化不覆盖）

- 用户端排队卡文案含「坐席繁忙」「排队中」
- 接入后虾饺退下动画（`prefers-reduced-motion` 降级）
- `/desk` 简报 RichText 与用户端一致
- `/admin` 规则开关保存后新会话生效

## 5. 退出标准

- 自动化：**12/12 PASS**（允许 D 场景 LLM 不可用时 fallback 通过）
- 无 P0/P1 代码审查未关闭项
- CodeGraph 已 sync，`Docs/CodeWiki.md` 已更新

## 6. 报告产物

- `tests/reports/handoff_acceptance_YYYYMMDD_HHMMSS.html`
- 最新一次：**2026-06-20 12/12 PASS** → `tests/reports/handoff_acceptance_20260620_162315.html`

> **端口**：`E2E_BASE_URL` 默认 `http://127.0.0.1:8001`；若 `main.py` 自动占用 8002，请执行  
> `set E2E_BASE_URL=http://127.0.0.1:8002` 后再跑脚本。
- 控制台摘要 + exit code 0/1
