# Contract: VIP客服工作台流程

## GET `/api/v1/desk/sessions`

返回坐席可处理会话列表。每条至少包含：

```json
{
  "session_id": "sess_001",
  "summary": "用户反馈发货慢并要求确认清关进度",
  "status": "queuing",
  "emotion_level": 4,
  "required_tier": "standard",
  "wait_seconds": 420,
  "suggested_next_step": "先同步订单与物流进度，再解释清关节点"
}
```

## POST `/api/v1/desk/session/{session_id}/accept`

**行为**: 客服确认阅读服务记录后接手。前端必须先弹出确认框或确认面板。

## POST `/api/v1/desk/session/{session_id}/transfer`

**行为**: 转交同事。必须提供目标客服，失败时返回可读 `message`。

## POST `/api/v1/desk/session/{session_id}/escalate`

**行为**: 升级到高级客服或专项队列。

## POST `/api/v1/handoff/close`

**行为**: 结案。必须记录结案原因和结果，返回后会话进入 `closed`。

## POST `/api/v1/handoff/reset`

**行为**: 用户侧撤销/清空当前转VIP客服会话，仅允许匹配 handoff token 的客户或有权限的后台/坐席调用。

## 验收

- 所有失败必须有中文反馈。
- 未选择目标客服时不能发起转交。
- 移动端能完成接手、回复、转交/升级、结案。
