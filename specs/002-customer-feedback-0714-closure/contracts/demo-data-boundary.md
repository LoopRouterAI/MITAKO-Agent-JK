# Contract: 演示数据与甲方联调边界

## 演示响应必填字段

```json
{
  "data_mode": "demo",
  "source_system": "mitako_fixture",
  "integration_status": "not_connected"
}
```

## 待联调能力

未接入的企微、飞书、CRM/CDP、订单、库存、支付、退款、客服队列、对象存储、云转码、电话和短信能力必须返回：

```json
{
  "integration_status": "customer_integration_required",
  "write_effect": "none"
}
```

不得返回会让客户误解为已完成真实业务操作的成功状态。

