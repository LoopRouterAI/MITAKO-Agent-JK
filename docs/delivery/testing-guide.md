# 测试与验收指南

版本：2026-07-11

本文用于本地验证、客户自动化验收和生产联调前回归。测试对象包括客服 Agent、人工客服协同、运营后台、独立审核服务、私域 Agent 以及客户验证包。

## 1. 验收顺序

| 阶段 | 目标 | 责任方 |
|---|---|---|
| 静态检查 | 编译、构建、OpenAPI 与文档完整性 | 我方研发 |
| API 回归 | 鉴权、隔离、审核任务、批次、私域链路 | 我方测试/甲方自动化工具 |
| 页面冒烟 | 用户端、坐席台、运营后台、审核工作台 | 双方项目组 |
| 样本盲测 | 不向模型提供人工标签，对比人工结论 | 双方业务与测试 |
| 生产联调 | 替换 Mock 适配器，验证真实业务契约 | 双方开发 |

## 2. 自动化命令

先启动主服务与视觉审核服务，再执行：

```powershell
npm run build
venv\Scripts\python.exe -m py_compile main.py agent.py business_readiness_service.py
venv\Scripts\python.exe scripts\check_private_deployment_api.py
venv\Scripts\python.exe scripts\check_review_service_batch.py
venv\Scripts\python.exe scripts\check_review_sop_alignment.py
venv\Scripts\python.exe scripts\check_private_domain_agent_e2e.py
venv\Scripts\python.exe scripts\check_private_domain_10k_scale.py
venv\Scripts\python.exe scripts\check_customer_agent_0709_regression.py
venv\Scripts\python.exe scripts\check_visual_workbench_smoke.py
```

若脚本名称因分支调整，以 `scripts/` 中同名验收入口和 `docs/delivery/README.md` 为准。任何失败项都不得通过删除断言或降低阈值绕过。

## 3. 独立审核 API 验收

审核服务优先覆盖四类任务：商品有伤、发错货、漏发货、未成年人退款材料核验。

| 场景 | 必验内容 |
|---|---|
| 单任务 | 完整业务 JSON、多图片/多视频、幂等键、任务状态、结构化结论 |
| 批量任务 | 批次创建、逐任务并发处理、部分失败隔离、批次进度 |
| 大文件 | 元数据预检、直传/对象存储地址、抽帧计划、超限错误码 |
| 抽帧 | 支持后台配置 `fps`，密集审核可配置 1 FPS 或 2 FPS，并保留动态策略 |
| 报告 | 结论、证据、置信度、缺失材料、人工复核建议、耗时、Token 与成本估算 |
| 可观测性 | 以 `job_id` 关联任务、阶段状态、错误分类、失败分段、成本状态和重试信息；完整跨服务 trace_id 待生产日志平台联调 |

批量能力分两种，验收时不得混用：网页“批量父目录”是最多 10 个案件的小批量同步复测工具；正式批量由调用方为每个案件分别创建异步 `/api/v1/review/jobs`，使用同一 `batch_id` 查询汇总。120GB 数据只能按正式异步案件批次导入，不能走网页同步批量。

### 盲测要求

- 输入 JSON、文件名、目录名、提示词和上下文不得包含“正样本/负样本/正确答案”等人工标签。
- 人工标注仅进入测试评估器，不进入模型请求。
- 同一 Case 应重复执行，统计结论一致率、置信度波动、耗时和成本。
- 120G 素材应通过清单分批导入，不直接把全量原始文件塞入单个请求。

## 4. 页面验收

| 入口 | 地址 | 通过标准 |
|---|---|---|
| 用户端 | `/` | 咨询、转人工、消息同步正常，无内部字段泄露 |
| 坐席台 | `/desk` | 接单、回复、转交、升级、审核摘要可用 |
| 运营后台 | `/admin` | 队列、审批、监控、审核任务、私域运营数据可查看 |
| 视觉审核工作台 | `http://127.0.0.1:7861/` | 上传、抽帧、审核、报告生成可完成 |

## 5. 私域 Agent 验收

- 群事件、商品事件、库存/稀有掉落事件可按契约写入。
- 分群、用户生命周期、IP 兴趣、价值与风险标签可查询。
- 运营动作受频率、安静时段、风险策略和审批边界约束。
- 舆情事件可预警、降温并转 1 对 1 客服。
- 企业微信、飞书、CRM/CDP 和真实商品系统未联调时，必须明确显示为 Mock/待联调。

## 6. 通过标准

- 自动化回归全部通过，页面无控制台错误和乱码。
- 受保护接口无凭证拒绝访问，租户间不可越权。
- 单任务失败不阻塞整个批次，失败可定位、可重试。
- 客户验证包不包含真实 Key、数据库、原始样本、内部研发文档或调试参数。
- POC 只给出审核建议和人工复核依据，不自动执行退款、发货、库存或财务写操作。
