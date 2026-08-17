# MITAKO Agent 客服与售后审核 POC

MITAKO Agent 是供甲方客服、产品和 Java 后端研发验证的售后审核 POC。当前核心不是“让大模型直接决定退款”，而是把用户素材、订单/SKU、包裹物流和可选仓库事实整理为可追溯证据，再输出客服可执行的审核建议。

> 当前状态（2026-08-18）：四场景源码、自动回归、API/Web 技术链、JKAdmin 规则治理、媒体预处理和八案报告已进入可追溯发布版本。八案是“每场景 2 案”的工程验收样本，不代表生产准确率；报告索引会明确每案通过点和剩余边界。发布入口以 [四场景审核主线进度](docs/product/四场景审核主线进度-20260814.md)、[开发者更新日志](docs/release/2026-08-18-developer-release-notes.md) 和 [甲方用户更新说明](docs/release/2026-08-18-customer-update-notes.md) 为准。

当前三包 Release：[私人仓库 v2026.08.18-r1](https://github.com/jackdiy/MITAKO-Agent/releases/tag/v2026.08.18-r1) / [公司仓库 v2026.08.18-r1](https://github.com/LoopRouterAI/MITAKO-Agent-JK/releases/tag/v2026.08.18-r1)。

## 交付入口

甲方先读 [0817 四场景业务理解与发布验收说明](甲方沟通交付文档/0817四场景审核业务理解与发布验收说明.html)、[八份报告质量索引](甲方沟通交付文档/0817四场景八份审核报告质量索引.html) 和 [甲方技术对接与私有化部署说明](甲方沟通交付文档/0817甲方技术对接与私有化部署说明.html)。

Java/后端研发先读 [内部研发文档入口](我方内部开发文档/README.md)、[当前业务契约](docs/product/四场景审核业务决策与报告契约-20260812.md)、[四场景黄金经验](docs/product/四场景黄金审核经验/README.md)、[开发者更新日志](docs/release/2026-08-18-developer-release-notes.md) 和 [交付包拆分说明](docs/release/2026-08-18-package-layout.md)。

八份 HTML 报告的直接入口和每案质量结论集中在 [八份报告质量索引](甲方沟通交付文档/0817四场景八份审核报告质量索引.html)。发布物拆为 [三类交付包](docs/release/2026-08-18-package-layout.md)：内部研发包不再携带大体量样本和离线敏感图片；独立验收证据包携带 8 份 HTML、119 个 WebP 和 manifest；客户 ZIP 通过授权 API 的签名媒体查看原片和证据。

## 核心能力

- 四个独立审核场景：商品有伤、发错货、漏发货、未成年人退款资料。
- 异步审核 API：创建工单、查询状态、批次汇总、JSON 结果、签名 HTML 报告和签名媒体。
- 视觉审核工作台：目录/多文件提交、媒体预检、模型事实抽取、场景后处理和报告查看。
- 双层客服报告：首层只显示结论、确定性、材料状态和下一步；详情层显示场景专属证据和原片时间点。
- 客服系统 POC：用户端、VIP 坐席台、运营后台和私域 Agent 演示链。

真实甲方订单、仓库、CRM、企微、飞书和退款执行接口目前只有契约或 Mock，不伪装为已接入。

## 一次审核如何完成

```text
Java/API 或本地工单目录
  -> 程序盘点文件、业务字段、SHA-256、重复项和可解码状态
  -> 图片独立 WebP；超阈值视频评估全时长 VP9 代理
  -> 场景专属 Prompt + 严格 JSON Schema 请求多模态模型
  -> 模型只返回可见原子事实、置信度、理由和证据引用
  -> 程序计算材料齐全性、订单/包裹对账和 SOP 规则
  -> 程序生成客服建议、人工路由和公开安全 DTO
  -> API 与 Web 共用同一 DTO 渲染双层报告
```

项目不调用生图模型，也不让模型自由生成最终业务动作。退款、补发、换货、赔偿、拒绝和最终定责由甲方系统或有权限人员执行。

## 四场景差异

| 场景 | 模型主要提取 | 程序主要判断 | 报告详情 |
|---|---|---|---|
| 商品有伤 | 初次拆包、开箱八字段、伤点、严重度、离镜、速度/剪辑语义 | 开箱门槛、严重结构伤窄例外、三段人为致损链 | 开箱九项、逐伤点、严重度、成因、原片证据 |
| 发错货 | 同包裹实收商品身份、数量、角色/系列/版本/形态/附件 | 订单 SKU 与实收身份对账、发错/漏发场景切换 | 应收、实收、同包裹证据、身份属性差异 |
| 漏发货 | 逐包裹实收、视频六项或静态三类事实 | 应发减实收、分包/赠品规则、商品构成、仓库终核 | 证据路线、仓库状态、逐包裹差异和未确认项 |
| 未成年人退款资料 | 五类材料分类、字段可读性和跨材料一致性 | 五类齐全性、可纠正补件、非标准人工、低龄条件 | 五类交通灯、具体缺口、冲突、风险和证据 |

唯一业务真源是 [四场景审核业务决策与报告契约](docs/product/四场景审核业务决策与报告契约-20260812.md)，场景细节位于 [四场景黄金审核经验](docs/product/四场景黄金审核经验/README.md)。

## 模型与渠道

模型配置集中在 [`configs/model_catalog.py`](configs/model_catalog.py)，Prompt 和 Schema 集中在 [`prompts/visual_review/`](prompts/visual_review/)。

- 试点默认：百度云渠道 `gemini-3.5-flash-lite`，`thinkingLevel=HIGH`，`mediaResolution=HIGH`，完整原生视频 `fps=1`，默认不发送 `maxOutputTokens`。
- `gemini-3.7-flash`：百度云最小请求已通过的显式高质量候选，视觉能力更强、成本更高；仅允许管理员显式启用，不进入自动兜底。
- 当前审核模型目录仅保留上述两个模型；其他历史模型不得出现在运行时选择列表或自动兜底中。

模型只接收当前任务必要的脱敏业务上下文。人工标签、样本正负目录、预告时间点、完整个人信息、内部 Prompt 和渠道密钥不得进入公开结果。

## 媒体预处理

- 图片逐张生成 WebP，不拼成长图；最长边超过 3840 像素时缩至不超过 2560，先无损，必要时质量 90。
- 视频满足任一条件时评估代理：不小于 100 MB、任一边超过 2K、超过 24 FPS、平均码率超过 6 Mbps，或供应商拒绝原片。
- 视频代理默认 VP9 WebM，保留完整时长，最长边不超过 2560、帧率不超过 24、码率不超过 6 Mbps；HEVC 只允许显式选择。
- 原始文件保留并记录哈希。D 盘空间不足时，运行媒体优先进入 `VISUAL_RUNTIME_MEDIA_DIR`，当前 Windows 环境可自动选择 `E:\MITAKO_Agent_Runtime`。
- 全片 1 FPS WebP 回退默认关闭；原生审核失败时返回系统重试，不自动触发高成本抽帧。

## Java 接入

Java 网关应调用 `/api/v1/review/*`，不要直接依赖视觉工作台内部路由。建议顺序：

1. `POST /api/v1/review/metadata/validate` 校验场景和业务字段。
2. `POST /api/v1/review/jobs` 提交 metadata 与附件。
3. 轮询 `GET /api/v1/review/jobs/{job_id}`，或按 `batch_id` 查询批次。
4. 读取公开 JSON；需要 HTML 时访问报告端点，媒体使用任务级签名 URL。
5. 根据 `material_readiness`、`advisory_assessment` 和场景详情决定客服下一步。

完整契约见 [`docs/delivery/openapi.yaml`](docs/delivery/openapi.yaml)、[REST API 总览](docs/api/rest-api-overview.md) 和 [Java 联调指南](我方内部开发文档/Java开发部署与联调指南.md)。生产重写时应保留租户、幂等、追加式人工裁决、公开脱敏和证据版本，不要把开放字典直接映射为最终业务动作。

## 前端职责

- 用户端只负责上传、显示处理状态和接收甲方允许公开的补件/处理结果。
- 坐席端先显示简洁结论，再按需展开场景详情和原视频时间点。
- JKAdmin 已支持租户级模型启停、默认切换、真实冒烟、强制修改理由、版本历史和回档；当前运行目录仅允许 Lite 与 3.7，变更会记录账号、时间、角色、理由和版本。
- 人工同意、否决、补件、重审与聊天状态同步尚未实现正式事件状态机，不能把现有技术重试当人工重审。

## 目录

| 路径 | 职责 |
|---|---|
| `review_service/` | 正式审核 API、任务、材料状态、决策、报告与存储 |
| `prompts/visual_review/scenes/` | 四场景稳定 Prompt 规则入口 |
| `prompts/visual_review/schemas.py` | 结构化响应 Schema 唯一维护区 |
| `configs/model_catalog.py` | 模型能力、渠道类型、超时与成本估算 |
| `poc/visual_review_poc/` | 媒体处理、模型调用、事实聚合与 HTML 渲染 |
| `src/` | 用户端、坐席台和管理后台 |
| `docs/product/` | 当前业务契约、主线进度和黄金经验 |
| `docs/delivery/` | OpenAPI、部署、测试和 Java 对接资料 |

## 启动

Windows 11：

```bat
setup_venv.bat
一键启动-Windows.bat
```

Ubuntu：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm install
npm run build
./一键启动-Ubuntu.sh
```

默认入口：用户端 `http://127.0.0.1:8000/`、坐席台 `/desk`、管理后台 `/admin`、视觉工作台 `http://127.0.0.1:7861/`。

## 验证与发布

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\check_documentation_release.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\pre_release_internal_validation.ps1 -RunModelBatch
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\package_release.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\package_internal_release.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\package_four_scenario_evidence.ps1
.\.venv\Scripts\python.exe scripts\check_release_packages.py
```

默认打包仍执行完整预发布门禁。仅修改 README、发布说明或包布局，且当前 8 案冻结证据仍通过哈希与契约校验时，可对两个打包脚本显式追加 `-ReuseValidatedAcceptanceEvidence`，跳过重复的真实模型/API E2E；三包解压、内容、隐私、哈希和启动冒烟仍必须执行。客户包不包含源码、内部文档、模型渠道、Key、Prompt、数据库、日志或原始样本；内部研发包不得外发。

## 安全边界

- `.env`、数据库、用户上传、原始样本、运行媒体、日志和发布 ZIP 不进入 Git。
- 对外 API、Workbench 和 HTML 必须使用同一公开投影与脱敏规则。
- 订单、物流、仓库、身份、运营商等未接入的权威事实只能标记未提供或待核验。
- 旧 Companion、陪伴、角色扮演和文字冒险能力保持封存。
