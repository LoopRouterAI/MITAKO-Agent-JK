# MITAKO Agent v3 Beta 发布回执

发布时间：2026-08-19 13:35:53 +08:00

## Git 与 Release

- 版本：`v3.0.0-beta.1`
- 发布提交：`65c3ca24e2baf7bc569ea7802ce3ba1478d78b51`
- 私人仓库 Release：<https://github.com/jackdiy/MITAKO-Agent/releases/tag/v3.0.0-beta.1>
- 公司仓库 Release：<https://github.com/LoopRouterAI/MITAKO-Agent-JK/releases/tag/v3.0.0-beta.1>
- 两个仓库的 `main` 均已包含该发布提交及后续发布记录；两个 Release 均标记为预发布版本。

## 三份发布资产

| 资产 | 大小 | SHA-256 | 边界 |
|---|---:|---|---|
| `MITAKO_Agent-customer-preview-20260819.zip` | 27,243,491 B | `f6e481b503d7aa2229faffc50e9f44d04088174e28452163e57c118c052570b6` | 甲方运行包；不含源码、Key、数据库和离线敏感证据 |
| `MITAKO_Agent-internal-dev-20260819.zip` | 65,947,626 B | `fe8becb59ec881146aa9191b9d3f6f2f1d443af8b08b1d44c18a4943a0abcd27` | 内部研发包；包含源码、测试和研发文档 |
| `MITAKO_Agent-four-scenario-evidence-20260819.zip` | 134,244,755 B | `ff85fe65d226315bcc87fda672a8095859ca01d1684498b11caab18bb8343b5d` | 授权验收包；包含 8 份 HTML、119 个媒体文件和哈希 manifest |

GitHub 两个 Release 返回的资产摘要与本地统一验包结果一致。

## 验证证据

- 全仓：`1490 passed + 100 subtests passed`。
- 客服沟通：15 个案例各连续 3 轮，`45/45` 通过。
- 客户运行包：解压运行 API 冒烟 `14/14`，视觉健康检查通过，报告签名在服务重启后仍有效。
- 62 图容量冒烟：全部附件成功接收；外部模型不可用时返回 `technical_processing_incomplete/system_retry`，不再触发公开 API `500`。
- 发布包：三个 manifest 均绑定发布提交，媒体哈希和隐私边界校验通过。

## 线上部署状态

2026-08-19 13:35 +08:00 对 `https://agent.deeptokenai.cn` 做只读冒烟：主页和视觉工作台健康接口可访问，但 `/api/v1/version` 返回 `404`，主页仍引用旧前端资产。因此 GitHub 代码与 Release 已完成，Deeptokenai.cn 尚未部署本 v3 Beta，不能把当前线上页面描述为新版本。

部署后必须再次检查 `/api/v1/version`，确认后端提交、前端构建和客服策略版本与本 Release 一致。
