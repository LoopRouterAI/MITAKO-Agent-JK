# 虾淘售后审核服务 API 契约与自动化验收（2026-07-10）

## 结论

甲方真实调用不应依赖手动工作台录入订单号。工作台只保留给人类演示和复核；系统对接使用主 FastAPI 内的独立审核编排服务：

- 一个案件携带完整业务字段和多张图片、多段视频、文本/JSON 材料。
- 每个案件独立获得 `job_id`，异步排队、查询、失败诊断和重试。
- 批量任务由调用方并发提交案件，并使用 `batch_id` 查询聚合状态，避免把多个大案件塞进一个超大 HTTP 请求。
- 视觉工作台继续作为模型执行器，审核编排服务不重复实现模型调用。
- 所有结果只提供证据、置信度和流程建议，不自动退款、补发、换货、拒绝或最终定责。

## 甲方样本字段盘点

现有样本体现的案件结构包括：

- 工单字段：`id`、`order_no`、`tag`、`status`、`admin_status`、`created_at`、`updated_at`。
- 用户诉求：`content.txt`。
- 历史对话：`reply.json`，包含用户/客服消息、时间、图片引用和售后卡片事件。
- 素材清单：`resources[].path`、`fields`、`local_file`、`oss_keys`、`status`。
- 业务主数据：`order_items`、`product_master_data`、`warehouse_master_data`。
- 多媒体：单案件可含多图、多视频；最大现有案件约 556MB。

场景映射：

| 对外场景 | 底层视觉能力 | 当前样本 |
|---|---|---|
| `wrong_item` | 开箱连续性 + 订单/实物/SKU/规格比对 | `sample_001`、`sample_002` |
| `product_damage` | 瑕疵位置/数量/严重度 + 图片真实性 + 开箱连续性 | `sample_003` |
| `minor_refund` | 材料完整性、一致性、篡改风险，只能转人工多级审核 | `sample_004` |
| `missing_item` | 订单数量、拆单状态、全家福、自封袋/面单、完整开箱比对 | 当前无真实样本，只完成契约和 SOP 规则覆盖 |

## API

所有接口使用现有 Bearer 集成账号 Token。

### 1. 校验案件元数据

`POST /api/v1/review/metadata/validate`

请求体为 OpenAPI 中的 `ReviewCaseMetadata`。自动化客户端可在上传大文件前先校验字段。

核心字段：

- `client_case_id`：甲方案件唯一 ID。
- `scenario`：`product_damage`、`wrong_item`、`missing_item`、`minor_refund`。
- `ticket_id`、`user_id`、`order_no`、`customer_claim`。
- `order_items`、`product_master_data`、`warehouse_master_data`、`logistics`。
- `conversation_history`、`sop_context`。
- `asset_fields`：按原文件名声明素材来自 `images`、`reply`、`werehouse_message` 等字段。
- `source_record`：原样保留甲方 manifest 的 `id/tag/status/admin_status/created_at/updated_at/resources` 等全部 JSON 字段。
- `sampling_policy`：配置 `adaptive`、`strong`、`strict`、`forensic` 或 `custom` 抽帧策略；可选 `auto_escalate`、`confidence_threshold` 和 `forensic_checks`。
- `continuity_policy`：离镜复核阈值、是否强制主体连续性专项扫描和专项分段大小。
- `damage_causality_policy`：商品有伤场景是否强制执行动作前、动作中、动作后三段因果扫描。
- `fulfillment_baseline`：版本化应发清单、每项数量、赠品/特典/随机规则、包裹数、物流单号和包裹到商品行的映射。
- `evidence_coverage`：本次实际提交的包裹引用/物流单号，以及是否完整展示全部包裹和物品。声明为“全部上传”但不提供实际包裹映射时仍视为材料不完整。

### 2. 上传前采样规划

`POST /api/v1/review/sampling-plan`

甲方后台可在上传前传入视频时长、文件大小、视频数量、场景、采样策略、连续性策略和损伤因果策略。接口返回预计帧数、主审核/主体连续性/损伤因果各通道调用数、总模型调用数、并行轮次和是否建议走对象存储转码代理。

- `adaptive`：按时长/文件大小抽取 6-24 帧，适合低成本粗筛。
- `strong`：`1 fps`，是 `strict` 的清晰业务别名。
- `strict`：`1 fps`，单视频最多 1200 帧，每 24 帧一个模型分段。
- `forensic`：`2 fps`，单视频最多 1800 帧，每 24 帧一个模型分段。
- `custom`：甲方配置 `0.1-2 fps`、帧上限和每次调用帧数。

`adaptive` 默认只执行主审核，以控制批量初筛成本；不会无条件升级到 1 FPS。`strong/strict/forensic` 自动启用主体连续性专项通道，商品有伤场景同时启用损伤因果专项通道。甲方也可在自适应档显式开启 `force_dense_scan` 或 `force_action_scan`，此时采样计划会同步提升时间分辨率并返回增加后的总调用数。

当前 543,351,335 字节、452.5 秒样本在 `strict` 下预计 454 帧、19 个模型分段、10 个并行轮次，并建议先走对象存储转码代理。
同一视频在 `forensic` 下预计 906 帧。采样点按完整时轴均匀计算，不依赖原视频帧率整除，因此 25fps、29.97fps 等素材都保持接近后台配置的目标频率；触及帧上限后仍均匀覆盖首尾。

### 3. 创建审核案件

`POST /api/v1/review/jobs`

Content-Type：`multipart/form-data`

- `metadata`：`ReviewCaseMetadata` 的 JSON 字符串。
- `files`：可重复字段，支持多图、多视频、`.txt`、`.json`。
- Header `Idempotency-Key`：同一业务请求重放时返回原案件；同一 Key 对应不同请求返回 409。

返回 HTTP 202：

```json
{
  "ok": true,
  "created": true,
  "job": {
    "job_id": "RJ-...",
    "status": "QUEUED",
    "scenario": "wrong_item",
    "assets": []
  }
}
```

### 4. 查询、列表与重试

- `GET /api/v1/review/jobs/{job_id}`
- `GET /api/v1/review/batches/{batch_id}?limit=100&offset=0`：全批次状态与成本由数据库聚合，案件明细分页返回。
- `GET /api/v1/review/jobs?status=SUCCEEDED&scenario=wrong_item`
- `POST /api/v1/review/jobs/{job_id}/retry`

状态：`QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`、`RETRYING`。

成功结果包含：

- `review.summary`：预测标签、置信度、人工复核要求。
- `review.agent_brief`：客服可读结论和下一步。
- `review.agent_report`：证据包、素材画廊、采用证据、反证、材料缺口、连续性与真实性评估。
- `review.agent_report.parsed.confidence_components`：主分段模型自评均值、损伤成因假设分、履约对账识别分、主体可见覆盖率和规则降级后的最终决策分。完成独立留出集校准前，这些分数都不是“真实正确率”。
- `review.agent_report.parsed.fulfillment_reconciliation`：应发清单、视频已识别清单、疑似缺失项、未确认项、包裹观察记录、证据时间点和证据充分性。
- `media_forensics`：模型调用前的非 AI 容器、流、帧率、包时间轴和编辑器元数据信号；信号不等同于已证实剪辑。
- `recommended_escalation`：低置信、review、材料缺口或取证风险触发的有界升级建议；默认只建议，不自动重复调用模型。
- `boundary`：业务动作边界。

失败结果保留 `diagnostics`，可定位 HTTP 状态、执行阶段和错误类型。

### 5. 指标

- `GET /api/v1/review/metrics`
- `GET /metrics`
- `GET /metrics/prometheus`

当前指标：排队数、运行数、成功数、失败数、平均耗时、最老排队时长、worker 数、累计推理 Token、累计估算美元成本。

### 6. HTML 报告

- `GET /api/v1/review/jobs/{job_id}/report`
- 使用与任务查询相同的 Bearer Token 鉴权。
- 报告展示结论、置信度分解、支持证据、反证/可疑帧、损伤动作前/中/后证据、离镜前/起点/重新入镜证据、履约清单对账、问题时间点、材料缺口、模型局限、全时轴采样信息、各通道调用数、推理耗时、估算 Token 与估算美元成本。
- 报告不展示模型渠道、模型名、Key、内部 Prompt、原始模型响应或定价配置。

## 大文件与 120GB 批次方案

当前真实可运行路径支持单文件默认不超过 650MB、单案件默认不超过 750MB。已使用 556,390,436 字节案件完成实际 API 上传与审核。审核进程保留原始文件用于证据回看，但不会把完整视频直接发送给多模态模型，而是：

1. 读取完整视频时轴，不再只扫描开头窗口。
2. 由甲方选择自适应粗筛、`1 fps` 严格审核、`2 fps` 取证审核或自定义频率。
3. 密集帧形成主审核、主体连续性和商品有伤因果三个独立通道；各通道分段并行执行，专项通道任一分段失败或漏帧时最终结论强制降级为人工复核。
4. 将视频帧和大图片统一缩放、压缩为 JPEG，再与完整业务上下文一并送审。
5. 聚合全部分段证据、风险、置信度、Token、成本和耗时，并在报告中记录实际帧数与分段数。

对于甲方约 120GB 的生产批次，不应让所有原始素材经由 FastAPI 应用服务器中转。推荐生产链路：

1. 甲方服务端获取七牛云或同类对象存储的短期上传凭证，客户端/业务服务直传原始素材。
2. 对象存储回调登记对象 Key、SHA256、大小、MIME、时长、订单/工单和资源字段映射。
3. 通过七牛云持久化处理等转码服务生成 H.264 720p、约 1-2Mbps 的审核代理视频，并生成故事板或关键帧；原始文件保留用于争议复核。
4. 审核任务引用代理视频/关键帧，按案件并发提交；回调或轮询获得结果，失败案件独立重试。
5. 生产适配层需要甲方提供对象存储空间、回调域名、转码模板、数据保留和出境策略后联调。当前仓库没有这些真实权限，因此明确标记为待联调，不伪装已接入。

## 评测标签隔离

模型输入侧禁止 `expected_predicted_label`、`human_conclusion`、`ground_truth`、标准答案、正/负样本标记等字段。`sample_labels.json` 不能作为审核附件上传；人工标签只允许在模型返回后用于离线评测。服务会对 metadata、JSON/TXT 附件和文件名执行硬拦截。

双人标注、标签仲裁和理由完整度属于双方可选的评测数据治理流程，不是生产审核 API 的必填字段或运行时门槛。离线统计可使用 `scripts/analyze_visual_review_results.py`，该脚本不参与推理。

## 非 AI 媒体取证

部署机安装 `ffprobe` 并加入 `PATH` 后，服务在模型调用前执行有界检查：容器/流时长、音视频时长差、帧率与时基、编辑器/转码元数据，以及最多 20,000 个媒体包的时间戳连续性。包时间戳回退或异常大间隔只作为复核信号，不能单独证明剪辑或篡改。

未安装 `ffprobe`、超时或无法解析时返回 `status=unavailable`，模型审核仍可继续；不得把不可用状态解释为“视频正常”。超时由 `REVIEW_FFPROBE_TIMEOUT_SECONDS` 配置。

## 自动化验收

启动服务后执行：

```powershell
$env:E2E_BASE_URL="http://127.0.0.1:8000"
.\.venv\Scripts\python.exe scripts\check_private_deployment_api.py
.\.venv\Scripts\python.exe scripts\check_private_domain_agent_e2e.py
.\.venv\Scripts\python.exe scripts\check_private_domain_10k_scale.py
.\.venv\Scripts\python.exe scripts\check_review_input_isolation.py
.\.venv\Scripts\python.exe scripts\check_review_media_preprocessing.py
.\.venv\Scripts\python.exe scripts\check_review_service_batch.py --samples sample_002,sample_004 --run-id acceptance-001
.\.venv\Scripts\python.exe scripts\check_review_service_batch.py --samples sample_002,sample_004 --sampling-preset strict --run-id strict-acceptance-001
```

完整样本：

```powershell
.\.venv\Scripts\python.exe scripts\check_review_service_batch.py --samples sample_001,sample_002,sample_003,sample_004 --run-id full-acceptance-001 --timeout 1800
```

## 已验证结果

以下结果验证的是接口、批处理、大文件、幂等、失败恢复和报告链路，不代表在甲方业务留出集上的准确率。历史模型自报的 `confidence=0.95` 不能解释为“95% 审核正确率”；准确率必须在标签隔离后的独立样本上另行统计。

- OpenAPI/API smoke：13/13。
- 私域 Agent 群分层、商品候选、舆情转客服、后台复盘：4/4。
- 私域商品事件 1 万群本地规模验证：10,000/10,000 完成评估和候选持久化，风险群拦截正确，本机约 0.1 秒；该结果不等同于真实企微网络吞吐。
- 两案件并发：发错货与未成年人资料均成功返回结构化结果。
- 严格采样批次：发错货视频按 `1 fps` 送审 38 帧，拆分为 2 个模型分段；批次共 86,897 tokens，估算成本 0.233567 美元。
- 商品有伤：16 个文件约 106MB，成功完成接口与报告链路。
- 最大样本：10 个文件共 556,390,436 字节，成功完成接口与报告链路。
- 幂等重放：返回原 job_id，`created=false`。
- 幂等冲突：HTTP 409。
- 视觉执行器故障：案件进入 FAILED 并保留 502 诊断；服务恢复后原 job_id 重试成功。
- 安全扫描：公开审核结果不包含模型渠道、模型名、Key、内部 Prompt、原始响应或定价配置；仅展示脱敏的 Token 数和估算美元成本。

## 仍需甲方提供

- 真实漏发货正样本、反样本及人工最终结论。
- 订单、拆单、物流、仓库、商品主数据字段字典，以及应发商品行、数量、赠品/特典/随机规则、包裹与物流单号关联方式。
- 甲方服务账号/SSO/API 网关鉴权方案。
- 多实例部署时使用的正式任务队列和对象存储。
- 企微、飞书、客服系统、商品库、订单系统的真实权限与回调地址。
