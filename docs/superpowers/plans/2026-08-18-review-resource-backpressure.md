# 审核资源背压与 2GB 部署保护实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** 让正式 API、Web Demo、模型分块和视频转码在低内存服务器上共享可控的资源预算，不再因批量请求无界堆积导致 OOM/卡死。

**Architecture:** 新增一个仅依赖 Python 标准库的资源守门模块，读取 Linux cgroup/proc 或 Windows 原生内存水位；API 使用有界调度槽位保留数据库 QUEUED 状态，工作台使用同一进程级案件槽位和转码槽位，所有入口返回可诊断的忙碌状态。低内存默认将案件、转码、分块并发压到 1，显式配置仍受安全上限约束。

**Tech Stack:** Python stdlib、FastAPI、SQLite、ThreadPoolExecutor、ffmpeg。

---

### Task 1: 资源预算与背压契约

**Files:**
- Create: `review_service/resource_guard.py`
- Test: `tests/review_service/test_resource_guard.py`

- [x] 写内存快照、低内存并发上限、案件/转码槽位和诊断输出的失败测试。
- [x] 运行定向测试确认失败。
- [x] 实现标准库资源探测和可超时上下文管理器。
- [x] 运行定向测试确认通过。

### Task 2: 正式 API 有界队列

**Files:**
- Modify: `review_service/service.py`
- Modify: `review_service/router.py`
- Test: `tests/review_service/test_review_queue_backpressure.py`

- [x] 写队列容量、排队数、执行数和任务完成后补位的失败测试。
- [x] 用有界调度槽位替换无界提交，保留 QUEUED 任务并在槽位释放后补位。
- [x] 将队列/资源诊断加入 metrics/readiness。

### Task 3: Web Demo 与模型/转码并发统一门禁

**Files:**
- Modify: `poc/visual_review_poc/workbench_server.py`
- Modify: `poc/visual_review_poc/native_video_proxy.py`
- Modify: `poc/visual_review_poc/specialized_model_pass.py`
- Modify: `poc/visual_review_poc/model_selection_e2e.py`
- Test: `tests/visual_review/test_resource_backpressure.py`

- [x] 写 Web 入口拒绝/等待、低内存分块并发、转码并发和诊断字段测试。
- [x] 在三个 Web 审核入口复用案件槽位；模型分块和未成年人分块使用资源建议并发；转码使用共享转码槽位和内存检查。
- [x] 运行定向测试。

### Task 4: 轻量验证与主线记录

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `docs/product/四场景审核主线进度-20260814.md`

- [x] 增加低内存部署参数和 compose 内存/并发示例。
- [x] 运行聚焦测试、py_compile、git diff --check、CodeGraph sync。
- [x] 记录当前限制：本轮不调用真实模型，需在 2GB 预生产环境进行一次批量容量验收。
