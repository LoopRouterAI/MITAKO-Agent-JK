# Codex 接续开发交接说明

日期：2026-07-06

## GitHub 状态

- 仓库地址：`https://github.com/jackdiy/MITAKO-Agent.git`
- 分支：`main`
- 当前边界：私人仓库，可提交 `.env`；已从 `.env` 和 `.env.example` 移除指定的两个路由通道配置。
- 本地与远端应保持：`main...origin/main`。
- 未认证访问 GitHub API 返回 404，同时本机可正常 `git push`，符合私有仓库表现。

新设备接续：

```bash
git clone https://github.com/jackdiy/MITAKO-Agent.git
cd MITAKO-Agent
npm install
npm run build
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
python scripts/dual_system_smoke_test.py
```

## 仓库包含

- `.env`：私人仓库内可用于跨设备接续开发；不要放入对外 ZIP。
- 客服 Agent 用户端、VIP客服工作台、运营后台源码。
- 三大视觉审核场景工作台与 POC 代码。
- 面向 Java 技术栈的接口契约：`docs/delivery/openapi.yaml`。
- Java/Spring Boot 对接样例：`docs/delivery/java-client-sample.md`。
- 甲方沟通交付文档：`甲方沟通交付文档/`。
- 我方内部开发文档：`我方内部开发文档/`。
- Spec Kit 计划：`specs/001-customer-poc-professional-upgrade/`。
- 最新客服交互验收报告：`tests/reports/customer_chat_acceptance_20260706.html` 和 `.md`。

## 不走普通 Git 的本地材料

这些材料仍保留本地，但不适合普通 Git 提交；需要迁移时走 Git LFS、网盘或内网制品库：

- `data/*.db`
- `viking_memory/`
- `tests/reports/screenshots/`
- `poc/visual_review_poc/sample_videos/`
- `docs/三大审核场景的小量样本/`
- `docs/客服当前的问题与对话/`
- 其他 PDF、ZIP、大视频和模型文件

## 当前产品边界

项目目标已经从陪伴/角色扮演收敛为商业 POC：

- 专业、同理、有边界的客服 Agent。
- VIP客服能接手、转交、升级、查询订单、物流、售后上下文。
- 后台展示队列、服务记录、质检、补偿审批、运营报表和运维健康指标。
- 三大视觉审核优先场景：开箱视频/发错货、商品有伤、未成年人资料审核。
- 视觉审核以多模态理解模型为主，不再把 YOLO 作为主线。
- 真实甲方接口当前只做 Mock 和契约说明，不能伪装为已接入生产。

## 推荐阅读顺序

1. `README.md`
2. `docs/README.md`
3. `docs/delivery/README.md`
4. `docs/delivery/openapi.yaml`
5. `docs/delivery/java-client-sample.md`
6. `我方内部开发文档/index.html`
7. `甲方沟通交付文档/index.html`
8. `specs/001-customer-poc-professional-upgrade/plan.md`
9. `tests/reports/customer_chat_acceptance_20260706.html`

## 下一位 Codex 的工作约束

先跑：

```bash
git status --short --branch
npm run build
python scripts/dual_system_smoke_test.py
```

再改代码。不要先重构。

必须遵守：

- 私人仓库可提交 `.env`，但不得提交数据库、运行时记忆、日志、测试截图、大视频、压缩样本包。
- 不恢复旧 Companion、陪伴、角色扮演、文字冒险入口。
- 面向甲方和普通用户的页面不得暴露模型渠道、Key、内部 Prompt、调试参数。
- 真实甲方接口只写 Mock、契约和适配层，不声明已接入。
- 大改动后至少跑 `npm run build` 和 `python scripts/dual_system_smoke_test.py`。

最近一次已通过验证：

- `npm run build`
- `python -m py_compile business_api.py main.py agent.py agent_llm.py business_mock_service.py business_readiness_service.py`
- `python scripts/dual_system_smoke_test.py`，结果 `8/8`
