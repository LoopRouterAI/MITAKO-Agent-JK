# 研发工程师上手手册

> 适用：接手 MITAKO_Agent 的我方研发 · 首次克隆到可验收约 **30～60 分钟**

## 1. 仓库是什么

单进程 FastAPI + 五端 React SPA，内含 **两套产品**：

| 系统 | 前台 | 后台 | 数据 |
|------|------|------|------|
| **A · 智能客服** | `/` | `/desk` `/admin` | handoff.db / admin.db |
| **B · Companion** | `/companion` | `/companion-desk` | companion.db |

文档入口：**[开发上手.md](../../开发上手.md)**（根目录）· **[测试指南.md](../../测试指南.md)** · 交付索引 **[delivery/README.md](./README.md)**

## 2. 环境准备（Windows）

```bat
cd MITAKO_Agent
setup_venv.bat          REM 若无 venv
npm install
copy .env.example .env    REM 填入 LLM API Key（对话功能需要）
```

可选 CodeGraph（加速探索）：

```powershell
npm install -g @colbymchenry/codegraph@latest --registry=https://registry.npmmirror.com
codegraph init -i
codegraph sync .
```

## 3. 日常开发启动

```bat
一键启动-Windows.bat
```

等价于：`npm run build` → `seed_auth.py` → `main.py`（Mock Chatwoot）

| 账号 | 密码 | 用途 |
|------|------|------|
| admin | admin123 | /admin |
| desk0816 | desk123 | /desk |
| comp_ops | comp123 | /companion-desk |

## 4. 改代码后必做

```bat
npm run build                              REM 改了前端
scripts\双系统测试-自动化-Windows.bat      REM 发版前 E2E
scripts\双系统测试-全链路-Windows.bat      REM 发版前 E2E + 联调
```

主菜单：`双系统测试-Windows.bat`（根目录）· 指南：[测试指南.md](../../测试指南.md)

首次 Browser E2E：

```bat
venv\Scripts\playwright install chromium
```

CodeGraph 大改后：

```bat
codegraph sync .
```

并更新 `docs/CodeWiki.md` 与相关 `docs/changelog/`。

## 5. 联调甲方接口（模拟终端）

**不要**把 Mock 写进 `main.py`；用独立进程：

```bat
tools\partner_lab\启动甲方模拟终端-Windows.bat
tools\partner_lab\联调-MITAKO对接模拟终端-Windows.bat
```

说明：[integration-lab.md](./integration-lab.md)

## 6. 目录速查

| 路径 | 内容 |
|------|------|
| `main.py` | FastAPI 入口、路由 |
| `agent.py` | 虾饺 LangGraph、SOP 召回 |
| `handoff_*.py` | 转人工 |
| `companion_api.py` | 系统 B API |
| `auth/` | JWT、SSO、多租户 |
| `src/` | 五端 React |
| `tests/e2e/` | 自动化验收 |
| `tools/partner_lab/` | 甲方模拟终端 |
| `docs/delivery/` | 部署/测试/验收 |
| `specs/` | 需求规格（已归档至 `docs/archive/specs/`） |

## 7. 严格鉴权 / 生产配置

见 [deployment-guide.md](./deployment-guide.md) · [production-checklist.md](../security/production-checklist.md)

```env
MITAKO_AUTH_REQUIRED=1
MITAKO_JWT_SECRET=<长随机>
MITAKO_SSO_DEMO=0
REDIS_HOST=<生产 Redis>
```

## 8. 验收与分工

| 阶段 | 内容 | 文档 |
|------|------|------|
| V1 | 平台 + 文档 + 模拟终端 | [acceptance-checklist-v1.md](./acceptance-checklist-v1.md) |
| V2 | 真实 IdP / Chatwoot staging | integration/* |
| V3 | SOP RAG + 虾淘 API | [sop-coverage-gap.md](../product/sop-coverage-gap.md) |

## 9. 常见问题

| 问题 | 处理 |
|------|------|
| 8000 被占用 | `scripts\kill_mitako_ports.ps1` |
| E2E Playwright 失败 | `playwright install chromium` |
| desk 401 | 登录 desk0816 或设 `MITAKO_AUTH_REQUIRED=0` |
| Companion 401 | 先 Onboarding 拿 companion_token |
| SSO 联调 | `seed_lab_tenant.py` + 联调 BAT |

## 10. 提交规范

- 可验收功能 → `docs/changelog/` 一条
- 对接契约变更 → 同步 `tools/partner_lab/` + `integration-lab.md`
- 勿提交 `.env`、`data/*.db` 含真实密钥
