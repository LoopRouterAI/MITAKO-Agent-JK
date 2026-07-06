# MITAKO Agent 客服与视觉审核 POC

MITAKO Agent 是一个面向甲方技术可行性验证的客服系统 POC，当前交付范围包括：

- 用户端智能客服：专业、同理、有边界的服务型助手。
- 人工客服工作台：接单、阅读服务记录、回复、转交、升级处理。
- 运营后台：队列、坐席、服务记录、质检、补偿审批、运营与运维指标。
- 视觉审核工作台：开箱视频/发错货、商品有伤、未成年人资料审核三类优先场景。
- 甲方与我方两套文档系统：对接物料、接口说明、POC 测试说明、内部设计指南。

旧版 Companion、陪伴、角色扮演、文字冒险能力已从当前产品入口中剥离。当前系统不提供恋爱、陪伴、角色扮演或持续情感依赖能力，只保留客服场景需要的专业同理表达。

## 快速启动

### Windows

```bat
setup_venv.bat
一键启动-Windows.bat
```

### Ubuntu

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm install
npm run build
./一键启动-Ubuntu.sh
```

## 本地入口

| 能力 | 地址 |
|---|---|
| 用户端智能客服 | `http://127.0.0.1:8000/` |
| 人工客服工作台 | `http://127.0.0.1:8000/desk` |
| 运营后台 | `http://127.0.0.1:8000/admin` |
| 视觉审核工作台 | `http://127.0.0.1:7861/` |
| 甲方交付文档 | `http://127.0.0.1:8790/甲方沟通交付文档/index.html` |
| 我方内部文档 | `http://127.0.0.1:8790/我方内部开发文档/index.html` |

## 常用命令

```bash
npm run build
npm run test:e2e
npm run accept:cs-agent
python scripts/dual_system_smoke_test.py
python scripts/check_admin_ui_smoke.py
python scripts/check_visual_workbench_smoke.py
```

## 关键文档

| 文档 | 用途 |
|---|---|
| `甲方沟通交付文档/index.html` | 给甲方 CEO、客服负责人、Java 开发、项目经理浏览 |
| `甲方沟通交付文档/甲方对接物料与接口清单.md` | 甲方需要提供的物料、接口、样本和权限 |
| `甲方沟通交付文档/客服Agent与视觉审核对接指南.md` | 客服 Agent 与视觉审核接口对接说明 |
| `我方内部开发文档/index.html` | 给我方研发、测试、实施、产品浏览 |
| `我方内部开发文档/客服Agent视觉审核系统设计指南.md` | 内部系统设计、模块边界与正式开发指南 |
| `docs/delivery/openapi.yaml` | 面向 Java 技术栈的接口契约参考 |
| `docs/delivery/deployment-guide.md` | 部署与上线说明 |
| `tests/reports/customer_chat_acceptance_20260706.html` | 用户端客服交互最后一轮验收报告 |

## POC 边界

- 当前真实甲方业务接口只做 Mock 和契约说明，不伪装为已接入生产系统。
- 本地 `mock_data.json` 只用于演示订单、物流、售后、商品、地址等流程。
- 生产联调前必须由甲方提供测试环境、接口契约、鉴权方式、脱敏样本、人工结论和上线审批。
- `.env`、数据库、运行时记忆、日志、测试截图、视频样本和模型文件不得提交到 GitHub。

## 打包交付

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package_release.ps1
```

打包脚本会按交付规则过滤本地密钥、数据库、日志、运行时缓存和大文件。不要手工压缩整个仓库交付给甲方。
