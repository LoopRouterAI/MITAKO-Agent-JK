# Feature Specification: 冒险模式视觉沉浸与配图系统

**Feature ID**: `006-adventure-visual-immersion`

**Created**: 2026-06-19

**Status**: Draft → Ready for Plan

**Input**: 为 Companion 文字冒险增加伙伴内心独白交互、LLM+生图协同配图、世界观一致性守卫、128K 级上下文压缩；目标百万级用户规模。

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 伙伴内心可展开 (Priority: P1)

作为冒险中的用户，我希望看到伙伴的**内心想法**以可识别、可折叠的方式呈现（仅伙伴有，用户无），这样我在阅读剧情时能选择「浅读对话」或「深读心理」，而不被大段心理描写打断节奏。

**Why this priority**: 内心独白是角色沉浸的核心差异化；实现成本低、体验增益高，且不依赖生图 API。

**Independent Test**: 进入任意冒险会话，收到含内心标记的回复后，默认折叠显示摘要，点击可展开全文；再次点击可收起。

**Acceptance Scenarios**:

1. **Given** 伙伴回复含内心内容，**When** 消息渲染完成，**Then** 内心块默认折叠，显示一行摘要（如「💭 伙伴在想…」），正文不可见。
2. **Given** 内心块已折叠，**When** 用户点击，**Then** 平滑展开完整内心文本，不影响选项栏与输入框可用性。
3. **Given** 用户消息或【旁白】块，**When** 渲染，**Then** 不出现内心折叠 UI（仅伙伴内心）。

---

### User Story 2 — 场景/角色设定图一次生成、全程复用 (Priority: P1)

作为用户，我希望每次进入新世界观或切换新场景/新角色时，系统自动生成**高密度设定参考图**（角色表 + 场景板），后续每回合插图都引用这些资产，使人物与场景视觉一致。

**Why this priority**: 无一致性资产则配图随机、破坏沉浸；这是配图系统的根基。

**Independent Test**: 开启「原神·璃月」冒险 → 首屏出现设定图生成 Loading → 完成后资产入库；同会话后续插图风格/角色面貌保持一致。

**Acceptance Scenarios**:

1. **Given** 用户确认进入新世界观，**When** 会话开始，**Then** 触发角色设定图 + 首个场景设定图生成（可并行），聊天区显示占位 Skeleton。
2. **Given** 叙事 LLM 标记 `>>新场景<<`，**When** 场景 ID 变化，**Then** 若该场景无设定图则生成场景板后再出插图；已有则复用。
3. **Given** 出现新命名 NPC，**When** 该角色首次登场，**Then** 生成该角色迷你设定卡并关联后续插图 prompt。

---

### User Story 3 — 回合配图与聊天记录一体展示 (Priority: P2)

作为用户，我希望在关键剧情节点看到**横屏 16:9 场景图**或**竖屏 3:4 照片式**插图，与当回合消息绑定，生成过程中有明确 Loading，失败时有降级文案而非白屏。

**Why this priority**: 配图是视觉沉浸的直接载体，依赖 P1 资产层。

**Independent Test**: 完成一回合对话后，消息气泡下方出现配图卡片；生成中显示 shimmer 占位；完成后可点击查看大图。

**Acceptance Scenarios**:

1. **Given** 叙事完成且 LLM 输出 `<illust:scene>` 或等价标记，**When** 配图任务入队，**Then** 消息区立即显示「正在绘制场景…」占位，不阻塞继续阅读文字。
2. **Given** 配图成功，**When** 渲染，**Then** 16:9 场景图以全宽卡片展示；照片类为 3:4 竖图，圆角与冒险主题一致。
3. **Given** 主生图服务失败，**When** 触发兜底，**Then** 自动切换备用模型重试一次；仍失败则保留文字并显示「本镜暂未能呈现」轻提示。

---

### User Story 4 — 世界观纠偏保持沉浸 (Priority: P2)

作为用户，当我输入与当前时代/场景不符的内容（如古代背景说「加特林」「坐飞机」），伙伴应以**世界观内认知**回应（不懂、用相近事物类比、礼貌困惑），而不是跳出角色或硬接现代设定。

**Why this priority**: 百万用户规模下 OOC（Out of Character）会快速流失；与现有安全围栏互补。

**Independent Test**: 在三国冒险中输入「我开直升机来接你」→ 伙伴表示不明该物，用「机关鸢/奇械」等世界观内类比或纯困惑，不开启现代剧情。

**Acceptance Scenarios**:

1. **Given** 冒险已锁定世界观 bible，**When** 用户输入时代错位概念，**Then** 回复在 200 字内完成纠偏，不指责用户，提供 2–3 个世界观内替代选项。
2. **Given** 用户坚持现代武器/科技，**When** 连续 2 轮，**Then** 伙伴温柔拉回当前场景目标，不生成违规或违和插图 prompt。

---

### User Story 5 — 长会话上下文可控 (Priority: P3)

作为长期冒险用户，我希望系统在接近上下文上限前自动**压缩历史**（保留 bible、设定图索引、最近 N 回合、关键抉择），使单会话可持续数小时且响应稳定。

**Why this priority**: 百万用户意味着长会话与重试多；128K 是工程目标而非用户可见功能。

**Independent Test**: 模拟 80+ 回合后发起新消息，总 prompt token 估算 ≤128K，且最近 5 回合原文完整、关键 NPC/场景未丢失。

**Acceptance Scenarios**:

1. **Given** 会话 token 估算 >100K，**When** 新回合开始，**Then** 自动摘要较早回合写入 `adventure_summary`，原文归档可检索。
2. **Given** 压缩已发生，**When** 用户询问 10 回合前的抉择，**Then** 伙伴仍能基于摘要正确回忆（抽样测试 ≥90%）。

### Edge Cases

- 生图配额用尽（U1 1500/5h）：排队提示 + 仅文字模式，不崩溃。
- 用户快速连点选项导致并发配图：同一会话配图队列串行，后者合并或取消重复任务。
- 世界观含用户自定义合法内容：风格跟随 `world_setting`，但安全围栏仍拦截违法/色情/涉政。
- 内心块与流式打字机：流式期间内心标记未闭合时不渲染折叠 UI，完成后一次性呈现。
- 离线/无 API Key：跳过配图与设定图，冒险文字模式仍可用。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 支持伙伴专属内心富文本标记，并在 UI 中默认折叠、点击展开/收起。
- **FR-002**: 系统 MUST 在冒险会话级维护「世界观 bible」（称谓、时代、禁忌、视觉风格关键词）。
- **FR-003**: 系统 MUST 在新世界观/新场景/新命名角色首次出现时，生成并持久化设定参考图元数据（URL、prompt 快照、版本）。
- **FR-004**: 系统 MUST 由叙事 LLM 输出结构化插图意图（类型 scene/photo、主体、情绪、镜头），再由独立 prompt 构建器生成生图 prompt；禁止直接把用户原文送生图。
- **FR-005**: 系统 MUST 默认使用 SenseNova U1 Fast；失败时自动 fallback Agnes Image 2.1 Flash（可配置关闭）。
- **FR-006**: 系统 MUST 区分横屏 16:9（2752×1536）场景图与竖屏 3:4（1760×2368）照片式插图。
- **FR-007**: 系统 MUST 在配图进行中于消息流展示 Loading 占位，完成后与消息 ID 绑定展示；历史消息重新加载时图片仍可用（本地或 CDN URL 持久化）。
- **FR-008**: 系统 MUST 对时代/场景错位输入执行世界观纠偏，不破坏伙伴人设与安全围栏。
- **FR-009**: 系统 MUST 将会话上下文压缩至约 128K token 预算内，保留 bible + 资产索引 + 摘要 + 最近完整回合。
- **FR-010**: 冒险记忆 MUST 继续与日常 OpenViking 隔离；配图资产与冒险摘要仅存在于冒险存储域。
- **FR-011**: 所有用户可见文案 MUST 走 i18n；Loading/错误/折叠摘要须可本地化。
- **FR-012**: Monitor 观测台 MUST 可查看配图任务阶段（prompt 构建 / U1 / fallback / 完成 / 失败）与 quota。

### Key Entities

- **AdventureWorldBible**: 世界观锁定文本、视觉风格、时代标签、纠偏策略摘要。
- **AdventureVisualAsset**: 类型（character_sheet | scene_board | turn_illust）、关联 scene_id/character_id、image_url、prompt_hash、model_used、size。
- **AdventureIllustIntent**: LLM 输出的插图结构化意图（turn_id、illust_type、subjects、mood、shot_notes）。
- **AdventureContextBundle**: 送入叙事 LLM 的压缩包（bible + summaries + recent_messages + asset_captions）。
- **CompanionInnerThought**: 消息内嵌块，含 summary/full_text，仅 role=assistant。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 90% 测试用户能在 3 次点击内理解内心折叠交互（可用性走查 n≥5）。
- **SC-002**: 同会话内连续 10 张插图，角色面部/服装一致性主观评分 ≥4/5（内部评审量表）。
- **SC-003**: 配图请求 p95 首帧占位出现 <500ms（文字 SSE 完成后立即插入占位事件）。
- **SC-004**: 主模型失败后兜底成功率 ≥85%（staging 100 次抽样）。
- **SC-005**: 80 回合模拟后上下文估算 ≤128K tokens，且最近 5 回合零截断。
- **SC-006**: 世界观纠偏场景通过率 ≥95%（预设 40 条 OOC 测试语料）。
- **SC-007**: 生图配额耗尽时会话可继续，零白屏/零未捕获异常（E2E）。

## Assumptions

- SenseNova U1 Fast 与 Agnes 2.1 Flash 在演示期免费，生产需监控 quota 与成本。
- U1 Fast 不支持 image input；一致性靠**高密度文字 prompt + 设定图 URL 写入 prompt 描述**（非 img2img），后续若 API 支持再升级。
- 设定图/插图 URL 由第三方 CDN 提供；需考虑过期与本地缓存策略（SQLite 存 URL + fetched_at）。
- 叙事 LLM 仍使用用户已配置的 `deepseek-v4-flash` 等，不在本特性中变更模型 ID。
- 配图触发由 LLM 显式标记控制，避免每回合都生图导致 quota 爆炸；默认每 2–3 回合最多 1 张插图（可配置）。

## Out of Scope (v1)

- 视频生成（Seedance 等）与 img2img 参考图上传。
- 用户上传参考图自定义角色脸。
- 多伙伴同框独立设定（仅主角伙伴 + NPC 列表）。
