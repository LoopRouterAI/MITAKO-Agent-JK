# 审核建议结果 API 使用说明

版本：2026-07-28

## 1. 使用目的

审核服务输出的是“事实证据判断 + 证据分数 + 人工复审建议 + 风险信号”，不直接执行退款、补发、换货、拒绝或最终定责。甲方系统可以按自身已审批规则消费结构化字段，也可以让客服阅读 HTML 报告。

旧字段 `predicted_label`、`system_yes_no`、`decision` 暂时保留用于兼容；新接入应优先读取 `result.review.advisory_assessment`。

## 2. 请求配置

在 `/api/v1/review/jobs` 的 `metadata` JSON 中加入：

```json
{
  "client_case_id": "CASE-20260723-001",
  "scenario": "product_damage",
  "output_options": {
    "include_html_report": false
  },
  "review_routing_policy": {
    "required_below_confidence": 0.5,
    "optional_below_confidence": 0.8,
    "out_of_frame_resubmit_seconds": 3.0
  }
}
```

字段说明：

| 字段 | 默认值 | 作用 |
|---|---:|---|
| `output_options.include_html_report` | `true` | `true` 返回结构化 JSON 并开放 HTML；`false` 只返回 JSON |
| `review_routing_policy.required_below_confidence` | `0.5` | 低于该证据分数时建议必须人工复审 |
| `review_routing_policy.optional_below_confidence` | `0.8` | 低于该分数但未达到必须复审条件时建议抽检 |
| `review_routing_policy.out_of_frame_resubmit_seconds` | `3.0` | 连续离镜达到该秒数时建议补充连续原视频 |

三个阈值只控制建议分级，不授权服务执行任何售后动作。离镜本身不等于剪辑、调包或欺诈。

`required_below_confidence` 必须小于或等于 `optional_below_confidence`；逆序配置返回 HTTP 422，不会被服务静默改写。

## 3. 主要响应

```json
{
  "advisory_assessment": {
    "scenario": "product_damage",
    "assessment": {
      "conclusion_code": "evidence_supports_claim",
      "conclusion": "当前视觉证据支持商品存在可见损伤。",
      "confidence": 0.88,
      "confidence_level": "high",
      "calibration_status": "uncalibrated_evidence_score"
    },
    "human_review": {
      "level": "optional",
      "reason_codes": ["non_blocking_risk_signal"],
      "recommendation": "存在非阻断风险信号，甲方可按风险偏好抽检；不要求每单人工复审。"
    },
    "workflow_recommendation": "continue_by_customer_policy",
    "signals": [
      {
        "code": "short_out_of_frame",
        "severity": "warning",
        "duration_seconds": 1.4,
        "effect": "短暂离镜或遮挡仅降低证据强度，不单独触发拒绝或强制人工复审。"
      }
    ],
    "policy": {
      "policy_ref": "MITAKO-ADVISORY-20260723@1",
      "advisory_only": true,
      "business_action_allowed": false
    }
  },
  "report": {
    "requested": false,
    "status": "not_requested",
    "html_url": null
  }
}
```

`confidence` 是当前证据链的未校准证据强度分，不是客观正确率，也不是退款成功概率。

商品有伤场景中，伤情存在性与损伤成因分开计算。明确可见伤情可以输出 `evidence_supports_claim`；成因、责任或商品连续性未完全确认时，以 `signals` 和 `human_review=optional` 表达，不再覆盖已经确认的伤情事实。发错货、漏发货缺少订单、规则、包裹或证据覆盖基准时仍保持 `evidence_inconclusive`。

## 4. 人工复审三级含义

| `human_review.level` | 适用情况 | 建议使用方式 |
|---|---|---|
| `required` | 服务失败、证据实质冲突、证据分数低于必须复审阈值 | 授权人员核对原始材料 |
| `optional` | 短暂遮挡、轻度取证信号、中等证据分数、非阻断不确定项 | 甲方按风险偏好抽检，不要求每单人工 |
| `not_required` | 证据链达到配置门槛，或材料缺口可直接向用户补齐 | 按 `workflow_recommendation` 继续 |

## 5. 流程建议

| `workflow_recommendation` | 含义 |
|---|---|
| `human_review` | 建议必须人工复审 |
| `request_more_material` | 当前优先补充材料，无需仅因材料缺口先占用人工席位 |
| `continue_by_customer_policy` | 甲方系统按自身已审批规则继续处理 |
| `system_retry` | 当前请求内结构修复与逐张恢复后仍未完整处理；调用方可受控重跑整案，可能重复模型成本，不要求用户补件 |

连续离镜达到默认 3 秒时，系统输出 `request_more_material + not_required`。这是“当前开箱证据不完整”，不是“自动拒绝”，也不是“已证明用户调包”。

## 6. HTML 报告

- 网页工作台默认 `include_html_report=true`。
- 正式 API 默认也生成 HTML，兼容旧调用方。
- JSON-only 请求设为 `false` 后，不生成报告文件；访问 `/api/v1/review/jobs/{job_id}/report` 返回 HTTP 409，错误码 `review_report_not_requested`。
- HTML 首屏展示事实结论、证据分数、三级复审建议、流程建议、风险信号和业务边界；后续展示关键帧、反证、时间点、订单基线和媒体取证。
- HTML 的标题、事实结论、人工复审建议和流程建议全部来自同一份 `advisory_assessment`。`request_more_material + not_required` 不得显示为“需要 VIP 客服复核”。
- HTML 中的帧图、关键图和原视频链接统一使用主服务任务级地址 `/api/v1/review/jobs/{job_id}/media/{media_id}`；调用方不需要也不应访问内部视觉服务地址。

## 7. 批量案件

生产批量仍按“每案一个异步 job、共用 `batch_id`”提交。每案可以独立配置是否生成 HTML，独立重试和查询；批次查询不把一个案件的失败扩散到其他案件。

网页父目录批量用于小批量人工复测，默认逐案生成 HTML；直接调用工作台接口时可传 `include_html_report=false` 只取 JSON。

单案素材容量采用动态策略：默认 40 份以内为 `standard`，41-200 份为 `expanded`，服务全部接收后分批处理并聚合结果。响应的 `ingestion.capacity_mode/soft_limit/safe_limit` 可用于观测本案容量状态。超过安全上限返回 HTTP 413，错误码 `too_many_review_assets`，并包含 `received_count` 与 `safe_limit`；部署方可按机器、模型和成本评测调整安全上限，但不得静默截断已接收资料。

若已接收资料中仍有未处理批次，结果必须标记 `processing_status=technical_processing_incomplete`、`workflow_recommendation=system_retry`，`confidence=null`，且不得把内部失败转换成用户 `material_gaps`。本版本的任务重试会重跑整案，可能重复模型成本；不宣称跨进程断点续跑。

## 8. 兼容与审计

- `policy.policy_ref` 用于记录本次建议规则版本。
- `policy.business_action_allowed` 永远为 `false`。
- 商品有伤默认策略为 `classification_recommendation + MITAKO-PD-ADVISORY@20260728.1`。它只输出事实建议：完整审查未见主诉伤情可建议 `negative`，明确伤情可建议 `positive`，证据冲突或关键基准缺失为 `review`；不授权退款、换货、补偿或拒绝。
- `signals` 记录信号代码、程度、影响和可用持续时间，方便甲方后续配置抽检规则。
- 旧字段 `human_required`、`decision`、`system_yes_no` 会镜像新主契约，避免新旧客户端得到相反分流；新开发仍应只以 `advisory_assessment` 为准。
- 人工标签、标准答案和评测目录名不得进入审核请求；只能在审核完成后离线比对。

完整数据模型以 [OpenAPI](./openapi.yaml) 为准，Java 流式上传示例见 [Java 接入样例](./java-client-sample.md)。

## 9. 多源证据和风险隔离

发错货、漏发货的新接入方必须同时阅读 [客诉审核 Agent 与沟通 Agent 接口联调指南](./after-sales-agent-integration.md)。特别注意：

- `logistics` 是结构化包裹/轨迹快照，不再建议传任意散乱 JSON。
- `conversation_history` 只能包含本次审核时点之前的必要对话，不得包含人工最终决定、退款结果或评测标签。
- `customer_risk_context` 只接收脱敏聚合统计，只影响服务端抽检优先级，不发送给视觉模型，不改变本次事实结论，也不允许自动拒绝。
- 发错货和漏发货如果缺少商品到包裹/运单的权威映射，仍可审核媒体，但确定性结论会降级。

## 10. 动态容量真实回归

```powershell
.venv\Scripts\python.exe scripts\check_dynamic_material_capacity_http.py --base-url http://127.0.0.1:8000 --count 62
```

该脚本不读取或发送人工标签，只验证真实 HTTP 上传、异步任务、动态容量、全部图片处理和结构化聚合。机器报告写入 `tests/reports/dynamic_material_capacity_http_latest.json`。
