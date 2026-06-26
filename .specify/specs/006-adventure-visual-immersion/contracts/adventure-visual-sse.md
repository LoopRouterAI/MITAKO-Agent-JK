# Contract: Adventure Visual SSE Events

**Version**: v2.1-draft  
**Base**: `/api/v2/companion/adventure/start|chat` (existing SSE)

## Existing Events (unchanged)

`safety`, `review`, `chunk`, `api_log`, `choices`, `card`, `session`, `message`, `done`, `adventure_exit`

## New Events

### `inner_parsed`

伙伴消息解析出内心块（可选，可在 `message` payload 内嵌代替独立事件）。

```json
{
  "message_id": "msg_xxx",
  "inner": {
    "summary": "担心主人脚下青苔",
    "full": "……完整内心……"
  }
}
```

### `illust_queued`

文字叙事已落库，配图任务入队。

```json
{
  "message_id": "msg_xxx",
  "illust_type": "scene",
  "placeholder": true
}
```

### `illust_generating`

```json
{
  "message_id": "msg_xxx",
  "stage": "prompt_build | u1 | agnes_fallback",
  "model_id": "sensenova-u1-fast"
}
```

### `illust_ready`

```json
{
  "message_id": "msg_xxx",
  "asset_id": "asset_xxx",
  "url": "https://...",
  "size": "2752x1536",
  "aspect": "16:9",
  "model_id": "sensenova-u1-fast"
}
```

### `illust_failed`

```json
{
  "message_id": "msg_xxx",
  "reason": "quota_exhausted | api_error | cooldown",
  "user_hint": "i18n key companion.adventureIllustFailed"
}
```

### `illust_skipped`

未触发或 cooldown 跳过。

```json
{
  "message_id": "msg_xxx",
  "reason": "cooldown | no_marker"
}
```

### `visual_asset_ready`

设定图（非回合插图）完成，供 Monitor / 可选 UI 预览。

```json
{
  "asset_id": "asset_xxx",
  "asset_type": "character_sheet | scene_board",
  "entity_key": "char:小伴",
  "url": "https://..."
}
```

## REST Extensions

### GET `/api/v2/companion/adventure/assets/{user_id}`

Query: `session_id`, `type`

Response:

```json
{
  "ok": true,
  "assets": [
    {
      "id": "asset_xxx",
      "asset_type": "scene_board",
      "entity_key": "scene:暗河支流",
      "url": "https://...",
      "status": "ready"
    }
  ]
}
```

### GET `/api/v2/companion/adventure/bible/{user_id}`

Response: `{ "ok": true, "bible": { ... } }`

## Narrative Markup (LLM output contract)

| Markup | Meaning |
|--------|---------|
| `>>场景名<<` | 场景标题 |
| `---` | 段落分隔 |
| `【…】` | 第三人称旁白块 |
| `「…」` | 对白 |
| `<inner>摘要\|正文</inner>` | 伙伴内心（仅一条/回合） |
| `<illust:scene>` | 请求 16:9 场景插图 |
| `<illust:photo>` | 请求 3:4 照片插图 |
| `[1]…` | 选项（剥离到 footer） |

## Message Payload Extension (`message` event)

```json
{
  "id": "msg_xxx",
  "role": "assistant",
  "content": "…strip markers…",
  "choices": [],
  "mode": "adventure",
  "inner": { "summary": "…", "full": "…" },
  "illust": {
    "status": "queued",
    "type": "scene"
  }
}
```

## Frontend Handling

1. 收到 `message` → 渲染文字 + `InnerThoughtBlock` + 若 `illust.status=queued` 显示 Skeleton
2. 收到 `illust_ready` → 更新同 `message_id` 的 `AdventureIllustCard`
3. Monitor 订阅 `illust_generating` / `api_log` stage `adventure_illust_*`
