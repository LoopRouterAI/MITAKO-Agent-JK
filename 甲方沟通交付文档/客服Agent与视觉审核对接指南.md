# 客服 Agent 与视觉审核对接指南

版本：2026-07-05
适用对象：甲方 CEO、客服负责人、业务负责人、信息化负责人、Java 开发团队、双方项目经理

## 1. 当前目标

本 POC 聚焦两类人效提升：

- 客服主链路：发货慢、清关慢、仓库慢、物流慢、退货退款、商品破损、未成年人退款等问题，由客服 Agent 先承接情绪、整理上下文、提示补件，必要时转VIP客服。
- 三类视觉审核：开箱视频/发错货、商品有伤、未成年人资料审核，为VIP客服输出证据摘要、置信度、缺失材料和复核建议。

当前版本不会直接写入甲方生产订单、仓库、财务、退款或私域触达系统。上线前需要双方完成测试环境接口、权限、样例数据、人工复核标准和回滚方案确认。

## 2. 总体流程

```text
用户 App / 小程序提交咨询或申诉材料
  -> 甲方 Java 后台创建工单，同步订单、SKU、物流、历史投诉和上传材料
  -> MITAKO 创建客服会话或视觉审核任务
  -> 视觉审核服务生成证据摘要、置信度、缺失材料和复核建议
  -> VIP客服工作台查看报告、视频时间点、图片证据和用户诉求
  -> VIP客服确认通过、拒绝、补件或升级
  -> 结论回写甲方工单系统
  -> 客服 Agent 只基于“审核状态、人工结论、可对用户表达的摘要”继续对话
```

## 3. 三类审核入口

三类审核不建议混在同一个客服入口里。推荐按客服岗位和业务队列拆成独立任务类型：

| 审核类型 | 典型材料 | 系统输出 | 人工动作 |
| --- | --- | --- | --- |
| 开箱视频/发错货审核 | 用户诉求、开箱视频、订单商品名、SKU、规格、仓库商品主数据、补充图片 | 视频连续性、箱体/商品是否离镜、规格/角色/款式是否匹配、可疑时间点、置信度 | 通过、拒绝、补件、升级 |
| 商品有伤审核 | 破损/瑕疵图片、视频、包装图、订单商品、历史投诉 | 损伤位置、是否疑似运输/开箱前损伤、图片真实性风险、证据强弱、置信度 | 通过、拒绝、补拍、升级 |
| 未成年人资料审核 | 监护人诉求、订单归属材料、关系证明、聊天/付款记录 | 材料完整性、身份一致性、隐私风险、缺失字段、置信度 | 人工确认、补件、主管/法务升级 |

## 4. 甲方需要提供的数据

| 类别 | 必要字段 |
| --- | --- |
| 工单 | `ticketId`、`userId`、`tenantId`、工单状态、创建时间、客服队列、用户诉求文本 |
| 订单 | `orderNo`、下单时间、商品列表、实付金额、售后状态、焦点订单 |
| 商品主数据 | SKU、商品名、规格、尺寸、角色、款式、随机/盲抽规则、官方图 |
| 物流与仓库 | 发货状态、清关状态、入仓状态、最后更新时间、异常原因、仓库备注 |
| 历史投诉 | 同一用户历史工单、对话摘要、已给出的承诺、补偿记录 |
| 材料 | 视频、图片、文件名、上传时间、素材来源、用户补充说明 |
| 人工标注 | 最终人工结论、理由、是否支持用户诉求、是否需要补件 |

## 5. 建议接口总览

真实联调时可以按甲方网关规范调整 path、鉴权和字段命名。

| 方向 | 方法 | 路径 | 用途 |
| --- | --- | --- | --- |
| 甲方 -> MITAKO | POST | `/openapi/v1/tickets/sync` | 同步客服工单与上下文 |
| 甲方 -> MITAKO | POST | `/openapi/v1/review-tasks` | 创建视觉审核任务 |
| 甲方 -> MITAKO | POST | `/openapi/v1/review-tasks/{taskId}/materials` | 上传或追加材料 |
| 甲方 -> MITAKO | GET | `/openapi/v1/review-tasks/{taskId}` | 查询审核进度和摘要 |
| 甲方 -> MITAKO | POST | `/openapi/v1/human-decisions` | 回写人工最终处理意见 |
| MITAKO -> 甲方 | POST | `{callbackBase}/mitako/review-result` | 审核完成回调 |
| MITAKO -> 甲方 | POST | `{callbackBase}/mitako/customer-service-event` | 转VIP客服、补件、升级等事件回调 |

## 6. 鉴权、签名与重试

建议所有写接口都使用：

```http
Authorization: Bearer <access_token>
X-Timestamp: 1783216400000
X-Nonce: 3a7d6a0b9f
X-Signature: HMAC-SHA256(method + path + timestamp + nonce + bodySha256, secret)
Idempotency-Key: ticketId-taskType-clientRequestId
Content-Type: application/json
```

重试规则：

- `429`、`502`、`503`、`504` 使用指数退避重试。
- `400`、`401`、`403`、`409` 不自动重试，进入联调排查。
- 所有写请求必须携带 `Idempotency-Key`，避免重复创建任务或重复回写。

## 7. 创建视觉审核任务示例

```json
{
  "tenantId": "mitako",
  "ticketId": "TK202607050001",
  "taskType": "UNBOXING_VIDEO",
  "priority": "HIGH",
  "customerClaim": "用户反馈收到 75mm，但订单购买规格为 90mm。",
  "order": {
    "orderNo": "PT_202606276662210",
    "paidAt": "2026-06-27T12:30:00+08:00",
    "items": [
      {
        "sku": "SKU-AG-90-PATIENT",
        "name": "角色徽章 病患款",
        "spec": "90mm",
        "quantity": 1
      }
    ]
  },
  "productMasterData": {
    "sku": "SKU-AG-90-PATIENT",
    "officialSpec": "90mm",
    "character": "病患",
    "style": "徽章",
    "blindBoxRule": "非盲抽，SKU 固定"
  },
  "materials": [
    {
      "materialId": "MAT-001",
      "type": "VIDEO",
      "fileName": "unboxing.mp4",
      "downloadUrl": "https://example.com/signed/unboxing.mp4",
      "uploadedAt": "2026-07-05T10:00:00+08:00"
    },
    {
      "materialId": "MAT-002",
      "type": "IMAGE",
      "fileName": "certificate.jpg",
      "downloadUrl": "https://example.com/signed/certificate.jpg"
    }
  ]
}
```

## 8. 审核结果回调示例

```json
{
  "tenantId": "mitako",
  "ticketId": "TK202607050001",
  "taskId": "RV202607050001",
  "taskType": "UNBOXING_VIDEO",
  "status": "REVIEW_COMPLETED",
  "suggestedDecision": "SUPPORT_CUSTOMER_CLAIM",
  "confidence": 0.93,
  "manualPolicy": "SPOT_CHECK",
  "summaryForAgent": "材料显示用户提供的实物合格证为 75mm，与订单 90mm 规格不一致；视频连续性较高，暂未发现明显调包风险。",
  "evidence": [
    {
      "type": "VIDEO_FRAME",
      "timecode": "00:42",
      "description": "画面出现商品合格证，尺寸字段可见为 75mm。"
    },
    {
      "type": "IMAGE",
      "materialId": "MAT-002",
      "description": "补充图片中的合格证尺寸与视频关键帧一致。"
    }
  ],
  "missingMaterials": [],
  "nextAction": "建议客服进入抽检确认后按售后流程处理。"
}
```

## 9. Java 对接示例

```java
WebClient client = WebClient.builder()
    .baseUrl("https://mitako-gateway.example.com")
    .defaultHeader("Content-Type", "application/json")
    .build();

Mono<String> result = client.post()
    .uri("/openapi/v1/review-tasks")
    .header("Authorization", "Bearer " + accessToken)
    .header("X-Timestamp", timestamp)
    .header("X-Nonce", nonce)
    .header("X-Signature", signature)
    .header("Idempotency-Key", idempotencyKey)
    .bodyValue(payload)
    .retrieve()
    .bodyToMono(String.class);
```

## 10. 状态机

| 状态 | 含义 | 下一步 |
| --- | --- | --- |
| `CREATED` | 任务已创建 | 等待材料或进入队列 |
| `MATERIAL_READY` | 材料已齐 | 开始审核 |
| `AI_REVIEWING` | 正在生成证据摘要 | 等待结果 |
| `NEED_MORE_MATERIAL` | 材料不足 | 通知客服补件 |
| `REVIEW_COMPLETED` | 审核摘要完成 | 进入人工复核或抽检 |
| `HUMAN_CONFIRMED` | 人工已确认 | 回写甲方工单 |
| `CLOSED` | 任务关闭 | 归档 |
| `FAILED_RETRYABLE` | 临时失败 | 自动重试 |
| `FAILED_FINAL` | 不可恢复失败 | 人工处理 |

## 11. 上线验收口径

- 甲方可在 Java 测试环境创建工单和视觉审核任务。
- 工单、订单、SKU、物流、历史投诉、材料能形成同一证据包。
- 审核结果能回写甲方工单系统，并可被VIP客服查看。
- 客服 Agent 对用户只表达服务进展、补件建议和人工确认后的结论，不暴露内部模型、渠道、调试日志或底层字段。
- 高置信结果只建议抽检，低置信或材料不足必须人工逐条复核。

## 12. 甲方上线前确认表

| 角色 | 需要确认 |
| --- | --- |
| 客服负责人 | 三类审核的人工通过、拒绝、补件标准 |
| Java 开发负责人 | 接口字段、鉴权、回调、重试、幂等 |
| 商品负责人 | SKU、规格、角色、款式、盲抽规则字段 |
| 仓库负责人 | 出库记录、缺件、错发、破损协同流程 |
| 合规负责人 | 未成年人资料、隐私字段、材料保留周期 |
| 项目负责人 | 灰度范围、回滚方式、上线节奏 |
