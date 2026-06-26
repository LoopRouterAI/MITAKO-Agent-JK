# 双系统测试指南

> **系统 A** · 智能客服（`/` `/desk` `/admin`）  
> **系统 B** · Companion（`/companion` `/companion-desk`）  
> 验收勾选：[acceptance-checklist-v1.md](./acceptance-checklist-v1.md)

---

## 1. 脚本速查（Windows）

所有脚本位于项目根目录（或 `scripts/`），双击或在项目根执行。

| 脚本 | 用途 | 耗时 |
|------|------|------|
| **[双系统测试-Windows.bat](../双系统测试-Windows.bat)** | **主菜单**（推荐） | — |
| [双系统测试-手工UAT-Windows.bat](../双系统测试-手工UAT-Windows.bat) | 构建 + 启动 + 冒烟 + 五端 | ~2 分钟 |
| [双系统测试-自动化-Windows.bat](../../scripts/双系统测试-自动化-Windows.bat) | 全量 E2E（等同 `run_all_e2e.bat`） | ~10 分钟 |
| [双系统测试-全链路-Windows.bat](../../scripts/双系统测试-全链路-Windows.bat) | E2E + 甲方联调实验室 | ~15 分钟 |
| [dual_system_smoke_test.py](../../scripts/dual_system_smoke_test.py) | 快速 API/页面冒烟 | ~10 秒 |
| [run_all_e2e.bat](../../scripts/run_all_e2e.bat) | 底层 E2E 编排（被自动化脚本调用） | ~10 分钟 |
| [联调-MITAKO对接模拟终端-Windows.bat](../../tools/partner_lab/联调-MITAKO对接模拟终端-Windows.bat) | SSO + Chatwoot Live 自联调 | ~3 分钟 |

### 1.1 推荐测试顺序（发版前）

```bat
cd MITAKO_Agent
scripts\双系统测试-全链路-Windows.bat
```

或分步：

```bat
scripts\双系统测试-自动化-Windows.bat
scripts\双系统测试-手工UAT-Windows.bat
tools\partner_lab\联调-MITAKO对接模拟终端-Windows.bat
```

### 1.2 首次环境

```bat
setup_venv.bat
npm install
copy .env.example .env    REM 填入 LLM API Key（对话功能需要）
venv\Scripts\playwright install chromium   REM 首次 E2E 需要
```

---

## 2. 测试分层

| 层级 | 目的 | 脚本 / 文档 |
|------|------|-------------|
| **L0 冒烟** | 五端可访问 + 核心 API | `dual_system_smoke_test.py` |
| **L1 自动化 E2E** | 平台工程回归 | `双系统测试-自动化-Windows.bat` |
| **L2 甲方模拟终端** | SSO / Chatwoot / 业务契约 | [integration-lab.md](./integration-lab.md) |
| **L3 手工 UAT** | 五端 UI 体验 | `双系统测试-手工UAT-Windows.bat` + 下文 §4–§5 |
| **L4 SOP 业务** | 真实 SOP 分支 | [sop-coverage-gap.md](../product/sop-coverage-gap.md)（V3） |

---

## 3. 账号与 URL

基址默认：**http://127.0.0.1:8000**

| 系统 | 端 | URL | 账号 | 密码 |
|------|-----|-----|------|------|
| A | 用户端 | `/` | — | — |
| A | 坐席台 | `/desk` | desk0816 | desk123 |
| A | 运营台 | `/admin` | admin | admin123 |
| A | 审批（主管） | `/admin` | supervisor | super123 |
| B | Companion | `/companion` | Onboarding 自建 | — |
| B | 运营台 | `/companion-desk` | comp_ops | comp123 |

---

## 4. 系统 A 手工 UAT（约 30 分钟）

**前置**：运行 `scripts\双系统测试-手工UAT-Windows.bat`（或 `一键启动-Windows.bat`）

### 4.1 用户端 `/`

| # | 操作 | 期望 |
|---|------|------|
| A-1 | 发送「我的排球少年盲盒什么时候出荷？」 | 有意图/情绪 capsule |
| A-2 | 高情绪话术或点击转人工 | 排队卡 → 连接成功 |
| A-3 | 消息中 `@虾饺 总结一下` | 旁听回复 |

### 4.2 坐席台 `/desk`

| # | 操作 | 期望 |
|---|------|------|
| A-4 | 登录 desk0816 | 会话列表含上一步 session |
| A-5 | 查看简报 → 接单 → 回复 | 用户端 `/` 同步收到坐席消息 |

### 4.3 运营台 `/admin`

| # | 操作 | 期望 |
|---|------|------|
| A-6 | 队列快照、坐席管理、路由 JSON 保存 | 无报错 |
| A-7 | 创建补偿审批 → supervisor 批准 | 状态变为已批准 |
| A-8 | 报表 summary + CSV 导出 | 文件可下载 |
| A-9 | 7×24 运维页 | Chatwoot/SLA 状态可见 |

---

## 5. 系统 B 手工 UAT（约 20 分钟）

### 5.1 用户端 `/companion`

| # | 操作 | 期望 |
|---|------|------|
| B-1 | 完成 Onboarding（起名、性格） | 进入对话 |
| B-2 | 闲聊 3 轮 | 情绪陪伴口吻 |
| B-3 | 「我的订单物流延迟了要退款」 | 切换 `cs_parttime` |
| B-4 | 添加盯单、心愿单、商品搜索 | 各功能有响应 |

### 5.2 运营台 `/companion-desk`

| # | 操作 | 期望 |
|---|------|------|
| B-5 | Companion 端发起「联系运营」 | handoff 成功 |
| B-6 | comp_ops 登录 → 接单 → 回复 | 用户端收到运营消息 |
| B-7 | 打开 `/desk` 会话列表 | **不出现** Companion 会话 |

---

## 6. 自动化 E2E 明细

运行：

```bat
scripts\双系统测试-自动化-Windows.bat
```

报告：`tests/reports/*.html`

| Python 脚本 | 覆盖 |
|-------------|------|
| `run_full_pipeline_e2e.py` | 系统 A 全链路 + Browser |
| `run_admin_operations_e2e.py` | Admin 17 项 |
| `run_companion_features_e2e.py` | 系统 B 9 项 |
| `run_enterprise_production_e2e.py` | SSO / Chatwoot / Ops 6 项 |
| `run_auth_strict_e2e.py` | 严格鉴权 9 项（脚本内自动重启 AUTH=1） |

---

## 7. 甲方模拟终端联调

```bat
tools\partner_lab\联调-MITAKO对接模拟终端-Windows.bat
```

| 检查点 | URL / 说明 |
|--------|------------|
| Chatwoot 事件 | http://127.0.0.1:9102/events |
| Admin SSO（bpo-east） | http://127.0.0.1:8000/admin |
| 自测脚本 | 末尾 `self_integration_test` 须 **N/N PASS** |

详情：[integration-lab.md](./integration-lab.md)

---

## 8. 严格鉴权模式（生产预演）

`run_all_e2e.bat` 已包含 AUTH=1 阶段。单独验证：

```bat
set MITAKO_AUTH_REQUIRED=1
venv\Scripts\python.exe main.py
venv\Scripts\python.exe tests\e2e\run_auth_strict_e2e.py
```

手工：无 token 访问 `/api/v1/desk/sessions` 应返回 **401**。

---

## 9. V1 通过标准

| 项 | 标准 |
|----|------|
| L1 E2E | 全部脚本 exit code 0 |
| L2 联调 | `self_integration_test.py` 全 PASS（含 Chatwoot Live） |
| L3 手工 | §4–§5 无 P0 阻塞 |
| L4 SOP | 文档交付齐全（执行能力不阻塞 V1 平台签） |

---

## 10. 故障排查

| 现象 | 处理 |
|------|------|
| 8000 被占用 | `scripts\kill_mitako_ports.ps1` |
| E2E Browser 失败 | `venv\Scripts\playwright install chromium` |
| desk 401 | 先登录 desk0816，或 `MITAKO_AUTH_REQUIRED=0` |
| Companion 401 | 先完成 Onboarding |
| 冒烟 FAIL | 确认 `main.py` 已启动 |
| Chatwoot Live skip | 必须用联调 BAT 以 `CHATWOOT_MOCK=0` 重启 |

相关文档：[engineer-onboarding.md](./engineer-onboarding.md) · [deployment-guide.md](./deployment-guide.md)
