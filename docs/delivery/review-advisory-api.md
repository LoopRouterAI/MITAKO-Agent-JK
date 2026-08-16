# 审核建议结果 API 使用说明

版本：2026-08-15

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
    "policy_ref": "MITAKO-ROUTING@20260815.1"
  }
}
```

未成年人资料默认策略：

```json
{
  "client_case_id": "MINOR-20260730-001",
  "scenario": "minor_refund",
  "minor_refund_policy": {
    "review_mode": "standard",
    "authoritative_verification": "disabled"
  },
  "output_options": {
    "include_html_report": true
  }
}
```

`review_mode=standard + authoritative_verification=disabled` 是默认值：完成五类材料、可见字段一致性和图片风险初审，不因甲方没有身份/运营商接口而强制转人工。`authoritative_verification=advisory` 只增加黄色提示；只有甲方明确选择 `review_mode=strict + authoritative_verification=required` 时，未完成权威核验才阻断。

字段说明：

| 字段 | 默认值 | 作用 |
|---|---:|---|
| `output_options.include_html_report` | `true` | `true` 返回结构化 JSON 并开放 HTML；`false` 只返回 JSON |
| `review_routing_policy.policy_ref` | `MITAKO-ROUTING@20260815.1` | 选择服务端已批准的复审策略；调用方不能改写业务阈值 |
| `minor_refund_policy.review_mode` | `standard` | 未成年人资料视觉初审；`strict` 仅供甲方显式启用 |
| `minor_refund_policy.authoritative_verification` | `disabled` | `disabled/advisory/required`；默认不依赖外部验真接口 |

复审阈值由服务端批准策略统一管理，不授权服务执行任何售后动作。离镜时长只作证据描述；是否影响证据强度取决于必要展示窗口和重新入镜同物关系，离镜本身不等于剪辑、调包或欺诈。调用方传入旧阈值字段会返回 HTTP 422，不会被静默忽略。

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

离镜时长只作为黄色证据说明。只有离镜发生在争议商品的必要展示窗口内，且重新入镜后无法确认仍为同一物件时，系统才降低连续性证据强度；不会按统一秒数自动补件、拒绝，也不会据此声称用户调包。

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
- 商品有伤默认策略为 `classification_recommendation + MITAKO-PD-ADVISORY@20260731.1`。该版本把主视频、补充图片和官方 SKU 图分层，并加入不合规开箱视频的 SOP 倾向；旧 `20260728.1` 快照行为保持不变。它只输出事实建议，不授权退款、换货、补偿或拒绝。
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

## 11. 未成年人资料结果口径

- `minor_material_assessment.checklist`：五类材料是否识别、质量状态和证据图片编号。
- `minor_material_assessment.field_consistency`：只比较图片中可见字段是否互相对得上，不冒充政府、运营商或支付系统验真。
- `minor_material_assessment.authenticity_assessment`：图片风险提示。缺少 EXIF 或单个疑似编辑信号默认标黄；多项相互印证才标红。
- `minor_material_assessment.authoritative_verification.status=not_configured_optional`：默认未配置且不阻断；不是接口故障。
- 五类材料齐全、字段仅有非阻断存疑时允许 `decision=continue_by_customer_policy`、`human_required=false`，由甲方按风险偏好抽检。
- 字段明确冲突、字段比对技术失败、多重疑似编辑证据或严格验真待完成时才 `human_required=true`。
- `agent_brief.next_step` 与 `advisory_assessment` 同源：`optional` 只提示抽检，`not_required` 明确无需人工，不能沿用模型早期生成的逐单 VIP 复核文案。
- `material_inventory[].document_state` 区分已填写资料、空白模板、示例和未知；`sop_eligibility` 区分有效、仅辅助、无效和未知。普通运营商账户截图不得替代用户特定的手机号实名归属证明。
- `material_inventory[].quality_issues` 可以在脱敏公开响应中解释黄/红原因；OCR 原文、姓名、证件号、手机号、护照号和地址继续禁止公开。

真实盲测命令：

```powershell
.venv\Scripts\python.exe scripts\check_minor_refund_144989.py `
  --sample-root "E:\AIGC\0 Mitako样本" `
  --base-url http://127.0.0.1:8000
```

该脚本会过滤人工标签、最终回复、隐藏资源文件和无效媒体，只把用户诉求与真实媒体送入正式异步 API。

## 12. 0731 结构化证据与能力边界

- 审核输入中的自然语言可以包含用户对历史处理的转述；服务只按 `annotation`、`label`、`ground_truth` 等评测字段和禁止文件隔离答案，不靠普通文本关键词删消息。
- `damage_causality_assessment.damage_presence` 只表示主视频内是否有可回链的伤情证据；补充图片所见位于 `evidence_source_summary.supplemental_images`，不得改写主视频结论。
- `object_continuity_assessment.tracked_subjects[].out_of_frame_events[]` 提供离镜前、离镜、重新入镜证据以及按源时间戳估算的持续时间。该时间是采样边界估计，不单独证明调包或剪辑。
- `media_forensics.assets[].playback_speed_assessment` 只在有可信技术依据时返回倍速；一般用户上传视频缺少原始时钟基准时返回 `status=unknown`、`constant_speed_multiplier=null`。画面节奏疑似加速是另一项模型观察，两者不得混用。
- 未成年人资料中的护照可以输出非敏感的 `document_type`、`issuing_country_or_region`、身份角色与关系一致性状态；证件号、手机号、地址和 OCR 原文不在公开响应中返回。
- `pass_integrity_status=partial_specialized` 表示某个专项证据维度存在局部缺口，不等于主审核失败，也不自动强制整案人工复审；调用方应读取 `advisory_assessment` 作为最终分流主契约。
