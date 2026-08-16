# 系统 A：AI客服与VIP客服协同

## 1. 产品范围

| 端 | URL | 角色 | 能力 |
|---|---|---|---|
| 用户端 | `/` | C 端用户 | AI客服对话、情绪识别、转VIP客服、服务记录 |
| 坐席台 | `/desk` | VIP客服 | 服务记录、接单、回复、转交、升级 |
| 运营后台 | `/admin` | 主管/运营 | 坐席、队列、审批、报表、路由、运维 |

系统 A 使用多租户标识隔离账号、会话、审批、路由配置和审计记录。验证环境使用脱敏样本数据，不连接客户真实生产系统。

## 2. 部署方式

一键启动：

```bat
start-windows.bat
```

详见 [deployment-guide.md](./deployment-guide.md)。

## 3. 甲方配合项

| 项 | 甲方需要提供 | 文档 |
|---|---|---|
| 企业登录 | 测试租户、Client、Secret、角色映射 | [customer-integration-materials-checklist.md](./customer-integration-materials-checklist.md) |
| 会话同步 | 测试账号、同步方向、消息字段、状态字段 | [integration-lab.md](./integration-lab.md) |
| 业务接口 | 订单、售后、仓库、财务、审核材料测试接口 | [customer-integration-materials-checklist.md](./customer-integration-materials-checklist.md) |
| SOP 验收 | 高频场景、边界规则、人工复核标准 | [customer-integration-materials-checklist.md](./customer-integration-materials-checklist.md) |

## 4. 验证账号

验证环境账号由我方交付负责人现场发放，并按角色分为运营负责人、主管、VIP客服、只读验收四类。交付文档不固化账号密码；进入联调或上线阶段后，由双方按企业登录和权限矩阵重新配置。

## 5. 系统能力

| 能力 | 用途 |
|---|---|
| AI客服对话 | 承接用户咨询，识别诉求、情绪和订单线索 |
| 转VIP客服 | 用户申请或高风险场景触发后进入坐席队列 |
| 坐席工作台 | 服务记录、接单、回复、转交、升级 |
| 运营后台 | 坐席、队列、审批、报表、路由、运维 |
| 登录与权限 | 支持按角色控制后台与坐席操作范围 |

## 6. 验收要点

| 项 | 标准 |
|---|---|
| 转VIP客服 | 用户端申请后，坐席台可见服务记录并接单 |
| 双端同步 | 坐席回复后，用户端实时收到消息 |
| 转交升级 | 转交、升级、关闭状态正确变化 |
| 审批 | 申请人与审批人不能为同一人 |
| 严格鉴权 | 受保护接口无有效访问凭证返回 401 |
| 租户隔离 | 不同租户账号不能互相操作会话 |
| 业务边界 | 验证环境只输出处理建议，不写入真实业务系统 |
| E2E | 我方提交的全量自动化验收报告通过 |
