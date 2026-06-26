# MITAKO Agent 更新日志

本文件记录项目主要版本与近期改动。更细分的交付/安全变更见 [`docs/changelog/`](./docs/changelog/)。

---

## [未发版] 2026-06-26 — 私人仓库初始化

### 仓库与同步

- 初始化 Git 仓库，目标远程：`https://github.com/jackdiy/MITAKO-Agent`
- **纳入版本库**：`.env`、`data/*.db`、`viking_memory/`、`dist/`、文档与 Spec
- **排除**：`venv/`、`node_modules/`、`.codegraph/`、SQLite 临时锁文件（`*.db-wal` / `*.db-shm`）
- 业务 SQLite 均使用项目内相对路径 `data/`，拉取后无需改配置即可沿用会话与账号数据

### 跨设备同步建议

1. **推送前**：停止 `一键启动-Windows.bat` 或占用 8000 端口的进程，避免 SQLite 写入冲突
2. **拉取后**：`setup_venv.bat`（若未建 venv）→ `npm install` → 直接启动；`.env` 与 `data/` 已随仓库同步
3. **冲突处理**：若 `data/*.db` 出现 merge 冲突，保留较新一方或在本机备份后选用一份完整库文件

### 数据文件说明（`data/`）

| 文件 | 用途 |
|------|------|
| `auth.db` | 用户/租户/SSO 相关认证数据 |
| `admin.db` | 坐席档案、补偿审批等管理后台 |
| `handoff.db` | 转人工会话、消息、转交审计 |
| `companion.db` | Companion 陪伴会话、trace、冒险模式等 |

---

## 2026-06 — Companion 可观测重构（Spec 011）

### 用户端 `/companion`

- 粉色多巴胺配色 + **PhoneFrame** 手机竖屏体验，与系统 A 视觉语言对齐
- 右侧 **AgentMonitor**：LangGraph 节点 trace、API 日志、情绪与安全 capsule
- 修复 SSE 解析不稳定导致的「无回复」问题；无 API Key 时提供 fallback 回复

### 后台 `/companion-desk`

- 由误实现的「人工陪伴台」改为 **全局观测台**（只读 trace，不提供人工接入）
- 支持按安全审核、情绪、长对话等维度筛选 `companion_turn_traces`

### 编排

- LangGraph 流水线：`safety_scan → emotion_analyze → generate_reply`
- 可选 LangSmith：`LANGCHAIN_TRACING_V2` + `LANGCHAIN_API_KEY`

---

## 2026-06 — V1 交付文档与联调实验室

详见 [`docs/changelog/delivery-v1-2026-06.md`](./docs/changelog/delivery-v1-2026-06.md)

- 新增 `docs/delivery/` 部署、测试、验收、integration-lab
- `tools/partner_lab/` 甲方模拟终端（IdP / Chatwoot / 业务 API）
- `scripts/run_all_e2e.bat` 全量 E2E；`scripts/seed_lab_tenant.py` 联调租户
- E2E 全绿：full_pipeline 54/54、admin 17/17、companion 9/9 等

---

## 2026-06 — 安全加固与企业生产（009/010）

详见 [`docs/changelog/security-hardening-2026-06.md`](./docs/changelog/security-hardening-2026-06.md)

### 鉴权（P0）

- Desk / Companion 读接口 JWT 保护；WebSocket 需 `handoff_token` 或 desk JWT
- Companion C 端 `companion_user` JWT；`/api/v1/handoff/reset` 仅 admin

### 多租户 / SSO（P1）

- `handoff_sessions.tenant_id` 与查询隔离；OIDC 真实 token 交换
- `MITAKO_SSO_DEMO` 默认 **0**；生产走 IdP 对接

### 其他（P2）

- SLA 锁：配置 `REDIS_HOST` 时使用 Redis 分布式锁
- `HANDOFF_BACKEND` 支持 `sqlite` / `hybrid`（Chatwoot）

---

## 2026-06 — LLM 与客服 Agent

- **默认模型**切换为 **DeepSeek V4 Flash**（SenseNova），客服场景 `DEEPSEEK_REASONING_EFFORT=none` 关闭思考模式以提速
- `llm_models.py` 多供应商注册表：DeepSeek V4 Flash + Agnes 2.0 Flash 备用
- `llm_rate_limit.py` 滑动窗口配额追踪（DeepSeek 500 次/5h 等）
- `agent.py` 统一「虾饺」人设与沟通红线；`#高亮词#` 轻量多媒体语法

---

## 更早里程碑（摘要）

| 阶段 | 内容 |
|------|------|
| 005 | Companion 陪伴 Agent 平台（情绪、订单助理、冒险模式雏形） |
| 007 | 人机协同转人工平台（desk、handoff、WebSocket） |
| 008 | Admin 运营后台（坐席、审批、报表） |
| 006 | UI/UX 重构、OpenUI 流式卡片 |
| 003 | 流式 SSE 端到端对话 |

完整 Spec 归档：`docs/archive/specs/`、`.specify/specs/`
