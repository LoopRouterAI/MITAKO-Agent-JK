# Codex 接续开发交接说明

日期：2026-07-06

## 1. GitHub 状态

- 仓库地址：`https://github.com/jackdiy/MITAKO-Agent.git`
- 分支：`main`
- 本文创建前已同步提交：`3f81fb3 chore: remove local conversation archive`
- 本地与远端状态：`main...origin/main`，无领先或落后。
- 未认证访问 GitHub API 返回 404，同时本机可正常 `git push`，符合私有仓库表现。

新设备接续：

```bash
git clone https://github.com/jackdiy/MITAKO-Agent.git
cd MITAKO-Agent
```

如果需要真实模型调用，把 `.env.example` 复制为 `.env`，再用可信渠道补真实密钥。当前 GitHub 最新快照不跟踪 `.env`、SQLite 数据库、运行时记忆、日志、截图、视频样本和大压缩包。

## 2. 拉取后能否开始开发

可以开始源码开发、前端构建、接口契约阅读和 Mock 联调。

推荐最小启动流程：

```bash
npm install
npm run build
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
python scripts/dual_system_smoke_test.py
```

Windows 本地演示按根目录 `README.md` 使用：

```bat
一键启动-Windows.bat
```

主要入口：

- 用户端智能客服：`http://127.0.0.1:8000/`
- 人工客服工作台：`http://127.0.0.1:8000/desk`
- 运营后台：`http://127.0.0.1:8000/admin`
- 视觉审核工作台：`http://127.0.0.1:7861/`

## 3. 当前仓库包含什么

当前 GitHub 快照包含：

- 客服 Agent 用户端、人工客服工作台、运营后台源码。
- 三大视觉审核场景工作台与 POC 代码。
- 面向 Java 技术栈的接口契约：`docs/delivery/openapi.yaml`。
- Java/Spring Boot 对接样例：`docs/delivery/java-client-sample.md`。
- 甲方沟通交付文档：`甲方沟通交付文档/`。
- 我方内部开发文档：`我方内部开发文档/`。
- Spec Kit 计划：`specs/001-customer-poc-professional-upgrade/`。
- 最新客服交互验收报告：`tests/reports/customer_chat_acceptance_20260706.html` 和 `.md`。

当前 GitHub 快照不包含：

- `.env` 真实密钥。
- `data/*.db` 本地 SQLite 数据库。
- `viking_memory/` 运行时记忆。
- `tests/reports/screenshots/` 可重跑截图。
- `poc/visual_review_poc/sample_videos/` 公开视频样本。
- `docs/三大审核场景的小量样本/` 甲方原始小样本。
- `docs/客服当前的问题与对话.zip` 和其他巨大原始材料包。

这些被排除的材料不要直接塞进 Git。确实需要给对方时，单独走网盘、内网制品库或 Git LFS。

## 4. 需求和设计上下文

本轮项目目标已经从“陪伴/角色扮演”收敛为商业 POC：

- 专业、同理、有边界的客服 Agent。
- 人工客服能接手、转交、升级、查询订单/物流/售后上下文。
- 后台需要展示队列、服务记录、质检、补偿审批、运营报表和运维健康指标。
- 三大视觉审核优先场景：开箱视频/发错货、商品有伤、未成年人资料审核。
- 视觉审核以多模态理解模型为主，不再把 YOLO 作为主线。
- 真实甲方接口当前只做 Mock 和契约说明，不能伪装为已接入生产。

关键阅读顺序：

1. `README.md`
2. `docs/delivery/README.md`
3. `docs/delivery/openapi.yaml`
4. `docs/delivery/java-client-sample.md`
5. `我方内部开发文档/index.html`
6. `甲方沟通交付文档/index.html`
7. `specs/001-customer-poc-professional-upgrade/plan.md`
8. `tests/reports/customer_chat_acceptance_20260706.html`

## 5. 下一位 Codex 的工作方式

先跑这三条确认环境：

```bash
git status --short --branch
npm run build
python scripts/dual_system_smoke_test.py
```

再做改动。不要先重构。

必须遵守：

- 不提交 `.env`、数据库、运行时记忆、日志、测试截图、大视频、压缩样本包。
- 不恢复旧 Companion、陪伴、角色扮演、文字冒险入口。
- 面向甲方和普通用户的页面不得暴露模型渠道、Key、内部 Prompt、调试参数。
- 真实甲方接口只写 Mock、契约和适配层，不声明已接入。
- 大改动后至少跑 `npm run build` 和 `python scripts/dual_system_smoke_test.py`。

最近一次已通过验证：

- `npm run build`
- `python -m py_compile business_api.py main.py agent.py agent_llm.py business_mock_service.py business_readiness_service.py`
- `python scripts/dual_system_smoke_test.py`，结果 `8/8`
