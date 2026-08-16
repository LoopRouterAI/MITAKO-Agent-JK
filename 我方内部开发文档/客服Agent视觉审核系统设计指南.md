# 客服 Agent + 视觉审核系统设计指南

版本：2026-07-05
适用对象：我方产品、研发、测试、实施、项目负责人
边界：本文件为内部设计资料，不直接发给甲方。

## 1. 当前产品边界

当前 POC 只保留客服业务系统：

- 用户端AI客服：专业、同理、有边界，承接用户情绪并推进订单、物流、售后、材料补充和转VIP客服。
- VIP客服工作台：查看服务记录、接单、回复、转交、升级。
- 运营后台：坐席管理、队列监控、服务记录、质检、审批、报表、运维。
- 三大视觉审核工作台：开箱视频/发错货、商品有伤、未成年人资料审核。

旧版 Companion、陪伴、文字冒险和角色扮演代码已经封存到 `archive/companion_roleplay_mode_20260705/`。客服 Agent 可以保留 MBTI 风格设定，但只用于“专业、同理、有边界”的客服表达，不提供虚拟陪伴、恋爱、角色扮演或持续情感依赖服务。

## 2. 关键代码边界

| 模块 | 路径 | 职责 |
| --- | --- | --- |
| 用户端客服 | `src/App.jsx`、`src/hooks/useChatSSE.js`、`src/components/chat/` | SSE 对话、业务卡片、转VIP客服同步 |
| 客服 Agent | `agent.py`、`agent_llm.py` | 意图识别、SOP 检索、业务查询、回复生成、安全净化 |
| VIP客服工作台 | `src/desk/`、`handoff_service.py`、`handoff_store.py` | 队列、接单、回复、转交、升级、审计 |
| 运营后台 | `src/admin/`、`admin_service.py`、`admin_store.py` | 坐席、队列、审批、报表、运维 |
| 业务适配层 | `business_api.py`、`business_mock_service.py`、`business_readiness_service.py` | 验证环境业务接口、SOP 分支、准备度判断 |
| 视觉审核工作台 | `poc/visual_review_poc/workbench_server.py`、`workbench.html`、`report_renderer.py` | 三类审核入口、材料处理、报告生成 |
| 回归脚本 | `scripts/check_visual_workbench_smoke.py`、`tests/e2e/` | 工作台和客服主链路验收 |

## 3. 工作台与客服系统打通方式

### 3.1 数据流

```text
甲方 Java 后台 / POC 样例材料
  -> 创建 review_task
  -> 上传视频、图片、文本、订单、SKU、物流、历史投诉
  -> 视觉审核服务生成 structured_review_result
  -> VIP客服工作台展示 report_url + evidence_summary
  -> 坐席确认 human_decision
  -> 客服 Agent 只消费 public_summary / next_action
  -> 用户端收到专业客服表达
```

### 3.2 Agent 消费协议

客服 Agent 不应读取模型原始返回，也不应向用户暴露帧号、模型、渠道、token、成本等内部字段。它只消费以下字段：

```json
{
  "reviewTaskId": "RV202607050001",
  "taskType": "PRODUCT_DAMAGE",
  "status": "REVIEW_COMPLETED",
  "publicSummary": "材料显示商品表面存在明显划痕，仍需要客服核对包装和订单主数据后处理。",
  "nextAction": "请补充包装外观照片，或由客服抽检后进入售后流程。",
  "confidenceBand": "HIGH",
  "requiresHumanDecision": true
}
```

### 3.3 VIP客服工作台展示协议

坐席端可以看到更完整的审核摘要：

```json
{
  "resultLabel": "SUPPORT_CUSTOMER_CLAIM",
  "confidence": 0.91,
  "continuityScore": 0.88,
  "tamperRisk": "LOW",
  "evidence": [
    {
      "type": "VIDEO_FRAME",
      "timecode": "00:42",
      "frameIndex": 18,
      "thumbnailUrl": "/media/review/RV001/frame_018.jpg",
      "description": "合格证尺寸字段可见为 75mm。"
    }
  ],
  "missingMaterials": [],
  "recommendedHumanAction": "抽检确认后按售后流程处理"
}
```

## 4. 三类审核的产品设计

### 4.1 开箱视频/发错货审核

目标：帮助客服判断用户诉求是否有视觉证据支撑，并识别调包、剪辑、箱体离镜、关键证据缺失。

必须输入：

- 用户诉求文本。
- 订单商品名、SKU、规格。
- 商品主数据：尺寸、角色、款式、随机/盲抽规则。
- 开箱视频，可包含多个视频。
- 用户补充图片。
- 历史工单和客服已承诺事项。

输出要求：

- `resultLabel`：支持诉求、不支持诉求、证据不足、需补件、需升级。
- `confidence`：0 到 1。
- `continuityScore`：视频连续性评分。
- `tamperRisk`：高、中、低。
- `evidence`：必须关联时间戳、帧号、图片缩略图。
- `missingMaterials`：缺少什么材料，客服能直接照着要。

### 4.2 商品有伤审核

目标：识别商品瑕疵位置、是否具备售后处理价值、是否需要补拍、是否存在图片真实性风险。

额外关注：

- 图片是否过低分辨率、过度裁剪、遮挡、反光。
- 是否缺少包装外观、外盒、快递面单、商品整体图。
- 是否疑似生成图、二次编辑图或无法证明与该订单有关。

### 4.3 未成年人资料审核

目标：辅助客服检查材料完整性和一致性，不做自动退款裁决。

额外关注：

- 监护人身份与用户/订单关联是否可解释。
- 是否缺少订单归属、付款记录、监护关系、沟通记录。
- 是否包含不应长期保存的敏感信息。

## 5. 任务状态机

| 状态 | 说明 | 系统动作 |
| --- | --- | --- |
| `CREATED` | 任务创建 | 校验幂等键、写入任务 |
| `MATERIAL_READY` | 材料齐备 | 进入队列 |
| `AI_REVIEWING` | 审核中 | 抽帧、组证据包、调用审核模型 |
| `NEED_MORE_MATERIAL` | 材料不足 | 生成补件建议 |
| `REVIEW_COMPLETED` | 审核完成 | 生成客服可读 HTML 报告 |
| `HUMAN_REVIEWING` | 人工复核中 | 坐席查看报告 |
| `HUMAN_CONFIRMED` | 人工确认 | 回写甲方工单 |
| `FAILED_RETRYABLE` | 可重试失败 | 429/5xx 指数退避 |
| `FAILED_FINAL` | 不可恢复失败 | 坐席人工处理 |

## 6. 接口适配层设计

建议新增独立适配层，不让 Agent 直接调用甲方业务接口：

```text
partner_adapter/
  auth.py                  # token、签名、重试
  ticket_client.py          # 工单同步
  review_task_client.py     # 审核任务
  material_client.py        # 材料下载与上传
  callback_client.py        # 回写甲方
  schemas.py                # Pydantic 契约
```

适配层必须支持：

- Java 网关常见 HMAC 签名。
- `Idempotency-Key`。
- 429/5xx 指数退避。
- 请求追踪 ID。
- 素材下载白名单和内网地址拦截。
- 回调失败进入补偿队列。

## 7. 队列与并发策略

POC 当前可以单机运行；正式版本建议：

- 审核任务进入队列，按 `priority`、`taskType`、`createdAt` 排序。
- 单任务可多材料并行预处理，单模型请求受限流器控制。
- 429 必须重试，不跳过；重试策略为 1s、2s、4s、8s、16s，上限后转 `FAILED_RETRYABLE` 并提示人工。
- 大视频先本地抽帧、压缩、切片，避免直接上传超大文件。
- 抽帧参数支持后台配置：`fps`、`maxFrames`、`probeSeconds`、`strictContinuity`。

## 8. 模型策略

内部选型保留三层：

| 层级 | 用途 | 说明 |
| --- | --- | --- |
| 主审模型 | 输出结构化审核结论 | 优先选择稳定、跨帧理解强、理由清晰的多模态模型 |
| 复核模型 | 双盲校验 | 只用于高风险、低置信、高金额或争议强样本 |
| 降级策略 | 服务可用性 | 供应商失败时重试和切换，返回可解释失败原因给坐席 |

正式选型不能靠 3 个样本下结论。至少需要甲方提供每类正负样本各 50 条，理想规模为每类 200 到 300 条，包含人工结论与理由。

## 9. UI 与交互要求

视觉审核工作台要为高频客服操作优化：

- 三类任务独立入口，不让客服先理解“场景下拉框”。
- 支持拖放上传、选择文件夹、批量材料包和后续接口接入。
- 审核报告结论置顶，后面才是证据链、推理和缺失材料。
- 图片用浮层预览，不跳转离开报告页。
- 视频证据能定位到时间戳。
- 队列状态、失败重试、耗时、材料数量清晰可见。
- 面向甲方的报告不展示模型名、渠道、token、密钥、内部 prompt。

## 10. 合规与话术边界

- 不使用“陪伴”“恋人”“朋友式长期情绪依赖”等产品定位。
- 可以使用 MBTI 服务人格，但表达必须围绕客服任务。
- 客服 Agent 对用户只说“我帮你核实”“需要补充材料”“会转客服确认”，不能说“模型判定”“供应商结果”“内部审核失败”。
- 未成年人资料默认最小化展示和最短必要保留。
- 自动审核只给参考意见，退款、补发、拒赔必须由人工或甲方系统执行。

## 11. 验收脚本

```powershell
npm run build
python scripts/dual_system_smoke_test.py
python scripts/check_data_isolation.py
python scripts/check_auth_migration_dry_run.py
python tests/e2e/run_admin_operations_e2e.py
python tests/e2e/run_enterprise_production_e2e.py
python tests/e2e/run_auth_strict_e2e.py
python scripts/check_visual_workbench_smoke.py
```

## 12. 下一步落地计划

1. 将视觉审核工作台的三类入口稳定为正式组件，保留批量上传和文件夹扫描。
2. 新增 `review_task` 数据模型与队列存储。
3. 新增甲方 Java 对接适配层，先连测试环境。
4. 将审核报告摘要写入VIP客服工作台服务记录。
5. 将人工结论回写给甲方工单系统。
6. 收集甲方每类正负样本，跑模型稳定性、成本和一致性评测。
7. 上线前完成权限、日志脱敏、材料保留周期和回滚演练。
