# Java / Spring Boot 接入样例

版本：2026-07-23
推荐：Spring Boot 3、WebClient、Jackson。

Java 系统只调用 FastAPI 主服务。内部视觉服务、模型凭证和数据库不对 Java 网关暴露。

## 1. WebClient

```java
@Configuration
public class MitakoConfig {
  @Bean
  WebClient mitakoWebClient(WebClient.Builder builder,
                            @Value("${mitako.base-url}") String baseUrl) {
    return builder.baseUrl(baseUrl).build();
  }
}
```

## 2. 登录并获取集成 Token

```java
public Mono<String> login(WebClient client, String username, String password) {
  return client.post()
      .uri("/api/v1/auth/login")
      .contentType(MediaType.APPLICATION_JSON)
      .bodyValue(Map.of(
          "username", username,
          "password", password,
          "tenant_id", "mitako"))
      .retrieve()
      .bodyToMono(JsonNode.class)
      .map(body -> body.path("token").asText());
}
```

## 3. 上传前校验 metadata

```java
public Mono<JsonNode> validateMetadata(WebClient client, String token, Map<String, Object> metadata) {
  return client.post()
      .uri("/api/v1/review/metadata/validate")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
      .contentType(MediaType.APPLICATION_JSON)
      .bodyValue(metadata)
      .retrieve()
      .bodyToMono(JsonNode.class);
}
```

最小 metadata：

```json
{
  "client_case_id": "CASE-20260711-001",
  "scenario": "wrong_item",
  "batch_id": "BATCH-20260711-001",
  "customer_claim": "用户称收到的角色与订单不一致",
  "order_items": [{"sku": "SKU-001", "product_name": "角色拍立得", "specification": "A款", "quantity": 1}],
  "fulfillment_baseline": {
    "baseline_version": "ORDER-001@2026-07-22T10:00:00+08:00",
    "expected_items": [{
      "item_ref": "LINE-1",
      "sku": "SKU-001",
      "product_name": "角色拍立得",
      "specification": "A款",
      "expected_quantity": 1,
      "master_image_urls": ["https://approved-cdn.example/products/SKU-001.png"]
    }],
    "expected_package_count": 1,
    "packages": [{"package_ref": "PKG-1", "tracking_no": "SF000001", "expected_item_refs": ["LINE-1"]}],
    "selection_rules_complete": true
  },
  "evidence_coverage": {"submitted_package_refs": ["PKG-1"], "submitted_tracking_nos": ["SF000001"]},
  "product_master_data": {"LINE-1": {"sku": "SKU-001", "product_name": "角色拍立得", "specification": "A款"}},
  "sampling_policy": {"preset": "strict", "frames_per_model_call": 24},
  "continuity_policy": {"out_of_frame_warning_seconds": 3.0, "force_dense_scan": true},
  "output_options": {"include_html_report": false},
  "review_routing_policy": {
    "required_below_confidence": 0.5,
    "optional_below_confidence": 0.8,
    "out_of_frame_resubmit_seconds": 3.0
  }
}
```

`master_image_urls` 是官方商品基准图，不是用户证据。服务只读取当前案件 `expected_items` 引用的有限图片，去重、校验并缓存后以内联图片发送给模型；不会下载整个商品库。无法读取时任务继续使用 SKU/名称/规格/数量文字基线，报告明确显示降级状态。

不要仅凭一个物流单号自行生成 `packages[].expected_item_refs`。只有甲方订单/仓储接口明确提供分包与商品映射时才填写；否则留空并让漏发货审核保持 `degraded_review`。

漏发货案件不能只传订单号。以下字段是自动形成确定结论的最低结构；任一缺失时服务仍可审核视频连续性，但最终强制返回 `review`：

```json
{
  "client_case_id": "CASE-MISSING-001",
  "scenario": "missing_item",
  "customer_claim": "用户称少发一个徽章和一份特典",
  "fulfillment_baseline": {
    "baseline_version": "ORDER-001@2026-07-16T10:00:00+08:00",
    "expected_items": [
      {"item_ref": "LINE-1", "sku": "SKU-001", "product_name": "徽章", "expected_quantity": 2},
      {"item_ref": "BONUS-1", "sku": "BONUS-001", "product_name": "活动特典", "expected_quantity": 1, "item_type": "bonus"}
    ],
    "expected_package_count": 1,
    "packages": [{"package_ref": "PKG-1", "tracking_no": "SF000001", "expected_item_refs": ["LINE-1", "BONUS-1"]}],
    "benefit_rules": [{"rule_id": "PROMO-1", "description": "满额赠活动特典一份"}],
    "benefit_rules_complete": true,
    "selection_rules_complete": true
  },
  "evidence_coverage": {
    "submitted_package_refs": ["PKG-1"],
    "submitted_tracking_nos": ["SF000001"],
    "all_packages_uploaded": true,
    "all_items_displayed": true
  },
  "logistics": {
    "source": "customer_logistics_system",
    "snapshot_at": "2026-07-23T10:00:00+08:00",
    "all_packages_delivered": true,
    "packages": [{"package_ref": "PKG-1", "tracking_ref": "masked-or-internal-ref", "shipment_status": "delivered"}]
  }
}
```

## 4. 采样规划

```java
public Mono<JsonNode> samplingPlan(WebClient client, String token) {
  return client.post()
      .uri("/api/v1/review/sampling-plan")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
      .contentType(MediaType.APPLICATION_JSON)
      .bodyValue(Map.of(
          "duration_seconds", 452.5,
          "source_bytes", 543351335,
          "video_count", 1,
          "scenario", "product_damage",
          "sampling_policy", Map.of("preset", "strict", "frames_per_model_call", 24),
          "continuity_policy", Map.of("out_of_frame_warning_seconds", 3.0, "force_dense_scan", true),
          "damage_causality_policy", Map.of("force_action_scan", true, "dedicated_chunk_frames", 20)))
      .retrieve()
      .bodyToMono(JsonNode.class);
}
```

采样规划返回 `estimated_channel_calls.main_review/object_continuity/damage_causality` 和 `estimated_total_model_calls`。Java 侧应使用总调用数做容量与成本预估，不要只读取旧字段 `estimated_model_segments`。

`adaptive` 默认只执行主审核；`strong/strict/forensic` 会自动启用连续性专项，商品有伤还会自动启用损伤因果专项。采样与连续性参数可以在契约范围内进一步收紧，但不能关闭强度档位要求的专项保护。自动分类的 `decision_policy` 不接受调用方自定义门槛：请求只能选择服务端已批准的 `policy_ref`，未批准版本保持人工复核。

## 5. 多文件案件提交

```java
public Mono<JsonNode> createReviewJob(
    WebClient client,
    ObjectMapper mapper,
    String token,
    String idempotencyKey,
    Map<String, Object> metadata,
    List<Path> files) throws JsonProcessingException {

  MultipartBodyBuilder body = new MultipartBodyBuilder();
  body.part("metadata", mapper.writeValueAsString(metadata));
  for (Path file : files) {
    body.asyncPart("files", DataBufferUtils.read(
            new FileSystemResource(file),
            new DefaultDataBufferFactory(),
            256 * 1024), DataBuffer.class)
        .filename(file.getFileName().toString())
        .contentType(MediaType.APPLICATION_OCTET_STREAM);
  }

  return client.post()
      .uri("/api/v1/review/jobs")
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
      .header("Idempotency-Key", idempotencyKey)
      .contentType(MediaType.MULTIPART_FORM_DATA)
      .body(BodyInserters.fromMultipartData(body.build()))
      .retrieve()
      .bodyToMono(JsonNode.class);
}
```

注意：使用流式 `Resource`/`DataBuffer`，不要 `Files.readAllBytes()` 读取 543MB 视频。

如案件有甲方离线订单快照，可把 `order_info_snapshot.json` 作为同一 multipart 的一个 `files` 项上传。服务会合并重复 SKU 数量，只提取本单 SKU、名称、规格、应发数量、物流引用、与本单相关的抽赏规则和商品主图，不把 `user`、`user_address`、价格、`all_goods` 整表或人工标签送入模型。快照只有物流单号但没有分包-SKU 映射时，系统不会猜测包裹内容。生产正式接入时，优先在 `metadata.order_items`、`metadata.fulfillment_baseline` 和 `metadata.product_master_data` 传递同等结构化数据；离线快照只用于本轮评测和联调。

## 6. 查询任务

```java
public Mono<JsonNode> getJob(WebClient client, String token, String jobId) {
  return client.get()
      .uri("/api/v1/review/jobs/{jobId}", jobId)
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
      .retrieve()
      .bodyToMono(JsonNode.class);
}
```

轮询终态：`SUCCEEDED` 或 `FAILED`。建议从 2 秒开始退避，单次查询超时 10 秒。

新接入优先读取 `job.result.review.advisory_assessment`：

- `assessment.conclusion/confidence/calibration_status`：事实结论、证据分数和未校准口径。
- `human_review.level`：`required`、`optional`、`not_required`。
- `workflow_recommendation`：`human_review`、`request_more_material`、`continue_by_customer_policy`。
- `signals[]`：离框、证据冲突、材料缺口和媒体取证信号。
- `policy.business_action_allowed`：恒为 `false`。

当 `output_options.include_html_report=false` 时，`review.report.status=not_requested` 且 `html_url=null`；不要继续请求报告路由。完整说明见 [审核建议结果 API 使用说明](./review-advisory-api.md)。

## 7. 查询批次

```java
public Mono<JsonNode> getBatch(WebClient client, String token, String batchId, int offset) {
  return client.get()
      .uri(builder -> builder
          .path("/api/v1/review/batches/{batchId}")
          .queryParam("limit", 100)
          .queryParam("offset", offset)
          .build(batchId))
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
      .retrieve()
      .bodyToMono(JsonNode.class);
}
```

`summary.total/statuses/inference_total_tokens/inference_estimated_usd` 是全批次聚合，不受当前明细分页影响。

## 8. 重试

```java
public Mono<JsonNode> retryJob(WebClient client, String token, String jobId) {
  return client.post()
      .uri("/api/v1/review/jobs/{jobId}/retry", jobId)
      .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
      .retrieve()
      .bodyToMono(JsonNode.class);
}
```

## 9. 错误处理

| HTTP | 处理 |
|---:|---|
| 401/403 | 刷新凭证或检查角色/租户，不自动无限重试 |
| 409 | 幂等键与请求内容冲突，停止并报警 |
| 409 `review_report_not_requested` | 当前任务选择了 JSON-only，不应再次请求 HTML |
| 413 | 文件/案件过大，改走对象存储转码方案 |
| 415 | 文件类型、扩展名、MIME 或内容无效 |
| 422 | metadata 或标签隔离校验失败 |
| 429/502/503/504 | 保持相同幂等键，指数退避 |

## 10. 安全要求

- Token、密码和服务凭证不写日志。
- Java 只保存公开任务结果，不保存内部模型响应。
- 未成年人材料和面单按甲方保留周期加密、脱敏和删除。
- 不把人工标准答案或评测标签传入 `/review/jobs`。
- 业务动作必须由人工或甲方系统确认。

## 11. 多源客诉证据接入

生产环境不要让坐席手工拼接订单和物流。Java 适配层应在客诉创建时调用甲方内部服务，冻结同一时点的订单、商品、包裹物流和当前工单对话，再生成 `ReviewCaseMetadata`。

`logistics` 推荐结构：

```json
{
  "source": "customer_logistics_system",
  "snapshot_at": "2026-07-23T10:00:00+08:00",
  "all_packages_delivered": true,
  "packages": [{
    "package_ref": "PKG-1",
    "tracking_ref": "internal-or-masked-ref",
    "carrier": "SF",
    "shipment_status": "delivered",
    "events": [{"status": "delivered", "occurred_at": "2026-07-22T16:20:00+08:00"}]
  }]
}
```

`customer_risk_context` 只允许传近 N 天售后次数、同场景次数、甲方已有风险等级和原因码。不要传历史对话或用户隐私原文；服务端不会把该字段送给模型。

完整场景字段和联调步骤见 [客诉审核 Agent 与沟通 Agent 接口联调指南](./after-sales-agent-integration.md)。
