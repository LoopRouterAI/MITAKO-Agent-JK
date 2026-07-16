# Java 开发部署与联调指南

版本：2026-07-16

## 1. Java 的职责边界

甲方或我方 Java 网关只调用 FastAPI 主服务，不直接调用内部视觉服务、数据库或模型渠道。

推荐调用顺序：

1. 获取集成账号 Bearer Token。
2. 调用 `/api/v1/review/metadata/validate` 校验案件 JSON。
3. 对大视频调用 `/api/v1/review/sampling-plan` 获取抽帧和转码建议。
4. 使用 `multipart/form-data` 提交 `/api/v1/review/jobs`。
5. 保存 `job_id` 与 `batch_id`，轮询状态或由后续回调适配层通知。
6. 读取公开报告并由人工客服做最终业务处理。

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
- 漏发货：必须使用 `fulfillment_baseline` 提交版本化应发清单、商品行数量、赠品/特典声明、包裹数和包裹商品映射；使用 `evidence_coverage` 提交本次实际包裹引用/物流单号和完整展示声明。
- 商品有伤：使用 `damage_causality_policy` 控制动作因果专项扫描；使用 `continuity_policy` 配置离镜阈值和连续性专项扫描。
- 甲方未提供完整基准时接口不拒绝创建任务，但 `metadata/validate` 会返回 `degraded_review`，运行结果固定降级到人工复核。

## 4. 大文件

- 小于直接上传阈值：Java 网关可以流式转发，不把文件整体读入 JVM 堆。
- 543MB 或超长视频：优先让甲方上传对象存储并转码/生成故事板。
- 120GB 批次：按案件拆分，不创建一个超大 HTTP 请求。
- 当前 POC 的 `/review/jobs` 为 multipart 上传；对象引用适配器需要双方在联调阶段确认 URL 签名、过期、回调和下载白名单。

## 5. 超时与重试

| 操作 | 建议超时 | 重试 |
|---|---:|---|
| 登录/metadata 校验 | 10 秒 | 仅网络和 5xx |
| 采样规划 | 10 秒 | 仅网络和 5xx |
| multipart 上传 | 按文件大小，建议 10-30 分钟 | 使用相同幂等键 |
| 任务查询 | 10 秒 | 可重试 |
| 报告下载 | 30 秒 | 可重试 |

任务执行本身是异步的，HTTP 上传完成不代表审核完成。

## 6. 联调验收

```bat
set E2E_BASE_URL=http://127.0.0.1:8000
.venv\Scripts\python.exe scripts\check_private_deployment_api.py
.venv\Scripts\python.exe scripts\check_review_input_isolation.py
.venv\Scripts\python.exe scripts\check_customer_agent_0714_regression.py
.venv\Scripts\python.exe scripts\check_review_service_batch.py --samples sample_003 --run-id java-integration
```

如果内部环境目录名为 `venv`，可将上述 `.venv` 替换为 `venv`。预发布脚本会自动识别两种目录。

Java 侧至少补充：

- metadata 校验 200/422。
- 幂等重放 `created=false` 且 job_id 不变。
- 文件过大 413、格式错误 415、标签输入 422。
- 批次分页时 summary 仍是全批次统计。
- 服务重启后未完成任务可恢复或重试。

## 7. 上线前配置

- TLS、域名、网关超时和上传大小。
- SSO/集成账号和最小权限。
- 主服务到视觉服务的内网地址。
- 数据库、队列、对象存储和备份。
- Prometheus/Grafana、日志采集和告警。
- 密钥通过环境或密钥管理服务注入，不写配置文件和镜像。
