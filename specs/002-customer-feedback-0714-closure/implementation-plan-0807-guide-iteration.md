# 0807 黄金指南与速度影响迭代 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将五份人工黄金指南转化为可验证的结构化审核规则，完成随机真实样本、报告视觉、甲方 HTML 和双 ZIP 交付。

**Architecture:** 复用现有 1/2 FPS 抽帧、主审核、连续性、损伤成因、确定性聚合和版本化决策链。模型只输出可回链事实，服务端聚合速度实际影响与材料字段，版本化策略决定建议，报告只展示客服可理解结果。

**Tech Stack:** Python、FastAPI、Pydantic、现有视觉模型调用链、unittest/pytest、HTML 报告渲染、PowerShell 发布脚本。

---

### Task 1: 冻结失败回归

**Files:**
- Modify: `tests/visual_review/test_model_request_isolation.py`
- Modify: `tests/visual_review/test_global_timeline_aggregation_0717.py`
- Modify: `tests/review_service/test_decision_policy_0717.py`
- Modify: `tests/visual_review/test_damage_causality.py`
- Modify: `tests/visual_review/test_minor_material_pipeline.py`
- Modify: `tests/visual_review/test_report_evidence_rendering.py`

- [ ] **Step 1: 写速度影响失败测试**

覆盖 `accelerated + none` 非阻断、`accelerated + uncertain + 1 FPS` 保持 `review` 并建议 2 FPS、`accelerated + material + >=2 FPS` 命中不合规。

- [ ] **Step 2: 写指南业务失败测试**

覆盖封箱起始缺失、面单不可读、后补材料无时态关联、手工品外观差异资格不确定、手机号持有人不是申请监护人、短便条不完整和学校材料只作辅助。

- [ ] **Step 3: 运行并确认按预期失败**

```powershell
.venv\Scripts\python.exe -m unittest tests.visual_review.test_model_request_isolation tests.visual_review.test_global_timeline_aggregation_0717 tests.review_service.test_decision_policy_0717 tests.visual_review.test_damage_causality tests.visual_review.test_minor_material_pipeline tests.visual_review.test_report_evidence_rendering -v
```

预期：新增用例因字段或规则尚不存在而失败，既有用例保持通过。

### Task 2: 实现速度影响与开箱硬字段

**Files:**
- Modify: `poc/visual_review_poc/review_model_prompt.py`
- Modify: `poc/visual_review_poc/model_selection_e2e.py`
- Modify: `review_service/decision_policy.py`
- Modify: `review_service/service.py`

- [ ] **Step 1: 扩展模型事实契约**

新增 `speed_review_impact`、`critical_evidence_observable`、`affected_review_items`、`sealed_start`、`waybill_visible`、`issue_visible_in_continuous_opening`，要求证据按视频、帧和时间戳回链。

- [ ] **Step 2: 确定性聚合速度影响**

聚合优先级为 `material > uncertain > none`；没有疑似加速时保持 `none`，无法证明速度影响时不得猜测 `material`。

- [ ] **Step 3: 更新版本化策略顺序**

在可见伤情正向规则之前处理已确认不合规；`uncertain + <2 FPS` 保持 `review` 并生成 2 FPS 升级建议；`material + >=2 FPS` 才形成速度导致的不合规。

- [ ] **Step 4: 运行速度与决策测试**

```powershell
.venv\Scripts\python.exe -m unittest tests.visual_review.test_model_request_isolation tests.visual_review.test_global_timeline_aggregation_0717 tests.review_service.test_decision_policy_0717 -v
```

预期：全部通过。

### Task 3: 实现来源时态、特殊商品和未成年人材料规则

**Files:**
- Modify: `poc/visual_review_poc/damage_causality.py`
- Modify: `poc/visual_review_poc/damage_causality_model_prompt.py`
- Modify: `poc/visual_review_poc/minor_material_model_prompt.py`
- Modify: `poc/visual_review_poc/minor_material_pipeline.py`

- [ ] **Step 1: 保留主视频与后补材料的独立事实**

后补材料不得成为主视频 `first_visible_evidence`；只有 `temporal_linkage=true` 才可支持开箱时态。

- [ ] **Step 2: 增加特殊商品缺陷资格**

将 `appearance_difference` 与 `business_defect_qualification` 分离，缺少甲方标准时保持不确定。

- [ ] **Step 3: 增加监护人手机号和承诺书字段**

复用现有一致性检查，加入持有人角色、内容完整性、申请范围、收款信息和日期；学校材料固定为 `supporting_only`。

- [ ] **Step 4: 运行对应测试**

```powershell
.venv\Scripts\python.exe -m unittest tests.visual_review.test_damage_causality tests.visual_review.test_minor_material_pipeline -v
```

预期：全部通过。

### Task 4: 报告、随机验证与视觉 QA

**Files:**
- Modify: `poc/visual_review_poc/report_renderer.py`
- Modify: `tests/visual_review/test_report_evidence_rendering.py`
- Create: `tests/reports/review_0807_random_acceptance_latest.json`
- Create: `tests/reports/review_0807_random_acceptance_latest.html`

- [ ] **Step 1: 更新报告表达并通过回归**

报告显示抽帧强度、橙色加速信号、实际影响、受影响项目和强化复核状态，不展示内部策略号、模型渠道、Key、Prompt 或样本路径。

- [ ] **Step 2: 固定随机种子抽样并执行真实链路**

从中立副本抽取至少 4 个商品有伤和 1 个未成年人样本，记录种子、案件中立 ID、1/2 FPS、结构化结果、请求 ID、路由范围和错误原因；标签仅在推理后评估。

- [ ] **Step 3: 桌面与移动端视觉 QA**

检查首屏、速度卡、证据卡、媒体回链、文本溢出、交互和控制台错误；不通过则修复后重测。

### Task 5: 独立审查、文档与发布

**Files:**
- Modify: `我方内部开发文档/MITAKO售后审核Agent业务认知基线-20260727.md`
- Create: `我方内部开发文档/升级日志-2026-08-07-黄金指南与速度影响闭环.md`
- Create: `甲方沟通交付文档/0807黄金指南学习与审核能力更新说明.html`
- Create: `docs/delivery/mitako-0807-guide-acceptance-20260807.html`
- Modify: `scripts/package_release.ps1`
- Modify: `scripts/package_internal_release.ps1`

- [ ] **Step 1: 独立 Agent 审核**

分别检查提示词是否过度限制、策略是否绕过硬条件、代码是否存在低级/性能问题、报告是否准确易读；修复全部高/中风险。

- [ ] **Step 2: 更新业务与验收文档**

记录新旧规则覆盖关系、真实验证证据、仍有效旧结论、失效内容、剩余风险和四场景自我限制审计。

- [ ] **Step 3: 全量验证并生成发布物**

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
npm run build
powershell -ExecutionPolicy Bypass -File scripts/pre_release_internal_validation.ps1
powershell -ExecutionPolicy Bypass -File scripts/package_release.ps1
powershell -ExecutionPolicy Bypass -File scripts/package_internal_release.ps1
.venv\Scripts\python.exe scripts/check_release_packages.py
```

预期：全量测试、构建、发布门禁和双 ZIP 独立解压冷启动全部通过，产物仅位于 `dist/`。
