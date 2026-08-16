# Research: 冒险视觉沉浸与配图

**Feature**: 006-adventure-visual-immersion  
**Date**: 2026-06-19

## R1 — 生图主备选型

**Decision**: 主路径 SenseNova U1 Fast（`POST /v1/images/generations`，model `sensenova-u1-fast`）；失败 fallback [Agnes Image 2.1 Flash](https://agnes-ai.com/doc/agnes-image-21-flash)。

**Rationale**:

- 项目已有 `image_service.py` + `image_models.py` 注册 U1，共用 `SENSENOVA_API_KEY`。
- U1 专长**信息图/设计板**排版，与用户提供的「高密度集成设定图」思路一致（单次 2752×1536 多视图阵列）。
- Agnes 作为零成本兜底，避免单点失败导致聊天白屏。

**Alternatives considered**:

| 方案 | 弃用原因 |
|------|----------|
| GPT-Image / Nano Banana 2 | 用户指定 U1 优先；且需额外 Key |
| 每镜单独 SD 抽卡 | 一致性差、quota 消耗大 |
| img2img 参考图 | U1 当前不支持 image input |

## R2 — 一致性策略（无 img2img）

**Decision**: 「一次生成设定板 + 文字引用资产」三层：

1. **Character Sheet**：五视图 + 表情 + 特写（2K 横板，U1 prompt 见 playbook）
2. **Scene Board**：主视觉 + 时间切片 + 空间视图 + 材质特写 + HEX 色板
3. **Turn Illustration**：prompt 首部注入 `ASSET_REF: character={name} scene={id} hex={...}` 与 bible 风格句

**Rationale**: U1 仅文本 prompt；通过高密度设计表 prompt 把多角度/色板压进单次生成，减少调用次数（用户强调的「极致省钱」）。

## R3 — 插图尺寸规范

**Decision**:

| 类型 | 比例 | U1 size 参数 | 用途 |
|------|------|--------------|------|
| 设定板 / 场景图 | 16:9 | `2752x1536` | scene_board、turn scene |
| 照片式插图 | 3:4 | `1760x2368` | 角色特写、拍立得感 |

**Rationale**: 与用户要求一致；场景横屏沉浸、人物竖屏贴近手机聊天流。

## R4 — 内心独白标记

**Decision**: `<inner>一行摘要|完整内心</inner>`

- 仅伙伴 assistant 消息允许
- 前端默认折叠，展示摘要 + chevron
- 流式时未闭合标签不渲染，完成后 parse

**Alternatives**: `~波浪~`（易与删除线冲突）、`> 引用`（已用于独白）

## R5 — 插图触发协议

**Decision**: 叙事 LLM 在正文末尾（选项前）输出一行结构化标记：

```text
<illust type="scene" mood="tense" subjects="伙伴,主人,岩道" />
```

或简写 `<illust:scene>` / `<illust:photo>`。

后端 `IllustIntentParser` 剥离标记，不展示给用户；决定是否入队（受 cooldown 约束）。

## R6 — 上下文 128K 压缩

**Decision**: 分层上下文包（送入 LLM 顺序）：

1. System（bible + 规则 + 资产 caption 列表）≈8–15K
2. `adventure_summary` 滚动摘要 ≈10–20K
3. 最近 8 回合完整 messages ≈60–80K
4. 当前 user message

超 100K（字符×1.5 启发式）触发：将第 9–20 回合合并写入 summary，删除原文引用。

**Rationale**: SQLite 存全文归档；LLM 仅吃压缩包。128K 为硬预算，非精确 tiktoken（v1 heuristic，v1.1 可换 tiktoken）。

## R7 — 世界观纠偏

**Decision**: 开局生成 `WorldBible` JSON：

```json
{
  "era": "古代三国",
  "tech_ceiling": "冷兵器与机关术",
  "anachronism_policy": "unknown_object",
  "visual_style": "电影级半写实",
  "forbidden_topics": ["现代枪械直述"]
}
```

用户输入经 lightweight classifier（regex + 可选 LLM）检测 anachronism → 注入 `（系统：请以{bible}内认知回应，勿接受现代物品）` 到 user 消息前缀。

伙伴示例：不懂「加特林」→「从未听闻此物名，是西域奇械么？」

## R8 — UI Loading 时机

**Decision**:

| 事件 | UI |
|------|-----|
| `illust_queued` | 消息下 shimmer 卡「正在绘制本镜…」 |
| `illust_generating` | 进度 indeterminate + 可选阶段文案 |
| `illust_ready` | 替换为图片卡，fade-in |
| `illust_failed` | 轻量文案 + 保留文字 |

文字 SSE **先完成**再并行配图，避免用户只看 Loading。

## R9 — Quota 与降级

**Decision**: 复用 `llm_rate_limit.py` 模式；U1 1500/5h 用尽 → 直接 Agnes；两者皆失败 → 跳过插图，SSE `illust_skipped` reason=quota。

## References

- 内部 playbook: [docs/adventure/image-prompt-playbook.md](../../docs/adventure/image-prompt-playbook.md)
- U1 API: `.env.example` + 用户提供文档
- Agnes: https://agnes-ai.com/doc/agnes-image-21-flash
- 现有实现: `image_service.py`, `companion_adventure.py`
