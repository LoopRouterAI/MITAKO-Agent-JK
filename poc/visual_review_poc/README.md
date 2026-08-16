# 三大视觉审核独立 POC

本目录独立验证甲方优先级最高的三类场景：

1. 开箱视频审核
2. 商品有伤审核
3. 未成年人资料审核

这三类场景约占甲方客服人力 60%，且爆单时会挤占客服主链路人力。本 POC 的目标是证明“视觉审核链路可以跑通，并能输出客服可用的证据、风险和补件建议”，不是替甲方业务系统做自动裁决。

## 当前优先入口

客服可视化工作台：

```bat
poc\visual_review_poc\一键启动视觉审核工作台-Windows.bat
```

打开：

```text
http://127.0.0.1:7861
```

工作台支持：

- 上传本地视频，适合 App、小程序或客服后台已收到的视频材料。
- 输入公开视频 URL，服务端使用 `yt-dlp` 下载到本地后再审核。
- 按开箱视频、商品有伤、资料审核三个独立队列提交；工作台一次只处理一个队列。
- 配置 1 FPS / 2 FPS、探测秒数、抽帧上限、送模型帧数。
- 送入用户诉求、订单/工单上下文、抽帧图片和补充图片，统一做多模态审核。
- 审核完成后打开客服可见摘要页；内部报告可展示模型名、渠道、耗时、Token、成本和原始返回。
- 导入人工确认 CSV/JSON 样本表，检查样本完备性；包含辅助结论时才统计命中情况。

## VideoExtractor 吸收结论

已完整阅读 `kabuqin/VideoExtractor` 的 README、架构文档、后端任务流、下载器、平台解析器、任务 API 和前端任务表单。它不是单纯下载器，而是“分享文本/URL 输入 -> 平台识别 -> 元数据解析 -> 下载复用 -> 任务状态 -> 字幕/转写 -> 文案生成 -> 编辑导出”的本地短视频流水线。

本 POC 已吸收与客服视觉审核直接相关的部分：

- 分享文本中提取公开视频 URL。
- YouTube、B 站、抖音、TikTok、小红书等平台识别。
- `yt-dlp` 元数据预览：标题、作者、时长、封面、解析器。
- 下载缓存和 manifest 复用，避免同一 URL 重复下载。
- 可选 cookies：`VISUAL_URL_COOKIES_FILE`、`VISUAL_URL_COOKIES_BROWSER`。
- 失败边界如实暴露：无效 URL、平台限制、登录/反爬、下载失败。

暂不吸收 Whisper 语音转写、平台文案生成、文案编辑和导出系统。当前攻坚点是甲方三类视觉审核，语音转写和营销文案会把工作台拉向“内容生产工具”，不利于证明客服质检链路。

## Gemini 3.5 Flash 单样本审核

当前命令行 Demo 已收敛为单职责验证：本地视频输入、自建抽帧、同目录补充图片、用户诉求和工单上下文，默认交给 `gemini-3.5-flash-lite` 审核；仅在显式实验时可选择 `gemini-3.7-flash` 高质量候选，并输出可复盘 HTML/JSON 报告。

```bat
poc\visual_review_poc\一键运行本地视频三路审核Demo-Windows.bat D:\demo\sample.mp4
```

不传视频路径时，会使用甲方授权 `sample_001`：

```bat
poc\visual_review_poc\一键运行本地视频三路审核Demo-Windows.bat
```

直接运行可配置更严格的抽帧策略：

```powershell
python poc\visual_review_poc\local_video_triage_demo.py --video D:\demo\sample.mp4 --fps 2 --max-frames 16 --api-frame-limit 8 --probe-seconds 20
```

关键参数：

| 参数 | 作用 |
|---|---|
| `--fps 1` / `--fps 2` | 自建抽帧频率；严格查剪辑、离镜建议从 2 FPS 起步 |
| `--max-frames` | 连续性分析最多保留多少帧 |
| `--api-frame-limit` | 送入多模态模型的帧数上限，用于控制成本 |
| `--probe-seconds` | 只探测视频前多少秒，便于 POC 快速迭代 |

输出位置：

```text
poc\visual_review_poc\reports\gemini35_single_audit_*.html
poc\visual_review_poc\reports\gemini35_single_audit_*.json
```

## 公开样例与真实样本

下载公开样例：

```bat
poc\visual_review_poc\一键下载公开视频样例-Windows.bat
```

样例清单：

```text
poc\visual_review_poc\sample_videos\download_manifest.json
```

公开样例只用于保证本地视频链路可验收，不代表甲方真实业务准确率。正式 POC 应替换为甲方授权、脱敏后的真实售后视频、图片和资料样本。

准确率评测不能用 3 条样例下结论。最小盲测集建议：

- 开箱视频：合规 50 条、不合规 50 条。
- 商品有伤：确认有伤 50 单、确认没伤/不支持 50 单。
- 未成年人资料：完整 50 单、缺失 50 单。
- 发错货/SKU 比对可作为视觉识别扩展项，另建正负样本。

更稳妥的 POC 验收建议每个结论类 200-300 条。每条样本都需要人工最终结论和人工原因，否则只能证明链路可跑通，不能证明准确率。

## 代码边界

| 文件 | 作用 |
|---|---|
| `local_video_triage_demo.py` | Gemini 3.5 Flash 单样本审核入口：抽帧、补充图片、结构化审核、HTML/JSON 报告 |
| `workbench_server.py` | 客服视觉审核工作台后端：上传/URL 下载后调用单 Gemini 审核脚本 |
| `workbench.html` | 客服可视化操作台 |
| `url_video_fetcher.py` | 公开视频 URL 下载器，使用 `yt-dlp` 下载到本地 |
| `download_public_samples.py` | 下载公开视频样例，并写入样例 manifest |
| `gemini_adapter.py` | Gemini 结构化输出契约 POC |
| `review_engine.py` | 结构化审核规则，保持结果契约稳定 |

## 验收标准

- 本地视频可通过 `--video` 输入。
- Demo 必须自己抽帧，并支持 1 FPS / 2 FPS。
- Gemini 3.5 Flash 使用同一批本地证据帧和补充图片。
- HTML 必须展示模型原始返回、JSON 解析结果、SystemPrompt、UserPrompt、帧清单和补充图片清单。
- 人工标签只允许用于报告侧评测，不得进入发送给模型的 Prompt。
- `.env` 密钥不得出现在 HTML/JSON 报告中。
- 只生成证据链、补拍建议、人工复核建议，不自动定责、拒赔、退款或补发。
