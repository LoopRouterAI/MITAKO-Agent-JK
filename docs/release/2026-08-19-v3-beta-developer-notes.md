# MITAKO Agent v3 Beta 开发者发布说明

发布日期：2026-08-19

版本标签：`v3.0.0-beta.1`

适用对象：Java、Python、前端、测试、实施与运维研发。

## 本版解决什么

本版集中修复用户沟通链路，不用视觉审核或日志能力冒充客服质量提升。修复来源是 `MITAKO客服Agent用户沟通全量测试报告_20260818.pdf` 中的 10 项人工反馈：未成年人手机号材料、模糊商品、特典漏发、虚构材料接收、发错/漏发路由、延期退款转人工、高风险投诉、地址修改失败和隐私删除。

## 核心结构变化

- 新增 `customer_service/` 领域层：确定性意图、事实来源、工具回执、场景策略、ReplyPlan、回复守卫和公开状态投影。
- LangGraph 保留编排职责；语言模型只润色程序生成的 ReplyPlan，不得修改意图、情绪、业务结论、动作状态、回执或下一步。
- API、用户端和坐席端统一消费 `conversation_state`，不再从自然语言猜测“已转接、已完成、审核中”。
- 用户陈述和系统事实分离。`user_statement` 永不成为 verified fact；`queued / succeeded` 强制要求工具名、回执和时间戳。
- 客户端停止生成、断连、全链超时和同 Session 新轮次会取消并等待旧任务；取消轮次不会写助手消息、人工队列或成功终态。
- 人工转接先暂存，只有 SSE 成功终态提交后才发布队列事件；发布失败会回滚本轮消息和队列状态。

## API 变化

`POST /api/v1/chat` 的 SSE `done / transfer / card` 增加同源公开字段：

```json
{
  "conversation_state": {
    "intent": {},
    "facts": [],
    "material_state": {},
    "action_state": {},
    "next_step": {},
    "core_conclusion": ""
  }
}
```

公开投影不包含模型、渠道、Prompt、内部工具名、附件内部引用或个人证件原值。

新增 `GET /api/v1/version`：

```json
{
  "backend_commit": "...",
  "frontend_build": "...",
  "customer_policy_version": "MITAKO-CUSTOMER-CHAT-20260818.1",
  "deployed_at": "..."
}
```

客户包启动脚本自动注入上述版本字段；生产部署也应显式注入，禁止通过运行时 Git 命令猜版本。

## 前端变化

- 生成期间发送按钮原位变为“停止生成”，桌面与手机均满足 44px 触控目标。
- 用户端和坐席端共用 `ConversationStateCard`，状态统一为未提交、待执行、已受理、排队中、已完成、未执行成功、等待人工。
- 材料尚未上传时只显示“未提交 / 上传本轮待审核材料”，不会出现无依据默认订单、售后处理单或高危人工提示。
- 人工队列状态变化后，用户端通过状态查询更新同一公开状态；坐席端读取当前队列回执覆盖旧简报。

## 自动验证

- 全仓：`1476 passed + 100 subtests passed`。
- 客服领域与正式 API：15 场景连续 3 轮，`45/45`。
- P1：`6/6`。
- 禁止词命中：`0`。
- 虚构完成态：`0`。
- PC、1024×768 Pad、390×844 手机：公开状态一致且无横向溢出。
- 前端构建：`1926 modules transformed`。

机器证据：[客服沟通验收 JSON](../testing/evidence/customer_chat_20260819_acceptance.json)；人工可读报告：[客服沟通回归验收](../testing/客服Agent用户沟通回归验收-20260819.md)。

## 仍未接通的边界

- 真实甲方订单、仓库、地址修改、隐私、退款和 CRM 接口仍为契约或 Mock。
- 写操作未接通时必须显示失败、待执行或人工入口，不能显示已修改/已删除/已退款。
- 本地 15×3 使用确定性 ReplyPlan 渲染器，不代替线上真实模型回归和人工客服复验。
- 旧 Companion、陪伴、角色扮演和文字冒险能力继续封存。
