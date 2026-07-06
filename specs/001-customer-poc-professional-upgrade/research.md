# Research: 商业级客服 POC 专业化升级

## Decision 1: 视觉风格以视觉审核工作台为锚点

**Decision**: 用户端、人工台、后台统一向 `poc/visual_review_poc/workbench.html` 的明亮工具风格靠拢：白底、柔和阴影、细边框、局部多巴胺渐变、降低硬黑边和大面积青柠。

**Rationale**: 当前后台和人工台存在大量全局黑边、硬投影和过亮绿色，导致状态块像按钮、工具感粗糙。视觉审核工作台是用户明确认可的参考锚点。

**Alternatives considered**:

- 继续沿用 PPT 黑边卡通风格：演示冲击强，但客服后台不够专业。
- 完全改成冷静 B2B 灰蓝风格：稳定，但不符合用户要求的多巴胺/PPT 气质。

## Decision 2: 演示数据必须有生命周期，但不伪装成真实接口

**Decision**: 后台需要提供“演示数据状态、加载、清空、空状态说明”，并明确当前外部业务数据来自 Mock 或演示样本。

**Rationale**: 甲方需要看到真实界面交互长什么样，但不能被误导为已接入生产订单/仓库/清关/退款系统。

**Alternatives considered**:

- 页面默认塞满假数据：容易误导甲方。
- 默认空白：无法展示系统价值。

## Decision 3: 人工客服工作台按真实坐席流程组织

**Decision**: 人工台操作区拆成接手确认、回复、转交/升级、结案；会话列表必须展示诉求差异、等待时长、风险等级、建议下一步。

**Rationale**: 客服人员在高压队列中需要先判断“这单是谁、等多久、诉求是什么、下一步做什么”，不能靠阅读长服务记录自行推理。

**Alternatives considered**:

- 保留三栏桌面布局，仅改样式：无法解决移动端和流程混层问题。
- 全量重写工作台：风险高，容易丢现有接手/转交能力。

## Decision 4: 视觉审核工作台保留独立展示页，但支持三大任务直达

**Decision**: 保留总览页用于展示实力，同时支持 `?scenario=video_unboxing`、`?scenario=product_damage`、`?scenario=minor_material` 直达具体审核任务。

**Rationale**: 甲方实际客服不会在一个入口反复选择场景；但售前演示需要总览。

**Alternatives considered**:

- 只保留单页下拉：理解成本高。
- 拆成三个服务：部署和维护成本过高。

## Decision 5: 运维 BI 只吸收 Relay Pulse / Check CX 的核心思想

**Decision**: 不引入外部 Go/Postgres 或独立监控项目，只在现有后台展示可用率、延迟、连续运行、队列压力、SLA 告警、模型/视觉审核调用状态。

**Rationale**: POC 阶段需要“简单可靠有用”，不是部署完整监控平台。

**Alternatives considered**:

- 接入 Relay Pulse 完整系统：超出当前交付范围。
- 只展示 uptime：不能说明 Agent 客服业务是否健康。

## Decision 6: 安全边界优先于演示便利

**Decision**: `/api/v1/handoff/reset` 必须要求匹配 handoff token 或后台/坐席权限，不能无 token 删除会话。

**Rationale**: 子 Agent 审查发现该接口可按 session_id 删除会话、消息、转交事件和业务审计，这是商业 POC 的 P0 风险。

**Alternatives considered**:

- 仅在前端隐藏按钮：不能防止直接请求。
- 继续默认租户删除：破坏租户与数据隔离叙事。
