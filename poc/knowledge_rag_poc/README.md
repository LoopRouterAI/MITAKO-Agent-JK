# 客户自维护知识库 / RAG POC

本 POC 固定客服知识库接入契约，后续可把本地 fixture 替换为 WeKnora 或等价企业知识库/RAG 服务。

## 运行

```bat
poc\knowledge_rag_poc\一键运行知识库RAG-POC-Windows.bat
```

或：

```powershell
.\venv\Scripts\python.exe .\poc\knowledge_rag_poc\demo.py
```

## 验收

- 只检索已审核文档，草案文档不得进入正式回答。
- 每次回答必须返回引用来源、版本和命中词。
- 低置信度或无依据时必须转VIP客服。
- RAG 只提供可追溯依据，不执行退款、拒赔、补发、改工单状态。
- 支持错误知识回滚的契约。

## 后续替换点

| 当前 POC | 后续生产候选 |
|----------|--------------|
| `fixtures.py` | WeKnora 文档库 |
| `rag_engine.retrieve()` | WeKnora 混合检索 API |
| `answer_with_citations()` | Agent 的引用回答节点 |
| `rollback_doc()` | 知识库版本管理/审核发布流程 |
