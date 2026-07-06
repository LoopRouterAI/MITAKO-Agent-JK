# MITAKO 客服系统交付文档索引

本目录用于说明当前 POC 的启动、验收、部署和交付边界。当前交付范围为智能客服、人工客服工作台、运营后台、业务适配层和视觉审核工作台；旧版陪伴与角色扮演服务线已封存，不再纳入当前验收。

## 文档清单

| 文档 | 适合阅读对象 | 用途 |
|---|---|---|
| [system-a-cs-platform.md](./system-a-cs-platform.md) | 客服负责人、运营负责人 | 智能客服、转人工、坐席台与运营后台能力说明 |
| [customer-integration-materials-checklist.md](./customer-integration-materials-checklist.md) | 甲方开发、客服负责人 | 真实联调前需要准备的接口、样例和规则 |
| [acceptance-checklist-v1.md](./acceptance-checklist-v1.md) | 双方项目经理、验收负责人 | 现场验收与 UAT 清单 |
| [deployment-guide.md](./deployment-guide.md) | 部署负责人、我方实施 | 本地验证环境启动方式 |
| [testing-guide.md](./testing-guide.md) | 测试、客服负责人 | 回归测试和手工验收方式 |
| [integration-lab.md](./integration-lab.md) | 双方开发、信息化负责人 | 联调前的接口契约演练方式 |
| [openapi.yaml](./openapi.yaml) | 甲方 Java 开发、我方研发 | POC 接口契约草案 |
| [java-client-sample.md](./java-client-sample.md) | 甲方 Java 开发、我方研发 | Spring Boot 接入样例 |
| [poc-uat-checklist.md](./poc-uat-checklist.md) | 双方项目经理、验收负责人 | POC UAT 签收表 |
| [capacity-planning.md](./capacity-planning.md) | 架构、运维 | 生产部署容量规划输入 |
| [observability-runbook.md](./observability-runbook.md) | 运维、研发 | 7×24 可观测与排障 |
| [data-model-compliance-checklist.md](./data-model-compliance-checklist.md) | 法务、研发、客服负责人 | 数据安全与模型合规清单 |

## 当前边界

交付包用于验证客服 Agent、人工接手、后台运营、视觉审核工作台、服务记录和审计链路。订单、售后、仓库、财务、私域触达与视觉审核生产接口需要在真实联调阶段接入甲方测试环境。

真实联调前，甲方需要提供接口契约、测试环境地址、脱敏样例、权限规则、人工复核标准和验收口径。双方确认范围后，再将脱敏样例能力替换为甲方测试环境能力。
