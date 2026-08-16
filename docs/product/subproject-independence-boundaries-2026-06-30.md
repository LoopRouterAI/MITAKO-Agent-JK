# 子项目独立性边界

当前仓库是模块化单体，不是多个强独立仓库。主 FastAPI 进程承载客服 Agent、VIP客服工作台、运营后台和业务适配层；视觉审核工作台作为独立 POC 服务运行。

## 当前边界

| 子系统 | 独立性 | 当前入口 | 数据边界 | 说明 |
| --- | --- | --- | --- | --- |
| 客服 Agent 主链路 | 中 | `/`、`/api/v1/chat/stream` | `handoff.db`、业务 fixture/适配层 | 负责安抚、解释、SOP 分流、转VIP客服 |
| VIP客服工作台 | 中 | `/desk`、`/api/v1/handoff/*` | `handoff.db` | 负责队列、接单、回复、工单协作 |
| 运营后台 | 中 | `/admin`、`/api/v1/admin/*` | `admin.db`、`auth.db` | 负责配置、审批、报表、观测 |
| 视觉审核工作台 | 高 | `poc/visual_review_poc/`、`7861` | POC 临时目录/报告 | 三大审核场景独立入口，后续通过接口写回工单 |
| 甲方联调实验室 | 高 | `tools/partner_lab/` | 本地模拟服务 | 模拟 Java 后台、OIDC、IM 和业务回调 |

旧版 Companion、陪伴、文字冒险、角色扮演代码已经封存到 `archive/companion_roleplay_mode_20260705/`，不再作为当前子系统、路由、接口或验收范围。

## 解耦目标

1. 视觉审核工作台通过 `review_task_id` 与客服工单关联，不直接持有甲方业务主键的最终裁决权。
2. 客服 Agent 只生成建议、补件要求、工单摘要和转VIP客服动作，不自动退款、拒赔、补发或资料终审。
3. 甲方 Java 后台通过 REST/JSON、OIDC/JWT、HMAC 回调和幂等键对接。
4. 对外文档只描述接口契约和业务流程，不暴露模型供应商、内部 prompt、密钥、调试日志或成本明细。

## 后续拆分建议

当进入真实生产联调后，可以把视觉审核任务服务拆为独立服务：`review-api`、`review-worker`、`review-report` 三层；主客服系统只保留工单同步、报告引用和人工复核入口。
