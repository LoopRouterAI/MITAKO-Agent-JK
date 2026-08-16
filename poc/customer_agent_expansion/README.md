# 甲方新增需求综合 POC

本目录用于验证三类优先审核场景、私域线索整理和客服 Agent 主链路能否形成一个可交付闭环。旧版 Companion、陪伴、角色扮演能力已经封存到 `../../archive/companion_roleplay_mode_20260705/`，不再作为当前 POC、演示或交付范围。

## 验证目标

1. 视觉审核：消费 `poc/visual_review_poc/` 的结构化输出，证明开箱视频、商品有伤、未成年人资料审核可以进入售后证据链。
2. 私域 Agent：把群消息整理成用户标签、购买意向、负面情绪预警和人工跟进清单。
3. 客服 Agent：复用 `run_business_flow` 验证 SOP 分流、业务卡片、任务中心、越权动作阻断、审计事件和人工复核准备态。
4. 服务人格：保留“专业、同理、有边界”的客服表达能力，只用于解释、安抚、补件和转VIP客服，不做陪伴、恋爱或角色扮演。

## 运行方式

```powershell
.\venv\Scripts\python.exe .\poc\customer_agent_expansion\demo.py
```

或双击：

```text
poc\customer_agent_expansion\一键运行POC-Windows.bat
```

## 通过标准

- JSON 报告包含 `video_review`、`private_domain_agent`、`customer_service_agent`、`service_personality`、`acceptance` 五段。
- 视觉审核链路能区分通过、疑似、失败、补充材料和人工复核建议。
- 私域链路输出用户标签、推荐候选、待人工跟进和每日摘要。
- 客服链路证明商品有伤、物流异常、退款、未成年人退款等分支不会自动执行高风险动作。
- 服务人格只输出专业客服价值，不承诺退款、拒赔、视频定责或真实业务操作。

## 边界

- 真实甲方后台、客户系统、仓库、财务、企微和视觉模型在本目录中只通过 fixture/本地契约验证。
- 少量样例只能证明流程结构，不证明生产准确率；准确率需要甲方提供正负样本后盲测。
- 私域 Agent 当前只做线索整理和触达草案，不自动群发、不自动写入企微。
- 高风险动作只生成待人工确认任务，不自动退款、补发、拒赔、改绑或封禁。
