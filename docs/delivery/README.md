# MITAKO 交付文档索引

版本：2026-07-11

本目录是客户测试 ZIP 内的权威部署、接口、测试和验收材料。接口字段以当前 `openapi.yaml` 为准，完成度以全量复验报告为准。

## 首要文档

| 文档 | 读者 | 用途 |
|---|---|---|
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
