# 部署指南

版本：2026-07-31

## 1. 组件

| 组件 | 默认端口 | 启动入口 | 是否对外暴露 |
|---|---:|---|---|
| FastAPI 主服务 | 8000 | `uvicorn main:app` | 是，经网关/TLS |
| 视觉审核服务 | 7861 | `poc.visual_review_poc.workbench_server` | 否，仅主服务内网调用 |
| 前端静态资源 | 主服务同端口 | `dist/` | 是 |
| 数据库 | 本地 SQLite；生产建议 PostgreSQL | 运行时数据目录 | 否 |
| 队列 | POC 线程池；生产建议 Redis/MQ | 主服务内部 | 否 |

## 2. 环境要求

| 项目 | POC | 生产建议 |
|---|---|---|
| 系统 | Windows 11 / Windows Server / Ubuntu 22.04+ | Linux 或甲方标准容器平台 |
| Python | 3.11+ | 固定补丁版本 |
| Node.js | 18+ | 只用于构建前端 |
| FFmpeg/ffprobe | 必装；Windows 可运行 `scripts/setup_ffprobe_windows.ps1` | 固定系统包或镜像层版本 |

模型服务认证由内部运维配置，甲方业务接口不暴露模型渠道或认证细节。运行日志只记录必要的状态码、重试和耗时，不记录凭证或媒体正文。
| 磁盘 | 按样本规模 | 原始素材进入对象存储，不占应用节点长期磁盘 |
| 网络 | 可访问审核服务 | 主服务、视觉服务、数据库、对象存储内网互通 |

## 3. Windows 启动

```bat
setup_venv.bat
npm install
npm run build
一键启动-Windows.bat
```

安装并验证 Windows 开发机媒体取证依赖：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_ffprobe_windows.ps1
$env:REVIEW_FFPROBE_PATH = (node -e "console.log(require('ffprobe-static').path)")
python scripts\check_review_runtime_dependencies.py --media D:\approved-samples\sample.mp4
```

手工启动：

```bat
venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
venv\Scripts\python.exe -m poc.visual_review_poc.workbench_server
```

## 4. Linux 启动

```bash
python3 -m venv venv
sudo apt-get update && sudo apt-get install -y ffmpeg
venv/bin/pip install -r requirements.txt
npm ci
npm run build
venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

视觉服务使用第二个进程：

```bash
venv/bin/python -m poc.visual_review_poc.workbench_server
```

生产应由 systemd、Supervisor、Kubernetes 或甲方进程平台管理两个进程，不使用开发自动重载。

## 5. 环境变量

内部源码包的完整变量名见 `.env.example`；甲方预览包不携带环境文件，按本节变量清单由部署平台注入。必须配置：

- JWT/访问保护相关变量。
- 主文本服务凭证。
- 视觉审核服务凭证。
- `VISUAL_WORKBENCH_URL`：主服务调用视觉执行器的内网地址；分机部署时必须显式配置。未配置时才回退 `VISUAL_WORKBENCH_PORT`。
- 主服务和视觉服务上传/案件大小限制。
- `VISUAL_MAX_FOLDER_FILES`：网页单工单文件夹的文件数上限，默认 200。
- `VISUAL_MAX_BATCH_FOLDERS`：网页批量父目录的工单数上限，默认 10、最大 20。
- `VISUAL_MAX_BATCH_FILES`：网页批量父目录的总文件数上限，默认 400、最大 1000。
- `VISUAL_SUPPLEMENTAL_IMAGE_SOFT_LIMIT` / `VISUAL_MAX_SUPPLEMENTAL_IMAGES`：单案件图片软上限默认 40，超过后自动分段处理；安全上限默认 200，全部素材都必须处理或明确返回结构化拒绝，不能静默截断。
- `VISUAL_RUNTIME_MEDIA_DIR`：可选抽帧与报告媒体运行目录；默认位于视觉工作台目录下，生产挂载必须可写且持久，健康检查会验证可写性但不会公开绝对路径。
- `REVIEW_FFPROBE_PATH`：可选固定路径；为空时从主服务进程 `PATH` 查找。
- `REVIEW_WORKBENCH_RETRIES`：内部工作台遇到 429/502/503/504 时的有限重试次数，默认 2。
- `REVIEW_MODEL_TIMEOUT_SECONDS`：单次供应商请求超时，网页和正式审核 API 共用，默认 180 秒。
- `REVIEW_MODEL_RETRIES`：单次供应商软失败重试次数，默认 1；优先遵守 `Retry-After`，否则指数退避并加入抖动。只有可重试错误才进入下一个已配置渠道。
- `REVIEW_CHUNK_WORKERS`：单案件分段并发数，当前最大 4。执行器遇到 408/429/5xx 或软失败会降低后续波次并发，成功波次再逐步恢复；生产仍须按供应商限流压测配置。
- `REVIEW_MINOR_WORKERS`：未成年人图片分批并发数，默认 6、最大 8；只影响单案资料识别，不改变主服务任务并发。
- `REVIEW_CONTINUITY_FRAMES_PER_CALL`：连续性通道每次独立帧输入上限，当前最大为 24。模型逐张接收带帧序号与时间戳的 JPEG，不使用拼图作为审核证据；HTML 报告中的缩略图仅用于人工浏览。
- `REVIEW_PRODUCT_IMAGE_BASE_URL`：甲方订单快照中相对商品主图路径的 HTTPS 基地址。
- `REVIEW_PRODUCT_IMAGE_ALLOWED_HOSTS`：官方商品图主机白名单，多个主机用逗号分隔；禁止加入本机或内网主机。
- `REVIEW_PRODUCT_IMAGE_LIMIT`：单审核任务最多读取的官方商品图，默认 6、硬上限 12；盘点、启动和批次查询均不会触发全量下载。
- `REVIEW_PRODUCT_IMAGE_CACHE_DIR`：可选官方图缓存目录；未配置时使用 `MITAKO_DATA_DIR/visual_review_product_refs`，适配不同盘符、容器挂载和独立数据盘。
- `REVIEW_PRODUCT_IMAGE_MAX_BYTES`：单张官方图下载上限，默认 8MiB；超限、重定向、伪图片或非白名单资源均降级为文字订单基线。
- `REVIEW_PRODUCT_IMAGE_MAX_PIXELS`：解码前像素上限，默认 2000 万，防止小体积超大像素图片耗尽内存。
- `REVIEW_PRODUCT_IMAGE_MAX_EDGE` / `REVIEW_PRODUCT_IMAGE_JPEG_QUALITY`：送模前压缩边长和 JPEG 质量，默认 1280 / 82。
- `REVIEW_PRODUCT_IMAGE_MAX_SEGMENTS`：同一案件中附带官方图的主审核分段上限，默认且最大为 3（首/中/末），避免长视频重复发送导致成本失控。
- `REVIEW_PRODUCT_IMAGE_DNS_TIMEOUT_SECONDS`：官方图主机解析等待上限，默认 3 秒。
- `REVIEW_PRODUCT_IMAGE_CACHE_TTL_SECONDS` / `REVIEW_PRODUCT_IMAGE_CACHE_MAX_MB`：缓存时效与容量，默认 7 天 / 512MiB；超限按最旧文件淘汰。
- `VISUAL_REPORT_SIGNING_SECRET`：生产必须由 Secret 管理器注入固定高熵密钥，主服务与视觉服务必须一致；它同时保护内部后处理控制头，视觉工作台不应直接暴露到公网。
- `VISUAL_REQUIRE_PERSISTENT_SIGNING_SECRET=1`：生产必须开启；缺少固定签名密钥时视觉健康检查与主服务 readiness 失败。
- `VISUAL_REPORT_URL_TTL_SECONDS`：报告与媒体签名 URL 的有效期，默认 900 秒。
- 数据目录和日志目录。

真实 `.env` 不进入 Git、镜像和客户 ZIP。生产使用密钥管理服务或部署平台 Secret。

视觉服务不依赖供应商 Files API 或文件 URI。原视频在我方服务端解码，模型请求仅包含内联 Base64 的 JPEG 独立帧；可通过视觉健康检查的 `model_media_transport` 和审核契约的 `media_processing` 复核。

官方商品图同样不依赖供应商文件 URI：视觉服务只在当前案件需要时从白名单 CDN 读取有限图片，校验 HTTPS、主机、DNS、重定向、大小、MIME、文件特征和解码结果，压缩后以内联图片发送。相同 URL 命中本地缓存；下载失败不会伪装成已核验，报告会显示“部分可用/不可用”并保留 SKU 与应发清单文字基线。

## 6. 健康检查

```text
GET /openapi.json
GET /api/v1/ops/snapshot
GET /metrics
GET /metrics/prometheus
GET http://127.0.0.1:7861/api/health
GET /api/v1/review/readiness
```

主服务需要一个可用的集成账号 Token 才能读取受保护指标和审核 readiness。`readiness` 同时检查 ffprobe、上传目录写权限、至少三倍案件上限的磁盘余量、视觉工作台连通性，以及生产模式下的持久报告签名密钥；任一失败返回 503，生产编排不得继续导入新案件。

## 7. 大文件与 120GB 批次

- POC 直接上传默认单文件上限 650MB、单案件上限 750MB。
- Nginx 参考配置位于 `deploy/nginx/mitako-review.conf.example`，审核任务入口使用 `client_max_body_size 800m`、关闭请求缓冲并放宽上传/读取超时。
- Java/网关必须流式转发，禁止把完整视频读入 JVM 堆。
- 543MB 或超长视频优先对象存储直传、云转码和故事板/抽帧服务。
- 120GB 批次按案件并发提交，每个案件独立幂等、查询和重试。
- Java 可先调用 `/api/v1/review/sampling-plan` 估算帧数、分段和转码建议。
- 生产优先使用对象存储直传与媒体引用；当前对象存储、七牛云转码和甲方 Java 网关仍属于待联调，不伪装为已接入。

## 8. 容器启动

仓库提供可构建的 `Dockerfile` 和完整 `docker-compose.yml`。镜像内安装 ffmpeg/ffprobe，主服务只通过容器网络访问视觉工作台。

```bash
docker compose build
docker compose up -d
docker compose ps
```

部署平台应把真实 `.env` 改为 Secret 注入；不得把密钥烘焙进镜像。

## 9. 生产拓扑

```text
Client / Java Gateway / Nginx
  -> FastAPI 主服务（多副本）
     -> PostgreSQL
     -> Redis/MQ + worker
     -> 视觉审核服务（内网，多副本）
     -> 对象存储与转码服务
     -> Prometheus / 日志 / 告警
```

## 10. 发布门禁

```bat
npm run build
venv\Scripts\python.exe scripts\check_private_deployment_api.py
venv\Scripts\python.exe scripts\check_customer_agent_0709_regression.py
venv\Scripts\python.exe scripts\check_review_sop_alignment.py
venv\Scripts\python.exe scripts\check_review_media_preprocessing.py
venv\Scripts\python.exe scripts\check_review_input_isolation.py
venv\Scripts\python.exe scripts\check_private_domain_agent_e2e.py
venv\Scripts\python.exe scripts\check_visual_workbench_smoke.py
venv\Scripts\python.exe scripts\check_review_runtime_dependencies.py --media D:\approved-samples\sample.mp4
powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1
```

## 11. 故障处理

- 主服务不可用：检查端口、日志、数据库和 JWT 配置。
- 视觉服务不可用：任务保留失败诊断，可恢复服务后复用原 job 重试。
- 内部工作台 429/502/503/504：服务按 `REVIEW_WORKBENCH_RETRIES` 有限重试并在 `workbench_transport.attempts` 记录状态码和耗时；仍失败时保留同一 job 重试，不重复创建案件。
- 报告缺失：查询 job diagnostics 和视觉服务日志，不直接修改任务数据库。
- 大文件失败：检查 Nginx/网关上传限制、磁盘、超时和对象存储方案。
