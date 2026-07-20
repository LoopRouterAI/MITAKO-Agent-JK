# 视觉审核后台配置与模型选型 E2E 说明

更新时间：2026-07-20

## 当前路线

三大审核场景当前采用多模态模型选型路线，不再使用传统目标检测训练或本地权重路线。

- Gemini/GPT/Qwen/Doubao 使用同一批本地抽帧证据和补充图片。
- 抽帧、补充图片、用户诉求、订单/工单上下文共同组成输入证据包。
- 报告区分 API 成功、结构化成功、人工标注命中、三连测稳定性、时间戳命中、耗时和成本。
- 默认公开报告不暴露模型、渠道、端点、Token、成本；内部报告通过 `--internal-report` 展示。

## 当前供应商媒体请求方式

当前实际供应商不按 Gemini Files URI 能力设计。主链路固定为：原视频在我方服务端本地解码、抽帧并压缩为独立 JPEG；细节、连续性与成因审核都逐张以内联 Base64 图片调用供应商兼容接口。Gemini 兼容请求使用 `inline_data`，OpenAI 兼容请求使用 `data:image/...;base64`，不得生成或依赖 `file_uri`，也不得把拼图作为模型判定输入。

这项约束可从视觉服务 `GET /api/health` 的 `model_media_transport` 和主服务 `GET /api/v1/review/contract` 的 `media_processing` 检查。自动化验收必须断言 `supplier_file_uri_required=false`。

`REVIEW_MODEL_TIMEOUT_SECONDS`、`REVIEW_MODEL_RETRIES`、`REVIEW_CHUNK_WORKERS` 和 `REVIEW_CONTINUITY_FRAMES_PER_CALL` 分别控制单次供应商请求时限、软失败重试、分段并发和连续性分段大小。它们适用于网页单文件、网页文件夹和正式审核 API 的共享执行链路。

## 推荐命令

```powershell
venv\Scripts\python.exe poc\visual_review_poc\local_video_triage_demo.py `
  --customer-samples --scenario all `
  --fps 1 --max-frames 12 --api-frame-limit 12 --probe-seconds 0 `
  --supplemental-image-limit 4 `
  --compare-models DEFAULT --repeat-runs 3 --concurrency 24 `
  --request-timeout 240 --soft-retries 2 --enable-thinking `
  --text-review-image-detail high --internal-report
```

## 内部报告必须包含

- 每次审核输入的视频、用户诉求、抽帧数量、时间戳、补充图片数量。
- 渠道、端点、实际请求模型、状态码、耗时、Token、预估成本、重试记录。
- 模型原始返回全文。
- 解析后的 `decision`、`predicted_label`、`confidence`、`confidence_reason`。
- 支持证据、反证、材料缺口、补件建议。
- 逐帧描述、问题时间戳、跨帧追踪、阶段覆盖、真实性/剪辑风险判断。
- 结构化请求契约、解析状态、缺失字段、校验失败解释。

## 命中定义

“命中”只表示模型输出的 `predicted_label` 与人工标注期望标签一致。模型请求不会携带“人工确认正/负样本”等答案文本，人工标注只在报告侧用于评估。

## 结构化成功定义

结构化成功需要同时满足：

1. 模型返回可解析 JSON。
2. 包含必要业务字段。
3. `decision`、`predicted_label`、`evidence_status` 等枚举合法。
4. `confidence` 是 0-1 数字。
5. `business_action_allowed=false`。
6. `business_final_review_required=true`。
7. `human_required=true`。

API 成功但结构化失败，通常表示模型或渠道没有严格遵守业务 JSON 契约，或返回被截断、空文本、字段缺失、枚举不合规。

## 上线前仍需补齐

- 未成年人资料真实脱敏样本。
- 发错货正负样本和 SKU/商品主数据。
- 商品有伤轻伤/中伤/重伤、反光、遮挡、低清样本。
- 每个结论类至少正负各 50 条，稳定验收建议 200-300 条。
