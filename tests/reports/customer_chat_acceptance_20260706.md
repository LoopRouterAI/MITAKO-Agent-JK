# 用户端客服交互最后一轮需求验收报告

生成日期：2026-07-06
验收范围：用户端客服 Demo 的模拟数据、订单/商品工具、清空后加载节奏、演示用户切换。

## 总结

结论：通过。
此前缺口：没有落地验收需求核对进度报告；本报告和同目录 HTML 已补齐。

## 验收清单

| 编号 | 需求 | 状态 | 证据 |
|---|---|---:|---|
| A1 | “需关注”和“在途/待发”不应重复表达同一状态，需要区分刚发货与长期延期 | 通过 | `OrderPickerOverlay.jsx` 使用 `hasAttentionSignal` 判断风险队列，普通 `pending_shipment` 不再直接进入“需优先处理”；“在途/待发”仍覆盖 `in_transit / pending_shipment / preorder` |
| A2 | 商品 List 模拟数据太少，需要像正常电商用户 | 通过 | `ChatInput.jsx` 商品样本 11 条，覆盖现货、预售、盲抽、破损售后、规格咨询、纸品包装等 |
| A3 | 订单/商品长列表浮层需要滚动边界和羽化体验 | 通过 | 商品抽屉和订单抽屉均有 `overscroll-contain`、顶部/底部渐隐层、`scrollbar-gutter: stable` |
| A4 | 清空对话后不应立刻弹出推荐订单，需要 Loading 和查询过程 | 通过 | `useChatSSE.js` 分为“智能客服正在赶来”、“正在帮您查询中”、“已同步可咨询信息”，并用 `welcomeTurnId` 防止切换用户后的旧欢迎消息覆盖 |
| A5 | 需要切换模拟用户，覆盖正常用户、新用户、抽奖质疑、破损售后、未成年人退款等 | 通过 | `App.jsx` 增加 6 个演示用户；`mock_data.json` 有 6 个用户、16 笔订单；`usr_005` 新用户无推荐订单 |

## 自动检查结果

| 检查 | 结果 |
|---|---:|
| `mock_data.json` JSON 解析 | 通过 |
| `python -m py_compile business_api.py main.py` | 通过 |
| `npm run build` | 通过 |
| `python scripts/dual_system_smoke_test.py` | 通过，8/8 |
| 本地 API `/api/v1/orders/usr_004?sort=priority` | 通过，返回 3 笔订单 |
| 本地 API `/api/v1/welcome/usr_005` | 通过，无推荐订单 |

## 需求实现位置

| 文件 | 内容 |
|---|---|
| `src/App.jsx` | 演示用户切换入口 |
| `src/components/chat/ChatInput.jsx` | 商品/地址工具抽屉、商品样本、滚动羽化 |
| `src/components/chat/OrderPickerOverlay.jsx` | 订单筛选语义、状态说明、滚动羽化 |
| `src/hooks/useChatSSE.js` | 清空/切换后的欢迎加载流程 |
| `src/components/cards/openUILibrary.jsx` | Loading 卡支持 `headline` 和 `hintOverride` |
| `src/utils/orderHelpers.js` | 新增风险标签和优先级 |
| `business_api.py` | Demo 欢迎推荐和用户场景文案 |
| `mock_data.json` | 6 类用户与 16 笔订单样本 |

## 剩余风险

| 风险 | 说明 |
|---|---|
| 真实甲方接口未接入 | 当前仍是 POC Mock，符合 Spec Kit 边界；正式接入需按对接文档补订单、物流、售后、商品、地址接口 |
| 演示数据不是生产数据 | 样本只用于展示流程覆盖，不代表真实用户分布 |
| 浏览器截图未写入本报告 | 本轮以代码、构建、接口、烟测为验收依据；如要交付给甲方演示，可再补一张用户端截图 |
