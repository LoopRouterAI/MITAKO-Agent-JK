# 三大审核 Agent 自动化评测与模型选型

生成日期：2026-07-04

## 目标

三大审核场景不能只看一次模型返回。评测必须同时比较：

- 样本材料包：视频、补充图片、用户诉求、订单/工单上下文。
- Prompt 版本：当前主版本为 `sop_evidence_v3`。
- 模型版本：当前对比 `gemini-3.5-flash`、`gpt-5.5`、`qwen3.5-flash`、`qwen3.6-plus`、`doubao-seed-2.0-lite`、`doubao-seed-2.1-pro`。
- 业务指标：人工标注命中率、同模型三连测稳定性、结构化成功率、时间戳命中率、置信度、人工复核建议、耗时、成本。

## 当前实现

入口脚本：

```powershell
venv\Scripts\python.exe poc\visual_review_poc\local_video_triage_demo.py `
  --customer-samples `
  --scenario all `
  --fps 1 `
  --max-frames 12 `
  --api-frame-limit 12 `
  --probe-seconds 0 `
  --supplemental-image-limit 4 `
  --compare-models DEFAULT `
  --repeat-runs 3 `
  --concurrency 24 `
  --request-timeout 240 `
  --soft-retries 2 `
  --enable-thinking `
  --text-review-image-detail high `
  --prompt-profile sop_evidence_v3 `
  --auto-pass-confidence 0.88 `
  --manual-review-confidence 0.72 `
  --internal-report
```

## 指标定义

- API 成功：渠道返回成功响应。
- 结构化成功：返回可解析 JSON，且通过本地业务字段、枚举、置信度和人工复核边界校验。
- 命中：模型输出 `predicted_label` 与人工标注期望标签一致。人工标签只用于报告侧评估，不进入模型 Prompt。
- 时间戳命中：模型指出的问题时间戳能对应本次实际送入的抽帧证据。
- 选型分：结构化成功率、命中率、标签稳定性、时间戳命中率、平均置信度的加权结果，只用于 POC 排序。

## Prompt 迭代规则

`sop_evidence_v3` 的核心要求：

- 先做 `claim_parsing`，解析用户诉求中的期望商品、收到商品、尺寸/角色/损伤点/资料类型。
- 再做逐帧客观事实提取，绑定帧编号和时间戳。
- 做 `claim_signal_check`，输出 `supported`、`contradicted` 或 `unclear`。
- `predicted_label` 只表示材料是否支持用户诉求，不代表退款、拒赔、补发或定责。
- `business_action_allowed` 永远为 `false`，`business_final_review_required` 和 `human_required` 必须为 `true`。

## 自动化迭代方法

每轮新增 Prompt 或模型时，必须保留旧版本报告，并跑同一批样本：

1. 固定样本集和人工标注。
2. 固定抽帧参数和补充图片策略。
3. 每轮只改变一个变量：Prompt 版本或模型版本。
4. 比较命中率、结构化成功率、三连测稳定性、低置信转人工比例、成本和耗时。
5. 只有命中率提升且人工复核建议更合理，才把新 Prompt 设为默认。

## 仍需补齐

- 未成年人资料审核当前没有甲方真实样本，不能做真实 E2E 命中率评估。
- 发错货负样本仍太少，不足以判断稳定性。
- 商品有伤需要补更多高反光、轻伤、中伤、重伤、快递破损和用户暴力拆箱样本。
- 需要甲方提供 SKU 主数据、商品标准图、盲抽/随机规则，才能把“发错货”从视觉信号提升到更稳定的业务判断。
