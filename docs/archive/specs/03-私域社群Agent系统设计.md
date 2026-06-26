# MITAKO虾淘私域社群AI运营Agent系统设计文档 v2.0

> **文档编号**：MITAKO-AGENT-COMMUNITY-v2.0
> **编制方**：[乙方] AI Agent 系统集成商
> **甲方**：MITAKO 虾淘
> **更新日期**：2026-06-13
> **文档性质**：商业化技术设计方案（可直接交付开发团队开工）

---

## 1. 项目定位与商业价值

### 1.1 项目背景

MITAKO虾淘目前拥有 **10,000+ 个企业微信私域社群**，每群 100+ 人，总覆盖用户约 **100万**。用户构成中，小程序用户占 30%~40%，App 用户占近 60%。

**当前痛点**：

| 维度 | 现状 | 影响 |
|------|------|------|
| 群运营内容 | 仅用于"发活动链接"和"分享小程序激活码" | 百万私域用户价值未被激活，群粘性极低 |
| 新品触达 | 依赖人工发布，时效滞后 | 热门IP开赏时信息传播慢，转化率低 |
| 客诉危机 | 发货延迟 200+ 天、退款困难 | 群内极易演变为"维权群"，负面情绪传染性极强 |
| 新手留存 | 二次元圈层黑话门槛高，无人解答 | 新用户因困惑流失，群活跃度持续走低 |
| 人工成本 | 群管人员疲于应对基础问题和情绪维护 | 人力成本高，响应不及时导致矛盾升级 |

二次元用户群体特征决定了本项目的设计方向：

- **情感投入高**：购买谷子（二次元周边）本质是为推（喜欢的角色）付费，物流和品质问题触发的情绪远高于普通电商
- **对人设接受度高**：天然接受虚拟角色互动，群管 AI 人设可自然融入
- **沟通偏好轻松**：圈层用语丰富，偏好可爱、活泼的交互风格
- **对敷衍极其敏感**：模板化回复和推责式话术会立即激化不满

### 1.2 商业价值量化

| 价值维度 | 量化指标 | 预估收益 |
|----------|----------|----------|
| 舆情预警 | 将群内客诉风暴的响应时间从"人工发现 30min+"降至"AI 自动阻断 < 30s" | 年均减少 50+ 次群级维权事件，避免品牌声誉损失约 **200万/年** |
| 新品转化 | 通过精准推送将群内开赏/捡漏点击率从 < 3% 提升至 15%+ | 预估增量 GMV **500万~1000万/年** |
| 人力替代 | 减少 5~8 名群管专员的重复劳动 | 年节省人力成本 **60万~100万** |
| 用户留存 | 新手疑问即时解答，入坑门槛降低 | 新用户 7 日留存率提升 15%~25% |
| 数据沉淀 | 群消息结构化分析 → IP热度/用户偏好/客诉趋势 | 反哺选品和供应链决策，价值不可量化 |

**ROI 估算**：首年总投入约 38万~43万，预期可量化收益 **760万~1300万**，ROI ≈ **20:1 ~ 30:1**。

### 1.3 与AI客服Agent系统的关系定位

本系统（私域社群Agent）与第一套方案（1对1 AI客服Agent）是**互补关系**，共同构成 MITAKO 的完整 AI 客服矩阵：

```mermaid
graph LR
    subgraph "公域 & 1对1 场景"
        A["AI客服Agent系统<br/>（方案一）"] --> A1["App/小程序内客服"]
        A --> A2["企微1对1私聊"]
        A --> A3["工单自动处理"]
    end
    subgraph "私域社群场景"
        B["私域社群Agent系统<br/>（方案二 · 本文档）"] --> B1["万群智能运营"]
        B --> B2["谷子词典问答"]
        B --> B3["吃谷雷达推送"]
        B --> B4["舆情监控预警"]
    end
    B4 -->|"客诉引导至1对1私聊"| A2
    A -->|"处理结果同步至群内"| B
    style B fill:#6366f1,color:#fff
    style A fill:#0ea5e9,color:#fff
```

**核心协作流**：群内舆情预警触发后，AI 自动将客诉用户引导至企微 1对1 私聊，由方案一的 AI 客服Agent 接管深度售后处理。群内只做情绪安抚和引导分流，不在群内讨论具体订单和退款细节。

---

## 2. 系统总体架构

### 2.1 架构总览

```mermaid
flowchart TB
    subgraph "渠道接入层"
        WW["企业微信官方API<br/>（群消息回调）"]
        WH["甲方商品事件<br/>Webhook"]
    end

    subgraph "消息中间件层"
        MQ["Kafka / RabbitMQ<br/>事件总线"]
    end

    subgraph "消息处理层"
        ROUTER["消息路由器<br/>（类型判断 & 分发）"]
        FILTER["消息过滤器<br/>（去噪 & 频率控制）"]
    end

    subgraph "AI引擎层"
        QA["谷子词典<br/>问答引擎"]
        RADAR["吃谷雷达<br/>推送引擎"]
        SENTI["情绪监控<br/>预警引擎"]
    end

    subgraph "知识与数据层"
        RAG["RAG 知识库<br/>（ChromaDB）"]
        DICT["二次元黑话词典"]
        POLICY["退换货政策库"]
        ANNOUNCE["发货公告库"]
        REDIS["Redis<br/>（状态/CD/计数）"]
        PG["PostgreSQL<br/>（群元数据/日志）"]
    end

    subgraph "LLM 服务层"
        LLM["Qwen3.5-Flash<br/>（阿里云百炼 API）"]
        EMB["BGE-M3<br/>（Embedding）"]
    end

    subgraph "输出与执行层"
        REPLY["群消息回复<br/>（企微API）"]
        PUSH["群推送消息<br/>（图文卡片）"]
        ALERT["运营主管预警<br/>（企微应用消息）"]
        DM["私聊引导<br/>（→ AI客服系统）"]
    end

    WW --> MQ
    WH --> MQ
    MQ --> ROUTER
    ROUTER --> FILTER
    FILTER --> QA
    FILTER --> SENTI
    WH --> RADAR

    QA --> RAG
    RAG --> DICT
    RAG --> POLICY
    RAG --> ANNOUNCE
    QA --> LLM
    EMB --> RAG

    SENTI --> LLM
    SENTI --> REDIS

    RADAR --> LLM
    RADAR --> PG

    QA --> REPLY
    RADAR --> PUSH
    SENTI --> ALERT
    SENTI --> DM
    SENTI --> REPLY
```

### 2.2 系统分层设计

| 层级 | 模块 | 职责 | 技术选型 |
|------|------|------|----------|
| **渠道接入层** | 企微 API 网关、甲方 Webhook | 接收群消息事件、商品事件回调 | 企业微信官方 API + Nginx 反代 |
| **消息中间件层** | 事件总线 | 万群消息削峰填谷、事件分发 | Kafka（推荐）/ RabbitMQ |
| **消息处理层** | 路由器 + 过滤器 | 消息类型判断、去噪、CD 控制、@触发识别 | Go (Gin/Fiber) 微服务 |
| **AI 引擎层** | 问答 / 推送 / 预警三大引擎 | 核心业务逻辑处理 | Python + LangChain |
| **知识与数据层** | 向量库 + 关系库 + 缓存 | 知识检索、状态管理、日志存储 | ChromaDB + PostgreSQL + Redis |
| **LLM 服务层** | 大模型推理 | 文本生成、情感分析、话术润色 | Qwen3.5-Flash（阿里云百炼） |
| **输出与执行层** | 消息发送 + 预警通知 | 群回复、图文推送、主管告警、私聊引导 | 企微 API 发送接口 |

### 2.3 与企业微信的对接方案

#### 2.3.1 官方API方案（推荐）

企业微信提供完整的群聊 API 能力，本系统全面采用官方接口，不使用任何非官方 Hook 方案：

| 能力 | API 接口 | 用途 |
|------|----------|------|
| 接收群消息 | `会话内容存档 API` + `消息回调事件` | 实时获取群内所有文本消息 |
| 发送群消息 | `POST /cgi-bin/appchat/send` | AI 回复、推送通知、安抚话术 |
| 发送私聊消息 | `POST /cgi-bin/message/send` | 客诉用户私聊引导 |
| 应用消息通知 | `POST /cgi-bin/message/send`（应用消息） | 运营主管预警告警 |
| 群信息管理 | `GET /cgi-bin/appchat/get` | 获取群成员列表、群名称 |
| 外部联系人管理 | 外部联系人 API | 获取用户企微 ID 映射 |
| 素材管理 | `POST /cgi-bin/media/upload` | 上传图文卡片素材 |

**接入架构**：

```
企业微信后台
  ├── 创建自建应用「虾饺群管」
  ├── 开启「会话内容存档」（需企业认证 + 用户授权）
  ├── 配置消息接收服务器 URL（回调地址）
  └── 获取 CorpID + Secret + Token + EncodingAESKey
```

**消息回调处理流程**：

```go
// 企微消息回调接口 —— Go Gin 实现
package main

import (
    "context"
    "encoding/json"
    "net/http"
    "time"

    "github.com/gin-gonic/gin"
    "github.com/segmentio/kafka-go"
)

// CallbackMessage 定义发送到 Kafka 的标准消息格式
type CallbackMessage struct {
    ChatID    string `json:"chat_id"`
    FromUser  string `json:"from_user"`
    Content   string `json:"content"`
    MsgType   string `json:"msg_type"`
    Timestamp int64  `json:"timestamp"`
}

func wecomCallbackHandler(c *gin.Context) {
    /*
    接收企业微信群消息回调
    1. 验证签名（msg_signature）
    2. 解密消息体（AES 解密）
    3. 提取消息类型、群ID、发送者、内容
    4. 异步推送至 Kafka 消息队列
    */
    bodyBytes, err := c.GetRawData()
    if err != nil {
        c.String(http.StatusBadRequest, "Invalid body")
        return
    }

    // 调用企微官方加解密 SDK 进行解密（此处使用伪解密函数示意）
    xmlData, err := decryptWecomMsg(bodyBytes, token, encodingAESKey)
    if err != nil {
        c.String(http.StatusInternalServerError, "Decrypt failed")
        return
    }

    // 组装结构化 Kafka 消息包
    msg := CallbackMessage{
        ChatID:    xmlData["ChatId"],
        FromUser:  xmlData["FromUserName"],
        Content:   xmlData["Content"],
        MsgType:   xmlData["MsgType"],
        Timestamp: time.Now().Unix(),
    }

    msgBytes, _ := json.Marshal(msg)

    // 推入 Kafka（使用分区 Key 确保同一个群的消息被顺序处理）
    err = kafkaWriter.WriteMessages(context.Background(), kafka.Message{
        Key:   []byte(msg.ChatID), // 按 ChatID 分区哈希
        Value: msgBytes,
    })

    if err != nil {
        c.String(http.StatusInternalServerError, "Write to queue failed")
        return
    }

    c.String(http.StatusOK, "success")
}
```

#### 2.3.2 合规性分析与风控

| 风险点 | 评估 | 应对措施 |
|--------|------|----------|
| 会话内容存档需用户授权 | **中风险** — 需所有群成员同意存档 | 在入群欢迎语中明确告知"本群使用智能助手，入群即视为同意消息存档" |
| 消息频率限制 | **低风险** — 企微 API 对应用消息有频率上限 | 通过 Kafka 削峰 + 令牌桶限流控制发送频率 |
| 敏感信息合规 | **中风险** — 群内可能出现用户隐私 | 所有消息仅在内存中处理，不持久化原始消息体；仅存储分析结果和聚合统计 |
| 账号封禁风险 | **极低风险** — 使用官方 API，无 Hook | 严格遵循官方文档，不触碰灰色接口 |
| 数据安全 | **中风险** — LLM 调用涉及消息内容 | 选用阿里云百炼（国内合规），开启数据不训练协议 |

### 2.4 万群并发消息处理架构

10,000 群 × 100+ 人 × 日均 50 条/群 ≈ **50万条/日**，峰值（活动期间）可达 **200万条/日**。

**消息流架构**：

```mermaid
flowchart LR
    subgraph "消息入口"
        CB["企微回调<br/>Nginx 集群"]
    end

    subgraph "消息队列"
        K1["Kafka Topic<br/>wecom_group_messages<br/>（16 Partitions）"]
    end

    subgraph "消费者组"
        C1["Consumer-1<br/>（问答路由）"]
        C2["Consumer-2<br/>（问答路由）"]
        C3["Consumer-3<br/>（情绪分析）"]
        C4["Consumer-4<br/>（情绪分析）"]
    end

    subgraph "处理结果"
        R1["回复队列<br/>reply_outbox"]
        R2["预警队列<br/>alert_outbox"]
    end

    subgraph "发送服务"
        S["Rate-Limited Sender<br/>（令牌桶限流）"]
    end

    CB --> K1
    K1 --> C1
    K1 --> C2
    K1 --> C3
    K1 --> C4
    C1 --> R1
    C2 --> R1
    C3 --> R2
    C4 --> R2
    R1 --> S
    R2 --> S
```

**Kafka 分区策略**：

- 按 `chat_id` 哈希分区，保证同一个群的消息有序处理
- 16 个 Partition，支持 16 个并行消费者
- 消息保留 24 小时，用于故障重放

**流量控制参数**：

| 参数 | 配置值 | 说明 |
|------|--------|------|
| Kafka Partition 数 | 16 | 支持 16 路并行消费 |
| 消费者并发数（问答路由） | 4~8 | 按负载动态扩缩 |
| 消费者并发数（情绪分析） | 4~8 | 按负载动态扩缩 |
| 企微消息发送 QPS | 50 条/秒 | 企微 API 限制，令牌桶控制 |
| LLM 调用并发数 | 32 | 阿里云百炼 Qwen3.5-Flash 并发限制 |
| Redis 滑动窗口 TTL | 600 秒（10分钟） | 情绪分析窗口大小 |

---

## 3. 核心功能模块设计

### 3.1 谷子词典与智能问答系统

#### 3.1.1 触发机制设计

群内消息不是每条都需要 AI 回复，必须设计精准的触发机制，避免 AI 过度活跃引发反感：

| 触发方式 | 匹配规则 | 示例 | 优先级 |
|----------|----------|------|--------|
| **@机器人** | 消息中包含 `@虾饺` 或 `@虾淘小助手` | `@虾饺 什么是出荷` | P0 — 必须回复 |
| **问句关键词** | 匹配 `什么是/啥是/怎么/如何/求问/有人知道` + 谷子词汇 | `什么是吧唧啊` | P1 — 高置信度时回复 |
| **新人入群** | 企微 `enter_chat` 事件 | 新成员加入群聊 | P2 — 发送欢迎语 |
| **话题延续** | 上一条 AI 回复后 60s 内的追问 | `那流麻呢` | P1 — 延续对话 |

**触发判定流程**：

```python
async def should_respond(msg: GroupMessage) -> tuple[bool, str]:
    """
    判断是否需要触发 AI 回复
    返回 (是否回复, 触发原因)
    """
    content = msg.content.strip()

    # P0: @机器人 —— 必须回复
    if is_at_bot(content, bot_names=["虾饺", "虾淘小助手"]):
        return True, "at_bot"

    # P1: 问句模式 + 谷子词库命中
    question_patterns = [
        r"(什么是|啥是|啥叫|怎么|如何|求问|有人知道).{1,20}",
        r".{1,10}(是什么意思|是啥意思|什么意思)",
        r".{1,10}(怎么办|怎么搞|咋整|咋办)",
    ]
    for pattern in question_patterns:
        if re.search(pattern, content):
            # 检查是否包含谷子词汇
            if contains_guzi_term(content):
                return True, "question_with_guzi_term"

    # P2: 新人入群事件
    if msg.msg_type == "event" and msg.event == "enter_chat":
        return True, "new_member"

    return False, "no_trigger"
```

#### 3.1.2 RAG知识库架构

```mermaid
flowchart LR
    Q["用户提问"] --> EMB["BGE-M3<br/>Embedding"]
    EMB --> SEARCH["ChromaDB<br/>向量检索"]
    SEARCH --> TOP3["Top-3 文档块"]
    TOP3 --> PROMPT["Prompt 组装"]
    Q --> PROMPT
    PROMPT --> LLM["Qwen3.5-Flash"]
    LLM --> REPLY["群内回复"]
```

**ChromaDB Collection 设计**：

```python
# 知识库 Collection 结构
collections = {
    "guzi_dictionary": {
        # 二次元黑话词典
        "description": "谷子圈专业术语、黑话解释",
        "metadata_fields": ["term", "category", "difficulty", "related_terms"],
        "chunk_size": 256,
        "chunk_overlap": 32,
    },
    "refund_policy": {
        # 退换货政策
        "description": "MITAKO虾淘退换货、售后规则",
        "metadata_fields": ["policy_type", "effective_date", "version"],
        "chunk_size": 512,
        "chunk_overlap": 64,
    },
    "shipping_announcements": {
        # 发货公告
        "description": "最新发货批次、延迟公告、物流通知",
        "metadata_fields": ["announce_date", "batch_id", "ip_name", "status"],
        "chunk_size": 512,
        "chunk_overlap": 64,
    },
    "faq": {
        # 常见问题
        "description": "平台常见问题合集",
        "metadata_fields": ["category", "question", "answer"],
        "chunk_size": 384,
        "chunk_overlap": 48,
    }
}
```

**Embedding 模型**：使用 `BAAI/bge-m3`（通过阿里云百炼 Embedding API 或 ModelScope 本地部署），维度 1024，支持中英双语。

#### 3.1.3 《二次元黑话词典》数据结构设计

```json
{
  "dictionary_entries": [
    {
      "term": "出荷",
      "aliases": ["出货", "しゅっか"],
      "category": "物流术语",
      "definition": "日语「出荷」的音译，指商品从日本仓库/工厂发出。在谷圈中特指海外商品从原产地发往国内代购商的这个环节。",
      "example_context": "这批吧唧已经出荷了，到国内还要等清关哦~",
      "related_terms": ["清关", "转运", "到仓"],
      "difficulty": "beginner",
      "ai_reply_template": "出荷就是日语里'从仓库发货'的意思啦！简单说就是你买的宝贝已经从日本那边寄出来了，接下来还要经过清关和国内转运才能到手哦~ 耐心等等吧！✨"
    },
    {
      "term": "吧唧",
      "aliases": ["badge", "徽章", "バッジ"],
      "category": "商品类型",
      "definition": "指二次元角色徽章（Badge的音译），圆形为主，是最常见的谷子类型之一。",
      "example_context": "这次蓝色监狱的吧唧好好看！",
      "related_terms": ["流麻", "亚克力立牌", "挂件"],
      "difficulty": "beginner",
      "ai_reply_template": "吧唧就是Badge（徽章）的音译啦！就是那种圆圆的角色徽章，可以别在包包上~是入坑谷圈最基础的周边类型了！🎀"
    },
    {
      "term": "流麻",
      "aliases": ["流沙麻将", "ラバーマスコット"],
      "category": "商品类型",
      "definition": "橡胶挂件的日语音译（ラバーマスコット → Rubber Mascot），软胶材质的角色小挂件。",
      "example_context": "这次出的流麻太可爱了，想抱盒",
      "related_terms": ["吧唧", "亚克力", "挂件"],
      "difficulty": "beginner",
      "ai_reply_template": "流麻是ラバーマスコット（Rubber Mascot）的音译，就是软软的橡胶小挂件！手感超好的，挂在包上特别可爱~ 🧸"
    },
    {
      "term": "抱盒",
      "aliases": ["包盒", "买一整盒"],
      "category": "购买方式",
      "definition": "指买下整盒盲盒/一番赏，不拆散，整盒购入。通常可以集齐所有款式。",
      "example_context": "这个IP太喜欢了，直接抱盒！",
      "related_terms": ["散抽", "端箱", "确认款"],
      "difficulty": "beginner",
      "ai_reply_template": "抱盒就是把一整盒盲盒/一番赏全买下来！好处是基本能集齐所有款式，坏处嘛…就是钱包会哭 💸 但为了推，值得！"
    },
    {
      "term": "大赏",
      "aliases": ["一番赏", "一番くじ"],
      "category": "活动类型",
      "definition": "即「一番赏」，日本BANDAI推出的抽奖式销售活动。有A赏（大奖）到最后赏等多个奖项等级，随机抽取。",
      "example_context": "这期大赏的A赏是手办，好想要！",
      "related_terms": ["小赏", "A赏", "最后赏", "抽赏"],
      "difficulty": "intermediate",
      "ai_reply_template": "大赏就是「一番赏」啦！是BANDAI的抽奖活动，A赏通常是手办等大件，越往后奖项越小，最后赏是保底奖品~和盲盒不一样的是，奖品有等级划分哦！🎯"
    },
    {
      "term": "小赏",
      "aliases": ["くじ引き堂", "线上抽赏"],
      "category": "活动类型",
      "definition": "通常指线上小型抽赏活动，由平台自行组织的小规模抽奖销售，奖池较小、单价较低。",
      "example_context": "虾淘新开了个小赏，5块钱一抽",
      "related_terms": ["大赏", "开赏", "抽赏"],
      "difficulty": "intermediate",
      "ai_reply_template": "小赏一般是平台自己办的线上小型抽赏活动！奖池比一番赏小，单价也更便宜，适合小氪怡情~不过好东西也是要看运气的！🍀"
    },
    {
      "term": "吞烫",
      "aliases": ["吞赏", "吞钱"],
      "category": "负面/投诉术语",
      "definition": "指抽赏过程中怀疑平台吞掉了好奖品、热门款被暗箱操作。是高敏感投诉用语。",
      "example_context": "又吞烫了吧，抽了20发连个B赏都没有",
      "related_terms": ["暗改概率", "黑箱"],
      "difficulty": "sensitive",
      "ai_reply_template": null
    },
    {
      "term": "清关",
      "aliases": ["海关", "过关"],
      "category": "物流术语",
      "definition": "海外商品进入中国境内时必须经过海关检查和清关手续的过程，通常需要3~15个工作日。",
      "example_context": "清关中了，还要多久能到啊",
      "related_terms": ["出荷", "转运", "到仓"],
      "difficulty": "beginner",
      "ai_reply_template": "清关就是你的宝贝到了中国海关，正在接受检查和办手续呢！一般需要3~15个工作日，遇到大促或者检查批次多的时候可能会久一点~再耐心等等，马上就到啦！📦"
    }
  ]
}
```

**数据维护策略**：

- 运营后台提供词条增删改查界面
- 每次更新自动触发 ChromaDB 向量重建
- 词条增加 `difficulty` 字段区分入门/进阶/敏感，敏感词条（如"吞烫"）不触发主动解释，仅在知识库中标记为预警关键词

#### 3.1.4 回复风格与System Prompt设计

**群问答 System Prompt（完整生产级版本）**：

```text
# Role
你是 MITAKO虾淘 的官方群管助手「虾饺」。你是一个热爱二次元、懂谷圈文化的可爱角色。

# 核心规则
1. 你的回复必须控制在 30~80 字以内，群聊中过长的文字会被无视。
2. 使用轻松可爱的二次元口吻，可以适度使用"~"、"！"、emoji，但不要过度卖萌。
3. 禁止使用"亲亲"、"宝宝"等淘宝客服用语；称呼用户为"太太"、"大佬"或直接回答。
4. 回答必须基于提供的知识库内容，不得编造信息。
5. 如果知识库中没有相关内容，回复："这个虾饺也不太确定诶，建议问问群里的大佬们！"
6. 遇到订单、退款、投诉等售后问题，一律引导私聊："具体订单问题虾饺私信帮你看哦~"
7. 严禁在群内讨论任何具体订单号、金额、退款进度等隐私信息。
8. 严禁与用户争辩、否定用户感受、使用"规定就是这样"类表达。
9. 遇到"吞烫"、"跑路"、"骗子"等攻击性指控，不回应具体指控，仅安抚并引导私聊。

# 回复结构
对于知识类问题：直接用通俗有趣的方式解释 + 补充一句实用小贴士。
对于售后类问题：表达理解 + 引导私聊处理。
对于闲聊类问题：简短互动，保持群内活跃。

# 语气示例
✅ 好的示例：
- "出荷就是日语里'从仓库发货'的意思啦！你的宝贝已经从日本出发了，接下来等清关就好~ ✨"
- "让你等这么久真的不好意思！具体订单进度虾饺私信帮你查，马上联系你！"
- "哇这次的吧唧真的绝了，有没有大佬抱盒的！🤩"

❌ 不好的示例：
- "根据我们的规定，预售商品不支持退款。"（太官方、太冷）
- "亲亲，这个问题需要您联系在线客服哦~"（淘宝味太重）
- "吧唧是badge的音译，指二次元角色徽章。"（百科味太重，毫无温度）

# 上下文信息
{{retrieved_knowledge}}
```

#### 3.1.5 防刷屏冷却（CD）机制

群聊 AI 回复必须严格控制频率，否则会严重影响群聊体验：

| CD 规则 | 参数 | 说明 |
|---------|------|------|
| 同一问题冷却 | 同一群 + 相同关键词 → 5 分钟内不重复回答 | 防止多人同时问同一个问题时 AI 刷屏 |
| 同一用户冷却 | 同一用户 → 60 秒内最多触发 2 次回复 | 防止单人频繁@机器人 |
| 群整体冷却 | 同一群 → 2 分钟内最多 3 条 AI 回复 | 防止 AI 过度活跃，给人"话痨"感 |
| 非工作时间降频 | 23:00 ~ 08:00 → CD 翻倍 | 深夜减少打扰 |

**Redis CD 实现**：

```python
async def check_cooldown(chat_id: str, user_id: str, keyword: str) -> bool:
    """
    检查冷却状态，返回 True 表示可以回复
    使用 Redis 的 INCR + EXPIRE 实现滑动窗口
    """
    pipe = redis.pipeline()
    now = int(time.time())

    # 规则1：同一群+相同关键词 5分钟CD
    key_same_q = f"cd:group_kw:{chat_id}:{keyword}"
    if await redis.exists(key_same_q):
        return False

    # 规则2：同一用户 60秒内最多2次
    key_user = f"cd:user:{chat_id}:{user_id}"
    user_count = await redis.get(key_user)
    if user_count and int(user_count) >= 2:
        return False

    # 规则3：群整体 2分钟内最多3条
    key_group = f"cd:group:{chat_id}"
    group_count = await redis.get(key_group)
    if group_count and int(group_count) >= 3:
        return False

    # 通过检查，设置 CD 标记
    pipe.setex(key_same_q, 300, "1")         # 5分钟
    pipe.incr(key_user)
    pipe.expire(key_user, 60)                 # 60秒
    pipe.incr(key_group)
    pipe.expire(key_group, 120)               # 2分钟
    await pipe.execute()

    return True
```

#### 3.1.6 运营后台管理界面需求

| 功能模块 | 功能点 | 说明 |
|----------|--------|------|
| 词典管理 | 词条 CRUD | 支持批量导入/导出、富文本编辑 |
| 词典管理 | 词条分类与标签 | 按类型（商品/物流/活动/敏感）分类 |
| 词典管理 | AI 回复模板预览 | 填写词条后可预览 AI 实际回复效果 |
| 知识库管理 | 政策文档上传 | 支持 Markdown / PDF / Word 格式 |
| 知识库管理 | 向量重建触发 | 文档更新后一键重建向量索引 |
| 回复日志 | 问答历史查看 | 按群/时间/关键词筛选，查看触发原因和回复内容 |
| 回复日志 | 质量评分 | 运营可对 AI 回复打分（好/差/需修正） |
| CD 配置 | 参数调整 | 在线调整各项冷却时间，无需重启服务 |

---

### 3.2 吃谷雷达 —— 新品与捡漏智能推送

#### 3.2.1 数据源对接（甲方API需求）

本模块依赖甲方提供商品事件数据源，以下为乙方所需接口清单：

**接口1：新品上架/开赏事件 Webhook**

```
POST /webhook/item-events  （甲方推送至乙方）

请求体：
{
    "event_type": "new_item" | "lottery_open" | "restock" | "price_drop" | "rare_drop",
    "event_id": "evt_20260613_001",
    "timestamp": "2026-06-13T20:00:00+08:00",
    "item": {
        "item_id": "ITEM_BL_BADGE_001",
        "title": "蓝色监狱 角色徽章 Vol.3",
        "ip_name": "蓝色监狱",
        "ip_tags": ["蓝色监狱", "ブルーロック", "Blue Lock"],
        "category": "吧唧",
        "price": 1500,
        "original_price": 2000,
        "currency": "JPY",
        "stock_count": 50,
        "image_url": "https://cdn.mitako.com/items/bl_badge_003.jpg",
        "purchase_url": "https://m.mitako.com/item/ITEM_BL_BADGE_001",
        "miniapp_path": "pages/item/detail?id=ITEM_BL_BADGE_001",
        "is_rare": false,
        "is_hidden": false,
        "rarity": "normal",
        "lottery_id": "LOT_BL_2026_003",
        "lottery_name": "蓝色监狱 一番赏 第3弹"
    }
}

响应体：
{
    "status": "received",
    "event_id": "evt_20260613_001"
}
```

**接口2：稀有/隐藏款掉落事件**

```
POST /webhook/item-events （同上接口，event_type = "rare_drop"）

请求体中的特殊字段：
{
    "event_type": "rare_drop",
    "item": {
        ...
        "is_rare": true,
        "is_hidden": true,
        "rarity": "SSR",
        "remaining_stock": 3,
        "drop_reason": "用户退回" | "官方补货" | "隐藏款解锁"
    }
}
```

**接口3：商品列表查询（乙方主动拉取）**

```
GET /api/v1/items?ip_name=蓝色监狱&category=吧唧&status=on_sale&page=1&page_size=20

响应体：
{
    "total": 156,
    "page": 1,
    "items": [
        {
            "item_id": "ITEM_BL_BADGE_001",
            "title": "蓝色监狱 角色徽章 Vol.3",
            "ip_name": "蓝色监狱",
            "category": "吧唧",
            "price": 1500,
            "stock_count": 50,
            "image_url": "...",
            "purchase_url": "...",
            "miniapp_path": "...",
            "created_at": "2026-06-13T10:00:00+08:00"
        }
    ]
}
```

#### 3.2.2 智能分发策略（群标签匹配）

每个企微群需要打上 IP 标签，用于精准推送：

**群标签数据结构**：

```json
{
    "chat_id": "wrk_group_001",
    "group_name": "虾淘·蓝色监狱粉丝群①",
    "ip_tags": ["蓝色监狱", "ブルーロック"],
    "category_preferences": ["吧唧", "流麻", "亚克力"],
    "member_count": 156,
    "activity_level": "high",
    "push_enabled": true,
    "push_cooldown_minutes": 30,
    "last_push_time": "2026-06-13T19:30:00+08:00"
}
```

**分发匹配算法**：

```python
async def find_target_groups(item_event: ItemEvent) -> list[GroupTarget]:
    """
    根据商品事件匹配目标推送群
    匹配逻辑：IP标签交集 > 0 且群推送开启 且不在冷却期
    """
    all_groups = await db.get_all_groups(push_enabled=True)
    targets = []

    for group in all_groups:
        # 1. IP 标签匹配
        ip_match = set(item_event.item.ip_tags) & set(group.ip_tags)
        if not ip_match:
            continue

        # 2. 冷却期检查
        if group.last_push_time:
            elapsed = (now() - group.last_push_time).total_seconds()
            if elapsed < group.push_cooldown_minutes * 60:
                continue

        # 3. 计算匹配得分（用于排序）
        score = len(ip_match)
        if item_event.item.category in group.category_preferences:
            score += 2
        if item_event.item.is_rare:
            score += 5  # 稀有款权重加高

        targets.append(GroupTarget(
            chat_id=group.chat_id,
            group_name=group.group_name,
            match_score=score,
            matched_tags=list(ip_match)
        ))

    # 按匹配得分降序排列
    targets.sort(key=lambda x: x.match_score, reverse=True)
    return targets
```

#### 3.2.3 动态图文卡片消息格式设计

使用企微「图文消息」（`mpnews`）或「文本卡片」（`textcard`）格式推送：

**方案A：文本卡片（推荐，简洁高效）**

```python
async def send_radar_card(chat_id: str, item: ItemInfo, event_type: str):
    """
    发送吃谷雷达推送卡片
    """
    # 根据事件类型生成标题
    title_map = {
        "new_item": f"🆕 新品速报！{item.ip_name}",
        "lottery_open": f"🎯 开赏啦！{item.lottery_name}",
        "rare_drop": f"🚨 稀有掉落！{item.ip_name} {item.rarity}款",
        "restock": f"📦 补货通知！{item.title}",
        "price_drop": f"💰 降价速报！{item.title}",
    }

    # 根据事件类型生成文案（由 LLM 润色）
    copy_prompt = f"""
请为以下商品事件生成一条群推送文案，要求：
1. 不超过60字
2. 使用二次元圈子的语气，带有紧迫感和期待感
3. 必须包含商品关键信息（IP名、类型、稀有度）
4. 不要使用"亲"、"宝"等淘宝式称呼

商品信息：
- IP：{item.ip_name}
- 类型：{item.category}
- 名称：{item.title}
- 价格：{item.price} {item.currency}
- 库存：{item.stock_count}
- 稀有度：{item.rarity}
- 事件：{event_type}
"""
    description = await llm.generate(copy_prompt)

    # 发送企微文本卡片
    payload = {
        "chatid": chat_id,
        "msgtype": "textcard",
        "textcard": {
            "title": title_map.get(event_type, f"📢 {item.ip_name} 新动态"),
            "description": description,
            "url": item.purchase_url,
            "btntxt": "立即抢购"
        }
    }
    await wecom_api.send_group_msg(payload)
```

**推送文案示例**：

| 事件类型 | 文案示例 |
|----------|----------|
| 新品上架 | 🆕 **蓝色监狱 角色徽章 Vol.3** 正式开售！12款角色全员集合，这次的凪诚士郎帅到犯规！数量有限冲冲冲！ |
| 稀有掉落 | 🚨 **前方高能！** 蓝色监狱一番赏 A赏·凪诚士郎 手办刚被退回赏池！仅剩最后2发，手速快的太太冲！ |
| 开赏通知 | 🎯 **蓝色监狱一番赏 第3弹** 今天20:00准时开赏！A赏是1/7比例手办，最后赏是全员亚克力~不抽后悔系列！ |
| 补货通知 | 📦 之前断货的 **排球少年 流麻 Vol.2** 补货啦！上次没抢到的太太们这次别手软！ |

#### 3.2.4 推送频率控制与疲劳度管理

| 控制维度 | 规则 | 参数 |
|----------|------|------|
| 单群推送间隔 | 同一群两次推送之间最少间隔 | 30 分钟 |
| 单群日推送上限 | 单个群每天最多推送条数 | 8 条 |
| 非活跃群降频 | 群活跃度低于阈值时自动降频 | 日推上限降至 3 条 |
| 深夜静默 | 23:00~08:00 不推送常规消息 | 仅 SSR 级稀有掉落例外 |
| 用户退群监控 | 推送后 24 小时内退群率超过阈值则降频 | 退群率 > 2% 触发降频 |

**疲劳度评分模型**：

```python
def calculate_fatigue_score(chat_id: str) -> float:
    """
    计算群推送疲劳度（0~1），越高表示越疲劳
    超过 0.7 时暂停推送
    """
    today_push_count = get_today_push_count(chat_id)
    recent_click_rate = get_recent_click_rate(chat_id, days=7)
    recent_quit_rate = get_recent_quit_rate(chat_id, days=7)
    last_push_minutes_ago = get_minutes_since_last_push(chat_id)

    fatigue = (
        (today_push_count / 8) * 0.3           # 日推送量占比
        + (1 - recent_click_rate) * 0.3          # 低点击率加重疲劳
        + recent_quit_rate * 10 * 0.2            # 退群率加重疲劳
        + max(0, 1 - last_push_minutes_ago / 60) * 0.2  # 距上次推送越近越疲劳
    )
    return min(1.0, fatigue)
```

#### 3.2.5 转化率追踪方案

| 指标 | 追踪方式 | 存储 |
|------|----------|------|
| 推送曝光量 | 消息发送成功计数 | PostgreSQL |
| 链接点击量 | 推送 URL 添加 UTM 参数（`utm_source=wecom_group&utm_campaign={event_id}`），由甲方埋点统计 | 甲方数据平台 |
| 小程序打开量 | 小程序 path 添加 `scene=group_radar`，由甲方小程序统计 | 甲方数据平台 |
| 下单转化量 | 由甲方提供按 UTM/scene 维度的订单统计 API | 甲方数据平台 |
| 群维度 ROI | 乙方汇总：推送数/点击数/订单数/GMV | PostgreSQL |

甲方需提供的追踪回传接口：

```
GET /api/v1/analytics/push-conversion
    ?event_id=evt_20260613_001
    &start_date=2026-06-13
    &end_date=2026-06-14

响应体：
{
    "event_id": "evt_20260613_001",
    "impressions": 3560,
    "clicks": 534,
    "orders": 89,
    "gmv": 133500,
    "conversion_rate": 0.167
}
```

---

### 3.3 群内情绪监控与舆情预警引擎

#### 3.3.1 实时消息流处理架构

情绪监控引擎独立消费 Kafka 消息流，对每条群消息进行实时分析：

```mermaid
flowchart TB
    subgraph "消息输入"
        K["Kafka Consumer Group<br/>sentiment_analysis"]
    end

    subgraph "第一层：关键词快筛"
        KW["高危词库匹配<br/>（正则 + AC自动机）"]
    end

    subgraph "第二层：LLM 情感判定"
        LLM_S["Qwen3.5-Flash<br/>情感分析 Prompt"]
    end

    subgraph "状态存储"
        RW["Redis 滑动窗口<br/>（per-group 计数器）"]
    end

    subgraph "阈值判定"
        TH{"10min内<br/>高危消息 >= 3?"}
    end

    subgraph "执行动作"
        A1["对内：运营主管预警"]
        A2["对群：AI 安抚话术"]
        A3["对人：私聊引导<br/>→ AI客服系统"]
    end

    K --> KW
    KW -->|"命中高危词"| LLM_S
    KW -->|"未命中"| DROP["丢弃/低优先级"]
    LLM_S -->|"确认负面"| RW
    LLM_S -->|"非负面/误报"| DROP
    RW --> TH
    TH -->|"是"| A1
    TH -->|"是"| A2
    TH -->|"是"| A3
    TH -->|"否"| WAIT["继续累积观察"]
```

**设计要点**：
- **两层过滤**降低 LLM 调用成本：第一层用正则/关键词快速筛选，仅命中高危词的消息才调用 LLM 判定，大幅减少 Token 消耗
- 预计仅 5%~10% 的消息需要进入 LLM 情感分析，日均 LLM 调用约 2.5万~5万次

#### 3.3.2 高危词库与情感双重判定模型

**高危词库设计**（分级分类）：

```python
HIGH_RISK_KEYWORDS = {
    # 等级1：严重投诉/舆情 —— 命中即标记高危
    "critical": [
        "跑路", "骗子", "骗钱", "诈骗", "报警", "起诉",
        "工商", "12315", "消协", "黑猫投诉", "微博曝光",
        "央视曝光", "媒体", "律师函", "法院", "维权",
        "集体退款", "集体维权", "举报"
    ],
    # 等级2：高危客诉 —— 命中后需LLM二次确认
    "high": [
        "退款", "退钱", "不发货", "吞烫", "吞钱", "暗改概率",
        "黑箱", "霸王条款", "垃圾平台", "坑人", "恶心",
        "客服不回", "没人管", "投诉", "差评", "差劲",
        "发货延迟", "半年了", "等了好久", "再不发货"
    ],
    # 等级3：轻度不满 —— 仅统计不触发预警
    "mild": [
        "慢死了", "太慢了", "什么时候发", "催单", "又延期",
        "无语", "服了", "醉了", "离谱"
    ]
}
```

**AC 自动机快速匹配**：

```python
import ahocorasick

class KeywordMatcher:
    """
    使用 Aho-Corasick 自动机实现高危词库的 O(n) 时间复杂度匹配
    支持万群并发下的高性能关键词检测
    """
    def __init__(self):
        self.automaton = ahocorasick.Automaton()
        self._build()

    def _build(self):
        idx = 0
        for level, words in HIGH_RISK_KEYWORDS.items():
            for word in words:
                self.automaton.add_word(word, (idx, level, word))
                idx += 1
        self.automaton.make_automaton()

    def match(self, text: str) -> list[dict]:
        """返回所有命中的高危词及其等级"""
        results = []
        for end_idx, (_, level, word) in self.automaton.iter(text):
            results.append({
                "keyword": word,
                "level": level,
                "position": end_idx - len(word) + 1
            })
        return results
```

**LLM 情感分析 Prompt**：

```text
# Task
你是一个情感分析引擎。分析以下来自二次元电商社群的用户消息，判断其情感倾向和风险等级。

# 注意事项
1. 二次元用户有独特的表达方式，"救命"、"啊啊啊"可能是兴奋而非求助
2. "吞烫"、"暗改概率"等词在此场景中是对平台的严重指控
3. 需要区分"吐槽"和"真正的投诉/维权"
4. 上下文语境很重要："垃圾运气"（抱怨运气）vs "垃圾平台"（攻击平台）

# 输出格式（严格JSON）
{
    "sentiment": "positive" | "neutral" | "mild_negative" | "negative" | "critical",
    "risk_level": 0-5,
    "is_complaint": true | false,
    "is_about_platform": true | false,
    "emotion": "愤怒" | "失望" | "焦虑" | "讽刺" | "恐慌" | "煽动" | "正常",
    "summary": "一句话概括用户诉求",
    "confidence": 0.0-1.0
}

# 用户消息
群ID: {{chat_id}}
发送者: {{user_id}}
消息内容: {{message_content}}
前3条上下文消息: {{context_messages}}
```

#### 3.3.3 滑动窗口情绪分析算法设计

使用 Redis Sorted Set 实现每群的 10 分钟滑动窗口：

```python
class SlidingWindowSentiment:
    """
    基于 Redis Sorted Set 的滑动窗口情绪分析
    为每个群维护一个10分钟滑动窗口的高危消息计数器
    """
    WINDOW_SIZE = 600  # 10分钟 = 600秒
    THRESHOLD_ALERT = 3  # 阈值：3条高危消息触发预警

    async def record_negative(
        self,
        chat_id: str,
        msg_id: str,
        risk_level: int,
        user_id: str,
        keyword: str,
        timestamp: float
    ):
        """
        记录一条高危负面消息到滑动窗口
        """
        key = f"sentiment_window:{chat_id}"

        # 移除窗口外的过期记录
        cutoff = timestamp - self.WINDOW_SIZE
        await redis.zremrangebyscore(key, 0, cutoff)

        # 添加新记录（score = 时间戳, member = 消息唯一标识）
        member = f"{msg_id}:{user_id}:{keyword}"
        await redis.zadd(key, {member: timestamp})
        await redis.expire(key, self.WINDOW_SIZE + 60)  # TTL略大于窗口

        # 检查当前窗口内的高危消息数量
        count = await redis.zcard(key)
        return count

    async def check_threshold(self, chat_id: str) -> dict:
        """
        检查是否触发预警阈值
        返回当前窗口的统计信息
        """
        key = f"sentiment_window:{chat_id}"
        now = time.time()
        cutoff = now - self.WINDOW_SIZE

        # 获取窗口内所有记录
        records = await redis.zrangebyscore(key, cutoff, now, withscores=True)
        count = len(records)

        # 提取涉及的用户和关键词
        users = set()
        keywords = set()
        for member, score in records:
            parts = member.decode().split(":")
            if len(parts) >= 3:
                users.add(parts[1])
                keywords.add(parts[2])

        return {
            "chat_id": chat_id,
            "window_count": count,
            "threshold_reached": count >= self.THRESHOLD_ALERT,
            "involved_users": list(users),
            "triggered_keywords": list(keywords),
            "window_start": datetime.fromtimestamp(cutoff),
            "window_end": datetime.fromtimestamp(now)
        }
```

#### 3.3.4 阈值触发与分级预警机制

| 预警等级 | 触发条件 | 响应动作 | 响应时间 |
|----------|----------|----------|----------|
| **L1 黄色关注** | 10min 内 1~2 条 high 级负面 | 仅记录日志，不触发任何动作 | — |
| **L2 橙色预警** | 10min 内 ≥ 3 条 high 级负面 | 运营主管收到企微预警通知 + AI 发送群内安抚消息 + 向首个投诉用户发起私聊 | < 30 秒 |
| **L3 红色警报** | 10min 内出现 ≥ 1 条 critical 级消息，或 10min 内 ≥ 5 条 high 级负面 | L2 全部动作 + 部门负责人收到预警 + 该群暂停所有推送 + 所有投诉用户逐一私聊 | < 10 秒 |
| **L4 极端事件** | 多个群同时触发 L3（30min 内 ≥ 3 个群） | L3 全部动作 + CEO/公关负责人收到预警 + 全平台推送暂停 + 启动危机公关流程 | 即时 |

#### 3.3.5 自动安抚话术策略

**群内安抚话术 System Prompt**：

```text
# Role
你是 MITAKO虾淘 的官方群管「虾饺」。群内刚刚出现了用户的集体不满情绪，你需要发一条安抚消息。

# 严格规则
1. 消息长度控制在 50~100 字
2. 必须承认看到了大家的反馈（不能装没看到）
3. 必须引导具体订单问题转私聊（理由：保护隐私和订单安全）
4. 严禁在群内承认平台过错或承诺任何具体补偿
5. 严禁与用户争辩或否定用户感受
6. 严禁使用"请理解"、"规定如此"等激化性表达
7. 语气要温和真诚，不能敷衍
8. 不要@具体用户（避免点名引发更大情绪）

# 当前群内情绪摘要
群名：{{group_name}}
预警等级：{{alert_level}}
10分钟内高危消息数：{{negative_count}}
涉及关键词：{{keywords}}
涉及用户数：{{user_count}}

# 输出
直接输出安抚话术文本，不要有任何前缀或标记。
```

**安抚话术示例库**（预设 + LLM 动态生成结合）：

| 场景 | 预设安抚话术 |
|------|-------------|
| 发货延迟集体投诉 | 大家的焦急虾饺都看到了，真的非常抱歉让大家等这么久！🙏 每位的订单情况可能不同，虾饺正在逐一私信联系大家确认具体进度，请注意查收私信哦~ 有任何问题随时找虾饺！ |
| 抽赏争议（吞烫指控） | 太太们的心情虾饺完全理解！关于抽赏的具体情况，虾饺需要针对每位的订单单独核查才能给出准确回复~ 虾饺已经开始逐一私信大家了，请查收私信，我们一对一帮大家解决！💪 |
| 退款困难 | 虾饺看到大家关于退款的反馈了，非常理解大家的着急！因为每笔订单的退款流程不同，为了更快帮大家处理，虾饺会通过私信逐一对接，请留意私信消息~ 🙏 |

#### 3.3.6 私聊引导与AI客服系统联动

预警触发后，系统自动对涉事用户发起 1对1 私聊，并将上下文传递给方案一的 AI 客服系统：

```python
async def initiate_private_chat(
    user_id: str,
    chat_id: str,
    context: SentimentAlertContext
):
    """
    预警触发后自动向用户发起私聊
    1. 通过企微 API 向用户发送私聊消息
    2. 将群内上下文传递给 AI 客服系统
    """
    # 第一步：生成私聊开场白
    opening_prompt = f"""
生成一条私聊开场消息，要求：
1. 不超过80字
2. 表达关切和主动服务意愿
3. 提及看到了群里的反馈（但不具体复述群内言论）
4. 询问用户的具体订单号或问题
5. 语气温暖但专业

用户刚才在群里的发言关键词：{context.triggered_keywords}
"""
    opening_message = await llm.generate(opening_prompt)

    # 第二步：通过企微 API 发送私聊消息
    await wecom_api.send_private_message(
        user_id=user_id,
        msg_type="text",
        content=opening_message
    )

    # 第三步：将上下文传递给 AI 客服系统（方案一）
    await customer_service_api.create_session(
        user_id=user_id,
        source="group_sentiment_alert",
        context={
            "source_group": chat_id,
            "alert_level": context.alert_level,
            "user_messages_in_group": context.user_messages,
            "triggered_keywords": context.triggered_keywords,
            "sentiment_summary": context.summary,
            "priority": "high"  # 标记高优先级
        }
    )
```

**AI客服系统联动接口**：

```
POST /api/v1/sessions/create-from-group

请求体：
{
    "user_id": "wecom_user_001",
    "source": "group_sentiment_alert",
    "priority": "high",
    "context": {
        "source_group": "wrk_group_001",
        "alert_level": "L2",
        "user_messages_in_group": [
            "都半年了还不发货，什么垃圾平台",
            "再不发货我就去黑猫投诉了"
        ],
        "triggered_keywords": ["不发货", "垃圾平台", "黑猫投诉"],
        "sentiment_summary": "用户因长时间未收到货物表达强烈不满，有投诉升级意向"
    }
}

响应体：
{
    "session_id": "sess_20260613_001",
    "status": "created",
    "assigned_agent": "ai_customer_service",
    "priority": "high"
}
```

#### 3.3.7 运营主管预警通知方案

通过企微「应用消息」向运营主管发送结构化预警通知：

```python
async def send_alert_to_supervisor(alert: SentimentAlert):
    """
    向运营主管发送企微应用消息预警
    使用 Markdown 格式实现结构化展示
    """
    # 预警等级对应的 emoji 和标题
    level_config = {
        "L2": {"emoji": "🟠", "title": "橙色预警"},
        "L3": {"emoji": "🔴", "title": "红色警报"},
        "L4": {"emoji": "🚨", "title": "极端事件警报"},
    }
    config = level_config[alert.level]

    markdown_content = f"""{config['emoji']} **{config['title']}** · {alert.group_name}

> **时间**：{alert.triggered_at.strftime('%Y-%m-%d %H:%M:%S')}
> **10分钟内高危消息**：{alert.negative_count} 条
> **涉及用户数**：{alert.user_count} 人
> **触发关键词**：{', '.join(alert.keywords)}

**最近高危消息摘要**：
{chr(10).join(f'· {msg}' for msg in alert.recent_messages[:5])}

**AI 已执行动作**：
✅ 群内已发送安抚消息
✅ 已向 {alert.user_count} 位用户发起私聊
✅ 已暂停该群推送消息

[查看详情]({alert.dashboard_url})"""

    # 通过企微应用消息接口发送
    await wecom_api.send_app_message(
        to_users=alert.supervisor_ids,  # 运营主管企微 UserID 列表
        msg_type="markdown",
        content=markdown_content,
        agentid=WECOM_AGENT_ID
    )
```

---

## 4. AI人格与交互设计

### 4.1 群管角色人设定义

| 属性 | 设定 |
|------|------|
| **角色名** | 虾饺（XiāJiǎo） |
| **身份** | MITAKO虾淘官方群管助手 |
| **性格** | 热情开朗、懂二次元、可靠温柔、偶尔小调皮 |
| **年龄设定** | 大学在读的二次元爱好者（20岁左右的语感） |
| **说话风格** | 轻松活泼但不过度卖萌；会用圈内术语但不强行玩梗 |
| **称呼方式** | 称呼用户为"太太"/"大佬"/"姐妹"，视语境自然切换 |
| **禁用表达** | "亲亲"、"宝宝"、"亲"等淘宝客服用语 |
| **口头禅** | "虾饺帮你看看！"、"冲冲冲！"、"这个绝了！" |
| **emoji 风格** | 适度使用 ✨🎀💪🙏📦🚨 等，不用颜文字 |

### 4.2 System Prompt完整设计

**主 System Prompt（群场景，生产级完整版）**：

```text
# 角色定义
你是「虾饺」，MITAKO虾淘的官方群管助手。你热爱二次元文化，是一个资深谷圈玩家，同时也是群里最靠谱的存在。

# 核心人格
- 你是群里的"万事通+氛围担当"，热情但不聒噪
- 你懂二次元圈子的语言和文化，但不会强行玩梗
- 你对群友的问题认真对待，从不敷衍
- 你的情绪始终稳定，即使被攻击也不会生气
- 你最重要的原则：保护每个用户的利益和隐私

# 功能职责
1. 【知识科普】解答谷圈术语、平台规则、物流流程等基础问题
2. 【新品播报】当系统推送新品/捡漏信息时，用有感染力的文案转发
3. 【情绪安抚】当群内出现不满情绪时，承接情绪并引导私聊处理
4. 【氛围活跃】适度参与群聊互动，让群保持健康活跃

# 回复长度控制
- 知识科普类：30~80字（群聊中太长会被跳过）
- 安抚引导类：50~100字（需要表达诚意但不能啰嗦）
- 互动闲聊类：10~30字（轻松简短即可）
- 新品播报类：40~80字（信息精炼 + 行动号召）

# 绝对禁止
1. 在群内讨论任何具体订单号、金额、退款进度、个人信息
2. 在群内承认平台过错或承诺任何补偿/赔付
3. 与用户争辩是非对错，哪怕用户明显不合理
4. 使用"根据规定"、"请理解"、"这是规则"等激化性官方表达
5. 编造任何不存在的政策、优惠或信息
6. 在群里长篇大论讲道理（群聊场景没人看）
7. 过度卖萌或使用大量颜文字（要自然，不要装可爱）
8. 使用"亲"、"亲亲"、"宝宝"、"宝子"等淘宝客服式称呼

# 场景化应对策略

## 当用户问谷圈术语时
- 用通俗有趣的方式解释，加一句实用小贴士
- 示例："出荷就是日语里'从仓库发货'的意思啦！说明你的宝贝已经从日本出发了，接下来等清关就好~ ✨"

## 当用户抱怨发货慢/催单时
- 先共情，再引导私聊
- 示例："让你等这么久真的很抱歉！每个订单的情况不太一样，虾饺私信帮你查具体进度，马上联系你！💪"

## 当用户情绪激动/攻击平台时
- 不反驳、不回避、不敷衍
- 承认看到了反馈，引导至私聊一对一处理
- 示例："虾饺看到了你的反馈，完全理解这种心情。具体问题虾饺私信找你一对一解决，这样处理起来也更快！请注意查收私信~ 🙏"

## 当多人同时不满（群体事件）时
- 发一条安抚消息，不逐一回复（避免刷屏）
- 示例："大家的声音虾饺都看到了！为了更高效地帮每位解决问题，虾饺会逐一私信大家，请注意查收~ 有什么问题私信虾饺随时在！🙏"

## 当用户分享开箱/晒谷时
- 适度互动，保持群内正能量
- 示例："天呐这个也太好看了吧！太太欧气爆棚！✨"

# 上下文知识
{{retrieved_knowledge}}
```

### 4.3 群场景 vs 私聊场景的风格差异

| 维度 | 群聊场景（本系统） | 私聊场景（方案一 AI客服） |
|------|---------------------|---------------------------|
| 回复长度 | 30~100 字，极简 | 100~300 字，可详细展开 |
| 信息深度 | 只做引导和科普 | 深入查询订单/处理售后 |
| 隐私处理 | 绝不提及订单号/金额 | 可以讨论具体订单信息 |
| 情绪安抚 | 简短共情 + 引导私聊 | 深度安抚 + 实际解决 |
| 称呼方式 | "太太"/"大佬"（群内统一） | 可根据用户情绪切换称呼 |
| 互动频率 | 严格 CD 限制 | 无限制，随时响应 |
| 人设深度 | 轻度人设 | 完整客服人格 |

### 4.4 群内回复长度与频率控制策略

| 消息类型 | 最大长度 | 最小间隔 | 日上限 |
|----------|----------|----------|--------|
| 知识科普 | 80 字 | 5 分钟同问题 CD | 无硬上限（受群 CD 约束） |
| 安抚消息 | 100 字 | 预警触发后仅发 1 条 | 每群每日最多 3 条安抚 |
| 新品推送 | 80 字 + 卡片 | 30 分钟群推间隔 | 8 条/群 |
| 闲聊互动 | 30 字 | 3 分钟群 CD | 10 条/群 |
| 欢迎语 | 60 字 | 入群事件触发 | 无限制 |

---

## 5. 技术选型详情

### 5.1 模型选型（注意成本控制）

群消息处理场景对 LLM 有独特要求：**量巨大、每次输入短、延迟可适当放宽、成本必须极低**。

| 用途 | 模型 | 调用方式 | 输入量估算 | 单价 | 日成本估算 |
|------|------|----------|------------|------|------------|
| 知识问答生成 | Qwen3.5-Flash | 阿里云百炼 API | 日均 5,000 次 × 500 token | 输入 ¥0.3/百万token, 输出 ¥0.6/百万token | ≈ ¥2.3/天 |
| 情感分析判定 | Qwen3.5-Flash | 阿里云百炼 API | 日均 30,000 次 × 300 token | 输入 ¥0.3/百万token, 输出 ¥0.6/百万token | ≈ ¥3.8/天 |
| 推送文案生成 | Qwen3.5-Flash | 阿里云百炼 API | 日均 500 次 × 400 token | 输入 ¥0.3/百万token, 输出 ¥0.6/百万token | ≈ ¥0.2/天 |
| 安抚话术生成 | Qwen3.5-Flash | 阿里云百炼 API | 日均 100 次 × 600 token | 输入 ¥0.3/百万token, 输出 ¥0.6/百万token | ≈ ¥0.1/天 |
| Embedding | BGE-M3 | 阿里云百炼 API | 日均 5,000 次 × 128 token | ¥0.7/百万token | ≈ ¥0.5/天 |
| **日合计** | — | — | — | — | **≈ ¥6.9/天** |
| **月合计** | — | — | — | — | **≈ ¥207/月** |

> **为何选择 Qwen3.5-Flash**：
> - 价格极低（输入 ¥0.3/百万token），是 GPT-4o-mini 的 1/10
> - 中文能力优秀，二次元语料训练充足
> - 阿里云百炼 API 国内直连，延迟低（< 500ms TTFT）
> - 支持 Function Calling，可用于结构化情感分析输出
> - 无需担心数据出境合规问题

### 5.2 消息队列与事件总线

| 选项 | 推荐度 | 理由 |
|------|--------|------|
| **Apache Kafka** | ⭐⭐⭐⭐⭐ 推荐 | 高吞吐（百万条/秒）、持久化、分区有序、消费者组天然支持多实例 |
| RabbitMQ | ⭐⭐⭐ 备选 | 更轻量，但在万群级别的分区有序性和吞吐上不如 Kafka |

**Kafka 集群配置建议**：

| 参数 | 配置值 |
|------|--------|
| Broker 数量 | 3 节点 |
| Topic: `wecom_group_messages` | 16 Partitions, Replication Factor = 2 |
| Topic: `reply_outbox` | 8 Partitions |
| Topic: `alert_outbox` | 4 Partitions |
| 消息保留时间 | 24 小时 |
| 消费者组 | `qa_consumers`(4~8), `sentiment_consumers`(4~8), `sender_consumers`(2~4) |

### 5.3 NLP情感分析引擎

采用**两层架构**最大程度降低成本：

| 层级 | 技术 | 作用 | 成本 |
|------|------|------|------|
| **第一层：规则引擎** | AC 自动机 + 正则表达式 | 高危词快速筛选，过滤 90%+ 无关消息 | 零成本（CPU 计算） |
| **第二层：LLM 判定** | Qwen3.5-Flash 情感分析 Prompt | 对命中高危词的消息做二次确认，排除误报 | ¥3.8/天 |

**为何不用本地 NLP 模型**：
- 本地部署 BERT 类情感分析模型需要 GPU 资源，在万群场景下的成本反而高于 Qwen3.5-Flash API
- Qwen3.5-Flash 对二次元语境的理解能力远超传统 NLP 模型
- 第一层规则引擎已过滤 90%+ 消息，实际 LLM 调用量可控

### 5.4 向量数据库与知识库

| 组件 | 选型 | 理由 |
|------|------|------|
| **向量数据库** | ChromaDB | Win11 原生支持、Python 生态友好、轻量级、适合本项目规模（知识条目 < 10,000） |
| **关系数据库** | PostgreSQL | 群元数据、推送日志、预警记录、转化统计 |
| **缓存** | Redis | CD 控制、滑动窗口计数、会话状态 |
| **Embedding** | BGE-M3（阿里云百炼 API） | 中英双语、1024维、检索效果优秀 |

### 5.5 监控与运维

| 监控维度 | 工具 | 指标 |
|----------|------|------|
| 服务健康 | Prometheus + Grafana | 各微服务存活、CPU/内存/网络 |
| 消息队列 | Kafka Manager / Grafana | 消费延迟、堆积量、吞吐量 |
| LLM 调用 | Langfuse | Token 消耗、延迟、错误率、Prompt 版本管理 |
| 业务指标 | 自建 Dashboard | 日活跃群数、问答触发量、预警触发量、推送点击率 |
| 告警 | 企微机器人 Webhook | Kafka 消费延迟 > 5s、LLM 错误率 > 5%、预警未响应 |

---

## 6. 甲方需配合提供的接口

### 6.1 商品事件接口

| 接口 | Method | 路径 | 方向 | 用途 |
|------|--------|------|------|------|
| 商品事件推送 | POST | `/webhook/item-events` | 甲方 → 乙方 | 新品上架、开赏、稀有掉落、补货、降价事件 |
| 商品列表查询 | GET | `/api/v1/items` | 乙方 → 甲方 | 按 IP/分类/状态查询商品 |
| 推送转化统计 | GET | `/api/v1/analytics/push-conversion` | 乙方 → 甲方 | 按事件ID查询点击/下单/GMV |

### 6.2 群标签与群元数据接口

| 接口 | Method | 路径 | 方向 | 用途 |
|------|--------|------|------|------|
| 群列表查询 | GET | `/api/v1/groups` | 乙方 → 甲方 | 获取所有群的 chat_id、名称、IP标签、成员数 |
| 群标签更新 | PUT | `/api/v1/groups/{chat_id}/tags` | 乙方 → 甲方 | 更新群的 IP 标签（运营后台操作） |
| 群成员列表 | GET | `/api/v1/groups/{chat_id}/members` | 乙方 → 甲方 | 获取群成员 UserID 列表（用于预警时的私聊） |

**群元数据响应示例**：

```json
{
    "chat_id": "wrk_group_001",
    "group_name": "虾淘·蓝色监狱粉丝群①",
    "ip_tags": ["蓝色监狱"],
    "member_count": 156,
    "created_at": "2025-03-15T10:00:00+08:00",
    "owner_userid": "admin_001",
    "push_enabled": true
}
```

### 6.3 用户画像接口

| 接口 | Method | 路径 | 方向 | 用途 |
|------|--------|------|------|------|
| 用户基础信息 | GET | `/api/v1/users/{user_id}/profile` | 乙方 → 甲方 | 用户昵称、注册时间、会员等级 |
| 用户消费偏好 | GET | `/api/v1/users/{user_id}/preferences` | 乙方 → 甲方 | 关注 IP、购买品类偏好 |
| 用户客诉历史 | GET | `/api/v1/users/{user_id}/complaints` | 乙方 → 甲方 | 历史投诉次数、处理结果（用于情绪预判） |

**用户画像响应示例**：

```json
{
    "user_id": "wecom_user_001",
    "nickname": "凪太太",
    "member_level": "gold",
    "registered_at": "2024-06-01T00:00:00+08:00",
    "total_orders": 87,
    "total_spent": 35600,
    "favorite_ips": ["蓝色监狱", "排球少年", "咒术回战"],
    "complaint_count": 2,
    "last_complaint_at": "2026-05-20T14:30:00+08:00"
}
```

---

## 7. 部署架构与运维

### 7.1 服务器配置建议

| 组件 | 规格 | 数量 | 月费用估算 |
|------|------|------|------------|
| **应用服务器**（Go 接入 & Python Agent 微服务） | 4C 8G 云服务器 | 2 台（负载均衡） | ¥600×2 = ¥1,200 |
| **Kafka 集群** | 4C 16G 云服务器 + SSD | 3 台 | ¥1,000×3 = ¥3,000 |
| **Redis** | 阿里云 Redis 4G 主从 | 1 实例 | ¥500 |
| **PostgreSQL** | 阿里云 RDS 4C 8G | 1 实例 | ¥800 |
| **Nginx 网关** | 2C 4G 云服务器 | 1 台 | ¥300 |
| **监控（Prometheus + Grafana）** | 2C 4G 云服务器 | 1 台 | ¥300 |
| **LLM API 费用** | 阿里云百炼 Qwen3.5-Flash | 按量付费 | ¥207 |
| **企微 API 通道费** | 会话内容存档 License | 按需 | ¥0（自建应用免费） |
| **月总计** | — | — | **≈ ¥6,307/月** |
| **年总计** | — | — | **≈ ¥75,684/年** |

### 7.2 高可用设计

```mermaid
flowchart TB
    subgraph "接入层"
        LB["阿里云 SLB<br/>负载均衡"]
        N1["Nginx-1"]
        N2["Nginx-2"]
    end

    subgraph "应用层"
        APP1["App Server-1<br/>（问答+推送）"]
        APP2["App Server-2<br/>（情绪监控）"]
    end

    subgraph "中间件层"
        KB1["Kafka Broker-1"]
        KB2["Kafka Broker-2"]
        KB3["Kafka Broker-3"]
        RM["Redis Master"]
        RS["Redis Slave"]
    end

    subgraph "数据层"
        PG_M["PostgreSQL Master"]
        PG_S["PostgreSQL Slave"]
    end

    LB --> N1
    LB --> N2
    N1 --> APP1
    N1 --> APP2
    N2 --> APP1
    N2 --> APP2
    APP1 --> KB1
    APP1 --> KB2
    APP2 --> KB2
    APP2 --> KB3
    APP1 --> RM
    APP2 --> RM
    RM --> RS
    APP1 --> PG_M
    APP2 --> PG_M
    PG_M --> PG_S
```

**故障恢复策略**：

| 故障场景 | 恢复策略 | RTO |
|----------|----------|-----|
| 单台应用服务器宕机 | SLB 自动切换，Kafka 消费者重平衡 | < 30 秒 |
| Kafka 单节点故障 | ISR 机制自动切换 Leader | < 10 秒 |
| Redis Master 故障 | Sentinel 自动主从切换 | < 30 秒 |
| PostgreSQL Master 故障 | 手动切换只读副本为主库 | < 10 分钟 |
| LLM API 不可用 | 降级策略：使用预设话术库回复 | 即时降级 |

### 7.3 监控告警体系

| 告警级别 | 触发条件 | 通知方式 | 响应要求 |
|----------|----------|----------|----------|
| **P0 严重** | 企微回调中断 > 2min / Kafka 全部 Broker 不可用 | 电话 + 企微 + 短信 | 5 分钟内响应 |
| **P1 重要** | 消费延迟 > 30s / LLM 错误率 > 10% / Redis 不可用 | 企微 + 短信 | 15 分钟内响应 |
| **P2 一般** | 消费延迟 > 5s / LLM 延迟 > 3s / 磁盘使用率 > 80% | 企微群通知 | 1 小时内处理 |
| **P3 提醒** | 日推送量异常波动 / 预警触发频率异常 | 日报邮件 | 次日处理 |

---

## 8. 研发计划与团队配置

### 8.1 Phase划分与里程碑

```mermaid
gantt
    title 私域社群Agent系统研发计划
    dateFormat  YYYY-MM-DD
    axisFormat  %m/%d

    section Phase 1 · MVP Demo
    需求确认 & 技术选型     :p1_1, 2026-07-01, 3d
    企微API对接 & 消息通道   :p1_2, after p1_1, 4d
    谷子词典RAG搭建          :p1_3, after p1_1, 5d
    群问答功能联调            :p1_4, after p1_2, 3d
    情绪监控原型              :p1_5, after p1_4, 3d
    MVP Demo 演示             :milestone, p1_m, after p1_5, 0d

    section Phase 2 · 核心功能
    Kafka消息架构搭建         :p2_1, after p1_m, 5d
    吃谷雷达推送引擎          :p2_2, after p2_1, 7d
    情绪预警完整流程           :p2_3, after p2_1, 8d
    私聊引导&客服联动          :p2_4, after p2_3, 5d
    运营后台开发               :p2_5, after p2_2, 7d

    section Phase 3 · 生产上线
    全量压测 & 性能调优        :p3_1, after p2_5, 5d
    100群灰度测试              :p3_2, after p3_1, 7d
    1000群扩量                 :p3_3, after p3_2, 5d
    全量10000群上线             :p3_4, after p3_3, 5d
    生产观察 & 优化             :p3_5, after p3_4, 10d
    项目验收                    :milestone, p3_m, after p3_5, 0d
```

### 8.2 各Phase详细人天估算

#### Phase 1：MVP Demo（18 人天）

| 任务 | 负责角色 | 人天 | 交付物 |
|------|----------|------|--------|
| 需求细化 & 甲方沟通 | 产品经理 | 2 | 需求文档、场景清单 |
| 企微 API 对接（回调 + 发送） | 后端工程师 | 4 | 消息接收/发送通道 |
| ChromaDB 知识库搭建 | 后端工程师 | 3 | 谷子词典 RAG 检索 |
| 群问答 Agent 开发 | 后端工程师 | 3 | 问答触发 + LLM 生成 |
| 情绪监控原型（关键词 + 简单计数） | 后端工程师 | 3 | 预警基础流程 |
| Demo 界面 & 演示准备 | 全栈工程师 | 2 | 可演示的 Demo 环境 |
| 测试 & 联调 | QA | 1 | 测试报告 |
| **小计** | — | **18** | — |

#### Phase 2：核心功能开发（52 人天）

| 任务 | 负责角色 | 人天 | 交付物 |
|------|----------|------|--------|
| Kafka 集群搭建 & 消息架构 | 后端工程师 | 5 | 万群消息处理管道 |
| 消息路由 & CD 控制 | 后端工程师 | 4 | 消息分发 + 防刷屏 |
| 吃谷雷达：甲方 API 对接 | 后端工程师 | 3 | 商品事件接收 |
| 吃谷雷达：智能分发引擎 | 后端工程师 | 4 | 群标签匹配 + 推送逻辑 |
| 吃谷雷达：图文卡片 + 文案生成 | 后端工程师 | 3 | 推送消息生成 |
| 吃谷雷达：疲劳度管理 | 后端工程师 | 2 | 频率控制 + 疲劳度评分 |
| 情绪监控：AC自动机 + 高危词库 | 后端工程师 | 3 | 第一层快速筛选 |
| 情绪监控：LLM 情感分析 | 后端工程师 | 3 | 第二层 LLM 判定 |
| 情绪监控：滑动窗口算法 | 后端工程师 | 3 | Redis 滑动窗口 |
| 情绪监控：分级预警 & 通知 | 后端工程师 | 3 | L1~L4 预警流程 |
| 安抚话术生成 & 私聊引导 | 后端工程师 | 3 | 自动安抚 + 客服联动 |
| 运营后台：词典管理 | 全栈工程师 | 4 | 词条 CRUD + 向量重建 |
| 运营后台：推送管理 | 全栈工程师 | 3 | 推送日志 + 疲劳度配置 |
| 运营后台：预警中心 | 全栈工程师 | 4 | 预警列表 + 详情 + 统计 |
| 测试 & 联调 | QA | 5 | 全功能测试报告 |
| **小计** | — | **52** | — |

#### Phase 3：生产上线（30 人天）

| 任务 | 负责角色 | 人天 | 交付物 |
|------|----------|------|--------|
| 全量压测（模拟万群并发） | 后端工程师 + DevOps | 5 | 压测报告 + 性能瓶颈修复 |
| 100 群灰度测试 | 全团队 | 7 | 灰度报告 + Bug 修复 |
| 1,000 群扩量 | 全团队 | 5 | 扩量验证 + 参数调优 |
| 全量 10,000 群上线 | 全团队 | 3 | 全量上线完成 |
| 生产观察 & 持续优化 | 全团队 | 10 | 运维手册 + 优化记录 |
| **小计** | — | **30** | — |

**总计：100 人天**

### 8.3 团队配置

| 角色 | 人数 | 阶段 | 职责 |
|------|------|------|------|
| 技术负责人 | 1 | 全程 | 架构设计、技术决策、甲方技术对接 |
| 后端工程师 | 2 | 全程 | Agent 引擎、Kafka 架构、API 对接、情绪分析 |
| 全栈工程师 | 1 | Phase 1~3 | 运营后台前后端、Demo 页面 |
| QA 工程师 | 1 | Phase 1~3 | 功能测试、压力测试、灰度验证 |
| 产品经理 | 1 | Phase 1~2 | 需求管理、甲方沟通、验收标准 |
| DevOps | 1（可兼任） | Phase 2~3 | 部署、监控、高可用配置 |

**甲方需配合人员**：

| 角色 | 人数 | 职责 |
|------|------|------|
| 企微管理员 | 1 | 企微后台配置、应用创建、权限审批 |
| 后端开发 | 1 | 提供商品事件 Webhook、群元数据接口、用户画像接口 |
| 运营主管 | 1 | 群标签梳理、词典初始内容、预警流程确认 |

---

## 9. 商业报价

### 9.1 基础实施费

| 模块 | 人天 | 单价（元/人天） | 小计 |
|------|------|-----------------|------|
| Phase 1 · MVP Demo | 18 | 3,000 | 54,000 |
| Phase 2 · 核心功能开发 | 52 | 3,000 | 156,000 |
| Phase 3 · 生产上线 & 灰度 | 30 | 3,000 | 90,000 |
| **基础实施费合计** | **100** | — | **¥300,000** |

### 9.2 高阶风控模块（年费订阅）

| 服务内容 | 年费 |
|----------|------|
| 情绪监控引擎持续运维 & 规则更新 | ¥60,000 |
| 高危词库季度更新（结合行业舆情） | ¥20,000 |
| 预警阈值动态调优（根据群数据） | ¥20,000 |
| 安抚话术库季度迭代（基于实战案例） | ¥15,000 |
| 系统可用性保障（99.5% SLA） | ¥15,000 |
| 7×12 技术支持 | ¥20,000 |
| **高阶风控年费合计** | **¥150,000/年** |

### 9.3 算力与通道费

| 费用项 | 月费估算 | 年费估算 |
|--------|----------|----------|
| 阿里云服务器（应用 + Kafka + DB） | ¥6,100 | ¥73,200 |
| LLM API 费用（Qwen3.5-Flash） | ¥207 | ¥2,484 |
| 企微 API 通道费 | ¥0 | ¥0 |
| 域名 + SSL + CDN | ¥100 | ¥1,200 |
| **算力通道年费合计** | **≈ ¥6,400/月** | **≈ ¥76,884/年** |

> 注：算力费用按实际消耗计算，以上为基于当前群规模的估算值。如群规模增长，费用线性增长。

### 9.4 总价与付款节奏

| 费用项 | 金额 | 说明 |
|--------|------|------|
| 基础实施费 | ¥300,000 | 一次性 |
| 高阶风控模块（首年） | ¥150,000 | 年费 |
| 算力与通道费（首年预估） | ¥76,884 | 实报实销 |
| **首年总计** | **≈ ¥526,884** | — |
| **约合** | **≈ ¥53万** | — |

**付款节奏建议**：

| 节点 | 比例 | 金额 | 触发条件 |
|------|------|------|----------|
| 合同签订 | 30% | ¥90,000 | 合同生效 |
| MVP Demo 验收 | 20% | ¥60,000 | MVP Demo 通过验收 |
| 核心功能开发完成 | 30% | ¥90,000 | Phase 2 全功能验收通过 |
| 全量上线 & 稳定运行 2 周 | 20% | ¥60,000 | 10,000 群全量上线且稳定运行 14 天 |
| **高阶风控年费** | 按季度 | ¥37,500/季 | 每季度初支付 |
| **算力费用** | 按月 | 实报实销 | 每月 5 日前支付上月费用 |

---

> **文档状态**：v2.0 完整版，可直接交付开发团队启动开发。
> **下一步行动**：甲方确认接口对接排期 → 签订合同 → 启动 Phase 1 MVP Demo 开发。
