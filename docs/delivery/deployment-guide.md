# 部署指南

## 环境要求

| 项目 | 要求 |
|---|---|
| 系统 | Windows 11 / Windows Server 2019+ / Ubuntu 22.04+ |
| Python | 3.11+ |
| Node.js | 18+ |
| 浏览器 | Chrome / Edge 最新稳定版 |

## 本地验证启动

Windows：

```bat
setup_venv.bat
npm install
一键启动-Windows.bat
```

Ubuntu：

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
npm install
chmod +x ./一键启动-Ubuntu.sh
./一键启动-Ubuntu.sh
```

启动成功后访问：

| 页面 | 地址 |
|---|---|
| 用户端 AI客服 | `http://127.0.0.1:8000/` |
| VIP客服工作台 | `http://127.0.0.1:8000/desk` |
| 运营后台 | `http://127.0.0.1:8000/admin` |

## 视觉审核工作台

视觉审核工作台独立启动，默认用于开箱视频审核、商品有伤审核、未成年人资料审核。

```bat
venv\Scripts\python.exe poc\visual_review_poc\workbench_server.py
```

默认地址：

```text
http://127.0.0.1:7861/
```

## 验证环境边界

- 验证包使用脱敏样例数据，不连接甲方生产系统。
- 订单、售后、仓库、财务和私域触达动作只展示流程和建议，不写入甲方真实业务系统。
- 视觉审核工作台可处理本地上传视频、图片、文本和常见公开视频链接；上线前仍需甲方提供脱敏样例、审核规则和人工复核标准。
- 客服主站右侧观察面板用于坐席/运营调试，可折叠；普通用户侧不展示内部处理细节。
- 上线前必须启用正式访问保护、固定访问白名单，并完成数据备份与恢复演练。

## 上线前门禁

我方实施负责人发布前执行：

```bat
npm run build
python scripts/dual_system_smoke_test.py
python tests/e2e/run_enterprise_production_e2e.py
python scripts/check_visual_workbench_smoke.py
```

如需单独验证数据目录隔离和租户迁移备份：

```bat
set MITAKO_DATA_DIR=tmp\release-data-check
python scripts/check_data_isolation.py
python scripts/check_auth_migration_dry_run.py
```
