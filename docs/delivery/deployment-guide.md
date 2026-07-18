# 部署指南

版本：2026-07-17

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

完整变量名见 `.env.example`。必须配置：

- JWT/访问保护相关变量。
- 主文本服务凭证。
- 视觉审核服务凭证。
- `VISUAL_WORKBENCH_URL`：主服务调用视觉执行器的内网地址；分机部署时必须显式配置。未配置时才回退 `VISUAL_WORKBENCH_PORT`。
- 主服务和视觉服务上传/案件大小限制。
- `VISUAL_MAX_FOLDER_FILES`：网页单工单文件夹的文件数上限，默认 200。
- `VISUAL_MAX_BATCH_FOLDERS`：网页批量父目录的工单数上限，默认 10、最大 20。
- `VISUAL_MAX_BATCH_FILES`：网页批量父目录的总文件数上限，默认 400、最大 1000。
- `VISUAL_MAX_SUPPLEMENTAL_IMAGES`：单案件进入资料审核管线的图片上限，默认 40、最大 80。
- `REVIEW_FFPROBE_PATH`：可选固定路径；为空时从主服务进程 `PATH` 查找。
- `REVIEW_WORKBENCH_RETRIES`：内部工作台遇到 429/502/503/504 时的有限重试次数，默认 2。
- 数据目录和日志目录。

真实 `.env` 不进入 Git、镜像和客户 ZIP。生产使用密钥管理服务或部署平台 Secret。

## 6. 健康检查

```text
GET /openapi.json
GET /api/v1/ops/snapshot
GET /metrics
GET /metrics/prometheus
GET http://127.0.0.1:7861/api/health
GET /api/v1/review/readiness
```

主服务需要一个可用的集成账号 Token 才能读取受保护指标和审核 readiness。`readiness` 同时检查 ffprobe、上传目录写权限、至少三倍案件上限的磁盘余量和视觉工作台连通性；任一失败返回 503，生产编排不得继续导入新案件。

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
