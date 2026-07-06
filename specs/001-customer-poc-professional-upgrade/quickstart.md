# Quickstart: 商业级客服 POC 专业化升级验收

## 1. 启动系统

```powershell
cd D:\Jack\Jack-Code\CodeX_Project\MITAKO_Agent
npm run build
python main.py
```

视觉审核工作台：

```powershell
cd D:\Jack\Jack-Code\CodeX_Project\MITAKO_Agent\poc\visual_review_poc
python workbench_server.py --host 127.0.0.1 --port 7861
```

## 2. 打开页面

- 用户端客服：`http://127.0.0.1:8000/`
- 人工客服工作台：`http://127.0.0.1:8000/desk`
- 管理中心：`http://127.0.0.1:8000/admin`
- 视觉审核工作台：`http://127.0.0.1:7861/`
- 开箱视频直达：`http://127.0.0.1:7861/?scenario=video_unboxing`
- 商品有伤直达：`http://127.0.0.1:7861/?scenario=product_damage`
- 未成年人资料直达：`http://127.0.0.1:7861/?scenario=minor_material`

## 3. 验收路径

1. 用户端触发订单/售后/转人工，检查只读进度卡不再像按钮。
2. 人工客服工作台刷新队列，选择不同会话，检查会话、服务档案、建议动作随会话变化。
3. 接手会话，确认接手提示、回复、转交/升级、结案路径都有反馈。
4. 在 390px 宽度下检查人工台队列、会话、服务档案和输入区都可访问。
5. 管理中心检查监管大盘、队列监控、运营报表、运维大盘是否展示关键指标和失败反馈。
6. 视觉审核工作台用三大直达入口进入，检查客服能理解要补哪些材料。

## 4. 必跑检查

```powershell
npm run build
python scripts/check_visual_workbench_smoke.py
```

如服务已启动，可额外跑：

```powershell
python scripts/dual_system_smoke_test.py
```

## 5. 通过标准

- 无公开页面泄漏模型渠道、Key、内部 Prompt、外包或调试参数。
- 后台空状态、演示状态、失败状态都有中文解释。
- 移动端人工台没有横向溢出或主流程裁切。
- reset、转交、审批等高风险接口有权限与失败反馈。
