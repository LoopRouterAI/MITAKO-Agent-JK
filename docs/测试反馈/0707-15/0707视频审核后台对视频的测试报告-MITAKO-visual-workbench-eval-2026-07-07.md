# MITAKO 视觉审核工作台真实样本测试反馈

测试时间：2026-07-07
测试入口：https://agent.deeptokenai.cn/visual
样本来源：`/Volumes/馒头/0 Mitako二批样本/help_ticket_resources/help_ticket_resources`
测试目标：从专门的视频/图片审核工作台上传真实用户售后素材，查看视觉 Agent 评估结果，并与人工客服处理结果比对。

## 一、总体结论

视觉审核工作台已经比用户端聊天入口更进一步：它支持“工单文件夹”模式，可以把同一工单下的视频、图片、`content.txt`、`manifest.json`、`reply.json` 一起提交，并能生成 HTML 报告。

但本轮真实样本测试中，视觉 Agent 没有产出有效审核结论：

- 去重后测试 17 个真实案例。
- 接口全部返回 `ok: false`。
- 每个案例的 `successful_reviews` 都是 `0`。
- `predicted_label` 全部为 `null`。
- `confidence` 全部为 `null`。
- Agent 结论全部为：“证据不足，需要人工复核，置信度 None。”

因此，严格口径下，本轮有效视觉审核成功率为 **0/17，0.0%**。

若只按“最终标签是否碰巧和人工一致”做宽松统计，则有 **4/17，23.5%**。但这 4 条都是人工本来就要求补证，而 Agent 对所有案例都统一输出“证据不足”，所以不能说明 Agent 真的看懂了视频/图片。

## 二、测试方式

本次没有使用用户端聊天入口，而是使用 `/visual` 工作台。

提交方式：

- 选择“工单文件夹”模式。
- 按业务类型选择：
  - 商品有伤：`product_damage`
  - 发错货 / 漏发货：`video_unboxing`
- 每个案例上传同一工单目录中的：
  - 视频：mp4/mov 等
  - 图片：jpg/png/webp 等
  - 文本：`content.txt`
  - 结构化信息：`manifest.json`
  - 人工客服记录：`reply.json`

说明：

- 工作台“工单文件夹”模式要求目录中至少包含一个视频。
- 纯图片案例无法通过该模式提交，本轮未纳入最终统计。
- 页面上的内置样本按钮调用 `/api/review-sample` 时返回“样本不存在”，因此本轮只使用硬盘真实样本。

## 三、样本分布

去重后共 17 个案例：

| 类型 | 样本数 | 一致数 | 宽松一致率 |
| --- | ---: | ---: | ---: |
| 商品有伤 | 7 | 0 | 0.0% |
| 发错货 | 5 | 2 | 40.0% |
| 漏发货 | 5 | 2 | 40.0% |
| 合计 | 17 | 4 | 23.5% |

人工标签分布：

| 人工标签 | 含义 | 数量 |
| --- | --- | ---: |
| `accepted_solution` | 人工认可问题并进入售后/补偿/换货等方案 | 4 |
| `need_more_evidence` | 人工要求补充视频、时间点、面单、特写等证据 | 4 |
| `mismatch_or_reject` | 人工判断素材/订单/商品不匹配，或不支持用户诉求 | 6 |
| `manual_review` | 人工泛化处理或继续复核，无明确视觉结论 | 3 |

视觉 Agent 标签分布：

| 视觉 Agent 标签 | 数量 |
| --- | ---: |
| `need_more_evidence` | 17 |
| 其他标签 | 0 |

## 四、核心问题

### V1 工作台能接收素材，但没有完成有效视觉审核

每个案例的返回结构均类似：

```json
{
  "ok": false,
  "summary": {
    "cases": 1,
    "total_reviews": 1,
    "successful_reviews": 0,
    "predicted_label": null,
    "confidence": null,
    "needs_human_review": true
  },
  "agent_brief": {
    "conclusion": "证据不足，需要人工复核，置信度 None。",
    "confidence": null,
    "system_yes_no": null,
    "next_step": "请人工客服结合订单、售后规则和原始素材处理。"
  }
}
```

影响：

- 无法判断视频/图片是否真实。
- 无法判断素材是否与用户反馈一致。
- 无法判断发错货、漏发货、商品有伤是否成立。
- 无法和人工结论做真正准确率评测。

### V2 所有案例都输出同一类兜底结论

本轮 17 个案例中，人工结果包含：

- 人工已认可并给方案。
- 人工要求补证。
- 人工判断不匹配或拒绝方向。
- 人工泛化复核。

但视觉 Agent 全部输出“证据不足，需要人工复核”。

这说明当前结果更像异常兜底，而不是视觉审核判断。

### V3 宽松一致的 4 条不能代表能力命中

4 条宽松一致样本都是：

- 人工标签：`need_more_evidence`
- Agent 标签：`need_more_evidence`

但 Agent 对所有案例都输出这个标签，所以这只是“统一兜底碰巧命中”，不是模型识别出了证据缺口。

### V4 商品有伤场景与人工结果完全不一致

商品有伤 7 条样本：

- 人工认可并给方案：3 条
- 人工不匹配/拒绝方向：3 条
- 人工泛化复核：1 条

视觉 Agent 结果：

- 全部输出 `need_more_evidence`
- 一致率 0%

典型问题：

- 人工已生成售后方案的样本，Agent 仍说证据不足。
- 人工判断不匹配/不支持的样本，Agent 也只说证据不足，没有识别不匹配风险。

### V5 发错货/漏发货没有识别“不匹配/发错/漏发”结论

发错货、漏发货样本中，有多条人工判断为不匹配或不支持用户诉求。

视觉 Agent 没有输出：

- 商品不一致。
- 发错货成立。
- 漏发货成立。
- 订单/素材不匹配。
- 需拒绝或升级复核。

全部仍回到“证据不足/人工复核”。

### V6 纯图片案例无法通过当前文件夹模式评估

工作台的“工单文件夹”模式要求至少一个视频，否则前端会提示“文件夹里没有可审核的视频”。

但真实售后中很多商品有伤、折痕、污渍、错发实物对比都可能只有图片。

影响：

- 商品有伤图片审核能力无法完整覆盖。
- 当前“商品有伤审核”入口名称包含照片可信度，但实际文件夹模式仍依赖视频。

## 五、样本结果明细

| 案例 ID | 类型 | 人工结论 | Agent 结论 | 是否一致 | 报告 |
| --- | --- | --- | --- | --- | --- |
| 580813 | 商品有伤 | accepted_solution | need_more_evidence | 否 | `/reports/agent_folder_1783398274_2.html` |
| 587301 | 商品有伤 | mismatch_or_reject | need_more_evidence | 否 | `/reports/agent_folder_1783398548_10.html` |
| 583203 | 商品有伤 | manual_review | need_more_evidence | 否 | `/reports/agent_folder_1783398325_4.html` |
| 580718 | 商品有伤 | mismatch_or_reject | need_more_evidence | 否 | `/reports/agent_folder_1783398386_5.html` |
| 600501 | 商品有伤 | accepted_solution | need_more_evidence | 否 | `/reports/agent_folder_1783398519_8.html` |
| 581251 | 商品有伤 | accepted_solution | need_more_evidence | 否 | `/reports/agent_folder_1783398530_9.html` |
| 596044 | 商品有伤 | mismatch_or_reject | need_more_evidence | 否 | `/reports/agent_folder_1783398554_11.html` |
| 102678 | 发错货 | accepted_solution | need_more_evidence | 否 | `/reports/agent_folder_1783398426_6.html` |
| 312770 | 发错货 | need_more_evidence | need_more_evidence | 是* | `/reports/agent_folder_1783398556_12.html` |
| 310581 | 发错货 | need_more_evidence | need_more_evidence | 是* | `/reports/agent_folder_1783398561_13.html` |
| 510463 | 发错货 | mismatch_or_reject | need_more_evidence | 否 | `/reports/agent_folder_1783398573_14.html` |
| 73702 | 发错货 | manual_review | need_more_evidence | 否 | `/reports/agent_folder_1783398580_15.html` |
| 308963 | 漏发货 | mismatch_or_reject | need_more_evidence | 否 | `/reports/agent_folder_1783398444_7.html` |
| 312468 | 漏发货 | need_more_evidence | need_more_evidence | 是* | `/reports/agent_folder_1783398583_16.html` |
| 310773 | 漏发货 | need_more_evidence | need_more_evidence | 是* | `/reports/agent_folder_1783398585_17.html` |
| 514188 | 漏发货 | mismatch_or_reject | need_more_evidence | 否 | `/reports/agent_folder_1783398590_18.html` |
| 289067 | 漏发货 | manual_review | need_more_evidence | 否 | `/reports/agent_folder_1783398608_19.html` |

带 `*` 的一致仅为宽松一致：Agent 没有产出有效视觉判断，只是统一兜底到“证据不足/人工复核”。

完整结果文件：

- `/Users/lizhijing/Documents/Codex/2026-07-06/xi/outputs/mitako_media_regression/visual_case_pool.json`
- `/Users/lizhijing/Documents/Codex/2026-07-06/xi/outputs/mitako_media_regression/visual_agent_results.json`
- `/Users/lizhijing/Documents/Codex/2026-07-06/xi/outputs/mitako_media_regression/visual_agent_results_pool.json`

## 六、给产研的建议

### P0：先排查为什么 `successful_reviews` 全部为 0

这是当前最关键问题。需要确认：

- 视频抽帧是否成功。
- 抽帧图片是否真的送入多模态模型。
- 多模态模型是否返回结构化结果。
- 后端是否因解析异常、超时、模型错误而统一兜底。
- 报告中的“模型没有给出可采信证据”对应的真实异常日志是什么。

### P0：报告需要暴露失败原因

当前报告只显示“证据不足，需要人工复核，置信度 None”，但没有说明：

- 是没有抽到帧？
- 是模型调用失败？
- 是模型看了但不采信？
- 是 schema 解析失败？
- 是文件格式/大小/帧数问题？

建议在报告中增加：

- 抽帧状态。
- 送审帧数量。
- 模型调用状态。
- 结构化解析状态。
- 失败原因。

### P1：不要把系统失败包装成业务判断

如果模型调用失败，应显示“审核失败/未完成”，而不是“证据不足”。

否则产研和业务方会误以为 Agent 已经审核并判断证据不足。

建议区分：

- `review_failed`：系统或模型未完成审核。
- `insufficient_evidence`：模型完成审核后认为证据不足。
- `mismatch_detected`：发现商品/订单/素材不一致。
- `issue_supported`：素材支持用户问题。

### P1：支持纯图片商品有伤审核

当前文件夹模式要求视频，这会挡住大量真实商品有伤场景。

建议：

- 商品有伤入口允许纯图片提交。
- 若无开箱视频，再由 Agent 判断“图片可见问题”和“缺少开箱视频风险”，而不是直接拒绝进入审核。

### P1：输出结构化视觉结论

建议每个案例至少输出：

```json
{
  "review_status": "completed|failed",
  "authenticity": "high|medium|low|unknown",
  "issue_consistency": "match|partial|mismatch|unknown",
  "evidence_sufficiency": "sufficient|insufficient|unknown",
  "detected_issue": "damage|wrong_item|missing_item|none|unknown",
  "recommended_action": "approve_after_sales|request_more_evidence|reject_or_escalate|manual_review",
  "confidence": 0.0
}
```

## 七、阶段性结论

`/visual` 工作台已经具备真实素材上传和报告生成的雏形，但当前真实样本下没有完成有效视觉审核。现阶段不建议对外宣称“视觉 Agent 已能判断图片/视频是否真实、是否与用户反馈一致”。

更准确的状态是：

“视觉审核工作台可以接收工单素材并生成复核报告页面，但模型审核结果目前全部走证据不足/人工复核兜底，尚不能形成可用于准确率验收的视觉判定。”
