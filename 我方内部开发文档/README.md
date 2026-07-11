# 我方内部开发文档

版本：2026-07-11
适用对象：我方 Java/Python/前端研发、测试、实施、运维、产品和项目管理。

本目录用于研发交接和私有化部署，不进入甲方客户测试 ZIP。对外材料只使用 `甲方沟通交付文档/` 与 `docs/delivery/`。

## 新同事阅读顺序

1. [工程师入门.md](./工程师入门.md)：启动、端口、测试和开发边界。
2. [系统清单与代码地图.md](./系统清单与代码地图.md)：所有运行系统、代码入口、存储和依赖关系。
3. [Java开发部署与联调指南.md](./Java开发部署与联调指南.md)：Java 网关如何调用、部署和排障。
4. [升级日志-2026-07-11.md](./升级日志-2026-07-11.md)：从旧客服 POC 到当前审核服务、私域 Agent 和交付包的变更。
5. [内部研发包交付说明.md](./内部研发包交付说明.md)：源码、Key、数据库、样本和敏感数据交付边界。
6. [客服Agent视觉审核系统设计指南.md](./客服Agent视觉审核系统设计指南.md)：客服与视觉审核内部设计。
7. [全量需求复验报告](../docs/delivery/mitako-full-requirement-reaudit-20260711.html)：当前完成度和生产阻塞项。

## 权威契约

| 文档 | 说明 |
|---|---|
| [当前 OpenAPI](../docs/delivery/openapi.yaml) | 由当前 FastAPI 应用生成，不手工维护接口字段 |
| [Java 调用样例](../docs/delivery/java-client-sample.md) | WebClient 登录、审核提交、轮询、批次查询 |
| [部署指南](../docs/delivery/deployment-guide.md) | 主服务、视觉服务、环境变量和健康检查 |
| [测试指南](../docs/delivery/testing-guide.md) | 自动化与手工 UAT |
| [运维 Runbook](../docs/delivery/observability-runbook.md) | 指标、日志和故障恢复 |
| [容量规划](../docs/delivery/capacity-planning.md) | 大视频、120GB 批次和对象存储方案 |

## 当前系统边界

- 主服务和视觉服务是两个进程，主服务通过 HTTP 调用视觉服务。
- Java 系统调用主服务的 `/api/v1/review/*`，不直接依赖内部视觉模型接口。
- 私域 Agent 当前是群级 P0，不是完整生产运营平台。
- 真实企微、飞书、CRM、订单、库存和对象存储只做契约与适配，不得伪装已接入。
- 旧陪伴、角色扮演和文字冒险能力继续封存在 `archive/`，不得重新进入运行时和客户包。

## 发布纪律

- 每次客户打包前必须先启动内部源码版双服务，并执行 `scripts/pre_release_internal_validation.ps1`。
- `scripts/package_release.ps1` 已将上述校验设为强制前置，失败时不会生成新的客户 ZIP。
- 审核提示词、抽帧或模型路由发生变化时，发布候选版必须追加 `-RunModelBatch` 真实批量审核。

浏览入口：[index.html](./index.html)
