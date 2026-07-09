# 虾淘私域 Agent 私有化 API 验收口径（2026-07-09）

## 结论

当前交付边界应从“演示版前端”切换为“FastAPI / OpenAPI 服务能力”。如果甲方不使用我方客服前台和人工客服工作台，那么前端只用于本地演示，不作为生产验收项；生产验收应围绕接口契约、鉴权、事件入站、视觉审核任务、运维可观测和联调边界进行。

本轮无前端 API 烟测通过：`10/10`。

报告文件：`tests/reports/private_deployment_api_smoke_20260709_115649.json`

复现命令：

```powershell
$env:E2E_BASE_URL="http://127.0.0.1:8015"
venv\Scripts\python.exe scripts\check_private_deployment_api.py
```

## 当前可验收服务面

| 能力 | API | 当前状态 | 说明 |
|---|---|---|---|
| OpenAPI 契约 | `GET /openapi.json` | 通过 | 当前导出 OpenAPI 3.1.0，包含 59 个 path。 |
| 私域类型 Schema | `GroupMessageIn` / `ProductEventIn` / `ReviewTaskUploadResponse` | 通过 | 私域核心入站和审核上传响应已进入 OpenAPI components。 |
| 管理鉴权 | `POST /api/v1/auth/login` | 通过 | 本地验收使用演示账号；生产应改为甲方账号初始化或 SSO。 |
| 客户会话令牌 | `POST /api/v1/auth/customer-session` | 通过 | POC 用白名单会话；生产必须替换为甲方登录态/小程序态校验。 |
| 私域契约说明 | `GET /api/v1/private-domain/contracts` | 通过 | 返回企微、商品事件、客服/视觉审核等契约说明。 |
| 群消息入站 | `POST /api/v1/private-domain/group-message` | 通过 | 可接收甲方群消息事件并生成群画像、舆情/运营判断。 |
| 商品事件入站 | `POST /api/v1/private-domain/product-event` | 通过 | 可接收商品/库存/抽赏事件并生成候选触达。 |
| 图片/视频审核任务 | `POST /api/v1/private-domain/review-tasks` | 已实测通过 | 上传后调用视觉审核工作台并回写 `REVIEW_COMPLETED/REVIEW_FAILED`、`review_result`、`reviewed_at`。 |
| 异步审核模式 | `async_review=true` | 通过 | 上传立即返回任务 ID 和 `MATERIAL_READY`，后台任务随后回写审核结果；烟测任务 `RV-C4E23C7B9AD7` 已完成。 |
| 审核任务查询 | `GET /api/v1/private-domain/review-tasks/{task_id}` | 已实测通过 | 支持客户/坐席/管理员按权限读取任务。 |
| 运维快照 | `GET /api/v1/ops/snapshot` | 通过但当前 `degraded` | 可观测队列、视觉审核、报告安全、缓存/任务服务。当前 degraded 来自本地排队积压，不应掩盖。 |
| JSON 指标接口 | `GET /metrics` | 通过 | 保留给现有后台和轻量集成使用。 |
| Prometheus 指标接口 | `GET /metrics/prometheus` | 通过 | 可被甲方监控平台抓取，当前输出 uptime、ops status、handoff、视觉审核、公开报告安全指标。 |

## 甲方私有化验收应看什么

1. 接口契约：甲方拿 `/openapi.json` 生成客户端或导入 API 网关，逐项校验请求/响应结构。
2. 鉴权边界：生产环境必须开启受保护 API，并由甲方 SSO、服务端 JWT 或网关鉴权接管。
3. 群消息接入：甲方企微会话存档/群机器人把消息转成 `/private-domain/group-message` 事件。
4. 商品事件接入：商品库、订单、库存、抽赏、稀有掉落以 `/private-domain/product-event` 事件入站。
5. 客服系统接入：甲方客服系统调用我方接口创建/查询审核任务，读取 `review_result` 后在甲方工单内展示和处理。
6. 视觉审核链路：用户图片/视频由甲方系统上传到 `/private-domain/review-tasks`，我方服务调用视觉审核工作台并回写结果。
7. 可观测与排障：甲方验收应检查 `/api/v1/ops/snapshot`、`/metrics`、应用日志、视觉审核工作台日志。

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
| 异步视觉审核仍是进程内后台任务 | 多实例部署或进程重启时不如正式队列稳 | 生产接 Redis/Celery 或甲方任务队列；当前 POC 已支持先返回任务 ID 再轮询结果。 |
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

视觉上传链路已经单独实测：

- 图片任务：`RV-74A14084348B`，`REVIEW_COMPLETED`
- 视频任务：`RV-4A55208E5867`，`REVIEW_COMPLETED`
- 异步图片任务：`RV-C4E23C7B9AD7`，初始 `MATERIAL_READY`，后台回写 `REVIEW_COMPLETED`
