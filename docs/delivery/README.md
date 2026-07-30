# MITAKO 交付文档索引

版本：2026-07-30

本目录是客户测试 ZIP 内的权威部署、接口、测试和验收材料。接口字段以当前 `openapi.yaml` 为准，完成度以全量复验报告为准。

本轮多源客诉接入先读：[客诉审核 Agent 与沟通 Agent 接口联调指南](./after-sales-agent-integration.md)。它说明订单、包裹物流、当前工单对话、风险摘要的边界，以及审核 Agent 和沟通 Agent 如何接入甲方后台。

## 首要文档

| 文档 | 读者 | 用途 |
|---|---|---|
| [0730 未成年人资料与客服报告验收](./mitako-0730-minor-report-acceptance-20260730.html) | 双方负责人/研发/测试 | 默认策略、动态容量、真实 API、浏览器 E2E 和剩余边界 |
| [审核建议结果 API 使用说明](./review-advisory-api.md) | Java/产品/测试 | 事实结论、置信度、三级复审、离框补件和 JSON/HTML 选择 |
| [0730 非技术更新说明](../../甲方沟通交付文档/0730未成年人资料审核与客服报告升级说明.html) | 双方负责人/客服 | 用人话说明未成年人资料策略、交通灯报告和复测方法 |
| [0723 非技术更新说明](../../甲方沟通交付文档/0723审核结论置信度与人工复审分级说明.html) | 双方负责人/客服 | 用人话说明本轮代码实际改变了什么 |
| [订单资料与官方商品图按需接入说明](../../甲方沟通交付文档/0722订单资料与官方商品图按需接入说明.html) | 双方负责人/研发/测试 | 新资料完整度、唯一映射、官方主图按需读取、API/网页和剩余边界 |
| [视觉审核工程验收报告](./mitako-visual-evaluation-engineering-acceptance-20260716.html) | 双方负责人/研发/测试 | 0715 方法复核、三通道审核、损伤因果、履约对账、真实运行和边界 |
| [0714 对抗式验收报告](./mitako-0714-adversarial-acceptance-20260715.html) | 双方负责人/研发/测试 | 0714 反馈、根因、修复、自动化证据与外部联调边界 |
| [全量需求复验报告](./mitako-full-requirement-reaudit-20260711.html) | 双方负责人 | 40 项需求状态、测试证据、外部依赖和生产阻塞 |
| [部署指南](./deployment-guide.md) | Java/实施/运维 | 主服务、视觉服务、环境变量、健康检查和大文件方案 |
| [OpenAPI](./openapi.yaml) | Java 开发 | 当前 FastAPI 完整接口契约 |
| [Java 接入样例](./java-client-sample.md) | Java 开发 | 采样规划、多文件审核、轮询、批次查询 |
| [测试指南](./testing-guide.md) | 测试/实施 | API、视觉、客服、私域和页面回归 |
| [验收清单](./acceptance-checklist-v1.md) | 项目经理 | POC/UAT 签字范围 |

## 其他文档

- [客服平台说明](./system-a-cs-platform.md)
- [甲方对接物料清单](./customer-integration-materials-checklist.md)
- [联调实验室](./integration-lab.md)
- [容量规划](./capacity-planning.md)
- [可观测与排障](./observability-runbook.md)
- [数据与模型合规](./data-model-compliance-checklist.md)
- [POC UAT 表](./poc-uat-checklist.md)

## 当前系统

- 用户端 AI 客服、VIP 人工客服工作台、运营后台。
- 独立审核编排 API 和视觉审核执行服务。
- 商品有伤、发错货、漏发货、未成年人退款资料四类审核。
- 虾淘私域 Agent P0。
- 运维指标、Prometheus、任务诊断和发布包安全门禁。

## 边界

真实企微、飞书、订单、库存、CRM/CDP、对象存储转码和生产基础设施必须在甲方测试/灰度环境联调。当前交付包不包含真实 Key，也不自动执行退款、补发、换货、拒绝或最终定责。
