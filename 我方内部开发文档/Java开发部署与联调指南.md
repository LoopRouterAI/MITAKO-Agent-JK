# Java 开发部署与联调指南

版本：2026-07-23

## 1. Java 的职责边界

甲方或我方 Java 网关只调用 FastAPI 主服务，不直接调用内部视觉服务、数据库或模型渠道。

推荐调用顺序：

1. 获取集成账号 Bearer Token。
2. 调用 `/api/v1/review/metadata/validate` 校验案件 JSON。
3. 对大视频调用 `/api/v1/review/sampling-plan` 获取抽帧和转码建议。
4. 使用 `multipart/form-data` 提交 `/api/v1/review/jobs`。
5. 保存 `job_id` 与 `batch_id`，轮询状态或由后续回调适配层通知。
6. 优先读取 `advisory_assessment`；仅在 `report.requested=true` 时读取公开 HTML。

完整代码见 `docs/delivery/java-client-sample.md`。

## 2. 部署拓扑

```text
Nginx / Java Gateway
  -> FastAPI 主服务 :8000
     -> 视觉审核服务 :7861（仅内网）
     -> PostgreSQL/SQLite
     -> Redis/MQ（生产替换）
     -> 对象存储/转码（生产替换）
```

生产只暴露主服务；视觉服务、数据库和队列保持内网访问。

## 3. Java 请求要求

- `Authorization: Bearer <token>`。
- 所有创建类请求带 `Idempotency-Key`。
- `client_case_id` 在甲方系统内稳定唯一。
- 同批案件使用同一个 `batch_id`，每个案件仍独立提交。
- 文件 MIME、扩展名和内容必须一致。
- 不在 metadata 或文件中传 ground truth、人工结论和评测标签。
- 429/502/503/504 使用指数退避；4xx 参数错误不盲目重试。

场景基准：

- 发错货：每个订单行必须有唯一标识，或商品名+规格/款式的可唯一组合，并带应发数量。
- 官方商品图：在 `fulfillment_baseline.expected_items[].master_image_urls` 提交本单商品主图；服务端按任务限量读取和缓存，不要由 Java 预先批量下载，也不要提交整份商品库。
- 漏发货：必须使用 `fulfillment_baseline` 提交版本化应发清单、商品行数量、赠品/特典声明、包裹数和包裹商品映射；使用 `evidence_coverage` 提交本次实际包裹引用/物流单号和完整展示声明。
- 分包映射：一个物流单号不能自动证明所有 SKU 都属于同一包裹；没有权威包裹-SKU 关系时必须留空并接受降级复核。
- 商品有伤：使用 `damage_causality_policy` 控制动作因果专项扫描；使用 `continuity_policy` 配置离镜阈值和连续性专项扫描。
- 人工复审分级：使用 `review_routing_policy` 配置必须复审、建议抽检和 3 秒离镜补件阈值；离镜阈值不得解释为自动拒绝或已证实调包。
- 报告输出：网页默认生成 HTML；系统批量可用 `output_options.include_html_report=false` 只保留结构化 JSON。
- 商品有伤多诉求：用 `claim_scope.active_claim_ids` 明确本次原子诉求。后续追加的不同商品、部位或损伤机制必须新建 claim，不得用一个工单级标签覆盖全部诉求。
- 自动分类策略：`decision_policy` 默认 `conservative_review`。只有配置甲方批准的 `policy_ref@version` 并选择 `classification_recommendation` 后，才允许命中规则性 `negative`；该结果仍保持 `business_action_allowed=false`。
- 甲方未提供完整基准时接口不拒绝创建任务，但 `metadata/validate` 会返回 `degraded_review`。运行结果优先建议补材料，不再仅因材料缺口强制占用人工席位。

## 4. 大文件

- 小于直接上传阈值：Java 网关可以流式转发，不把文件整体读入 JVM 堆。
- 543MB 或超长视频：优先让甲方上传对象存储并转码/生成故事板。
- 120GB 批次：按案件拆分，不创建一个超大 HTTP 请求。
- 当前 POC 的 `/review/jobs` 为 multipart 上传；对象引用适配器需要双方在联调阶段确认 URL 签名、过期、回调和下载白名单。
- Nginx 参考配置为 `deploy/nginx/mitako-review.conf.example`。Java 网关的单文件上限不得低于 650MiB，整请求上限不得低于 750MiB，并应关闭大请求内存缓冲。

## 5. 超时与重试

| 操作 | 建议超时 | 重试 |
|---|---:|---|
| 登录/metadata 校验 | 10 秒 | 仅网络和 5xx |
| 采样规划 | 10 秒 | 仅网络和 5xx |
| multipart 上传 | 按文件大小，建议 10-30 分钟 | 使用相同幂等键 |
| 任务查询 | 10 秒 | 可重试 |
| 报告下载 | 30 秒 | 可重试 |

主服务到内部工作台的 429/502/503/504 由 `REVIEW_WORKBENCH_RETRIES` 做有限重试，每次尝试写入 `result.workbench_transport.attempts`。Java 侧仍按同一 `job_id` 查询，不创建重复案件。

任务执行本身是异步的，HTTP 上传完成不代表审核完成。

网页工作台的“批量父目录”只用于最多 10 个案件的小批量人工复测，视觉服务会在一个 HTTP 请求内逐案执行。生产 Java 批量不是上传父目录，而是并发创建多个独立异步 job、共用 `batch_id`；每案独立幂等、状态、重试和报告。

## 6. 模型媒体传输边界

Java 网关不调用模型供应商，也不需要实现 Gemini Files URI：

1. Java 只把案件 JSON 与媒体通过主服务审核 API 提交给我方。
2. 主服务将原媒体流式转发到内网视觉服务。
3. 视觉服务本地抽帧和压缩，细节、连续性与成因审核均逐张使用带帧号和时间戳的 JPEG 独立帧；拼图只可用于报告浏览，不得进入模型判定请求。
4. 视觉服务以内联 Base64 图片请求供应商；原始 MP4 不进入模型请求。
5. 官方商品图由视觉服务按本单白名单 URL 读取、校验、压缩和缓存，同样以内联图片发送；失败时保留文字订单基线并在报告中标记降级。

联调时调用 `/api/v1/review/contracts`，应看到 `media_processing.model_request_transport=inline_base64_images` 且 `supplier_file_uri_required=false`。视觉服务 `/api/health` 应返回同一口径。

## 7. 联调验收

```bat
set E2E_BASE_URL=http://127.0.0.1:8000
.venv\Scripts\python.exe scripts\check_private_deployment_api.py
.venv\Scripts\python.exe scripts\check_review_input_isolation.py
.venv\Scripts\python.exe scripts\check_customer_agent_0714_regression.py
.venv\Scripts\python.exe scripts\check_review_service_batch.py --samples sample_003 --run-id java-integration
.venv\Scripts\python.exe scripts\check_review_runtime_dependencies.py --media D:\approved-samples\sample.mp4
```

如果内部环境目录名为 `venv`，可将上述 `.venv` 替换为 `venv`。预发布脚本会自动识别两种目录。

Java 侧至少补充：

- metadata 校验 200/422。
- 幂等重放 `created=false` 且 job_id 不变。
- 文件过大 413、格式错误 415、标签输入 422。
- 批次分页时 summary 仍是全批次统计。
- 服务重启后未完成任务可恢复或重试。
- `required/optional/not_required` 三种复审分级和 `request_more_material` 流程建议。
- JSON-only 任务不生成 HTML，报告路由返回 409 `review_report_not_requested`。

字段级说明见 `docs/delivery/review-advisory-api.md`。

## 8. 上线前配置

- TLS、域名、网关超时和上传大小。
- SSO/集成账号和最小权限。
- 主服务到视觉服务的内网地址。
- 主服务进程可执行的 ffprobe 路径；调用 `/api/v1/review/readiness` 必须返回 200。
- 数据库、队列、对象存储和备份。
- Prometheus/Grafana、日志采集和告警。
- 密钥通过环境或密钥管理服务注入，不写配置文件和镜像。
