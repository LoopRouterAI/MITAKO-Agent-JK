# MITAKO Agent 客服与视觉审核 POC

MITAKO Agent 是一个面向甲方技术可行性验证的客服系统 POC，当前交付范围包括：

- 用户端 AI客服：专业、同理、有边界的服务型助手。
- VIP客服工作台：接单、阅读服务记录、回复、转交、升级处理。
- 运营后台：队列、坐席、服务记录、质检、补偿审批、运营与运维指标。
- 独立审核服务与视觉审核工作台：商品有伤、发错货、漏发货、未成年人退款材料核验四类优先场景，支持异步任务、批次、抽帧计划、置信度、成本估算和 HTML 报告。
- 私域 Agent P0：群事件/商品事件接入契约、用户与群分层、受控运营动作、舆情预警和转人工协同。
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
| 用户端 AI客服 | `http://127.0.0.1:8000/` |
| VIP客服工作台 | `http://127.0.0.1:8000/desk` |
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
python scripts/check_review_service_batch.py
python scripts/check_review_sop_alignment.py
python scripts/check_private_domain_agent_e2e.py
python scripts/check_admin_ui_smoke.py
python scripts/check_visual_workbench_smoke.py
python scripts/check_review_runtime_dependencies.py --media D:\approved-samples\sample.mp4
python scripts/check_order_reference_integration.py --snapshot D:\approved-samples\case\order_info_snapshot.json --report tests\reports\order-reference.json --limit 2
python -m playwright install chromium
python tests/e2e/run_desk_admin_screenshot_report.py
```

## 关键文档

| 文档 | 用途 |
|---|---|
| `甲方沟通交付文档/0722订单资料与官方商品图按需接入说明.html` | 1,422 个资料目录盘点、1,127 份快照同步、官方图按任务读取和仍待甲方确认项 |
| `我方内部开发文档/升级日志-2026-07-22-订单基线与官方商品图按需接入.md` | 路径映射、最小化适配、CDN 安全、缓存、API/报告链路和回归命令 |
| `甲方沟通交付文档/视觉审核逐帧与资料审核整改说明-2026-07-20.html` | 禁止拼图判定、617911 独立帧、144989 资料质量分层和 API/网页提交模式实测 |
| `我方内部开发文档/升级日志-2026-07-20-独立逐帧审核与资料质量分层.md` | 独立 JPEG 传输、24 帧分段、公开 DTO、测试命令与真实任务证据 |
| `甲方沟通交付文档/订单SKU快照接入与审核安全升级说明-2026-07-20.html` | 订单快照匹配结果、API/网页接入、数据缺口、隐私边界与审核安全升级 |
| `我方内部开发文档/升级日志-2026-07-20-视觉证据安全与SKU基准.md` | SKU 适配调用链、策略注册表、签名媒体、失败计费和回归命令 |
| `甲方沟通交付文档/未成年人资料字段一致性审核升级说明-2026-07-20.html` | 0718 反馈整改、五项字段一致性、144989 真实盲测和权威接口边界 |
| `我方内部开发文档/升级日志-2026-07-20-未成年人资料字段一致性.md` | 内部调用链、Schema、门禁、配置、回归与剩余风险 |
| `甲方沟通交付文档/index.html` | 给甲方 CEO、客服负责人、Java 开发、项目经理浏览 |
| `我方内部开发文档/index.html` | 给我方研发、测试、实施、产品浏览 |
| `我方内部开发文档/系统清单与代码地图.md` | 系统边界、模块清单和代码入口 |
| `我方内部开发文档/Java开发部署与联调指南.md` | Java 网关、私有化部署和联调方法 |
| `我方内部开发文档/客服Agent视觉审核系统设计指南.md` | 内部系统设计、模块边界与正式开发指南 |
| `docs/delivery/openapi.yaml` | 面向 Java 技术栈的接口契约参考 |
| `docs/delivery/mitako-full-requirement-reaudit-20260711.html` | 全需求复核与未完成边界报告 |
| `docs/delivery/mitako-0714-adversarial-acceptance-20260715.html` | 0714 反馈整改、真实样本与对抗式验收报告 |
| `docs/delivery/mitako-visual-evaluation-engineering-acceptance-20260716.html` | 0715 评测复核、三通道审核、损伤因果、履约对账与边界报告 |
| `甲方沟通交付文档/0717四样本审核工程整改与验收报告.html` | 四样本复测、Strong 2 FPS、全局时间轴、ffprobe、判负策略与真实 API 回归 |
| `docs/delivery/deployment-guide.md` | 部署与上线说明 |
| `Codex接续开发交接说明.md` | 迁移到另一台设备和 Codex 接续开发的上下文 |
| `tests/reports/customer_chat_acceptance_20260706.html` | 用户端客服交互最后一轮验收报告 |

## POC 边界

- 当前真实甲方业务接口只做 Mock 和契约说明，不伪装为已接入生产系统。
- 本地 `mock_data.json` 只用于演示订单、物流、售后、商品、地址等流程。
- 生产联调前必须由甲方提供测试环境、接口契约、鉴权方式、脱敏样本、人工结论和上线审批。
- 真实 `.env`、数据库、运行时记忆、日志、测试截图、视频样本、模型文件和超大原始资料不得 Git 提交。内部研发 ZIP 可在打包时安全加入当前 `.env` 与数据库快照，但不得转发甲方。

## 打包交付

先启动内部源码版主服务与视觉审核服务。打包命令会强制执行内部部署健康检查、构建、文档校验和关键回归；任一失败都会停止生成 ZIP。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package_release.ps1
```

我方 Java/Python/测试人员使用包含源码、内部文档、当前 `.env` 和数据库快照的内部研发包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package_internal_release.ps1
```

内部包含敏感配置和业务数据，不得转发甲方或上传公开位置。详见 `我方内部开发文档/内部研发包交付说明.md`。

涉及审核提示词、抽帧或模型路由的正式候选版，还应额外执行真实多模态批次：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/pre_release_internal_validation.ps1 -RunModelBatch
```

打包脚本会按交付规则过滤本地密钥、数据库、日志、运行时缓存和大文件。不要手工压缩整个仓库交付给甲方。
