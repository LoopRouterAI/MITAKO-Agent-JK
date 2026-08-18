# MITAKO Agent v2026.08.18-r2 发布说明

状态：当前有效

## 给研发人员

### PR1 日志系统边界

PR1 现在包含完整的审核观测链，而不只是 stderr：

- 视觉请求、重试、超时、资源等待、单案/文件夹生命周期事件写入独立 SQLite 事件表；
- 默认 `MITAKO_VISUAL_LOG_MODE=redacted`，服务器日志和 Web Demo 只显示“已向模型网关请求/成功/失败/排队”等脱敏信息；
- 研发服务器可显式设置 `MITAKO_VISUAL_LOG_MODE=internal`，查询模型、渠道、域名和详细错误元数据；
- 正式 API 提供 `GET /api/v1/review/jobs/{job_id}/events`，普通管理员只能读取脱敏事件，超级管理员才可读取内部级别；
- API 工单返回脱敏事件摘要和日志入口，Workbench 直接返回本轮脱敏事件并在页面显示“技术运行记录（脱敏）”；
- Prompt、payload、媒体正文、Key、Authorization 和原始模型响应无论模式都不会进入事件表。

这不是把内部模型日志展示给甲方客服；甲方只看到可理解的运行状态，研发人员才可以在受保护环境中查看详细技术事件。

本版本基于 `v2026.08.18-r1`，合入公司仓库 PR #1 的结构化视觉审核日志，并补齐低内存批量审核的资源预算。

### 代码变化

- `review_service/resource_guard.py` 读取 Windows 原生内存、Linux `/proc` 和 cgroup 水位，计算当前安全并发。
- 正式审核 API 使用有界调度槽位和持久 `QUEUED` 状态；队列满时返回 HTTP 429，并在 metrics/readiness 暴露等待数、执行数和资源水位。
- Workbench 案件入口、模型分块、未成年人分批和视频转码共用资源预算；2GB 级机器默认收敛为单并发，不能通过请求参数绕过。
- `visual_model_http_attempt/success/failure` 和单案、样本、文件夹生命周期事件统一写入结构化 stderr；日志行使用进程内锁，避免并发交错。
- 原生视频路径、代理失败、资源等待和截止时间提前结束均保留可定位事件；日志不写入 Prompt、payload、媒体正文、Key 或 Authorization。

### 验证

- `tests/review_service` + `tests/visual_review`：在本版本收口前的业务基线上全部通过；资源与观测定向回归 `14 passed`，Workbench/原生视频回归 `106 passed`。
- `compileall`、`git diff --check` 和 CodeGraph 索引通过。
- 本地未调用真实 Gemini；2GB 预生产仍需用 3--5 个并发 Case（含一个大视频）记录峰值内存、队列等待和最终状态。

### 部署边界

资源闸门是进程内保护。2GB 私有化部署应使用单 Workbench worker/单副本；若部署多个副本，需要在反向代理或共享队列层增加跨进程租约，不能把多个进程的本地并发相加当作全局预算。

## 给甲方客服人员

这次更新主要解决“同时送审很多工单时服务变慢或卡住”的问题。系统现在会先排队，资源不足时稍后继续，不会因为服务器内存小就同时处理过多视频。客服看到的仍是原来的四场景报告、材料是否齐全、证据和下一步建议；本版本没有改变退款、补发或拒绝等业务动作的权限边界。
