# 虾淘私域 Agent 独立实施计划

版本：2026-07-08  
来源：`docs/甲方需求/0708-虾淘私域Agent需求mitako_private_domain_agent_plan_optimized.md`  
边界：遵守 `specs/001-customer-poc-professional-upgrade/plan.md`，真实甲方接口只做 Mock 和契约说明，不伪装已接入。

## 1. 产品判断

私域 Agent 有商业化价值，但价值不在“群里多一个 AI 客服”。客服 Agent 解决的是问题发生后的一对一服务；私域 Agent 解决的是 1 万+群的群资产识别、分层触达、风险禁推、需求沉淀和运营复盘。

一期目标是群级运营闭环：

1. 群能被识别和分层：IP、角色、品类、活跃、转化、疲劳、风险。
2. 商品和活动能精准且安全触达：新品、开赏、补货、隐藏款、库存低位按群匹配。
3. 客诉能提前发现和阻断：不发货、退款、吞烫、霸王条款、多人数共振触发禁推和客服任务。

## 2. 独立模块边界

新增模块命名为“私域 Agent”，前端入口已放在运营后台导航中，后续代码按独立目录推进：

```text
src/admin/pages/PrivateDomainAgent.jsx     # 私域 Agent 后台入口
private_domain/                            # 后续新增：私域 Agent 后端独立域
  schemas.py                               # 群、商品事件、风险、客服任务契约
  service.py                               # 群级策略、禁推、任务生成
  store.py                                 # SQLite POC 存储，生产替换 PostgreSQL
  router.py                                # /api/v1/private-domain/*
```

不把私域逻辑写入现有客服 Agent 主流程，不复用聊天附件接口承载视频审核任务，不把视觉审核工作台伪装成已经联通甲方生产系统。

## 3. P0 实施顺序

1. 企微能力确认表：读群、发群、群成员、外部联系人、会话存档、群发、私聊、点击回传。
2. 数据契约：群资料、商品事件、点击归因、客服任务、客服回写。
3. 群资产模型：基础字段、动态指标、标签、风险、疲劳、健康分。
4. 谷子词典：术语/玩法/活动规则/售后边界，未知问题进入未命中池。
5. 吃谷雷达：商品事件解析、群匹配、高风险群排除、频控、链接归因。
6. 舆情治理：高危词候选、多人共振、L0-L5 分级、禁推、主管预警。
7. 客服协同：私域 Agent 创建任务，客服 Agent 回写状态。
8. Response Guard：所有外发内容审核，不承诺、不争辩、不公开订单隐私。
9. 后台看板：先展示契约状态、待接入项、试点节奏，不展示虚假实时数据。

## 4. 与客服系统打通

私域 Agent 调客服 Agent 的任务字段：

- `user_id`
- `external_user_id`
- `group_id`
- `risk_level`
- `issue_type`
- `message_summary`
- `evidence_messages`
- `possible_order_id`
- `priority`
- `required_action`

客服 Agent 回写字段：

- `ticket_id`
- `ticket_status`
- `handler_id`
- `handle_summary`
- `compensation_status`
- `refund_status`
- `shipping_status`
- `can_reduce_risk`
- `next_follow_up_time`

## 5. 视频 / 照片上传现状

现有用户端聊天附件只支持图片：

- 前端：`src/components/chat/ChatInput.jsx`
- 后端：`/api/v1/chat/attachments`
- MIME：`image/jpeg`、`image/png`、`image/webp`、`image/gif`

视觉审核工作台已经有独立视频入口：

- 服务：`poc/visual_review_poc/workbench_server.py`
- 接口：`/api/review`
- 输入：本地视频或公开 URL

下一步不应把视频直接塞进聊天附件接口，而应新增“审核任务”契约：用户材料 -> 审核任务 -> 视觉审核报告 -> VIP 客服工作台 -> 人工结论 -> 用户可见服务进度。

## 6. Key 与发布策略

真实 Key 不应进入对外 ZIP 或公共 GitHub 包。正确策略是：

1. `.env.example` 提供完整变量名和空值。
2. 本地 `.env` 或部署平台 Secret Manager 填真实值。
3. 启动脚本运行 `scripts/check_runtime_env.py`，只提示缺失项，不输出密钥。
4. 发布包继续排除 `.env`、数据库、日志、上传材料和视频样本。

当前已补齐的变量样例包括：

- `GEMINI_API_KEY`
- `GOOGLE_API_KEY`
- `GEMINI_MODEL`
- `GEMINI_API_BASE_URL`
- `VISION_REVIEW_API_KEY`
- `VISION_REVIEW_GEMINI_BASE_URL`
- `VISUAL_WORKBENCH_PORT`
- `VISUAL_URL_STRICT_DNS_GUARD`
- `VISUAL_URL_DIRECT_MAX_MB`

## 7. 60 天节奏

| 周期 | 目标 | 产出 |
| --- | --- | --- |
| 第 1-2 周 | 权限与数据定界 | 企微能力表、试点群名单、接口契约、词库和高危词 |
| 第 3-4 周 | 群级 MVP 联调 | 谷子词典、吃谷雷达、舆情预警、客服任务、后台入口 |
| 第 5-6 周 | 试点运行 | 200-500 群灰度、每日复盘、误报漏报修正 |
| 第 7-8 周 | 扩容判断 | 试点报告、风险复盘、1000-3000 群扩容计划 |

