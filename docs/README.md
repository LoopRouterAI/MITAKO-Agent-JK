# MITAKO Agent 文档索引

> 当前入口（2026-08-19）：视觉审核继续以四场景契约为真源；客服沟通 v3 Beta 先读 [开发者说明](./release/2026-08-19-v3-beta-developer-notes.md)、[甲方更新说明](./release/2026-08-19-v3-beta-customer-notes.md)、[15×3 回归验收](./testing/客服Agent用户沟通回归验收-20260819.md) 和 [发布回执](./release/2026-08-19-v3-beta-release-receipt.md)。

## 当前主入口

| 文档 | 读者 |
|---|---|
| [product/四场景审核主线进度-20260814.md](./product/四场景审核主线进度-20260814.md) | 所有人；当前 Task、证据、完成状态和唯一下一步 |
| [product/四场景审核业务决策与报告契约-20260812.md](./product/四场景审核业务决策与报告契约-20260812.md) | 产品、客服、Prompt/Schema、后端、前端和测试的唯一业务真源 |
| `product/四场景黄金审核经验/` | 四场景独立人工审核 SOP、禁止推断、原子事实、决策和报告经验 |
| [testing/四场景正式盲测解封评估-20260815.md](./testing/四场景正式盲测解封评估-20260815.md) | 当前正式 API 八案与人工黄金答案的逐案差异、人效边界和发布阻断 |
| [release/2026-08-18-developer-release-notes.md](./release/2026-08-18-developer-release-notes.md) | Java/Python/前端研发；本次代码、数据流、媒体与管理能力变化 |
| [release/2026-08-18-customer-update-notes.md](./release/2026-08-18-customer-update-notes.md) | 甲方客服、产品和项目负责人；本次版本的人话说明 |
| [release/2026-08-18-package-layout.md](./release/2026-08-18-package-layout.md) | 发布与验收人员；三份 ZIP 的内容、隐私和回滚边界 |
| [release/2026-08-19-v3-beta-developer-notes.md](./release/2026-08-19-v3-beta-developer-notes.md) | 研发；客服沟通架构、API、状态机和兼容边界 |
| [release/2026-08-19-v3-beta-customer-notes.md](./release/2026-08-19-v3-beta-customer-notes.md) | 甲方客服与项目负责人；本版可感知变化 |
| [release/2026-08-19-v3-beta-release-receipt.md](./release/2026-08-19-v3-beta-release-receipt.md) | 发布与运维；双仓 Release、三包哈希、测试证据和线上部署状态 |
| [testing/客服Agent用户沟通回归验收-20260819.md](./testing/客服Agent用户沟通回归验收-20260819.md) | 测试、研发和甲方验收；10 项问题与 15×3 证据 |
| [../Codex接续开发交接说明.md](../Codex接续开发交接说明.md) | 迁移设备与 Codex 接续 |
| [迭代维护笔记.md](./迭代维护笔记.md) | 下一轮 Codex 先读的踩坑与需求变化记录 |
| [../README.md](../README.md) | 所有人 |
| [delivery/deployment-guide.md](./delivery/deployment-guide.md) | 部署与实施 |
| [delivery/testing-guide.md](./delivery/testing-guide.md) | 测试与验收 |
| [delivery/acceptance-checklist-v1.md](./delivery/acceptance-checklist-v1.md) | 双方项目经理 |
| [api/rest-api-overview.md](./api/rest-api-overview.md) | 开发对接 |
| [security/production-checklist.md](./security/production-checklist.md) | 上线安全 |

## 对接与系统设计

| 文档系统 | 适合对象 |
|---|---|
| [../甲方沟通交付文档/index.html](../甲方沟通交付文档/index.html) | 甲方 CEO、客服负责人、Java 开发、项目经理 |
| [review_service_api_contract_20260710.md](./review_service_api_contract_20260710.md) | 审核接口对接与自动化验收人员 |
| [delivery/customer-integration-materials-checklist.md](./delivery/customer-integration-materials-checklist.md) | 双方联调与交付负责人 |
| [../我方内部开发文档/index.html](../我方内部开发文档/index.html) | 我方研发、测试、实施 |
| [../我方内部开发文档/客服Agent视觉审核系统设计指南.md](../我方内部开发文档/客服Agent视觉审核系统设计指南.md) | 我方正式开发团队 |

## 历史资料

`我方内部开发文档/MITAKO售后审核Agent业务认知基线-20260727.md`、`integration/百度Gemini原生视频模型选型与传输主线-20260810.md`、0807/0809/旧 0812 甲方说明与验收报告只保留审计追溯，不再作为当前完成状态或发布门禁。

旧版 Companion、陪伴、文字冒险与角色扮演能力已经封存在 `../archive/companion_roleplay_mode_20260705/`，不再作为当前 POC 产品、接口、测试或上线边界。历史 spec 仍可在 `archive/` 或 `docs/archive/` 中查阅。

## 维护约定

1. 可交付变更需要同步更新 `docs/delivery/` 和两套中文交付文档。
2. 接口契约变更需要同步更新 `docs/api/rest-api-overview.md` 和审核服务 API 契约。
3. 上线安全边界变更需要同步更新 `docs/security/production-checklist.md`。
