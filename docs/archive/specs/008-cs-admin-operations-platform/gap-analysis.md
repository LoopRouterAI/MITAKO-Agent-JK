# Gap Analysis：008 客服管理员运营后台

**对照基准**: `specs/02-AI客服Agent系统设计.md` §7–§8、§观测与运营层  
**当前实现**: `src/admin/HandoffAdmin.jsx` + `PUT /api/v1/admin/handoff/routing`  
**结论**: 当前 `/admin` 仅为 **007 P3 路由配置页**，**不是**甲方所需的管理员后台。

---

## 现状 vs 目标矩阵

| 能力域 | 甲方需求（02 文档 + 007 FR） | 当前 `/admin` | 差距 |
|--------|------------------------------|---------------|------|
| **身份与权限** | 主管/运营/BPO 管理员分级；SSO 或 token | 无鉴权，公开可改路由 | **P0 缺失** |
| **坐席管理** | 工号、团队、tier、技能、在线状态、排班占位 | 硬编码 `_DEMO_AGENTS` | **P0 缺失** |
| **路由策略** | 情绪/VIP/意图 → 队列；规则优先级 | ✅ JSON 规则 + SLA | 缺规则优先级 UI、生效预览 |
| **队列监控** | 实时排队数、等待时长、需主管标识 | 无 | **P0 缺失** |
| **会话监管** | 查看进行中会话、强制转交、重新分配 | 无 | **P1 缺失** |
| **转交审计** | `TransferEvent` 时间线、导出 | DB 有表，无 UI | **P1 缺失** |
| **SLA 看板** | 首响/回复超时、自动转交记录 | 仅配置阈值 | **P1 缺失** |
| **质检 / @虾饺 旁听** | 抽检旁听回复、越权话术告警 | observer 无 audit UI | **P1 缺失** |
| **补偿审批** | 10–100 元主管批、>100 多级（02 §8.1） | 无 | **P2 缺失** |
| **运营报表** | 会话量、转人工率、SLA 达标率 | 无 | **P2 缺失** |
| **系统配置** | 安全规则只读、模型开关只读 | 无 | **P3 缺失** |
| **i18n** | 全后台文案 i18n | 部分硬编码中文 | **P1 缺口** |

---

## 与 007 的关系

- **007** 交付了 handoff **运行时**（用户/desk/WS/简报）和 **最小** admin（路由 JSON）。
- **008** 在 **不破坏 007 API** 前提下，扩展：
  - 新表：`admin_users`、`agent_profiles`（替代 demo 列表）、`approval_requests`、`observer_audits`
  - 新 API 前缀：`/api/v1/admin/*`（鉴权保护）
  - 新前端：`/admin` 升级为 **多模块 Shell**（Dashboard / Agents / Routing / Queue / Audit / QC / Approvals）

---

## 验收门禁（008 专属）

- 管理员登录后可见队列大盘；未登录访问 mutating API → 401
- 坐席 CRUD 持久化，`/desk` 工号选择器读 DB 而非硬编码
- 转交审计页可筛选 session_id / event_type
- E2E：`tests/e2e/run_admin_operations_e2e.py` ≥ 15 项 PASS
