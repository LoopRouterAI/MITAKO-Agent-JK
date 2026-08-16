# Quickstart: 冒险视觉沉浸验证

**Feature**: 006-adventure-visual-immersion  
**Prerequisites**: `SENSENOVA_API_KEY` 有效；可选 `AGNES_API_KEY`

## 1. 环境

```bat
cd MITAKO_Agent
copy .env.example .env
REM 填写 SENSENOVA_API_KEY
npm run build
venv\Scripts\python.exe main.py
```

打开 http://127.0.0.1:8000/companion ，Ctrl+F5。

## 2. 内心折叠 (Phase A)

1. 进入冒险，世界观填「原神 · 璃月港」
2. 进行 2 回合对话
3. **期望**: 含 `<inner>…|…</inner>` 的回复出现「💭 摘要」折叠条，点击展开/收起
4. **期望**: 用户气泡、旁白块无内心 UI

## 3. 设定图 (Phase C)

1. 新开会话
2. **期望**: 开局 SSE 出现 `visual_asset_ready`（Monitor 可见）
3. GET `/api/v2/companion/adventure/assets/{user_id}` 返回 `character_sheet` + `scene_board`

## 4. 回合配图 (Phase D)

1. 推进至 LLM 输出含 `<illust:scene>` 的回合
2. **期望**: 文字先完整显示 → 下方 shimmer「正在绘制本镜…」
3. **期望**: ≤60s 内 `illust_ready`，16:9 图片卡片出现
4. 刷新页面，图片仍绑定在该消息下

## 5. Fallback (Phase F)

1. 临时将 `.env` 中 `SENSENOVA_API_KEY` 设为无效
2. 配置有效 `AGNES_API_KEY`
3. **期望**: Monitor 显示 `agnes_fallback`，仍出图或优雅 `illust_failed`

## 6. 世界观纠偏 (Phase B)

| 输入 | 期望 |
|------|------|
| 三国背景下「我开飞机接你」 | 伙伴表示不识「飞机」，用机关/飞鸟类比 |
| 「我用加特林扫射」 | 拒绝现代武器实操，拉回当前任务 |

## 7. 上下文压缩 (Phase E)

1. 运行 `pytest tests/unit/test_adventure_context.py -v`
2. **期望**: 模拟 100 条消息后 bundle token 估算 ≤128000

## 8. Quota 耗尽

1. 模拟 rate limit 满额
2. **期望**: 冒险文字继续；`illust_skipped` reason=quota；无白屏

## Monitor 检查点

- `adventure_illust_prompt` — prompt 字符数
- `adventure_illust_u1` / `adventure_illust_agnes` — 耗时与 model
- `adventure_context_compress` — 摘要触发次数
