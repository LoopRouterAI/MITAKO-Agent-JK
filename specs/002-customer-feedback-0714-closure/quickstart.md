# Quickstart: 0714 整改验收

1. 使用项目 `.venv` 安装依赖并启动主服务与视觉服务。
2. 运行 `scripts/check_customer_agent_0709_regression.py`。
3. 运行 `scripts/check_customer_agent_0714_regression.py`。
4. 运行私有化 API smoke、视觉工作台 smoke 和前端 `npm run build`。
5. 在用户端连续切换五个用户，复测 0714 原问题。
6. 从用户端创建审核任务，核对用户端、坐席台、API 和 HTML 报告一致性。
7. 运行内部发布打包脚本，在新目录解压、启动并重复步骤 2 到 4。

验收证据统一写入 `tests/reports/` 与 `docs/delivery/`。任何真实甲方能力在未联调前必须显示为演示或待联调。

