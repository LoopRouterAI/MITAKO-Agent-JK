# Implementation Plan: 0714 甲方反馈闭环整改

**Branch**: `002-customer-feedback-0714-closure` | **Date**: 2026-07-14 | **Spec**: [spec.md](./spec.md)

## Summary

在保留现有 React + FastAPI + SQLite + 视觉审核 POC 的前提下，建立统一业务案例和响应编排规则，优先修复跨用户/订单污染、业务意图错配、审核结果未回写、虚假转人工和坐席简报问题，再补齐审核服务稳定性、运维可观察性、演示边界和发布包验收。

## Technical Context

**Language/Version**: Python 3.x、JavaScript/React 18、HTML/CSS/JavaScript

**Primary Dependencies**: FastAPI、SQLite、LangGraph、React、Vite、现有视觉审核 POC

**Storage**: 现有业务 Mock JSON、SQLite 会话/后台数据库、视觉审核任务与报告目录

**Testing**: Python 专项回归、API smoke、视觉工作台 smoke、npm build、浏览器桌面与移动端回归、发布包解压后验收

**Target Platform**: Windows 11 内部研发与演示；兼容甲方 Linux 私有化部署

**Project Type**: 用户客服 Web + 坐席台 + 运营后台 + 标准审核 API + 视觉审核工作台

**Performance Goals**: 旧异步响应不得污染新用户；用户轮次最多一张卡；审核任务异步可追踪；批任务部分失败可隔离

**Constraints**: 不更改用户已配置模型名和接口名；不暴露 Key/Prompt；真实甲方接口只提供 Mock 与契约；不恢复旧陪伴能力

**Scale/Scope**: 0714 全部反馈、三类视觉样本、未成年人退款、发布包和内部开发文档

## Constitution Check

- SOP 优先：PASS。所有用户可见状态必须来源于持久化事实。
- 情绪与业务准确：PASS。L4 建议人工但继续给实质方案，L5/法律/明确请求才强制转接。
- 移动端与无障碍：PASS。一轮一个主卡降低刷屏。
- 模块化：PASS。编排、案例和审核状态使用独立函数/服务，避免继续扩大上帝文件。
- 品牌与安全：PASS。不新增模型、Key、Prompt 暴露。

## Project Structure

```text
agent.py                              # 意图、订单焦点、转接规则
business_readiness_service.py        # SOP 分支与业务动作
main.py                               # SSE 编排、审核与案例 API
handoff_service.py                    # 人工简报与接手首句
ops_service.py                        # 风险明细
src/hooks/useChatSSE.js               # 用户切换、附件与异步隔离
src/desk/HumanAgentDesk.jsx           # 坐席上下文与队列视图
src/admin/                            # 演示状态与风险明细
poc/visual_review_poc/                # 审核工作台与报告
scripts/                              # 0714 回归、smoke、发布包
tests/reports/                        # 自动化证据
docs/delivery/                        # 甲方与内部交付文档
```

## Phase Plan

1. 冻结 0714 规格、根因、数据模型和契约。
2. 先写失败回归，锁定订单优先级、意图、转接和卡片编排。
3. 修复 P0 统一状态与审核闭环。
4. 修复 P1 业务分支、坐席与运营体验。
5. 完成 API、浏览器、并发、发布包和文档验收。
6. 接入 0722 新订单快照资料：先完成只读盘点和唯一映射，再将当前审核任务需要的 SKU、履约基线和官方商品图按需注入；商品图不得全量下载，失败时必须可解释降级。
7. 统一审核建议结果：事实结论、未校准证据分数、三级人工复审、流程建议和风险信号分层；离框只作为证据条件，默认 3 秒建议补件，不单独证明调包或剪辑；API 可选择 JSON-only 或 JSON + HTML。
8. 建立客诉多源证据契约：发错货和漏发货分别校验订单、包裹、物流与证据覆盖；离线盲测只读取用户消息，禁止把人工终判送入模型；脱敏历史风险只影响抽检建议，不改变事实结论；未成年人资料继续拆分视觉一致性与甲方权威核验。
9. 将现网已验证的 Gemini 网关认证、Celery 任务注册和视觉结构化日志回迁 Git，并纳入发布门禁，避免运行环境修复只存在于服务器或运维记忆。
10. 将视频抽帧审核模型和渠道改为运行时配置：默认 `gemini-3.5-flash-lite`，按 BananaRouter、百度、API易、Google 官方顺序尝试；未配置的渠道直接跳过，继续复用现有重试、脱敏日志和业务报告边界，不新增路由服务。

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| 暂不引入独立微服务 | 当前 POC 先在现有服务内形成明确边界 | 立即拆服务会扩大交付风险，接口契约已为后续拆分保留边界 |

