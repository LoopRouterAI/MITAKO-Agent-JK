# Java / Spring Boot 接入样例

版本：2026-07-11
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
  "order_items": [{"sku": "SKU-001", "quantity": 1}],
  "sampling_policy": {"preset": "strict", "frames_per_model_call": 24}
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
          "sampling_policy", Map.of("preset", "strict", "frames_per_model_call", 24)))
      .retrieve()
      .bodyToMono(JsonNode.class);
}
```

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
