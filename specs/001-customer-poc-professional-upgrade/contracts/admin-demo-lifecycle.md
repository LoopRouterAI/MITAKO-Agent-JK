# Contract: 管理后台演示数据生命周期

## GET `/api/v1/admin/demo/status`

**权限**: 管理后台角色。

**Response**

```json
{
  "ok": true,
  "mode": "demo",
  "loaded_at": 1783238400,
  "scope": ["agents", "handoff_sessions", "approvals", "qc", "reports"],
  "message": "当前展示演示数据，未连接甲方生产接口。"
}
```

## POST `/api/v1/admin/demo/load`

**权限**: 管理后台角色。

**行为**: 加载或补齐演示坐席与演示会话，不覆盖真实甲方生产数据。POC 本地环境可重入执行。

## POST `/api/v1/admin/demo/clear`

**权限**: 管理后台角色。

**行为**: 清理演示会话、消息、转交事件、业务审计、质检、审批。不能清理真实接口数据。

## 验收

- 未登录或无权限请求必须失败。
- 页面必须标识当前数据来源。
- 清空后后台展示可解释空状态。
