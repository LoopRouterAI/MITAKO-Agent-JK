# MITAKO 0804 Evidence Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 分离证据事实、SOP 审核建议与人工复审，修复商品有伤全门槛回退和未成年人资料误判，并交付可由人工客服快速阅读、可盲测回归的版本。

**Architecture:** 保留现有模型调用、批处理和 API 契约，最小化修改三个共享入口：资料观察结果的确定性聚合、商品有伤 SOP 策略、HTML 报告信息层级。模型只输出可观察事实；服务端规则输出 SOP 建议；人工复审路由不再覆盖建议结论。

**Tech Stack:** Python、FastAPI、pytest、现有 HTML 报告渲染器、现有发布脚本。

---

### Task 1: 冻结证据语义与标签隔离

**Files:**
- Modify: `specs/002-customer-feedback-0714-closure/spec.md`
- Modify: `specs/002-customer-feedback-0714-closure/plan.md`
- Modify: `specs/002-customer-feedback-0714-closure/tasks.md`
- Modify: `tests/visual_review/test_model_request_isolation.py`

- [ ] **Step 1: 写入失败回归**

验证模型请求正文、媒体路径和结构化上下文不包含 `正样本`、`负样本`、`人工认可`、`人工拒绝`、`reply.json`、`annotation` 或人工终判字段。

- [ ] **Step 2: 运行失败回归**

Run: `venv\Scripts\python.exe -m pytest tests\visual_review\test_model_request_isolation.py -q`

Expected: 新增的中立路径或字段隔离断言在现状下失败，且失败原因是标签泄露检查未覆盖。

- [ ] **Step 3: 最小化实现隔离**

复用现有中立目录复制和上下文白名单，不增加新的样本格式；人工标签仅在推理完成后由评测器读取。

- [ ] **Step 4: 验证通过**

Run: `venv\Scripts\python.exe -m pytest tests\visual_review\test_model_request_isolation.py -q`

Expected: PASS。

### Task 2: 修复未成年人资料有效性与编辑风险

**Files:**
- Modify: `poc/visual_review_poc/minor_material_model_prompt.py`
- Modify: `poc/visual_review_poc/minor_material_pipeline.py`
- Modify: `tests/visual_review/test_minor_material_pipeline.py`

- [ ] **Step 1: 写入三组失败测试**

```python
def test_blank_template_does_not_satisfy_mobile_realname_requirement():
    result = aggregate_minor_material_results(case_with_blank_invoice_template(), observations_with_template())
    assert "mobile_realname" in result["missing_requirement_ids"]

def test_operator_account_screenshot_is_supporting_evidence_only():
    result = aggregate_minor_material_results(case_with_operator_profile_screenshot(), profile_observations())
    assert result["checklist_by_id"]["mobile_realname"]["status"] != "present"

def test_repeated_generic_edit_warnings_do_not_become_critical():
    result = aggregate_minor_material_results(complete_case(), generic_edit_warnings(6))
    assert result["authenticity_assessment"]["severity"] != "critical"
```

- [ ] **Step 2: 确认测试按预期失败**

Run: `venv\Scripts\python.exe -m pytest tests\visual_review\test_minor_material_pipeline.py -q`

Expected: 模板或普通截图被计为有效材料，或重复泛化风险被升级为 `critical`。

- [ ] **Step 3: 实现最小证据语义**

在既有观察结构中增加并消费 `document_state=filled|blank_template|example|unknown` 和 `sop_eligibility=valid|supporting_only|invalid|unknown`。只有用户特定、已填写且符合当前 SOP 的话费账单或电子发票满足手机号实名归属证明；普通运营商账户截图只作辅助证据。

编辑风险仅在存在图片级、位置明确、可复述的局部证据，或两个独立检查对同一异常形成交叉证实时升级；重复泛化描述、EXIF 缺失、压缩、转发、扫描件不升级为严重风险。

- [ ] **Step 4: 验证未成年人专项通过**

Run: `venv\Scripts\python.exe -m pytest tests\visual_review\test_minor_material_pipeline.py -q`

Expected: PASS。

### Task 3: 分离商品有伤建议与人工复审

**Files:**
- Modify: `review_service/decision_policy.py`
- Modify: `review_service/advisory_assessment.py`
- Modify: `tests/review_service/test_advisory_assessment.py`
- Modify: `tests/review_service/test_decision_policy_0717.py`

- [ ] **Step 1: 写入失败测试**

```python
def test_complete_usable_video_without_claimed_damage_recommends_not_support():
    result = apply_review_decision_policy(complete_video_no_damage_payload())
    assert result["predicted_label"] == "negative"
    assert result["decision_policy_audit"]["recommendation"] == "not_support_claim"

def test_optional_forensic_signal_does_not_erase_sop_recommendation():
    result = assess_review_advice(no_damage_payload(media_forensics="unknown"))
    assert result["sop_recommendation"]["code"] == "not_support_claim"
    assert result["human_review"]["level"] != "required"

def test_missing_material_requires_concrete_material_name():
    result = assess_review_advice(payload_with_missing_material("连续原视频"))
    assert result["flow_advice"]["code"] == "request_more_material"
    assert result["material_gaps"] == ["连续原视频"]
```

- [ ] **Step 2: 确认全门槛回退测试失败**

Run: `venv\Scripts\python.exe -m pytest tests\review_service\test_advisory_assessment.py tests\review_service\test_decision_policy_0717.py -q`

Expected: 可选门槛缺失仍把明确的“不支持”建议压成 `review`。

- [ ] **Step 3: 删除错误的全量合取门禁**

保留 `conditions` 作为审计信息，但不再以 `all(conditions.values())` 决定是否允许给出 SOP 建议。事实方向由主视频是否可用、是否观察到所诉损伤、是否存在明确证据冲突决定；连续性、离镜、取证和补充证据关联只调整置信度或复审等级。

- [ ] **Step 4: 验证策略专项通过**

Run: `venv\Scripts\python.exe -m pytest tests\review_service\test_advisory_assessment.py tests\review_service\test_decision_policy_0717.py -q`

Expected: PASS。

### Task 4: 收敛客服报告首屏

**Files:**
- Modify: `poc/visual_review_poc/report_renderer.py`
- Modify: `poc/visual_review_poc/report_assessment_sections.py`
- Modify: `tests/visual_review/test_report_evidence_rendering.py`

- [ ] **Step 1: 写入报告结构失败测试**

```python
def test_first_screen_contains_decision_reason_action_and_key_evidence():
    html = render_report(review_payload())
    assert "客服审核摘要" in html
    assert "为什么这样建议" in html
    assert "客服下一步" in html
    assert "关键证据" in html
    assert '<details class="panel technical-details"' in html

def test_review_summary_lists_concrete_missing_materials():
    html = render_report(payload_missing("手机号实名归属证明"))
    assert "请补充：手机号实名归属证明" in html
```

- [ ] **Step 2: 确认现有长报告结构失败**

Run: `venv\Scripts\python.exe -m pytest tests\visual_review\test_report_evidence_rendering.py -q`

Expected: 缺少统一首屏摘要或技术详情未折叠。

- [ ] **Step 3: 实现首屏四块信息和折叠详情**

首屏仅保留 SOP 建议与置信度、一句话原因、客服下一步、三至六条关键证据。视频密度、完整论证、SOP 门槛、置信度分解、因果、连续性、订单基线、官方图和完整画廊放入一个默认折叠区；空模块不渲染。

- [ ] **Step 4: 验证报告专项通过**

Run: `venv\Scripts\python.exe -m pytest tests\visual_review\test_report_evidence_rendering.py -q`

Expected: PASS。

### Task 5: 中立样本盲测与真实链路验收

**Files:**
- Modify: `scripts/check_review_sop_alignment.py`
- Create: `scripts/check_review_0804_blind_acceptance.py`
- Create: `tests/reports/review_0804_blind_acceptance_latest.json`

- [ ] **Step 1: 建立中立送审清单**

从样本源复制选中的正、负和补证案例到仅使用随机案件 ID 的临时目录；推理进程只能读取媒体、允许的业务 JSON 和用户诉求。评测进程在任务结束后再加载人工标签。

- [ ] **Step 2: 运行离线聚合与单元回归**

Run: `venv\Scripts\python.exe -m pytest tests\review_service tests\visual_review -q`

Expected: 0 failures。

- [ ] **Step 3: 运行真实 API 单件和批量盲测**

Run: `venv\Scripts\python.exe scripts\check_review_0804_blind_acceptance.py --sample-root "E:\AIGC\0 Mitako样本" --base-url http://127.0.0.1:8015`

Expected: 每个任务有 request/task ID、JSON 建议、置信度、复审等级和 HTML；模型请求泄露计数为 0；已知回归案例 479289、136480、580715 符合冻结口径；正负样本分别统计，不用目录标签参与推理。

- [ ] **Step 4: 运行网页端浏览器验收**

验证本地上传、工单文件夹、单任务、批量任务和报告图片回链；首屏在桌面和移动端无重叠，技术详情默认折叠。

### Task 6: 文档、HTML 和双 ZIP 交付

**Files:**
- Modify: `我方内部开发文档/README.md`
- Create: `我方内部开发文档/升级日志-2026-08-04-证据语义与客服决策收敛.md`
- Create: `甲方沟通交付文档/0804审核建议与客服报告更新说明.html`
- Create: `docs/delivery/mitako-0804-evidence-semantics-acceptance.html`
- Modify: `README.md`

- [ ] **Step 1: 写入人类可读说明与内部部署记录**

记录本轮修复、当前功能、测试方法、API 字段、演示数据边界、未接甲方真实接口边界、盲测样本和验收结果，不包含模型渠道、密钥、内部提示词或人工标签路径。

- [ ] **Step 2: 运行构建、发布门禁和打包**

Run: `npm run build`

Run: `venv\Scripts\python.exe scripts\check_release_packages.py`

Run: `powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1`

Run: `powershell -ExecutionPolicy Bypass -File scripts\package_internal_release.ps1`

Expected: 两个 ZIP 位于 `dist/`，客户包不含 `.env`、测试标签和内部文档；内部包包含源码、部署说明和环境变量模板。

- [ ] **Step 3: 独立解压冷启动验收**

在全新临时目录分别解压两包，运行发布包检查、API smoke、网页 smoke 和报告链接检查，记录 SHA-256、包大小和失败恢复方式。

- [ ] **Step 4: 收口目标**

只有单元、盲测、API、网页、构建、双包和独立解压验收全部通过后，才将目标标记为完成；未通过项保持活动状态并继续修复。
