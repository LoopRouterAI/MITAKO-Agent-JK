# Implementation Plan: 008 客服管理员运营后台

**Branch**: `008-cs-admin-operations-platform` | **Date**: 2026-06-20 | **Spec**: [spec.md](./spec.md)

## Summary

将 `/admin` 从单页「路由 JSON 编辑器」升级为甲方可用的 **多模块运营后台**：Dashboard、坐席管理、队列监管、审计回放、旁听质检、补偿审批、报表。复用 009 JWT；扩展 `handoff.db` 与 `/api/v1/admin/*`。

## Technical Context

**Frontend**: React 18 + Vite — 新 `src/admin/` 模块化（Shell + 子路由）  
**Backend**: FastAPI routers `admin_agents.py`, `admin_queue.py`, `admin_audit.py`, `admin_qc.py`, `admin_approvals.py`, `admin_reports.py`  
**Storage**: SQLite 扩展表（见 data-model.md）  
**Depends on**: 009 JWT/RBAC 基座

## Constitution Check

- i18n：全部 `admin.*` keys  
- 移动端：Dashboard 响应式；复杂表格桌面优先可接受  
- 品牌：延续 MITAKO 配色，禁止模板紫粉风

## Project Structure

```text
src/admin/
├── AdminShell.jsx           # 侧栏 + 路由
├── AdminLogin.jsx
├── pages/
│   ├── Dashboard.jsx
│   ├── AgentManagement.jsx
│   ├── RoutingRules.jsx     # 自 HandoffAdmin 迁移增强
│   ├── QueueMonitor.jsx
│   ├── AuditLog.jsx
│   ├── ObserverQC.jsx
│   ├── Approvals.jsx
│   └── Reports.jsx
admin_service.py             # 业务编排
admin_store.py               # CRUD
handoff_service.py           # agents 改读 DB
```

## API 前缀（contracts/admin-api.md）

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/v1/admin/auth/login` | 009 可共用 |
| CRUD | `/api/v1/admin/agents` | 坐席档案 |
| GET | `/api/v1/admin/queue/snapshot` | 队列大盘 |
| POST | `/api/v1/admin/queue/{sid}/reassign` | 强制分配 |
| GET | `/api/v1/admin/audit/events` | 转交审计 |
| GET | `/api/v1/admin/audit/sessions/{sid}/transcript` | 回放 |
| GET/PATCH | `/api/v1/admin/qc/observer` | 旁听质检 |
| CRUD | `/api/v1/admin/approvals` | 补偿审批 |
| GET | `/api/v1/admin/reports/summary` | 报表 |

## Phases

1. **P1**: AdminShell + Login + Dashboard + AgentManagement + desk 读 DB agents  
2. **P1**: QueueMonitor + reassign API  
3. **P2**: AuditLog + transcript  
4. **P2**: ObserverQC + Approvals  
5. **P3**: Reports + 导出 CSV  
6. **P2**: E2E 15 项

## Migration

- `_DEMO_AGENTS` → seed migration 脚本写入 `agent_profiles`  
- 现有 `HandoffAdmin.jsx` 逻辑迁入 `RoutingRules.jsx`
