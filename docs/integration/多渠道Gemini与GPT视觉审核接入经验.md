# 多渠道视觉审核接入经验

更新时间：2026-07-08

## 已验证结论

- `.env` 已支持官方 Gemini 与中性视觉审核网关所需 Key；报告不得输出密钥。
- 视觉审核网关使用 Gemini `generateContent` 兼容链路，便于在不暴露渠道商的前提下做容灾切换。
- YouTube 链接优先走 Gemini 原生视频理解；本地上传/平台 URL 下载后，统一走我方自建抽帧链路。
- 本地链路会把同一批抽帧、补充图片、用户诉求、订单/工单上下文送给各候选模型，保证模型选型公平。
- 当前视觉审核方案不再引入传统目标检测路线，三大场景以多模态理解、跨帧推理、补充图片交叉验证和人工复核阈值为核心。

## 路由策略

1. 主视觉审核网关先按 `Retry-After` 或指数退避重试。
2. 主网关软错误重试后仍失败，或硬错误，切官方 Gemini 通道。
3. Gemini 主审不可用时，再尝试 GPT/Qwen/Doubao 候选模型。
4. GPT-5.5 可作为高价值争议样本复核，不默认作为低成本主审。

软错误包括 408、409、425、429、500、502、503、504、timeout、rate limit、overloaded、temporarily unavailable。鉴权失败、模型不存在、参数错误按硬错误处理。

## 三类业务选型

| 场景 | 首选方案 | 复核候选 | 人工边界 |
|---|---|---|---|
| 开箱视频审核 | Gemini 3.5 Flash 基于抽帧和补充材料输出连续性、离镜、疑似剪辑、发错货信号 | GPT-5.5、Qwen、Doubao 做争议样本复核 | 低置信度、疑似剪辑、缺 SKU/主数据、模型分歧转VIP客服 |
| 商品有伤 | Gemini 3.5 Flash 输出损伤可见性、位置、严重程度、反光/遮挡风险、补拍建议 | GPT-5.5 做高价值复核，国产模型做成本候选 | 不自动补发、赔付、拒赔、定责 |
| 未成年人资料审核 | 只做脱敏材料完整性、隐私遮盖、材料链提示 | 候选模型只允许复核材料完整性，不做身份识别 | 必须人工终审，不把未脱敏原始证件送外部通用模型 |

## 当前 E2E 命令

```powershell
venv\Scripts\python.exe poc\visual_review_poc\local_video_triage_demo.py `
  --customer-samples --scenario all `
  --fps 1 --max-frames 12 --api-frame-limit 12 --probe-seconds 0 `
  --supplemental-image-limit 4 `
  --compare-models DEFAULT --repeat-runs 3 --concurrency 24 `
  --request-timeout 240 --soft-retries 2 --enable-thinking `
  --text-review-image-detail high --internal-report
```

内部报告必须展示：

- 每次调用送入的帧数、时间戳、补充图片和用户诉求。
- 视觉网关、端点、实际模型、耗时、Token、预估成本。
- 模型原始返回全文。
- 解析后的结论、理由、证据、反证、问题时间戳、补件建议。
- 结构化请求契约、解析状态、缺失字段和本地校验失败原因。

## 对甲方口径

可以说：三类高优先级场景的真实 API 调用链路已跑通，模型能输出结构化结论、置信度、证据、时间戳和人工复核建议。

不能说：已达到甲方真实准确率、可自动定责、可自动拒赔、可自动退款、可直接替代人工、未成年人资料可自动终审。
