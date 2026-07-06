# POC 报告索引

本目录是 POC 发布审查索引，避免研发接手时在多个目录里找最终报告。

## 当前报告位置

- 客服 Agent 验收报告：`tests/reports/cs_agent_acceptance_*.md`
- 全量 E2E 报告：`tests/reports/full_pipeline_*.html`、`tests/reports/admin_ops_*.html`、`tests/reports/enterprise_*.html`
- 视觉审核工作台 smoke：`tests/reports/visual_workbench_smoke_*.md`
- 视觉审核真实/轻量报告：`poc/visual_review_poc/reports/local_video_triage_e2e_*.html`

## 发布边界

- 甲方可看：视觉审核工作台公开摘要页、甲方沟通交付文档。
- 我方研发内用：完整 JSON、内部模型对比报告、Token/端点/成本信息。
- `scenario=all` 只用于 CLI 批量回归，工作台接口一次只允许一个业务队列。
