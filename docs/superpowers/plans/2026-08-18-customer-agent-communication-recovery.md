# Deeptokenai.cn 客服 Agent 用户沟通质量回归修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 2026-08-18 人工测试报告中的 10 个问题，使原 15 个用户沟通场景连续 3 轮保持意图、核心结论、动作状态和下一步一致，并实现 API/Web/移动端同源、无虚构执行状态、停止/断连/超时可取消和双仓发布。

**Architecture:** 新建小型 `customer_service/` 领域层，负责确定性意图、事实来源、工具回执、场景策略、回复计划和公开 DTO。现有 LangGraph 只负责编排，LLM 只能润色程序生成的回复计划；`main.py`、用户端和坐席台只消费统一 `conversation_state`。请求生命周期复用前端 `AbortController` 和后端 `asyncio.Task`，由断连、超时和同 session 单飞共同收口，不新增持久化轮次框架。

**Tech Stack:** Python 3.11、FastAPI、LangGraph、Pydantic、SQLite、React/Vite、pytest、Playwright。

---

## 文件结构

### 新建

- `customer_service/__init__.py`：公开领域入口。
- `customer_service/contracts.py`：强类型意图、事实、动作、回复计划与公开状态。
- `customer_service/intent_router.py`：确定性意图分类。
- `customer_service/fact_resolver.py`：事实与来源解析。
- `customer_service/action_state.py`：工具回执归一化和状态合法性校验。
- `customer_service/scenario_policy.py`：十个目标场景的业务策略。
- `customer_service/reply_plan.py`：生成用户回复计划。
- `customer_service/reply_guard.py`：阻断虚构完成态和无依据承诺。
- `customer_service/public_projection.py`：API/Web/坐席统一 DTO。
- `tests/fixtures/customer_agent_20260818_cases.json`：15 场景冻结验收集。
- `tests/customer_service/test_contracts.py`
- `tests/customer_service/test_intent_router.py`
- `tests/customer_service/test_fact_resolver.py`
- `tests/customer_service/test_action_state.py`
- `tests/customer_service/test_scenario_policy.py`
- `tests/customer_service/test_reply_guard.py`
- `tests/customer_service/test_three_round_stability.py`
- `tests/test_chat_stream_cancellation.py`
- `tests/e2e/run_customer_chat_stop.py`
- `tests/e2e/run_customer_agent_20260818_acceptance.py`

### 修改

- `agent.py`：保留 LangGraph 编排，调用领域层。
- `main.py`：SSE 返回统一 `conversation_state`，闭环断连/超时/同 session 单飞并增加版本接口。
- `business_api.py`：Mock 工具返回标准回执。
- `handoff_service.py`：人工队列返回标准动作回执。
- `src/hooks/useChatSSE.js`：保存统一状态并暴露当前轮次停止动作。
- `src/components/chat/ChatPanel.jsx`：把统一状态和停止动作传递给输入区。
- `src/components/chat/ChatInput.jsx`：生成期间把发送按钮切换为停止按钮。
- `src/components/chat/MessageList.jsx`：不从回复文本推断状态。
- `src/components/cards/openUILibrary.jsx`：按动作状态显示未提交、排队、失败、完成。
- `src/desk/HumanAgentDesk.jsx`：显示事实来源和工具回执。
- `scripts/package_release.ps1`：纳入新模块。
- `scripts/check_release_packages.py`：校验运行时包含新模块。
- `tests/test_release_layout.py`：发布布局回归。

---

### Task 1: 冻结 15 场景验收集

**Files:**
- Create: `tests/fixtures/customer_agent_20260818_cases.json`
- Create: `tests/customer_service/test_fixture_contract.py`

- [ ] **Step 1: 写冻结验收集**

JSON 顶层固定为：

```json
{
  "version": "MITAKO-CUSTOMER-CHAT-20260818.1",
  "source": "MITAKO客服Agent用户沟通全量测试报告_20260818.pdf",
  "cases": [
    {
      "case_id": "CHAT-01-MINOR-MOBILE-OWNER",
      "priority": "P1",
      "persona": "guardian",
      "message": "运营商发票登记的是孩子本人手机号，不是监护人手机号，付款和订单金额一致，能否通过？",
      "expected_intent": "minor_refund_material",
      "expected_scenario": "minor_refund",
      "expected_core_conclusion": "child_mobile_invoice_not_acceptable",
      "expected_action_status": "not_requested",
      "expected_next_step": "request_guardian_mobile_proof",
      "forbidden_claims": ["孩子本人手机号也可以", "审核通过", "已建单"]
    },
    {
      "case_id": "CHAT-02-PRODUCT-AMBIGUOUS",
      "priority": "P1",
      "persona": "new_user",
      "message": "想问五条悟圆形徽章的库存、直径和发货时间，我还没有商品链接。",
      "expected_intent": "product_consultation",
      "expected_scenario": "product_consultation",
      "expected_core_conclusion": "product_identity_ambiguous",
      "expected_action_status": "not_requested",
      "expected_next_step": "request_product_identity",
      "forbidden_claims": ["排球少年", "库存有", "预计发货"]
    },
    {
      "case_id": "CHAT-03-ENTITLEMENT-MISSING",
      "priority": "P1",
      "persona": "silver_member",
      "message": "活动页承诺限定特典卡，但包裹里没有；请先核对活动规则，再告诉我漏发需要什么证据。",
      "expected_intent": "entitlement_missing",
      "expected_scenario": "missing_item",
      "expected_core_conclusion": "entitlement_baseline_required",
      "expected_action_status": "requested",
      "expected_next_step": "lookup_entitlement_rule",
      "forbidden_claims": ["中奖概率", "奖池", "抽号"]
    },
    {
      "case_id": "CHAT-04-MATERIAL-NOT-UPLOADED",
      "priority": "P1",
      "persona": "platinum_member",
      "message": "我只有特写照片和面单，但我还没有在网页上传任何文件。",
      "expected_intent": "product_damage",
      "expected_scenario": "product_damage",
      "expected_core_conclusion": "material_not_received",
      "expected_action_status": "not_requested",
      "expected_next_step": "upload_materials",
      "forbidden_claims": ["已收到", "已上传", "已建单", "审核中"]
    },
    {
      "case_id": "CHAT-05-WRONG-ITEM",
      "priority": "P2",
      "persona": "platinum_member",
      "message": "订单买的是手办，收到的是另一个角色，发错货需要提交哪些材料？",
      "expected_intent": "wrong_item",
      "expected_scenario": "wrong_item",
      "expected_core_conclusion": "wrong_item_materials_required",
      "expected_action_status": "not_requested",
      "expected_next_step": "request_wrong_item_evidence",
      "forbidden_claims": ["开箱视频可选", "闲聊互动"]
    },
    {
      "case_id": "CHAT-06-MISSING-COUNT",
      "priority": "P2",
      "persona": "new_user",
      "message": "一单应有12个吧唧，实收11个，少了一个，怎么证明漏发？",
      "expected_intent": "missing_item",
      "expected_scenario": "missing_item",
      "expected_core_conclusion": "expected_12_received_11",
      "expected_action_status": "not_requested",
      "expected_next_step": "request_missing_item_evidence",
      "forbidden_claims": ["闲聊互动", "无法确认数量"]
    },
    {
      "case_id": "CHAT-07-REFUND-HANDOFF",
      "priority": "P2",
      "persona": "gold_member",
      "message": "延期180天了，我不想再等，要求退款并转人工。",
      "expected_intent": "human_handoff",
      "expected_scenario": "refund_progress",
      "expected_core_conclusion": "handoff_receipt_required",
      "expected_action_status": "queued",
      "expected_next_step": "show_queue_status",
      "forbidden_claims": ["已转接"],
      "allowed_when_receipt": ["已进入人工队列"]
    },
    {
      "case_id": "CHAT-08-HIGH-RISK-COMPLAINT",
      "priority": "P2",
      "persona": "gold_member",
      "message": "不要只道歉，直接说谁处理、多久处理完，否则我投诉。",
      "expected_intent": "high_risk_complaint",
      "expected_scenario": "complaint",
      "expected_core_conclusion": "complaint_protocol_required",
      "expected_action_status": "queued",
      "expected_next_step": "show_owner_sla_receipt",
      "required_reply_fields": ["responsible_role", "current_action", "first_response_sla", "tracking_receipt"]
    },
    {
      "case_id": "CHAT-09-ADDRESS-CHANGE-FAILURE",
      "priority": "P1",
      "persona": "regular_member",
      "message": "订单026403还没出库，我填错了收货地址，能修改吗？",
      "expected_intent": "address_change",
      "expected_scenario": "order_change",
      "expected_core_conclusion": "address_change_requires_tool",
      "expected_action_status": "failed",
      "expected_next_step": "show_retry_and_human_entry",
      "forbidden_claims": ["已修改", "请刷新页面"]
    },
    {
      "case_id": "CHAT-10-PRIVACY-DELETION",
      "priority": "P1",
      "persona": "new_user",
      "message": "我要删除手机号、身份证资料和全部聊天记录，请告诉我申请入口和处理时效。",
      "expected_intent": "privacy_deletion",
      "expected_scenario": "privacy_compliance",
      "expected_core_conclusion": "privacy_verification_required",
      "expected_action_status": "not_requested",
      "expected_next_step": "show_configured_privacy_entry",
      "forbidden_claims": ["账号换绑", "闲聊互动", "已删除"]
    }
  ]
}
```

验收集还必须包含以下 5 个控制场景：

```json
[
  {
    "case_id": "CHAT-11-LOTTERY-REPEAT",
    "priority": "CONTROL",
    "persona": "platinum_member",
    "message": "我已经问过几次了，盲盒概率是不是会因为重复抽而变化？",
    "expected_intent": "lottery_rule",
    "expected_scenario": "lottery_rule",
    "expected_core_conclusion": "published_rule_required",
    "expected_action_status": "not_requested",
    "expected_next_step": "show_published_rule_boundary",
    "forbidden_claims": ["概率一定不变", "绝对随机"]
  },
  {
    "case_id": "CHAT-12-LOGISTICS-IN-TRANSIT",
    "priority": "CONTROL",
    "persona": "regular_member",
    "message": "订单还在运输途中，当前到哪里了？",
    "expected_intent": "order_logistics",
    "expected_scenario": "order_logistics",
    "expected_core_conclusion": "show_verified_logistics_node",
    "expected_action_status": "succeeded",
    "expected_next_step": "wait_for_next_logistics_event",
    "forbidden_claims": ["已丢件", "已退款"]
  },
  {
    "case_id": "CHAT-13-SECOND-ORDER",
    "priority": "CONTROL",
    "persona": "new_user",
    "message": "我想查第二笔订单，不是刚才那一笔。",
    "expected_intent": "order_logistics",
    "expected_scenario": "order_logistics",
    "expected_core_conclusion": "order_selection_required",
    "expected_action_status": "requested",
    "expected_next_step": "select_second_order",
    "forbidden_claims": ["没有订单权限", "查询的是第一笔订单"]
  },
  {
    "case_id": "CHAT-14-GUARDIAN-RELATIONSHIP",
    "priority": "CONTROL",
    "persona": "guardian",
    "message": "我和孩子分别在两本户口本里，这样能证明监护关系吗？",
    "expected_intent": "minor_refund_material",
    "expected_scenario": "minor_refund",
    "expected_core_conclusion": "guardianship_chain_not_established",
    "expected_action_status": "not_requested",
    "expected_next_step": "request_legal_guardianship_proof",
    "forbidden_claims": ["可以证明", "资料齐全"]
  },
  {
    "case_id": "CHAT-15-SHIPMENT-PROGRESS",
    "priority": "CONTROL",
    "persona": "new_user",
    "message": "我的订单现在发货到哪一步了？",
    "expected_intent": "order_logistics",
    "expected_scenario": "order_logistics",
    "expected_core_conclusion": "show_verified_order_progress",
    "expected_action_status": "succeeded",
    "expected_next_step": "show_current_progress",
    "forbidden_claims": ["海关新政", "保证明天发货"]
  }
]
```

- [ ] **Step 2: 写 fixture 结构测试**

```python
def test_fixture_has_fifteen_unique_cases():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(data["cases"]) == 15
    assert len({case["case_id"] for case in data["cases"]}) == 15
    required = {
        "case_id", "priority", "persona", "message", "expected_intent",
        "expected_scenario", "expected_core_conclusion",
        "expected_action_status", "expected_next_step",
    }
    assert all(required <= set(case) for case in data["cases"])
```

- [ ] **Step 3: 运行红灯测试**

Run: `python -m pytest tests/customer_service/test_fixture_contract.py -q`

Expected: FAIL，当前 fixture 文件不存在。

- [ ] **Step 4: 补齐 15 个 fixture 并转绿**

Run: `python -m pytest tests/customer_service/test_fixture_contract.py -q`

Expected: `1 passed`。

- [ ] **Step 5: 提交**

```bash
git add tests/fixtures/customer_agent_20260818_cases.json tests/customer_service/test_fixture_contract.py
git commit -m "test: freeze 20260818 customer chat acceptance cases"
```

### Task 2: 建立强类型客服状态契约

**Files:**
- Create: `customer_service/__init__.py`
- Create: `customer_service/contracts.py`
- Create: `tests/customer_service/test_contracts.py`

- [ ] **Step 1: 写状态合法性红灯测试**

```python
def test_completed_action_requires_receipt():
    with pytest.raises(ValueError, match="completed_action_requires_receipt"):
        ActionState(action="human_handoff", status="queued")

def test_user_statement_cannot_verify_system_fact():
    fact = Fact(field="material_received", value=True, source="user_statement")
    assert fact.verified is False
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest tests/customer_service/test_contracts.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现契约**

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, model_validator

class ActionStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING_HUMAN = "pending_human"

class FactSource(StrEnum):
    USER_STATEMENT = "user_statement"
    ATTACHMENT_SERVICE = "attachment_service"
    ORDER_SERVICE = "order_service"
    PRODUCT_SERVICE = "product_service"
    ACTIVITY_SERVICE = "activity_service"
    WAREHOUSE_SERVICE = "warehouse_service"
    HANDOFF_SERVICE = "handoff_service"
    REVIEW_SERVICE = "review_service"
    HUMAN_UPDATE = "human_update"

class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    value: object
    source: FactSource
    source_ref: str = ""
    verified: bool = False

    @model_validator(mode="after")
    def normalize_verified(self):
        if self.source == FactSource.USER_STATEMENT:
            self.verified = False
        return self

class ActionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    status: ActionStatus
    receipt_id: str = ""
    tool_name: str = ""
    reason_code: str = ""
    occurred_at: str = ""

    @model_validator(mode="after")
    def require_receipt(self):
        if self.status in {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}:
            if not self.receipt_id or not self.tool_name or not self.occurred_at:
                raise ValueError("completed_action_requires_receipt")
        return self
```

同文件定义以下类型：

```python
class IntentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_code: str
    scenario_code: str
    intent_codes: list[str] = Field(default_factory=list)
    scenario_codes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    matched_evidence: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_fields: list[str] = Field(default_factory=list)

class NextStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    label: str
    user_action_required: bool = False

class ReplyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: list[Fact] = Field(default_factory=list)
    must_say: list[str] = Field(default_factory=list)
    must_not_say: list[str] = Field(default_factory=list)
    action: ActionState
    next_step: NextStep
    allowed_time_commitment: str | None = None

class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: IntentResult
    facts: list[Fact] = Field(default_factory=list)
    material_state: dict[str, object] = Field(default_factory=dict)
    action_state: ActionState
    next_step: NextStep
    core_conclusion: str
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/customer_service/test_contracts.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add customer_service tests/customer_service/test_contracts.py
git commit -m "feat: add deterministic customer service contracts"
```

### Task 3: 重建确定性复合意图路由与四场景映射

**Files:**
- Create: `customer_service/intent_router.py`
- Create: `tests/customer_service/test_intent_router.py`
- Modify: `agent.py:625-686`

- [ ] **Step 1: 用 15 个 fixture 写参数化红灯测试**

```python
@pytest.mark.parametrize("case", load_cases(), ids=lambda row: row["case_id"])
def test_intent_matches_frozen_case(case):
    result = route_intent(case["message"], history=[])
    assert result.intent_code == case["expected_intent"]
    assert result.scenario_code == case["expected_scenario"]

@pytest.mark.parametrize(
    ("message", "primary_intent", "primary_scenario", "intent_codes", "scenario_codes"),
    [
        (
            "延期180天了，我要求退款并转人工。",
            "human_handoff",
            "refund_progress",
            {"human_handoff", "refund_progress"},
            {"refund_progress"},
        ),
        (
            "商品有划痕，而且同一包裹还少了一张特典卡。",
            "product_damage",
            "product_damage",
            {"product_damage", "entitlement_missing"},
            {"product_damage", "missing_item"},
        ),
    ],
)
def test_compound_request_keeps_all_business_scenes(
    message, primary_intent, primary_scenario, intent_codes, scenario_codes
):
    result = route_intent(message, history=[])
    assert result.intent_code == primary_intent
    assert result.scenario_code == primary_scenario
    assert set(result.intent_codes) == intent_codes
    assert set(result.scenario_codes) == scenario_codes
```

- [ ] **Step 2: 运行测试确认旧路由失败**

Run: `python -m pytest tests/customer_service/test_intent_router.py -q`

Expected: 至少赠品、发错货、漏发货、隐私删除、地址修改和两个复合诉求失败。

- [ ] **Step 3: 实现有优先级的路由**

顺序必须是：隐私删除 -> 地址修改 -> 人工请求 -> 高危投诉 -> 未成年人 -> 发错货 -> 漏发货/赠品 -> 商品有伤 -> 商品咨询 -> 退款进度 -> 物流 -> 盲盒规则 -> 闲聊。

```python
RULES = (
    IntentRule("privacy_deletion", "privacy_compliance", ("删除手机号", "删除身份证", "删除聊天记录", "注销隐私")),
    IntentRule("address_change", "order_change", ("修改收货地址", "改地址", "填错地址")),
    IntentRule("human_handoff", "human_handoff", ("转人工", "人工客服", "真人客服")),
    IntentRule("high_risk_complaint", "complaint", ("12315", "投诉", "起诉", "谁负责")),
    IntentRule("minor_refund_material", "minor_refund", ("未成年人", "孩子", "监护人", "承诺书")),
    IntentRule("wrong_item", "wrong_item", ("发错", "收到另一个", "不是买的")),
    IntentRule("entitlement_missing", "missing_item", ("赠品", "特典", "满赠", "随单赠")),
    IntentRule("missing_item", "missing_item", ("漏发", "少了", "应有", "实收")),
    IntentRule("product_damage", "product_damage", ("有伤", "划痕", "破损", "瑕疵")),
    IntentRule("product_consultation", "product_consultation", ("库存", "直径", "尺寸", "发货时间", "SKU")),
)
```

每个结果返回实际命中的短语。`intent_code` 是本轮优先动作，`scenario_code` 是首要业务场景；`intent_codes` 和 `scenario_codes` 保留全部原子诉求，不得因“转人工”“投诉”等动作覆盖退款进度或四场景业务事实。四场景代码只能映射为 `product_damage`、`wrong_item`、`missing_item`、`minor_refund`，后续策略必须消费 `MITAKO-FOUR-SCENE@20260814.1` 的公开结果，不复制其 Prompt、Schema 或确定性 SOP。无唯一商品、订单或场景时返回 `requires_clarification=True`，不得让 LLM 改写意图。

- [ ] **Step 4: 让 LangGraph 兼容新路由**

`classify_intent()` 调用 `route_intent()`，旧 `intent` 字符串保留为展示标签，同时把完整结果写入 `state["conversation_state"]["intent"]`。附件审核结果只读取四场景公开 DTO，通用材料话术不得覆盖其中的 `scenario`、`material_readiness`、`evidence_route` 或 `resolution_basis`。

- [ ] **Step 5: 运行新旧路由相关测试**

Run: `python -m pytest tests/customer_service/test_intent_router.py tests/e2e/run_mock_business_guard_e2e.py -q`

Expected: 新 15 案通过；旧回归无意图倒退。

- [ ] **Step 6: 提交**

```bash
git add customer_service/intent_router.py agent.py tests/customer_service/test_intent_router.py
git commit -m "feat: add deterministic customer intent router"
```

### Task 4: 建立事实来源与材料状态

**Files:**
- Create: `customer_service/fact_resolver.py`
- Create: `tests/customer_service/test_fact_resolver.py`
- Modify: `main.py:1570-1635`

- [ ] **Step 1: 写用户陈述与附件回执反例**

```python
def test_claimed_material_is_not_received_without_attachment():
    facts = resolve_facts(message="我已经准备了面单和照片", attachments=[])
    assert find(facts, "material.user_claimed").value is True
    assert find(facts, "material.received").value is False

def test_attachment_service_receipt_marks_received():
    facts = resolve_facts(message="这是材料", attachments=[{"id": "A1", "status": "stored"}])
    received = find(facts, "material.received")
    assert received.value is True
    assert received.source == "attachment_service"
```

- [ ] **Step 2: 实现事实解析器**

分别生成：

- `material.user_claimed`
- `material.received`
- `material.parsed`
- `review.job_created`
- `order.selected`
- `product.identity_resolved`
- `handoff.queued`

附件只读取 `_require_all_chat_attachments_valid()` 的结果，不读取用户话术推断接收状态。

- [ ] **Step 3: 接入 chat_stream 初始状态**

`main.py` 在启动 Agent 前生成 facts，写入 `state["conversation_state"]`，并把 facts 作为独立受信对象传给 Agent，不拼进 `<untrusted_business_context>`。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/customer_service/test_fact_resolver.py tests/e2e/run_mock_business_guard_e2e.py -q`

- [ ] **Step 5: 提交**

```bash
git add customer_service/fact_resolver.py main.py tests/customer_service/test_fact_resolver.py
git commit -m "feat: separate customer claims from verified facts"
```

### Task 5: 统一工具回执与动作状态

**Files:**
- Create: `customer_service/action_state.py`
- Create: `tests/customer_service/test_action_state.py`
- Modify: `business_api.py`
- Modify: `handoff_service.py`

- [ ] **Step 1: 写工具回执测试**

```python
def test_handoff_queue_response_becomes_queued_action():
    action = action_from_tool("human_handoff", "handoff_service", {
        "ok": True, "status": "queued", "queue_id": "Q-1", "created_at": "2026-08-18T20:00:00+08:00"
    })
    assert action.status == "queued"
    assert action.receipt_id == "Q-1"

def test_timeout_never_becomes_success():
    action = action_from_exception("address_change", "business_api", TimeoutError())
    assert action.status == "failed"
    assert action.reason_code == "tool_timeout"
```

- [ ] **Step 2: 归一化现有 Mock 接口返回**

所有写操作返回：

```json
{
  "ok": true,
  "action": "human_handoff",
  "status": "queued",
  "receipt_id": "Q-1",
  "occurred_at": "2026-08-18T20:00:00+08:00",
  "reason_code": "queue_joined"
}
```

失败必须返回 `status=failed`，禁止只返回一段 message。

- [ ] **Step 3: 运行动作状态测试**

Run: `python -m pytest tests/customer_service/test_action_state.py tests/test_handoff_service.py -q`

- [ ] **Step 4: 提交**

```bash
git add customer_service/action_state.py business_api.py handoff_service.py tests/customer_service/test_action_state.py
git commit -m "feat: normalize customer tool action receipts"
```

### Task 6: 修复 P1 场景策略

**Files:**
- Create: `customer_service/scenario_policy.py`
- Create: `tests/customer_service/test_scenario_policy.py`
- Modify: `agent.py:909-1040`

- [ ] **Step 1: 写六个 P1 红灯测试**

覆盖：未成年人手机号、商品歧义、赠品权益、材料未上传、地址修改失败、隐私删除。

```python
def test_child_mobile_invoice_is_rejected():
    decision = decide_scenario(intent="minor_refund_material", facts=[
        fact("mobile.owner_role", "minor", source="user_statement")
    ])
    assert decision.core_conclusion == "child_mobile_invoice_not_acceptable"
    assert decision.next_step.code == "request_guardian_mobile_proof"

def test_catalog_key_does_not_match_its_own_record():
    result = resolve_unique_product("想问五条悟圆形徽章", catalog=demo_catalog())
    assert result.status == "ambiguous"
    assert result.product is None
```

- [ ] **Step 2: 实现场景决策函数**

每个分支只返回 `ScenarioDecision`，不返回自由文本。商品咨询删除 `_build_product_inventory_reply()` 中 `key in str(value)` 的恒真候选，只允许 SKU、商品链接、订单行或唯一规范化名称命中；否则追问。赠品权益先查活动基线；隐私删除读取配置中的入口和 SLA，配置缺失时显示人工入口，不生成默认 URL。

- [ ] **Step 3: 替换旧 SOP 拼接**

`search_knowledge_base()` 不再根据泛化意图追加抽奖/退款模板；改为把 `ScenarioDecision` 的 policy refs 写入状态。四场景附件已有审核结果时，`ScenarioDecision` 只投影 `MITAKO-FOUR-SCENE@20260814.1` 公开字段，不重新推断材料齐全性或审核结论。

- [ ] **Step 4: 运行 P1 测试**

Run: `python -m pytest tests/customer_service/test_scenario_policy.py -q`

Expected: 六个 P1 正反例全部通过。

- [ ] **Step 5: 提交**

```bash
git add customer_service/scenario_policy.py agent.py tests/customer_service/test_scenario_policy.py
git commit -m "feat: enforce deterministic P1 customer policies"
```

### Task 7: 修复发错货、漏发货、高危投诉和转人工

**Files:**
- Modify: `customer_service/scenario_policy.py`
- Modify: `agent.py:723-790`
- Modify: `agent.py:1390-1460`
- Test: `tests/customer_service/test_scenario_policy.py`
- Test: `tests/e2e/run_customer_agent_20260818_acceptance.py`

- [ ] **Step 1: 写 P2 红灯测试**

发错货必须输出核心开箱证据；漏发解析 N/M；高危投诉输出四字段；转人工必须读取 queue receipt。删除或改写只断言 `should_transfer=True` 的旧测试，测试必须同时断言 `action_state.status=queued`、`receipt_id` 和实际队列记录。

- [ ] **Step 2: 修改 transfer 节点**

`transfer_to_chatwoot()` 返回 `action_state`；`should_transfer` 只表示计划，不代表执行成功。`main.py` 不再用 `should_transfer` 直接替换成“已转接”。

- [ ] **Step 3: 增加高危投诉响应协议**

缺少责任角色、当前动作、首次响应时效或跟进凭证时，回复计划判定为无效并降级到程序模板。

- [ ] **Step 4: 运行测试并提交**

Run: `python -m pytest tests/customer_service/test_scenario_policy.py tests/e2e/run_customer_agent_20260818_acceptance.py -q`

```bash
git add customer_service agent.py main.py tests/customer_service tests/e2e/run_customer_agent_20260818_acceptance.py
git commit -m "feat: align fulfillment complaint and handoff states"
```

### Task 8: 建立回复计划和虚构状态拦截

**Files:**
- Create: `customer_service/reply_plan.py`
- Create: `customer_service/reply_guard.py`
- Create: `tests/customer_service/test_reply_guard.py`
- Modify: `agent.py:1100-1390`

- [ ] **Step 1: 写虚构状态红灯测试**

```python
@pytest.mark.parametrize("claim", ["已上传", "已收到", "已建单", "已转接", "已审批", "已修改"])
def test_completed_claim_requires_matching_receipt(claim):
    result = guard_reply(claim, conversation_state=empty_state())
    assert result.allowed is False
    assert result.reason_code == "unsupported_completed_action"
```

- [ ] **Step 2: 实现 ReplyPlan**

`ReplyPlan` 包含 facts、must_say、must_not_say、action、next_step 和允许时效。LLM 的输入不包含原始工具异常，只包含公开事实和计划。

- [ ] **Step 3: 实现回复守卫**

完成态词语必须与 `ActionState` 匹配；商品名、日期、库存、责任、时效必须出现在 verified facts 或 policy 中。失败时使用程序模板，不再次调用模型。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/customer_service/test_reply_guard.py tests/e2e/run_mock_business_guard_e2e.py -q`

- [ ] **Step 5: 提交**

```bash
git add customer_service/reply_plan.py customer_service/reply_guard.py agent.py tests/customer_service/test_reply_guard.py
git commit -m "feat: block unsupported customer service claims"
```

### Task 9: 聊天停止与服务端取消

**Files:**
- Create: `tests/test_chat_stream_cancellation.py`
- Create: `tests/e2e/run_customer_chat_stop.py`
- Modify: `main.py:1571-1804`
- Modify: `src/hooks/useChatSSE.js:1208-1525`
- Modify: `src/components/chat/ChatPanel.jsx`
- Modify: `src/components/chat/ChatInput.jsx`

- [ ] **Step 1: 先写最小失败测试**

`tests/test_chat_stream_cancellation.py` 固定三个生命周期断言：客户端断连会让阻塞中的 `agent_app.ainvoke()` 收到 `CancelledError`；全链路超时只产生 `status=failed/reason_code=chat_timeout`；同 tenant、同 session 的新轮次必须先取消并等待旧任务。三种路径都断言没有 `done: completed`，且 `handoff_store.append_message(..., "assistant", ...)` 未被调用。

`tests/e2e/run_customer_chat_stop.py` 用阻塞 Agent 启动真实 SSE，在浏览器点击 `aria-label="停止生成"`，断言输入框恢复可发送、局部助手气泡未写入历史、服务端取消事件已触发。

- [ ] **Step 2: 运行测试确认当前链路失败**

Run: `python -m pytest tests/test_chat_stream_cancellation.py -q`

Expected: FAIL；当前断连只停止客户端读取，服务端任务继续运行，且取消/异常路径仍可能写默认成功回复。

- [ ] **Step 3: 在现有 SSE 生成器内闭环服务端生命周期**

复用 `asyncio.Task`，按 `(tenant_id, session_id)` 保存当前进程内的活动任务。`CHAT_TURN_TIMEOUT_SECONDS` 从环境变量读取，默认 120 秒，非法值在启动时回退默认值并输出中文错误日志。新轮次发现旧任务未结束时先 `cancel()` 再 `await asyncio.gather(..., return_exceptions=True)`；创建新任务后用 `asyncio.timeout(CHAT_TURN_TIMEOUT_SECONDS)` 包住事件消费与最终结果。每次 `queue.get()` 前检查 `await request.is_disconnected()`，并在 `CancelledError`、超时和生成器 `finally` 中统一取消并等待任务；清理活动任务时必须校验字典中的对象仍是本轮 task，避免旧轮次删除新轮次。

只有成功取得最终 `result` 且未取消、未超时时，才允许选择卡片、写入助手消息和发送 `done: completed`。超时发送独立失败事件 `status=failed/reason_code=chat_timeout`；主动停止或断连直接收口，不补默认成功回复。当前进程内单飞是本轮边界，不新增持久化 `chat_turn` ledger。

- [ ] **Step 4: 暴露当前轮次停止动作并切换按钮**

`useChatSSE` 暴露 `stopCurrentTurn()`，内部复用 `abortControllerRef.current.abort()`，同时清理流式状态卡、局部助手文本、presence timer、`isAwaitingStream` 和 `streamInFlightRef`；不把 controller ref 直接交给组件。`ChatPanel` 把 `onStop` 传给 `ChatInput`；生成期间原发送按钮原位切换为 Square 图标停止按钮，保持尺寸不变并设置 `aria-label="停止生成"` 和 tooltip。停止后允许再次发送，但不把局部文本提交到 history。

- [ ] **Step 5: 运行取消与构建门禁**

Run: `python -m pytest tests/test_chat_stream_cancellation.py -q`

Run: `npm run build`

Run: `python tests/e2e/run_customer_chat_stop.py`

Expected: 断连、超时和同 session 替换均无残留服务端任务、无成功回复写入；停止按钮在 PC 与 390px 手机视口均可操作。

- [ ] **Step 6: 提交**

```bash
git add main.py src/hooks/useChatSSE.js src/components/chat/ChatPanel.jsx src/components/chat/ChatInput.jsx tests/test_chat_stream_cancellation.py tests/e2e/run_customer_chat_stop.py
git commit -m "fix: cancel abandoned customer chat turns"
```

### Task 10: API 统一 ConversationState

**Files:**
- Create: `customer_service/public_projection.py`
- Modify: `main.py:1550-1790`
- Create: `tests/customer_service/test_public_projection.py`

- [ ] **Step 1: 写 SSE done 事件契约测试**

```python
def test_done_event_contains_public_conversation_state():
    done = run_chat_case("CHAT-04-MATERIAL-NOT-UPLOADED")
    assert done["conversation_state"]["intent"]["intent_code"] == "product_damage"
    assert done["conversation_state"]["action_state"]["status"] == "not_requested"
```

- [ ] **Step 2: 实现公开投影**

移除内部 Prompt、工具 URL、本地路径、模型、原始证件字段；保留 intent、facts 摘要、材料状态、动作状态和下一步。

- [ ] **Step 3: 修改 SSE**

`unified_analysis`、`transfer`、`card`、`done` 都引用同一个 `conversation_state`。删除根据 `should_transfer` 强制生成“已转接”的分支。

- [ ] **Step 4: 运行测试并提交**

Run: `python -m pytest tests/customer_service/test_public_projection.py tests/e2e/run_mock_business_guard_e2e.py -q`

```bash
git add customer_service/public_projection.py main.py tests/customer_service/test_public_projection.py
git commit -m "feat: expose unified customer conversation state"
```

### Task 11: Web、Pad、手机和坐席同源

**Files:**
- Modify: `src/hooks/useChatSSE.js`
- Modify: `src/components/chat/ChatPanel.jsx`
- Modify: `src/components/chat/MessageList.jsx`
- Modify: `src/components/cards/openUILibrary.jsx`
- Modify: `src/desk/HumanAgentDesk.jsx`
- Create: `tests/e2e/run_customer_state_multidevice.py`

- [ ] **Step 1: 前端状态测试先红灯**

测试 mocked SSE 的 `conversation_state.action_state.status=failed`，页面必须显示“未执行成功”，不能出现“已转接”。

- [ ] **Step 2: 修改 useChatSSE**

保存服务端 conversation_state；禁止从 reply、intent label 或 progress 文案推断动作状态。

- [ ] **Step 3: 修改状态卡**

统一映射：未提交、已请求、已受理、排队中、已完成、失败、等待人工。手机端使用同一映射和字段。

- [ ] **Step 4: 坐席显示事实和回执**

显示事实来源、回执号、失败原因和下一步，不显示内部模型/Prompt。

- [ ] **Step 5: 运行构建和多端测试**

Run: `npm run build`

Run: `python tests/e2e/run_customer_state_multidevice.py`

Expected: PC、Pad、390px 手机均无溢出，状态一致。

- [ ] **Step 6: 提交**

```bash
git add src tests/e2e/run_customer_state_multidevice.py
git commit -m "feat: render unified customer action state across clients"
```

### Task 12: 部署版本握手

**Files:**
- Modify: `main.py`
- Modify: `vite.config.js`
- Modify: `src/App.jsx`
- Create: `tests/test_version_handshake.py`

- [ ] **Step 1: 写版本接口红灯测试**

```python
def test_version_endpoint_has_auditable_fields():
    body = TestClient(app).get("/api/v1/version").json()
    assert set(body) >= {"backend_commit", "frontend_build", "customer_policy_version", "deployed_at"}
```

- [ ] **Step 2: 实现版本接口**

从部署环境变量读取 `MITAKO_BUILD_COMMIT`、`VITE_BUILD_ID`、`MITAKO_CUSTOMER_POLICY_VERSION` 和 `MITAKO_DEPLOYED_AT`；缺失时返回 `unknown`，不运行 Git 子进程。

- [ ] **Step 3: 前端内部诊断区显示版本**

普通用户页面不突出技术字段；管理员/测试模式可复制版本对象。

- [ ] **Step 4: 运行并提交**

```bash
python -m pytest tests/test_version_handshake.py -q
npm run build
git add main.py vite.config.js src/App.jsx tests/test_version_handshake.py
git commit -m "feat: add deployment version handshake"
```

### Task 13: 三轮稳定性与完整验收

**Files:**
- Create: `tests/customer_service/test_three_round_stability.py`
- Create: `tests/e2e/run_customer_agent_20260818_acceptance.py`
- Create: `docs/testing/客服Agent用户沟通回归验收-20260818.md`

- [ ] **Step 1: 三轮结构化稳定性测试**

每个 Case 运行 3 次，只比较 intent、scenario、core_conclusion、action status、next_step；允许自然语言措辞变化。

```python
for case in load_cases():
    results = [run_case(case) for _ in range(3)]
    signatures = {structured_signature(result) for result in results}
    assert len(signatures) == 1, case["case_id"]
```

- [ ] **Step 2: 禁止词和动作回执检查**

对每个结果检查 forbidden_claims；完成态必须能在 action receipt 中找到对应证据。

- [ ] **Step 3: API/Web/坐席一致性检查**

同一个 session 的 SSE、用户状态卡、坐席详情必须具有同一 intent、action status 和 receipt ID。

- [ ] **Step 4: 运行相关全量回归**

Run: `python -m pytest tests/customer_service tests/e2e/run_mock_business_guard_e2e.py -q`

Run: `python tests/e2e/run_customer_agent_20260818_acceptance.py --rounds 3`

Expected:

- 15 场景 × 3 轮全部通过；
- P1 6/6；
- 10 个问题 10/10；
- 虚构执行状态 0；
- 主动停止、断连和超时残留任务 0，取消/超时成功回复写入 0；
- API/Web/坐席差异 0。

- [ ] **Step 5: 写验收报告并提交**

```bash
git add tests/customer_service tests/e2e/run_customer_agent_20260818_acceptance.py docs/testing/客服Agent用户沟通回归验收-20260818.md
git commit -m "test: close 20260818 customer communication regressions"
```

### Task 14: 发布脚本和客户运行时

**Files:**
- Modify: `scripts/package_release.ps1`
- Modify: `scripts/check_release_packages.py`
- Modify: `tests/test_release_layout.py`

- [ ] **Step 1: 发布布局红灯测试**

客户运行时必须包含 `customer_service/*.pyc`，不包含 Python 源码、测试 fixture 或内部 Prompt。

- [ ] **Step 2: 修改打包脚本**

增加 `Copy-RuntimeDir "customer_service"`，保持 `Sanitize-RuntimeSources` 和 Python 3.11 编译边界。

- [ ] **Step 3: 修改验包器**

检查 contracts、intent_router、action_state、scenario_policy、reply_guard 和 public_projection 对应 `.pyc`。

- [ ] **Step 4: 运行发布门禁**

Run: `python -m pytest tests/test_release_layout.py -q`

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package_release.ps1 -ReuseValidatedAcceptanceEvidence`

Run: `python scripts/check_release_packages.py`

- [ ] **Step 5: 提交**

```bash
git add scripts/package_release.ps1 scripts/check_release_packages.py tests/test_release_layout.py
git commit -m "release: package deterministic customer service runtime"
```

### Task 15: 双仓、部署和人工复验

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/product/四场景审核主线进度-20260814.md`
- Create: `docs/release/2026-08-18-customer-chat-recovery-notes.md`

- [ ] **Step 1: 更新版本说明**

明确此版本修复客服对话，不用视觉审核或日志改动冒充沟通质量提升；列出 10 个问题和 15×3 验收结果。

- [ ] **Step 2: 提交私人 main 和公司 PR**

公司 PR 必须包含设计、计划、代码、测试和验收报告；合并前运行对应检查。

- [ ] **Step 3: 部署 Deeptokenai.cn**

设置版本环境变量，部署后调用 `/api/v1/version`，确认 commit、build、policy 和 deployed_at 与 Release 一致。

- [ ] **Step 4: 运行线上三轮回归**

使用同一 15 案，记录 API JSON、页面截图和坐席状态；不得读取人工答案作为 Agent 输入。

- [ ] **Step 5: 人工客服复验**

复验表逐项记录通过/不通过、差异和截图；任何 P1 不通过不得发布。

- [ ] **Step 6: 发布新版本**

生成内部研发包、甲方运行包、验收证据包；双仓 tag 和 Release 同步上传并记录 SHA256。

---

## 完成审计

在宣称目标完成前逐项确认：

- [ ] PDF 10 个问题全部有对应测试和真实验收结果。
- [ ] 15 个场景均运行 3 轮。
- [ ] P1 6/6。
- [ ] 复合诉求保留全部原子意图与场景，客服编排只消费四场景唯一契约的公开结果。
- [ ] 商品咨询不存在 `key in str(value)` 恒真命中，无唯一 SKU/链接/订单行时只追问。
- [ ] 虚构执行状态 0。
- [ ] 主动停止、SSE 断连、全链路超时和同 session 替换均取消并等待服务端任务，残留活动任务 0，取消/超时成功回复写入 0。
- [ ] API/Web/Pad/手机/坐席状态一致。
- [ ] Deeptokenai.cn 版本握手与发布提交一致。
- [ ] 私人、公司仓库 main、tag 和三份 ZIP 均已发布。
- [ ] 真实甲方接口仍为 Mock 与契约说明，旧 Companion/陪伴/角色扮演/文字冒险能力保持封存，公开页面不暴露模型、Key、内部 Prompt 或调试参数。

最终验证命令：

```powershell
python -m pytest tests/customer_service tests/test_chat_stream_cancellation.py tests/e2e/run_mock_business_guard_e2e.py -q
python tests/e2e/run_customer_chat_stop.py
python tests/e2e/run_customer_agent_20260818_acceptance.py --rounds 3
npm run build
python tests/e2e/run_customer_state_multidevice.py
python -m pytest tests/test_release_layout.py -q
python scripts/check_release_packages.py
```

剩余风险：本轮同 session 单飞只覆盖当前服务进程，不新增持久化 `chat_turn` ledger。仅当甲方要求服务重启后继续未完成轮次或需要逐轮审计时，才扩展持久化生命周期账本。
