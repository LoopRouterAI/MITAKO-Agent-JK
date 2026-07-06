# 我方内部开发文档

本目录只给我方产品、研发、测试、实施和项目管理同事使用，用于后续正式开发、联调、上线和运维。这里可以记录内部模块边界、验证环境适配层、模型选型、测试命令、风险项和实施策略，不建议直接发给甲方。

## 建议阅读顺序

| 角色 | 建议先读 |
|---|---|
| 我方研发 | [客服Agent视觉审核系统设计指南.html](./客服Agent视觉审核系统设计指南.html)（[MD](./客服Agent视觉审核系统设计指南.md)） |
| 我方测试 | [POC审查Demo提交前检查清单-2026-07-03.md](./POC审查Demo提交前检查清单-2026-07-03.md)、`docs/delivery/testing-guide.md` |
| 我方实施 | [POC展示与联调开发说明.md](./POC展示与联调开发说明.md)、`docs/delivery/deployment-guide.md` |
| 项目负责人 | [客服Agent视觉审核系统设计指南.html](./客服Agent视觉审核系统设计指南.html)（[MD](./客服Agent视觉审核系统设计指南.md)）、[视觉审核后台配置与模型选型E2E说明.md](./视觉审核后台配置与模型选型E2E说明.md) |

## 必读交付附件

- [OpenAPI 契约草案](../docs/delivery/openapi.yaml)
- [Java / Spring Boot 接入样例](../docs/delivery/java-client-sample.md)
- [POC UAT 验收表](../docs/delivery/poc-uat-checklist.md)
- [生产部署与容量规划](../docs/delivery/capacity-planning.md)
- [可观测与 7×24 运维 Runbook](../docs/delivery/observability-runbook.md)
- [数据安全与模型合规清单](../docs/delivery/data-model-compliance-checklist.md)

## HTML 版本

可直接打开 [index.html](./index.html) 浏览我方内部文档系统。核心 HTML 页面均支持在线阅读、打开 MD、下载 MD 和复制 MD：

- [客服Agent视觉审核系统设计指南.html](./客服Agent视觉审核系统设计指南.html)：内部系统边界、工作台打通方式、接口适配层、队列重试、模型策略、验收脚本和落地计划。
- [../甲方沟通交付文档/甲方对接物料与接口清单.html](../甲方沟通交付文档/甲方对接物料与接口清单.html)：实施和研发核对甲方需要准备什么。
- [../甲方沟通交付文档/客服Agent与视觉审核对接指南.html](../甲方沟通交付文档/客服Agent与视觉审核对接指南.html)：研发与甲方 Java 团队对齐接口契约。

该目录用于我方研发评审、交接和后续迭代，不作为对外承诺材料；对外材料请只使用 `甲方沟通交付文档` 目录。
