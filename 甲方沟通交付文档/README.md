# 甲方沟通交付文档

本目录面向甲方 CEO、客服负责人、业务负责人、信息化负责人、Java 开发团队和双方项目经理。文档只描述业务流程、对接契约、验收口径和上线准备，不包含我方内部密钥、模型渠道、调试参数或研发实现细节。

## 建议阅读顺序

| 角色 | 建议先读 |
|---|---|
| CEO / 项目负责人 | [客服Agent与视觉审核对接指南.html](./客服Agent与视觉审核对接指南.html)（[MD](./客服Agent与视觉审核对接指南.md)） |
| 客服负责人 | [甲方POC测试说明.html](./甲方POC测试说明.html)（[MD](./甲方POC测试说明.md)）、[客服Agent与视觉审核对接指南.html](./客服Agent与视觉审核对接指南.html)（[MD](./客服Agent与视觉审核对接指南.md)）、[三类视觉审核优先说明.md](./三类视觉审核优先说明.md) |
| 甲方 Java 开发 | [客服Agent与视觉审核对接指南.html](./客服Agent与视觉审核对接指南.html)（[MD](./客服Agent与视觉审核对接指南.md)）、[甲方对接物料与接口清单.html](./甲方对接物料与接口清单.html)（[MD](./甲方对接物料与接口清单.md)） |
| 知识库负责人 | [知识库与视觉识别扩展需求.md](./知识库与视觉识别扩展需求.md) |

## 联调与验收附件

- [OpenAPI 契约草案](../docs/delivery/openapi.yaml)
- [Java / Spring Boot 接入样例](../docs/delivery/java-client-sample.md)
- [POC UAT 验收表](../docs/delivery/poc-uat-checklist.md)
- [数据安全与模型合规清单](../docs/delivery/data-model-compliance-checklist.md)
- [容量规划与并发建议](../docs/delivery/capacity-planning.md)
- [可观测性与运维值班手册](../docs/delivery/observability-runbook.md)

## HTML 版本

可直接打开 [index.html](./index.html) 浏览甲方独立文档系统。核心 HTML 页面均支持在线阅读、打开 MD、下载 MD 和复制 MD：

- [甲方对接物料与接口清单.html](./甲方对接物料与接口清单.html)：甲方需要准备的业务物料、接口、测试环境、负责人和上线确认项。
- [客服Agent与视觉审核对接指南.html](./客服Agent与视觉审核对接指南.html)：接口文档、对接说明、状态机、鉴权、回调和 Java 调用示例。
- [甲方POC测试说明.html](./甲方POC测试说明.html)：现场或远程 POC 怎么启动、怎么测、怎么验收。

HTML 版本与视觉审核工作台保持同款明亮工具风格，适合会议投屏、对齐开发接口和验收范围。
