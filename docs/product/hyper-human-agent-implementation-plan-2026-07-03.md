# 超拟人客服 Agent 落地执行计划

## 执行目标

把“带人格与 MBTI 的客服 Agent”从需求和说明推进到可验收系统。落地结果必须能证明：客户侧热情、理解用户且不暴露内部实现；坐席侧可观测、可调试；研发侧可评估、可扩展；甲方 SOP 与视频审核、商品有伤、未成年人资料审核三类重点需求有清晰处理链路和人工确认边界。

## 阶段计划

| 阶段 | 要做的事 | 退出条件 |
| --- | --- | --- |
| P0 安全底线 | 客户回复清洗、SSE 公开化、转VIP客服敏感信息脱敏、旧称呼清理。 | `run_mock_business_guard_e2e.py` 通过；生产源代码无旧称呼和已知错误话术。 |
| P1 SOP 与审核闭环 | SOP 分支、`review_design`、`evaluation_tags`、材料 checklist、视频连续性审核、人工确认动作。 | 评估矩阵覆盖履约慢、退款、商品有伤、视频审核、未成年人资料审核。 |
| P2 可观测调试 | `?dev=1` 面板接收公开化 `api_log`、`unified_analysis` 和节点时间序列。 | SSE 脱敏测试通过，前端构建通过。 |
| P3 扩展与交付 | 新 SOP 按关键词、review 设计、checklist、测试矩阵四处同步；真实接口只在甲方提供物料后联调。 | 每次交付前运行客服 Agent 验收门禁并保留报告。 |

## 必跑门禁

Windows：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_cs_agent_acceptance.ps1
```

或双击：

```text
scripts\客服Agent验收-Windows.bat
```

门禁会执行：

- Python 编译检查：`agent.py`、`business_readiness_service.py`、`main.py`、客服业务 E2E。
- 客服业务 E2E：人格、SOP、三大审核、SSE 公开观测、客户脱敏、人工转接。
- 前端构建：`npm run build`。
- 生产源代码敏感词扫描：旧称呼、错误首句、服务档位等客户可见风险。
- 报告输出：`tests/reports/cs_agent_acceptance_*.md`。

## 失败处理规则

任何门禁失败都不能包装成交付完成。先修失败项，再重跑同一个门禁；只要失败可复现，就以测试结果为准，不以文档描述为准。

## 真实甲方对接边界

真实退款、补发、改绑、客户后台、客服后台、图片/视频样本集准确率评测，必须等待甲方接口、权限、样本和负责人确认。本项目当前提供 POC 级本地业务就绪、审核初筛、人工确认和交付门禁，不能伪装成已经完成真实甲方业务改造。
