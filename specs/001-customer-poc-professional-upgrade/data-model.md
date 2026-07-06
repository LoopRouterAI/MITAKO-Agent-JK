# Data Model: 商业级客服 POC 专业化升级

## 演示数据状态

- `mode`: `empty` | `demo` | `real_contract_pending`
- `loaded_at`: 演示数据加载时间
- `scope`: 覆盖范围，如坐席、会话、审批、质检、报表、视觉审核样本
- `source_notice`: 页面展示文案，说明当前是否为 Mock/演示数据

## 客服会话

- `session_id`: 会话 ID
- `tenant_id`: 租户 ID
- `user_id`: 客户 ID
- `status`: `queuing` | `connected` | `transferring` | `escalated` | `closed`
- `summary`: 客户诉求摘要
- `emotion_level`: 情绪/风险等级
- `required_tier`: `standard` | `supervisor`
- `enqueued_at`: 入队时间
- `wait_seconds`: 当前等待秒数，后台动态计算
- `assigned_agent`: 已接手客服
- `pending_agent`: 待确认接管客服
- `brief`: 转人工服务记录
- `close_reason`: 结案原因
- `close_result`: 结案结果

## 客服人员

- `agent_id`: 坐席 ID
- `name`: 展示名
- `title`: 岗位名称
- `tier`: `standard` | `supervisor`
- `team`: 团队
- `skills`: 技能标签
- `enabled`: 是否可接单

## 服务记录

- `messages`: 用户、AI、人工、系统消息
- `transfer_events`: 接手、转交、升级、结案事件
- `business_events`: SOP、售后、仓库、退款、视觉审核、补偿审批事件
- `qc_status`: `pending` | `needs_followup` | `passed`

## 补偿申请

- `id`: 审批 ID
- `session_id`: 关联会话
- `user_id`: 客户 ID
- `amount`: 金额
- `currency`: 币种
- `reason`: 申请原因
- `status`: `pending` | `approved` | `rejected`
- `requester`: 发起人
- `approver`: 审批人
- `approval_level`: 审批等级

## 运营指标

- `queuing`: 排队数
- `connected`: 已接入数
- `escalated`: 升级待处理数
- `longest_wait_seconds`: 当前最长等待
- `avg_wait_seconds`: 平均等待
- `handoff_rate`: 转人工率
- `agent_sessions`: Agent 处理量
- `human_sessions`: 人工处理量
- `visual_review_count`: 视觉审核量
- `visual_review_avg_latency_seconds`: 视觉审核平均耗时
- `availability`: 服务可用状态

## 视觉审核任务

- `scenario`: `video_unboxing` | `product_damage` | `minor_material`
- `ticket_id`: 工单 ID
- `user_id`: 客户 ID
- `order_no`: 订单号
- `customer_claim`: 用户诉求文本
- `order_item`: 商品名
- `sku`: SKU/规格
- `logistics_status`: 物流/仓库/清关状态
- `evidence_files`: 视频、图片、补充资料
- `result`: 结论、置信度、证据链、缺失材料、人工动作建议
