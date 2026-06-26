# Tasks: 006-adventure-visual-immersion

**Ordered by dependency** — `[P]` 可并行

## Phase A — 内心独白 UI + 富文本 (P1)

- [ ] **A1** 在 `companion_richtext.py` 增加 `<inner>摘要|正文</inner>` 规范与 `parse_inner_thought()`
- [ ] **A2** 更新 `build_adventure_system` + 新建 `prompts/adventure-narrative.md`（人称/旁白/inner 规则）
- [ ] **A3** `formatText.js`：`parseAdventureInner()` + 从正文剥离 inner 供 UI 组件渲染
- [ ] **A4** 新建 `InnerThoughtBlock.jsx`，i18n keys（`adventureInnerExpand` 等）
- [ ] **A5** `CompanionMessageList` 集成内心块；流式完成后 parse
- [ ] **A6** 单元测试：inner 解析边界（未闭合、多条 inner 取首条）

## Phase B — World Bible + OOC (P2)

- [ ] **B1** 表 `companion_adventure_bible` + store CRUD
- [ ] **B2** `companion_adventure_context.py`：`generate_world_bible()` LLM 调用
- [ ] **B3** `detect_anachronism()` regex 集 + 注入纠偏 user 前缀
- [ ] **B4** 开局 `start_adventure` 生成 bible SSE `bible_ready`
- [ ] **B5** 40 条 OOC 语料测试 fixture

## Phase C — Prompt Builder + Playbook (P1)

- [ ] **C1** 编写 [docs/adventure/image-prompt-playbook.md](../../docs/adventure/image-prompt-playbook.md)（团队评审）
- [ ] **C2** 新建 `companion_adventure_visual.py`：`PromptBuilder.character_sheet()`
- [ ] **C3** 同文件：`PromptBuilder.scene_board()` / `turn_illust()`
- [ ] **C4** `IllustIntentParser` 解析 `<illust:scene|photo>`
- [ ] **C5** 表 `companion_adventure_visual_assets` + store
- [ ] **C6** 单元测试：prompt 含 HEX、镜头术语、世界观 style 注入

## Phase D — 生图队列 + SSE + 前端 (P2)

- [ ] **D1** `IllustQueue` asyncio 串行 worker（同 user_id）
- [ ] **D2** 集成 `image_service.generate_image` 主路径
- [ ] **D3** 新建 `agnes_image_service.py` + `image_models` 注册 fallback
- [ ] **D4** `companion_api.py` 发射 `illust_*` / `visual_asset_ready` 事件
- [ ] **D5** `useCompanionChat.js` 处理 illust SSE + 消息 state
- [ ] **D6** 新建 `AdventureIllustCard.jsx` + Loading skeleton
- [ ] **D7** Monitor `api_log` stage `adventure_illust_*`
- [ ] **D8** cooldown：`ADVENTURE_ILLUST_COOLDOWN_TURNS`

## Phase E — 上下文 128K (P3)

- [ ] **E1** `companion_adventure_context.py`：`estimate_tokens()` heuristic
- [ ] **E2** `build_context_bundle()` + 滚动摘要 LLM
- [ ] **E3** 表 `companion_adventure_summaries`
- [ ] **E4** `stream_adventure_turn` 改用 bundle 组装 messages
- [ ] **E5** 单元测试 100 回合 ≤128K

## Phase F — 集成与 E2E (P2)

- [ ] **F1** `.env.example` 补充 AGNES / ILLUST 配置项
- [ ] **F2** Playwright：`tests/e2e/adventure_visual.spec.ts`
- [ ] **F3** 更新 `docs/delivery/system-b-companion.md` 链接本 spec
- [ ] **F4** `/speckit-analyze` 交叉检查

## Parallel Tracks

```text
A1-A6 ──┬──> D5-D6
B1-B5 ──┤
C1-C6 ──┴──> D1-D4
E1-E5 (after B)
F* (after D,E)
```

## MVP Slice（可演示最小集）

**A1–A5 + C2 + D2 + D5–D6**：内心折叠 + 单张场景图 + Loading，不含 bible 压缩与 Agnes。
