# Contract: 视觉审核工作台

## Direct Entry

- `/visual-review?scenario=video_unboxing`
- `/visual-review?scenario=product_damage`
- `/visual-review?scenario=minor_material`
- POC 本地也支持 `workbench.html?scenario=...`

## POST `/api/review`

现有字段继续保留：

- `source_type`: `upload` | `url`
- `scenario`: `video_unboxing` | `product_damage` | `minor_material`
- `ticket_id`
- `user_id`
- `order_no`
- `customer_claim`
- `order_item`
- `sku`
- `logistics_status`
- `complaint_stage`
- `product_master_data`
- `warehouse_master_data`
- `conversation_history`
- `customer_tone`
- `file` 或 `video_url`

## Report Requirements

报告首屏必须展示：

- 结论
- 置信度
- 证据链
- 缺失材料
- 人工客服下一步动作

报告内部可以保留技术信息，但默认不暴露模型供应商、内部 Prompt 或渠道名给甲方业务人员。

## 验收

- 三大场景可直达，不依赖场景下拉。
- 上传失败、URL 不支持、素材过大时给明确下一步。
- 报告能作为客服工单处理依据，而不是纯技术测试输出。
