# Contract: ServiceCase 与订单归属

## 创建或继续案例

`POST /api/v1/service-cases`

请求必须包含 `user_id`、`session_id`、`message`，可包含显式 `order_ref`。响应返回 `case_id`、已验证订单、业务类型和数据来源。

订单选择规则：

1. 本轮显式订单引用优先。
2. 显式订单必须属于当前用户。
3. 无显式引用时才允许使用当前案例已绑定订单。
4. 不匹配时返回 `order_ownership_mismatch`，不得回退到其他订单。

## 查询案例

`GET /api/v1/service-cases/{case_id}`

必须返回订单、审核任务、人工会话和业务状态的一致快照。演示响应必须携带 DataProvenance。

