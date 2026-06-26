# Feature Specification: 冒险输入社交与富文本契约

**Feature ID**: `007-adventure-input-social`

**Created**: 2026-06-19

**Status**: In Progress

**Input**: DeepSeek 统一审核；GalGame 式 / 与 @ 输入；富文本 canonical 语法稳定；/冒险 须记忆隔离确认。

## User Scenarios

### US1 — Persona / 冒险内容 DeepSeek 审核 (P1)

作为运营/用户，所有影响 LLM 的 persona 字段与冒险叙事输出应经 **DeepSeek V4 Flash（SENSENOVA_API_KEY）** 审核，而非依赖用户当前选的主模型 Key。

**Acceptance**:

- `COMPANION_REVIEW_MODEL=deepseek-v4-flash` 为默认
- Persona L2 与 Adventure Reviewer 共用审核链
- 无 Key 时 L1 仍生效，Monitor 可标注 L2 skip

### US2 — @ 圈人与 / GalGame 指令 (P1)

作为冒险玩家，我可通过 `@伙伴名` / `@NPC` 指定对话对象，通过 `/观察` `/威胁` 等指令表达行动，无需手打名称。

**Acceptance**:

- 输入 `@` 弹出候选（伙伴、主人、近期 NPC）
- 发送时展开为 `【对 X 说】` 结构化前缀
- `/` 菜单含 GalGame 行动指令
- `/冒险` 仍弹出记忆隔离 Modal

### US3 — 富文本 Canonical 语法 (P1)

LLM 与前端仅使用稳定 markup；误用 `>标题>`、`>/SAY>>` 等须在 normalize 层修复。

**Canonical**:

| 用途 | 语法 |
|------|------|
| 场景 | `>>标题<<` |
| 对白 | `<say role="agent\|npc\|user" name="名">台词</say>` |
| 旁白 | `【…】` |
| 内心 | `<inner>摘要\|正文</inner>` |

**禁止**: `<>`、`>title>`、行首 `>` 作内心（与 blockquote 冲突）

## Non-Goals

- 完整 GalGame 存档系统
- 实时 NPC 自动抽取 NER（当前从 dialogues + 预设词表）

## Related

- `006-adventure-visual-immersion` — 配图/内心 UI
- `companion_review_config.py` — 审核模型配置
