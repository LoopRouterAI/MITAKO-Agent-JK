# 冒险叙事标记契约 v2（LLM ↔ 前端唯一标准）

> 本文件是 **唯一 canonical 语法**。System Prompt 与前端 RichText 渲染均以此为准；后端 normalize 仅作兜底，不得依赖兜底替代本契约。

## version
2

## scene_title
format: `>>标题<<`
line: 单独一行
forbidden:
  - `<>标题<>`
  - `>标题>`
  - `>标题>/SAY>>`
example_ok: `>>璃月港·晨雾<<`
example_bad: `<>璃月港<>`

## narration
format: `【旁白句】`
rule: 客观环境/动作；禁止「我」「你」
example_ok: `【{agent_name} 与 {user_title} 踏上石阶。】`

## dialogue
format: `<say role="agent|npc|user" name="说话人">台词</say>`
line: 每句单独一行
forbidden:
  - 「」包裹对白
  - `<>` 包裹对白
  - `>/SAY>>` 或 `<<SAY:…>>`
example_ok: `<say role="agent" name="{agent_name}">{user_title}，跟紧我。</say>`

## inner_thought
format: `<inner>摘要|完整内心</inner>`
limit: 每回合最多 1 条；仅伙伴
forbidden: 行首 `>` 代替 inner

## illust
format: `<illust:scene mood="…" subjects="A,B" />` 或 `<illust:photo … />`
limit: 每回合最多 1 个；放在选项 `[1]` 之前

## separator
format: `---`
forbidden: 连续空行

## choices
format: `[1] 纯中文选项`
forbidden: 选项内 `#g:词#` 等富文本

## emphasis
allowed: `**加粗**` `*斜体*` `~~删除线~~`
keywords: `#词#` `#v:词#` `#r:词#` `#c:词#` `#g:词#` `#a:词#`

## few_shot_correct
```
>>穿越落点·荒道<<
---
【不明裂隙将 {user_title} 与 {agent_name} 抛入此世，风里有陌生的铁锈味。】
<say role="agent" name="{agent_name}">{user_title}，还听得见吗？我们先别分开。</say>
<inner>必须稳住|{agent_name} 压下心跳，先确认 {user_title} 平安。</inner>
---
【道旁有断碑，字迹半毁。】
[1] 检查断碑
[2] 沿足迹前行
[3] 让 {agent_name} 说说对这里的印象
```

## few_shot_wrong_then_fix
wrong:
```
<>荒道<>
>主人，小心。>/SAY>>
```
must_output_like:
```
>>荒道<<
<say role="agent" name="{agent_name}">{user_title}，小心。</say>
```

## llm_reminder
输出前自检：场景是否 `>>…<<`？对白是否 `<say …>`？是否零个 `<>` 与 `>/SAY>>`？选项是否纯中文？
