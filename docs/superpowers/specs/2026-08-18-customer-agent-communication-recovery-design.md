# Deeptokenai.cn 客服 Agent 用户沟通质量回归修复设计

> 状态：待用户审阅
> 日期：2026-08-18
> 目标来源：`docs/测试反馈/MITAKO客服Agent用户沟通全量测试报告_20260818.pdf`
> 适用范围：`/api/v1/chat`、用户端 Web、坐席工作台、业务 Mock 契约、Deeptokenai.cn 部署

## 1. 目标

将当前客服 Agent 从“模型生成回复后再做局部安全修补”改造成“程序先确定意图、事实、动作和状态，模型仅负责自然语言表达”的可验收链路。

完成标准：

1. 报告中的 10 个问题全部关闭，其中 P1 全部通过。
2. 原 15 个测试场景连续运行 3 轮，场景分类、核心结论、结构化状态和下一步动作一致。
3. `已上传`、`已接收`、`已建单`、`已转接`、`已审批`、`已修改` 等完成态必须拥有真实工具回执。
4. API、用户回复、右侧意图卡、服务状态卡、坐席队列使用同一个结构化 DTO。
5. PC、Pad、手机端均能显示同一业务状态，不由前端自行猜测。
6. Deeptokenai.cn 可查询后端 commit、前端 build、规则版本和部署时间。

## 2. 非目标和边界

1. 不在本轮接入真实甲方订单、仓库、退款、地址修改或隐私工单系统。
2. Mock 接口只代表演示工具执行结果，不得描述成生产系统已执行。
3. 不改四场景视觉审核的 Prompt、Schema 和报告决策；客服对话只消费其公开结果。
4. 不重写登录、租户、坐席台、审核服务和现有前端框架。
5. 不允许通过增加 Prompt 文案或零散正则替代确定性状态修复。

## 3. 当前根因

当前 `agent.py` 同时负责关键词意图、订单查询、SOP 检索、补偿、回复生成、安全修正和人工转接，用户回复与执行状态之间没有强类型契约。

主要问题：

- 意图只能输出一个泛化字符串，赠品漏发、隐私删除、发错货和地址修改会落入相邻大类。
- 用户陈述、附件事实、订单事实和工具回执混在同一个 Prompt 上下文中。
- `should_transfer=True` 可直接产生“已转接”话术，未强制校验队列回执。
- 商品查询使用模糊字符串包含关系，没有唯一 SKU 门槛。
- 未成年人退款聊天回复只有通用材料清单，没有执行监护人手机号主体规则。
- 回复安全层主要依赖正则替换，无法检查完整业务状态。
- Web 状态卡、意图和回复存在不同数据源。

## 4. 推荐架构

### 4.1 数据流

```text
用户消息与附件
  -> 确定性意图路由
  -> 业务事实解析与来源标记
  -> 工具调用计划
  -> 工具执行与回执归一化
  -> 场景策略决策
  -> 回复计划
  -> LLM 语言表达
  -> 事实/状态一致性校验
  -> API、Web、坐席统一 DTO
```

### 4.2 模块边界

新建 `customer_service/`，避免继续扩张超过 1500 行的 `agent.py`。

| 文件 | 职责 |
|---|---|
| `customer_service/contracts.py` | 意图、事实来源、动作状态、回复计划和公开 DTO |
| `customer_service/intent_router.py` | 确定性意图与场景分类，返回匹配证据和是否需要追问 |
| `customer_service/fact_resolver.py` | 从订单、活动、附件、仓库、会话和人工回写生成带来源的事实 |
| `customer_service/action_state.py` | 统一工具回执，禁止无回执完成态 |
| `customer_service/scenario_policy.py` | 10 类目标场景的确定性规则和下一步动作 |
| `customer_service/reply_plan.py` | 生成 must-say、must-not-say、事实和下一步计划 |
| `customer_service/reply_guard.py` | 拦截无事实支撑的已完成动作、商品、时效和责任承诺 |
| `customer_service/public_projection.py` | 输出 API/Web/坐席共用的脱敏 DTO |

`agent.py` 只保留 LangGraph 编排和兼容入口；现有 `business_api.py`、`handoff_service.py` 和审核服务继续作为工具实现。

## 5. 核心契约

### 5.1 意图结果

```json
{
  "intent_code": "privacy_deletion",
  "scenario_code": "privacy_compliance",
  "confidence": 0.96,
  "matched_evidence": ["删除手机号", "身份证资料", "聊天记录"],
  "requires_clarification": false,
  "clarification_fields": []
}
```

支持的目标意图：

- `minor_refund_material`
- `product_consultation`
- `entitlement_missing`
- `product_damage`
- `wrong_item`
- `missing_item`
- `high_risk_complaint`
- `address_change`
- `privacy_deletion`
- `human_handoff`
- `order_logistics`
- `lottery_rule`
- `refund_progress`

### 5.2 事实

```json
{
  "fact_id": "attachment.received",
  "value": false,
  "source": "attachment_service",
  "source_ref": "session:SESSION-1",
  "verified": true,
  "observed_at": "2026-08-18T20:30:00+08:00"
}
```

允许来源：

- `user_statement`
- `attachment_service`
- `order_service`
- `product_service`
- `activity_service`
- `warehouse_service`
- `handoff_service`
- `review_service`
- `human_update`

`user_statement` 不能单独生成任何系统完成态。

### 5.3 动作状态

```text
not_requested -> requested -> accepted -> queued -> succeeded
                                  \-> failed
                                  \-> pending_human
```

动作对象：

- `material_upload`
- `review_job_create`
- `human_handoff`
- `address_change`
- `privacy_deletion`
- `refund_request`
- `replacement_request`
- `warehouse_lookup`

任何 `succeeded` 或 `queued` 必须包含：

- `receipt_id`
- `tool_name`
- `occurred_at`
- `status`
- 可公开的 `reason_code`

### 5.4 回复计划

```json
{
  "facts": [],
  "must_say": [],
  "must_not_say": [],
  "action": {},
  "next_step": {},
  "allowed_time_commitment": null
}
```

LLM 只能改写这些内容，不能增加商品、状态、时效、责任或已执行动作。

## 6. 十个问题的确定性修复

| 编号 | 场景 | 根因修复 | 通过标准 |
|---|---|---|---|
| 01 | 未成年人退款手机号 | 增加 `mobile_owner_role` 与申请监护人一致性规则 | 未成年人本人手机号发票明确不通过，不再输出可接受 |
| 02 | 商品咨询 | 商品匹配必须唯一命中 SKU/链接/订单行 | 无唯一商品时只追问，不返回任何默认库存或规格 |
| 03 | 赠品/特典漏发 | 新增 `entitlement_missing` 和活动权益基线 | 先确认是否应赠，再进入漏发证据或人工查询 |
| 04 | 材料状态虚构 | 用户陈述、附件接收、解析、建单四态分离 | 无附件回执时禁止出现已上传、已收到、已建单 |
| 05 | 发错货 | 独立路由到发错货公开契约 | 开箱视频是核心证据；缺失时明确证据等级和补件 |
| 06 | 漏发货 | 解析应发 N、实收 M、缺失 SKU | 回复、意图和状态卡均为漏发货且共享同一场景 ID |
| 07 | 延期退款转人工 | 转接话术绑定 handoff 回执 | 未排队时不得说已转接；显示申请人工或失败入口 |
| 08 | 高危投诉 | 固定四项响应协议 | 回复包含责任角色、当前动作、响应时效、跟进凭证 |
| 09 | 地址修改失败 | 地址工具结果与降级模板 | 失败时显示订单状态、失败原因、重试和人工入口 |
| 10 | 隐私删除 | 独立隐私合规意图和策略 | 只给已配置的验证入口、身份要求和 SLA，不编造执行 |

## 7. API 与前端

### 7.1 API

`POST /api/v1/chat` 的 `done` 事件新增：

```json
{
  "status": "completed",
  "reply": "...",
  "conversation_state": {
    "intent": {},
    "facts": [],
    "material_state": {},
    "action_state": {},
    "next_step": {}
  }
}
```

`unified_analysis`、右侧状态卡和坐席简报均从 `conversation_state` 投影，禁止独立重新分类。

### 7.2 Web/Pad/手机

- 用户端只展示用户可理解的意图、动作状态和下一步。
- 坐席端显示事实来源、工具回执、失败原因和建议动作。
- 手机端状态卡必须能区分“未提交、处理中、已排队、失败、完成”。
- 前端不得根据回复文本推断是否已转人工或已建单。

### 7.3 部署版本握手

新增 `GET /api/v1/version`：

```json
{
  "backend_commit": "...",
  "frontend_build": "...",
  "customer_policy_version": "...",
  "deployed_at": "..."
}
```

人工测试报告必须记录该对象，避免用旧部署解释新代码。

## 8. 错误处理

1. 业务接口超时：动作状态为 `failed`，保留重试和人工入口。
2. 找不到商品/订单/活动：进入追问，禁止用默认数据。
3. 转人工服务不可用：显示“尚未进入队列”，不得输出“已转接”。
4. 附件解析失败：显示“已接收但解析失败”，不得显示“审核中”。
5. 模型不可用：程序生成安全确定性回复，不改变结构化状态。
6. 回复与事实冲突：丢弃模型回复，使用 `reply_plan` 的程序模板。

## 9. 安全与隐私

- 公开 DTO 不包含内部 Prompt、模型、渠道、原始证件字段和本地路径。
- 隐私删除场景不把用户输入写入长期偏好记忆。
- 身份证号、手机号和地址进入模型前继续使用现有脱敏边界。
- 租户隔离沿用现有 JWT tenant claim，不允许跨租户查询工单或动作回执。

## 10. 测试策略

### 10.1 固定验收集

将 PDF 的 15 个场景转成脱敏 JSON fixture，记录：

- persona
- user_message
- order/context fixture
- expected_intent
- expected_core_conclusion
- expected_action_state
- expected_next_step
- forbidden_claims

### 10.2 测试层级

1. 意图路由单元测试：15 场景及近义改写。
2. 场景策略测试：十个问题逐项反例和正例。
3. 工具回执测试：成功、失败、超时、重复请求和无回执。
4. API SSE 测试：回复与 `conversation_state` 一致。
5. Web/Pad/手机浏览器测试：同一状态在三端一致。
6. 三轮稳定性测试：每个场景运行 3 次，比较结构化字段而非字面措辞。
7. Deeptokenai.cn 部署复验：记录版本握手、接口响应、截图和人工结论。

### 10.3 发布门禁

- P1 六项全部通过。
- 十个问题全部通过。
- 15 场景三轮结构化一致率 100%。
- 虚构执行状态 0 次。
- API/Web/坐席状态差异 0 次。
- 工具失败均有明确降级入口。

## 11. 实施顺序

1. 冻结 PDF fixture 与版本握手。
2. 建立状态契约和动作回执。
3. 重建确定性意图路由。
4. 实现 P1 业务规则与回复保护。
5. 实现 P2 场景策略和失败降级。
6. 接入 API/Web/坐席统一投影。
7. 完成三轮回归和人工复验。
8. 双仓提交、部署 Deeptokenai.cn、发布新版本。

## 12. 兼容与迁移

- 保留现有 LangGraph 节点名，逐步把节点内部逻辑委托给新模块。
- 保留现有 SSE 事件，新增字段而不删除 `reply` 和 `handoff_offer`。
- 旧前端在不读取 `conversation_state` 时仍可显示回复；新前端必须使用结构化状态。
- 历史会话缺少动作回执时显示“历史状态不可确认”，不回填虚假成功。
