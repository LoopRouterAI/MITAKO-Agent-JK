# 冒险配图 Prompt Playbook

**版本**: 1.0  
**适用模型**: SenseNova U1 Fast（主）· Agnes Image 2.1 Flash（备）  
**维护**: MITAKO Companion 冒险模式 · Feature 006

---

## 1. 设计哲学

### 1.1 高密度集成（一次生成、多次引用）

传统流程「一词一图」在长篇冒险中不可持续。本 playbook 要求：

- **角色**：一张 2K 角色设计表（多角度 + 表情 + 特写）
- **场景**：一张场景一致性板（主视觉 + 时间切片 + 空间视图 + 材质 + 色板）
- **回合插图**：在 prompt 中**文字引用**已生成资产的 entity_key、HEX 色板、镜头术语，而非 img2img

U1 Fast 擅长信息图排版；prompt 必须包含**排版指令**（网格、提案板、设计表），强制模型在单帧内输出多信息块。

### 1.2 强语义控制

使用影视行业术语提高命中率：

| 术语类 | 示例 |
|--------|------|
| 焦段 | 35mm 全身 / 50mm 半身 / 85mm 浅景深特写 |
| 景别 | WS 宽屏 / MCU 中近景 / CU 特写 / OTS 过肩 |
| 设备 | ARRI Alexa 35 色彩科学 |
| 结构 | 三幕结构、预可视化提案板 |

### 1.3 世界观风格注入

所有 prompt 首部固定注入（由 `WorldBible.visual_style` 替换）：

```text
VISUAL_WORLD: {visual_style}，严格遵守世界观「{era_label}」，禁止出现与时代不符的现代 UI/枪械/车辆除非 bible 允许。
PALETTE_REF: {hex_list_from_scene_board}
CHAR_REF: {agent_name} 外观以 character_sheet asset_{id} 为准：{one_line_appearance}
```

---

## 2. 角色设定图 Template（character_sheet）

**输出尺寸**: `2752x1536` (16:9)  
**触发**: 冒险 `start` 后首次，或新命名 NPC 首次登场

```text
你是国际一流的电影人物原画师。为「{world_title}」世界观制作伙伴「{agent_name}」的数字资产设计表。

排版：电影级角色设计表，暗调深色背景，艺术化不对称网格排版，专业工作室提案级。

角色描述：
{appearance_from_bible_or_persona}
{world_costume_notes}

视图必须包含（在同一画面中分区排列）：
- 五角度全身一致性（正/侧/背/3/4）
- 多角度表情头像研究（喜/怒/忧/惊/平静）
- 一张 85mm 浅景深电影感特写静帧

镜头与光影：
85mm 特写浅景深，35mm 全身自然曝光，柔和主光，电影级冷暖环境光，半写实，照片级肤质。

画质：
8K 级细节描述，流畅阴影，柔和照明，控制细节密度，无噪点、无过度锐化、无脏乱纹理。

文本渲染规则：
仅渲染带双引号的小节标题为画面内文字（不含引号本身）；其余描述不得变成画面文字。

禁止：现代 UI、水印、logo、二维码。
```

**后处理**: 从生成结果 meta 人工或 LLM 提取一行 `appearance_caption` 写入 DB，供后续 turn_illust 引用。

---

## 3. 场景一致性板 Template（scene_board）

**输出尺寸**: `2752x1536` (16:9)  
**触发**: `>>新场景名<<` 首次出现

```text
你是国际顶级场景概念设计师。请为「{scene_name}」制作场景一致性与视觉开发设计板。
世界观：{world_title} · 风格 {visual_style}
场景描述（空镜头，无人物）：{scene_description_from_narrative_llm}

排版：深色高级 UI 界面，网格化专业排版，画面留给视觉内容而非大标题。

分区需求：
- 主视觉（居中宽幅）：核心氛围与极致光影
- 时间切片（左侧纵向三格）：「白昼」「黄昏」「夜晚」
- 空间视图（顶部横向四格）：「正视图」「侧视图」「俯视图/平面蓝图」「仰视图」
- 细节质感（底部横向四格）：核心材质、光斑、关键道具、局部纹理微距
- 色彩规范（右侧纵向）：主色/辅助色/点缀色色块 + HEX 标注

文本渲染：
仅双引号内小节标题可渲染为画面中文标签；其他描述不得变文字。

风格：{visual_style}，结合严谨建筑蓝图感与工作室提案排版。
禁止：人物、现代 UI、水印。
```

**后处理**: 正则或 LLM 从 prompt 回写期望 HEX 列表到 `meta_json.palette`（若模型未画出 HEX，由叙事 LLM 补全 3–5 色）。

---

## 4. 回合插图 Template（turn_illust）

### 4.1 场景类（16:9）

**尺寸**: `2752x1536`

```text
电影剧照单帧，16:9 宽银幕，{visual_style}。

场景：{scene_name}（见 scene_board entity_key={scene_key}）
色板：{hex_list}
人物：{agent_name} 与 {user_title}（角色外观遵循 character_sheet）
动作与情绪：{action_from_illust_intent}
镜头：{WS|MCU|CU}，{35mm|50mm|85mm}，ARRI Alexa 35 色彩，{mood} 氛围

构图：主体清晰，环境支持叙事，无文字无 UI 无水印。
```

### 4.2 照片类（3:4）

**尺寸**: `1760x2368`

```text
竖构图 3:4 电影感肖像/拍立得式帧，{visual_style}。

主体：{agent_name}，{emotion}，{shot_notes}
背景：{scene_name} 虚化 bokeh
85mm 浅景深，柔和主光，肤色自然。

无文字、无 UI、无水印。
```

---

## 5. LLM 协同协议

### 5.1 叙事模型输出义务

每回合可选**最多一个**插图标记，放在选项 `[1]` 之前：

```text
<illust:scene mood="tense" subjects="伙伴,主人,岩道" />
```

内心（仅伙伴）：

```text
<inner>担心主人滑倒|{agent_name} 望着青苔，心口发紧——若 {user_title} 伤在这，……</inner>
```

### 5.2 Prompt Builder 职责

1. 读取 `IllustIntent` + bible + 关联 assets
2. 选择 template 4.1 或 4.2
3. 截断至 U1 `prompt` max tokens（4096）优先保留 VISUAL_WORLD + PALETTE + 动作
4. 调用 U1；失败则 Agnes 同 prompt（Agnes 参数见官方文档）

### 5.3 一致性检查清单（人工抽检）

- [ ] 髮色/服装与 character_sheet 描述一致
- [ ] 场景色调与 scene_board HEX 偏差可接受
- [ ] 无现代违和物（除非 bible 允许）
- [ ] 无文字水印

---

## 6. 配额与节流

| 类型 | 默认频率 |
|------|----------|
| character_sheet | 每会话 1 + 每新 NPC 1 |
| scene_board | 每新 scene_key 1 |
| turn_illust | 每 2 回合最多 1（`ADVENTURE_ILLUST_COOLDOWN_TURNS`） |

U1 限额 1500/5h：Monitor 告警阈值 80%。

---

## 7. Agnes Fallback 说明

当 U1 返回非 200、超时、quota 用尽时：

1. 同一 `prompt_text` 送 Agnes Image 2.1 Flash（见 [Agnes 文档](https://agnes-ai.com/doc/agnes-image-21-flash)）
2. `meta_json.fallback_used = true`
3. Monitor 标记 `adventure_illust_agnes`

Agnes prompt 可适当缩短排版指令，保留 VISUAL_WORLD + 主体描述。

---

## 8. 示例：原神 · 璃月（摘要）

**scene_board scene_key**: `璃月港·夜雨码头`

**palette**: `#1a2a3a`, `#c9a227`, `#4fd1c5`, `#2d1f3d`

**turn_illust intent**: MCU，伙伴与主人在雨棚下，紧张，35mm

---

## 9. 修订记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-06-19 | 1.0 | 初版，Feature 006 research 沉淀 |
