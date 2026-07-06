# Java / Spring Boot 接入样例

本样例给甲方 Java 技术栈和我方正式开发参考。POC 当前使用 Mock 业务接口，正式接入时应由甲方登录态或小程序态换取客户会话令牌。

```java
@Service
public class MitakoClient {
  private final WebClient webClient;

  public MitakoClient(WebClient.Builder builder) {
    this.webClient = builder.baseUrl("http://127.0.0.1:8000").build();
  }

  public Mono<String> issueCustomerToken(String userId, String sessionId) {
    return webClient.post()
        .uri("/api/v1/auth/customer-session")
        .contentType(MediaType.APPLICATION_JSON)
        .bodyValue(Map.of("user_id", userId, "session_id", sessionId, "tenant_id", "mitako"))
        .retrieve()
        .bodyToMono(JsonNode.class)
        .map(node -> node.get("token").asText());
  }

  public Flux<String> chatSse(String token, Map<String, Object> request) {
    return webClient.post()
        .uri("/api/v1/chat")
        .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
        .contentType(MediaType.APPLICATION_JSON)
        .accept(MediaType.TEXT_EVENT_STREAM)
        .bodyValue(request)
        .retrieve()
        .bodyToFlux(String.class)
        .retryWhen(Retry.backoff(2, Duration.ofMillis(500)).filter(this::isSoftError));
  }

  private boolean isSoftError(Throwable ex) {
    return ex instanceof WebClientResponseException.TooManyRequests
        || ex instanceof WebClientResponseException.ServiceUnavailable
        || ex instanceof TimeoutException;
  }
}
```

关键要求：

- 所有写接口带 `Idempotency-Key`，避免重试导致重复工单或重复补偿。
- 甲方订单、物流、仓库、清关、投诉记录接口只在正式联调后接入；POC 中不得伪装为真实生产数据。
- 视觉审核报告返回给客服的是公开脱敏摘要，内部模型名、供应商、原始响应、Prompt、成本不对甲方普通客服展示。
