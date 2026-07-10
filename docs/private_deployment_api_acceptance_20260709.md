# 虾淘私域 Agent 私有化 API 验收口径（2026-07-09）

## 结论

当前交付边界应从“演示版前端”切换为“FastAPI / OpenAPI 服务能力”。如果甲方不使用我方客服前台和人工客服工作台，那么前端只用于本地演示，不作为生产验收项；生产验收应围绕接口契约、鉴权、事件入站、视觉审核任务、运维可观测和联调边界进行。

截至 2026-07-10，无前端 API 烟测通过：`12/12`。

最新报告由验收脚本写入 `tests/reports/private_deployment_api_smoke_*.json`。

复现命令：

```powershell
$env:E2E_BASE_URL="http://127.0.0.1:8015"
venv\Scripts\python.exe scripts\check_private_deployment_api.py
```

## 当前可验收服务面

| 能力 | API | 当前状态 | 说明 |
|---|---|---|---|
| OpenAPI 契约 | `GET /openapi.json` | 通过 | 当前导出 OpenAPI 3.1.0，包含 66 个 path。 |
| 核心类型 Schema | `GroupMessageIn` / `ProductEventIn` / `ReviewCaseMetadata` / `ReviewJobResponse` | 通过 | 私域事件与案件审核模型已进入 OpenAPI components。 |
| 管理鉴权 | `POST /api/v1/auth/login` | 通过 | 本地验收使用演示账号；生产应改为甲方账号初始化或 SSO。 |
| 客户会话令牌 | `POST /api/v1/auth/customer-session` | 通过 | POC 用白名单会话；生产必须替换为甲方登录态/小程序态校验。 |
| 私域契约说明 | `GET /api/v1/private-domain/contracts` | 通过 | 返回企微、商品事件、客服/视觉审核等契约说明。 |
| 群消息入站 | `POST /api/v1/private-domain/group-message` | 通过 | 可接收甲方群消息事件并生成群画像、舆情/运营判断。 |
| 商品事件入站 | `POST /api/v1/private-domain/product-event` | 通过 | 可接收商品/库存/抽赏事件并生成候选触达。 |
| 甲方案件审核服务 | `POST /api/v1/review/jobs` | 已实测通过 | 一个案件支持多图、多视频、订单/商品/仓库/对话/SOP 上下文；异步返回 job_id。 |
| 审核元数据校验 | `POST /api/v1/review/metadata/validate` | 通过 | 自动化客户端可在上传大文件前先校验强类型 metadata。 |
| 审核任务查询/重试 | `GET /api/v1/review/jobs/{job_id}` / `POST .../retry` | 已实测通过 | 支持幂等、独立查询、失败诊断和复用原素材重试。 |
| 审核 HTML 报告 | `GET /api/v1/review/jobs/{job_id}/report` | 已实测通过 | 受 Bearer Token 保护，展示证据链、全时轴采样、耗时、Token 与估算成本，不暴露模型渠道、Key 或内部 Prompt。 |
| 用户端单文件兼容 | `POST /api/v1/private-domain/review-tasks` | 已实测通过 | 保留照片/拍摄/视频上传兼容，不作为甲方批量案件的主要接口。 |
| 异步审核模式 | `async_review=true` | 通过 | 上传立即返回任务 ID 和 `MATERIAL_READY`，后台任务随后回写审核结果；烟测任务 `RV-C4E23C7B9AD7` 已完成。 |
| 审核任务查询 | `GET /api/v1/private-domain/review-tasks/{task_id}` | 已实测通过 | 支持客户/坐席/管理员按权限读取任务。 |
| 运维快照 | `GET /api/v1/ops/snapshot` | 通过但当前 `degraded` | 可观测队列、视觉审核、报告安全、缓存/任务服务。当前 degraded 来自本地排队积压，不应掩盖。 |
| JSON 指标接口 | `GET /metrics` / `GET /api/v1/review/metrics` | 通过 | 输出审核排队、运行、成功、失败、平均耗时、worker、累计 Token 和估算成本。 |
| Prometheus 指标接口 | `GET /metrics/prometheus` | 通过 | 输出 uptime、handoff、视觉审核、案件队列、累计 Token、估算成本和公开报告安全指标。 |

## 甲方私有化验收应看什么

1. 接口契约：甲方拿 `/openapi.json` 生成客户端或导入 API 网关，逐项校验请求/响应结构。
2. 鉴权边界：生产环境必须开启受保护 API，并由甲方 SSO、服务端 JWT 或网关鉴权接管。
3. 群消息接入：甲方企微会话存档/群机器人把消息转成 `/private-domain/group-message` 事件。
4. 商品事件接入：商品库、订单、库存、抽赏、稀有掉落以 `/private-domain/product-event` 事件入站。
5. 客服系统接入：甲方 Server 把一个工单的多媒体与结构化字段提交到 `/api/v1/review/jobs`，读取案件状态和安全审核报告后在甲方工单内展示和处理。
6. 视觉审核链路：批量任务由调用方并发提交独立案件；服务端通过 SQLite 状态、幂等键和 worker 并发执行，避免一个超大批次请求拖垮全部案件。
7. 可观测与排障：甲方验收应检查 `/api/v1/ops/snapshot`、`/metrics`、应用日志、视觉审核工作台日志。
8. 大文件：当前服务对完整视频时轴均匀抽帧并压缩为 JPEG 输入模型；120GB 生产批次应使用对象存储直传、七牛云或同类服务转码/故事板，再按案件引用代理素材。
9. 标签隔离：人工结论和正负样本标签只能在模型返回后离线评测，服务入口会拒绝评测字段和 `sample_labels.json`。

## 明确不应承诺的内容

- 不承诺提供甲方生产客服前台。
- 不承诺提供甲方人工客服工作台。
- 不伪装已接入企微、飞书、商品库、订单系统。
- 不把视觉审核初筛当最终售后定责。
- 不把本地 SQLite 演示数据当生产规模方案；1 万群全量需要迁移到生产数据库、队列和对象存储。

## 当前缺口

| 缺口 | 风险 | 建议动作 |
|---|---|---|
| OpenAPI schema 仍有少量后台聚合字段使用 `Dict[str, Any]` | 甲方生成客户端时部分管理视图类型不够细 | P0 对接接口已补类型；后台 dashboard 聚合可在 P1 继续细化。 |
| Prometheus 指标仍是最小集 | 只能覆盖核心健康，不含完整链路追踪 | 接甲方 APM 后再补 trace_id、外部依赖耗时、视觉队列分位延迟。 |
| 审核 worker 当前为进程内线程池 | 已有 SQLite 状态、任务租约、恢复与重试，但不等同于跨机器队列 | 多实例/跨机器部署时替换为甲方队列或 Redis/Celery；API 与结果模型无需变化。 |
| 暂无甲方真实漏发货样本 | 只能验证接口契约与 SOP 规则，不能声明漏发识别准确率 | 甲方补充含订单、拆单状态、面单、全家福和开箱视频的正反样本后再做准确率验收。 |
| 120GB 对象存储/云转码适配尚未联调 | 当前已验证 556MB 单案件，但不应让 120GB 原始素材经应用服务器中转 | 甲方提供对象存储空间、上传凭证、回调域名、转码模板与保留策略后，实现对象引用适配器。 |
| 客户会话签发仍是 POC 白名单 | 不能直接用于生产登录态 | 接甲方登录态、小程序 code 或服务端签名。 |
| 当前本地 ops 状态 `degraded` | 演示环境有积压队列 | 验收前清理演示队列或展示 degraded 原因。 |

## 本轮新增验收脚本

新增文件：`scripts/check_private_deployment_api.py`

脚本只验证我方可交付服务面，不验证前端页面，也不伪装外部系统接入。默认覆盖：

- OpenAPI 必要 path
- 私域核心 Pydantic schemas
- admin token
- 私域契约
- 群消息事件
- 商品事件
- Ops snapshot
- JSON metrics
- Prometheus metrics
- customer session token
- 审核服务契约、强类型 schema、案件指标

视觉上传链路已经单独实测：

- 图片任务：`RV-74A14084348B`，`REVIEW_COMPLETED`
- 视频任务：`RV-4A55208E5867`，`REVIEW_COMPLETED`
- 异步图片任务：`RV-C4E23C7B9AD7`，初始 `MATERIAL_READY`，后台回写 `REVIEW_COMPLETED`

案件级审核服务实测：

- 发错货：`RJ-25C99957238C477A`，多文件并发任务，`SUCCEEDED`，置信度 `0.95`
- 未成年人资料：`RJ-AEDE05A7D35B4E5D`，多文件并发任务，`SUCCEEDED`，置信度 `0.95`
- 商品有伤：`RJ-C50E40AFBAF24D10`，16 个文件约 106MB，`SUCCEEDED`，置信度 `0.95`
- 大文件错发：`RJ-5F6BB513EAE8497D`，10 个文件共 556,390,436 字节，`SUCCEEDED`，置信度 `0.95`
- 故障恢复：`RJ-3BCC852141DA48DF`，视觉服务关闭时 `FAILED` 并记录 502 诊断，恢复后原 job_id 重试成功
- 全时轴/成本/HTML 回归：`RJ-D9E0FE9A613D453A` 与 `RJ-CF420A704A4D4723` 均通过；公开结果安全扫描通过，累计 `35,837 tokens`，估算成本 `$0.13267`
- 标签隔离：安全 metadata 通过；`ground_truth` metadata 与 `sample_labels.json` 附件均返回 HTTP 422
