# Data Model: 冒险视觉沉浸

**Feature**: 006-adventure-visual-immersion

## Entity Relationship

```text
companion_adventure_sessions (1) ──< companion_adventure_bible (1)
        │
        ├──< companion_adventure_visual_assets (*)
        ├──< companion_adventure_summaries (*)
        └──< companion_adventure_messages (*)
                    └── optional illust_asset_id FK
```

## Tables (SQLite extensions)

### companion_adventure_bible

| Column | Type | Notes |
|--------|------|-------|
| user_id | TEXT PK | |
| tenant_id | TEXT | default mitako |
| world_setting | TEXT | 用户输入 |
| bible_json | TEXT | WorldBible JSON |
| visual_style | TEXT | 供生图 |
| token_estimate | INTEGER | 最后估算 |
| updated_at | TEXT ISO | |

### companion_adventure_visual_assets

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | `asset_{uuid}` |
| user_id | TEXT | |
| tenant_id | TEXT | |
| session_id | TEXT | 关联 adventure session |
| asset_type | TEXT | character_sheet \| scene_board \| turn_illust |
| entity_key | TEXT | e.g. `scene:暗河支流` `char:伙伴` |
| image_url | TEXT | CDN |
| local_path | TEXT | 可选镜像 |
| prompt_text | TEXT | 完整送模 prompt |
| prompt_hash | TEXT | 去重 |
| model_id | TEXT | sensenova-u1-fast / agnes-... |
| size | TEXT | 2752x1536 等 |
| meta_json | TEXT | HEX 色板、镜头注释 |
| status | TEXT | pending \| ready \| failed |
| created_at | TEXT | |

### companion_adventure_summaries

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| user_id | TEXT | |
| tenant_id | TEXT | |
| from_turn | INTEGER | |
| to_turn | INTEGER | |
| summary_text | TEXT | 第三人称摘要 |
| created_at | TEXT | |

### companion_adventure_messages (alter)

| New Column | Type | Notes |
|------------|------|-------|
| inner_json | TEXT | `{summary, full}` 解析后存 |
| illust_asset_id | TEXT | FK visual_assets |
| illust_status | TEXT | none \| queued \| ready \| failed |

### companion_adventure_illust_queue

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | |
| user_id | TEXT | |
| message_id | TEXT | 绑定 assistant msg |
| intent_json | TEXT | IllustIntent |
| state | TEXT | queued \| running \| done \| failed |
| attempts | INTEGER | |
| error | TEXT | |
| created_at | TEXT | |

## JSON Schemas (logical)

### WorldBible

```json
{
  "era_label": "string",
  "tech_ceiling": "string",
  "address_user": "主人",
  "address_agent": "伙伴名",
  "visual_style": "string",
  "color_mood": "string",
  "anachronism_policy": "unknown_object | analogize | refuse",
  "taboo_list": ["string"]
}
```

### IllustIntent

```json
{
  "type": "scene | photo",
  "mood": "string",
  "subjects": ["string"],
  "scene_key": "string",
  "shot_notes": "string"
}
```

## State Transitions

### Illustration Job

```text
queued → running → done
                 ↘ failed → (retry fallback model) → done | failed
```

### Message illust_status

```text
none → queued → ready
              ↘ failed
```

## Validation Rules

- `inner_json` 仅当 role=assistant 且 mode=adventure
- 同 `entity_key` + `prompt_hash` 不重复生成（复用 URL）
- 单会话 `turn_illust` 计数 ≤ `ADVENTURE_ILLUST_MAX_PER_SESSION`
- bible 在 `start_adventure` 时生成，exit 不删（可选保留供重进）
