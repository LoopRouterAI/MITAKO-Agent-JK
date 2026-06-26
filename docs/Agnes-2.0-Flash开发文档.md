## Agnes-2.0-Flash

**Agnes-2.0-Flash** 是由 **Sapiens AI** 开发的一款快速、高效的语言模型，面向智能体工作流、工具调用、编程任务、推理、多轮对话、图片理解以及高频生产环境应用场景设计。

Agnes-2.0-Flash 在 **Claw-Eval** 基准测试中取得了强劲表现，在 **General Leaderboard** 中排名第 **9**，**Pass^3 分数为 60.9%**，展现出在主流语言模型中较强的自主智能体能力。

* * *

### "模型概述")模型概述

Agnes-2.0-Flash 针对快速、可靠、低成本的语言生成、智能体任务执行和图片理解进行了优化。

该模型支持以下能力：

<table class="notion-simple-table notion-block-3764a189eee580319fb4cb7ed314de40"><tbody><tr class="notion-simple-table-row notion-simple-table-header-row notion-block-3764a189eee580ef98b9cc3459943a30"><td class=""><p>能力</p></td><td class=""><p>说明</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580aaaa2ad19a03321330"><td class=""><p>Chat Completion</p></td><td class=""><p>为对话和应用生成高质量回复</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580f49c55dbc1d38a1986"><td class=""><p>多轮对话</p></td><td class=""><p>在多轮交互中保持上下文连续性</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580b0852ce28e0142647c"><td class=""><p>图片 URL 输入</p></td><td class=""><p>支持通过公网图片 URL 传入图片内容</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580809ba7d6e8ccebacd1"><td class=""><p>图片理解</p></td><td class=""><p>支持基于图片的内容理解、截图分析和信息提取</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580558ca2edb3ee499cd0"><td class=""><p>工具调用</p></td><td class=""><p>调用外部工具和函数，支持智能体工作流</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580df954cd228ac451ddb"><td class=""><p>智能体工作流</p></td><td class=""><p>支持规划、执行和多步骤任务完成</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580109302f6cdf3381b4d"><td class=""><p>编程任务</p></td><td class=""><p>辅助代码生成、调试、解释和重构</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58008825ccaa0c38d112d"><td class=""><p>推理</p></td><td class=""><p>处理结构化推理、任务拆解和决策</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580ce99ecdcbb7b423bd7"><td class=""><p>流式输出</p></td><td class=""><p>实时返回响应，提升用户体验</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58006a4abcb8a28f90398"><td class=""><p>OpenAI 兼容 API</p></td><td class=""><p>使用兼容 OpenAI Chat Completions API 的结构</p></td></tr></tbody></table>

* * *

### 适用场景

Agnes-2.0-Flash 适用于以下场景：

<table class="notion-simple-table notion-block-3764a189eee580eaa03bc6befc8117c7"><tbody><tr class="notion-simple-table-row notion-simple-table-header-row notion-block-3764a189eee580559195d6ad6d63c639"><td class=""><p>场景</p></td><td class=""><p>示例用例</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580f6b60fc1ac5f215365"><td class=""><p>AI 助手</p></td><td class=""><p>通用问答、日常助手、效率支持</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580b3bb02d7d9d5c358c3"><td class=""><p>自主智能体</p></td><td class=""><p>多步骤任务执行、规划和工具使用</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58070a0cbd76b9924d028"><td class=""><p>编程助手</p></td><td class=""><p>代码生成、调试、重构和解释</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580ef975bece8032800f1"><td class=""><p>工作流自动化</p></td><td class=""><p>任务拆解、流程自动化和执行规划</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58080b4ccf51b2ae8b55e"><td class=""><p>客户支持</p></td><td class=""><p>FAQ 问答、客服聊天机器人、服务自动化</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5805dabf5f4f7429f6250"><td class=""><p>搜索与问答</p></td><td class=""><p>基于搜索的回答、摘要生成、信息提取</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58099bcfbed5131052e5d"><td class=""><p>内容生成</p></td><td class=""><p>营销文案、文章、产品描述、脚本</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58056a8ede57c05949baf"><td class=""><p>开发者工具</p></td><td class=""><p>API 助手、文档助手、编程 Copilot</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5802fbd0bcc5710def894"><td class=""><p>AI 原生应用</p></td><td class=""><p>消费级应用、效率工具、智能体应用</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580029cfffa7e1f2b08fd"><td class=""><p>图片理解</p></td><td class=""><p>图片描述、截图分析、视觉问答、信息提取</p></td></tr></tbody></table>

* * *

### API 信息

#### Endpoint

<table class="notion-simple-table notion-block-3764a189eee580cd8c52e7d436b2980e"><tbody><tr class="notion-simple-table-row notion-simple-table-header-row notion-block-3764a189eee5809d962af1f4f1de3be5"><td class=""><p>项目</p></td><td class=""><p>说明</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58076bc6bf07e02ad310e"><td class=""><p>API Endpoint</p></td><td class=""><p><code class="notion-inline-code">https://apihub.agnes-ai.com/v1/chat/completions</code></p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580debbf7d16cec729418"><td class=""><p>Request Method</p></td><td class=""><p><code class="notion-inline-code">POST</code></p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58025afcbf2dce84d8a77"><td class=""><p>Content-Type</p></td><td class=""><p><code class="notion-inline-code">application/json</code></p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5803eb41ee7634ce12ac8"><td class=""><p>Authentication</p></td><td class=""><p><code class="notion-inline-code">Bearer Token</code></p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580fcb53acb46bc55ab06"><td class=""><p>Authentication Header</p></td><td class=""><p><code class="notion-inline-code">Authorization: Bearer YOUR_API_KEY</code></p></td></tr></tbody></table>

* * *

### 请求参数

<table class="notion-simple-table notion-block-3764a189eee58016a4ace34924a84e60"><tbody><tr class="notion-simple-table-row notion-simple-table-header-row notion-block-3764a189eee5801a92a7f387b4e824c8"><td class=""><p>参数</p></td><td class=""><p>类型</p></td><td class=""><p>是否必填</p></td><td class=""><p>说明</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580a39575d6741150f84e"><td class=""><p><code class="notion-inline-code">model</code></p></td><td class=""><p>string</p></td><td class=""><p>是</p></td><td class=""><p>模型名称，固定为&nbsp;<code class="notion-inline-code">agnes-2.0-flash</code></p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5802ab266cf8a7c7abb84"><td class=""><p><code class="notion-inline-code">messages</code></p></td><td class=""><p>array</p></td><td class=""><p>是</p></td><td class=""><p>对话消息数组，包括 system、user 和 assistant 消息</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58032b4bfea32053b14e9"><td class=""><p><code class="notion-inline-code">messages[].content</code></p></td><td class=""><p>string / array</p></td><td class=""><p>是</p></td><td class=""><p>消息内容。可为纯文本字符串，也可为包含&nbsp;<code class="notion-inline-code">text</code>、<code class="notion-inline-code">image_url</code>&nbsp;的内容数组</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580c98f11f9cc44eca70b"><td class=""><p><code class="notion-inline-code">temperature</code></p></td><td class=""><p>number</p></td><td class=""><p>否</p></td><td class=""><p>控制输出随机性。较低值会生成更确定性的结果</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580ed8fffda7158e8253e"><td class=""><p><code class="notion-inline-code">top_p</code></p></td><td class=""><p>number</p></td><td class=""><p>否</p></td><td class=""><p>控制核采样。较低值会使输出更加聚焦</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580168647dcf523bea0f6"><td class=""><p><code class="notion-inline-code">max_tokens</code></p></td><td class=""><p>number</p></td><td class=""><p>否</p></td><td class=""><p>响应中最多生成的 token 数</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580959984cdd5646d375f"><td class=""><p><code class="notion-inline-code">stream</code></p></td><td class=""><p>boolean</p></td><td class=""><p>否</p></td><td class=""><p>是否启用流式响应输出</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5809b98f4de053e12e0b9"><td class=""><p><code class="notion-inline-code">tools</code></p></td><td class=""><p>array</p></td><td class=""><p>否</p></td><td class=""><p>用于工具调用工作流的工具定义</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5806e961ada97ee1e2c44"><td class=""><p><code class="notion-inline-code">tool_choice</code></p></td><td class=""><p>string / object</p></td><td class=""><p>否</p></td><td class=""><p>控制模型是否以及如何使用工具</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580f58eb2e6609bf0868c"><td class=""><p><code class="notion-inline-code">chat_template_kwargs</code></p></td><td class=""><p>object</p></td><td class=""><p>否</p></td><td class=""><p>OpenAI 兼容请求中用于开启 Thinking 等扩展能力</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5807297afd296ec4e3872"><td class=""><p><code class="notion-inline-code">thinking</code></p></td><td class=""><p>object</p></td><td class=""><p>否</p></td><td class=""><p>Anthropic 兼容请求中用于开启 Thinking 模式</p></td></tr></tbody></table>

* * *

### 图片 URL 输入支持

Agnes-2.0-Flash 支持通过图片 URL 输入图片内容。开发者可以在同一个 `messages` 请求中同时传入文本指令和图片 URL，让模型基于图片进行理解、分析、问答或信息提取。

支持的输入类型包括：

<table class="notion-simple-table notion-block-3764a189eee5802cbf9cc64ac1c0fd87"><tbody><tr class="notion-simple-table-row notion-simple-table-header-row notion-block-3764a189eee580b3a24cffb1e6ccdaf7"><td class=""><p>输入类型</p></td><td class=""><p>支持方式</p></td><td class=""><p>说明</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580ca91a2c2dd686e5b8d"><td class=""><p>文本</p></td><td class=""><p><code class="notion-inline-code">text</code></p></td><td class=""><p>普通文本指令或问题</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58011afd2f5e159ff6b0f"><td class=""><p>图片 URL</p></td><td class=""><p><code class="notion-inline-code">image_url</code></p></td><td class=""><p>通过公网可访问的图片链接传入图片</p></td></tr></tbody></table>

#### 图片内容结构

当使用图片 URL 输入时，`messages[].content` 应使用数组结构，每个内容块代表一种输入内容。

```json
{
  "role": "user",
  "content": [
    {
      "type": "text",
      "text": "Describe the content of this image."
    },
    {
      "type": "image_url",
      "image_url": {
        "url": "https://example.com/image.jpg"
      }
    }
  ]
}
```

* * *

### 调用示例

#### 1\. 基础 Chat Completion 请求

用于生成普通的聊天补全响应。

```bash
curl https://apihub.agnes-ai.com/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agnes-2.0-flash",
    "messages": [
      {
        "role": "system",
        "content": "You are a helpful AI assistant."
      },
      {
        "role": "user",
        "content": "Explain how autonomous agents use tools to complete tasks."
      }
    ],
    "temperature": 0.7,
    "max_tokens": 1024
  }'
```

* * *

#### 2\. 流式输出请求

用于启用流式输出。

```bash
curl https://apihub.agnes-ai.com/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agnes-2.0-flash",
    "messages": [
      {
        "role": "user",
        "content": "Write a short product introduction for an AI assistant app."
      }
    ],
    "stream": true
  }'
```

* * *

#### 3\. 工具调用请求

用于需要外部工具调用的智能体工作流。

```bash
curl https://apihub.agnes-ai.com/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agnes-2.0-flash",
    "messages": [
      {
        "role": "user",
        "content": "What is the weather like in Singapore today?"
      }
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "Get the current weather for a location",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {
                "type": "string",
                "description": "The city and country"
              }
            },
            "required": ["location"]
          }
        }
      }
    ]
  }'
```

* * *

#### 4\. 图片 URL 输入请求

用于通过图片链接传入图片，并让模型理解或分析图片内容。

```bash
curl https://apihub.agnes-ai.com/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agnes-2.0-flash",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "Describe the content of this image."
          },
          {
            "type": "image_url",
            "image_url": {
              "url": "https://example.com/image.jpg"
            }
          }
        ]
      }
    ]
  }'
```

* * *

### 响应格式

```json
{
  "id": "chatcmpl_xxx",
  "object": "chat.completion",
  "created": 1774432125,
  "model": "agnes-2.0-flash",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Autonomous agents use tools by understanding the user's goal, breaking it into steps, selecting the right tools, executing actions, and using the results to complete the task."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 35,
    "completion_tokens": 58,
    "total_tokens": 93
  }
}
```

* * *

### 响应字段说明

<table class="notion-simple-table notion-block-3764a189eee5800b9d11c6667db939d8"><tbody><tr class="notion-simple-table-row notion-simple-table-header-row notion-block-3764a189eee580b8995cdc692e302195"><td class=""><p>字段</p></td><td class=""><p>类型</p></td><td class=""><p>说明</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580a282e2e3e1a74e0b53"><td class=""><p><code class="notion-inline-code">id</code></p></td><td class=""><p>string</p></td><td class=""><p>本次补全请求的唯一 ID</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580338f7ad44e3b9ea9c1"><td class=""><p><code class="notion-inline-code">object</code></p></td><td class=""><p>string</p></td><td class=""><p>对象类型，通常为&nbsp;<code class="notion-inline-code">chat.completion</code></p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580e3870dcebcda2e0d2b"><td class=""><p><code class="notion-inline-code">created</code></p></td><td class=""><p>integer</p></td><td class=""><p>请求时间戳</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580878dabf4ea9c17fcf1"><td class=""><p><code class="notion-inline-code">model</code></p></td><td class=""><p>string</p></td><td class=""><p>本次请求使用的模型</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5805ebc8bed2265f28e85"><td class=""><p><code class="notion-inline-code">choices</code></p></td><td class=""><p>array</p></td><td class=""><p>生成的响应结果列表</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5804b8089e81c93879e0f"><td class=""><p><code class="notion-inline-code">choices[].index</code></p></td><td class=""><p>integer</p></td><td class=""><p>响应结果的索引</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58042a45cf2b5dfab8a78"><td class=""><p><code class="notion-inline-code">choices[].message</code></p></td><td class=""><p>object</p></td><td class=""><p>Assistant 消息对象</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58096bcb7c23e430a3e35"><td class=""><p><code class="notion-inline-code">choices[].message.role</code></p></td><td class=""><p>string</p></td><td class=""><p>消息发送者角色</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5804d80f8f8abb5fadeb6"><td class=""><p><code class="notion-inline-code">choices[].message.content</code></p></td><td class=""><p>string</p></td><td class=""><p>模型生成的响应内容</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee58007a831f59fc7906075"><td class=""><p><code class="notion-inline-code">choices[].finish_reason</code></p></td><td class=""><p>string</p></td><td class=""><p>生成停止原因</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5808a875dd95898172172"><td class=""><p><code class="notion-inline-code">usage</code></p></td><td class=""><p>object</p></td><td class=""><p>Token 使用信息</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5805bb291f0de80db132a"><td class=""><p><code class="notion-inline-code">usage.prompt_tokens</code></p></td><td class=""><p>integer</p></td><td class=""><p>输入 token 数量</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5805ab354f61712e2df8e"><td class=""><p><code class="notion-inline-code">usage.completion_tokens</code></p></td><td class=""><p>integer</p></td><td class=""><p>输出 token 数量</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee5805a811de001fcac0197"><td class=""><p><code class="notion-inline-code">usage.total_tokens</code></p></td><td class=""><p>integer</p></td><td class=""><p>使用的 token 总数</p></td></tr></tbody></table>

* * *

### 为编码任务启用 Thinking

对于代码编写、调试、推理和 Agent 工作流，建议开启 Thinking 模式，以提升代码质量、任务拆解能力和问题解决效果。

#### OpenAI 兼容请求

使用 OpenAI 兼容 API 格式时，在请求体中添加 `chat_template_kwargs.enable_thinking`：

```json
{
  "model": "agnes-2.0-flash",
  "messages": [
    {
      "role": "user",
      "content": "Help me write a Python script to process a CSV file."
    }
  ],
  "chat_template_kwargs": {
    "enable_thinking": true
  }
}
```

#### Anthropic 兼容请求

使用 Anthropic 兼容 API 格式时，在请求体中添加 `thinking` 字段：

```json
{
  "model": "agnes-2.0-flash",
  "messages": [
    {
      "role": "user",
      "content": "Help me refactor this TypeScript function and explain the changes."
    }
  ],
  "thinking": {
    "type": "enabled",
    "budget_tokens": 2048
  }
}
```

`budget_tokens` 用于控制最大 Thinking token 预算。对于常见编码任务，建议从 `2048` 开始设置。对于更复杂的调试、重构或多步骤 Agent 任务，可以根据需要适当提高该值。

* * *

### 功能与兼容性

Agnes-2.0-Flash 支持以下能力：

+   Chat Completion

+   多轮对话

+   System Prompt

+   图片 URL 输入

+   图片理解

+   流式输出

+   工具调用

+   智能体工作流

+   编程任务

+   推理任务

+   JSON 风格输出

+   兼容 OpenAI Chat Completions API 的请求结构

* * *

### 最佳实践

#### Prompt 编写建议

为了获得更好的结果，建议提供清晰的指令、上下文和期望的输出格式。

#### 示例：产品文案生成

```text
You are a product marketing expert. Write a concise App Store description for an AI assistant app. The tone should be clear, professional, and user-friendly.
```

#### 示例：编程任务

对于编程任务，建议提供编程语言、框架、错误信息和期望行为。

```text
Help me debug this React component. The issue is that the button state does not update after clicking. Explain the cause and provide the corrected code.
```

#### 示例：智能体工作流

对于智能体工作流，建议清晰描述目标、可用工具和任务约束。

```text
You are an autonomous research agent. Search for relevant information, summarize the key findings, and return the result in a structured format with source links.
```

#### 示例：图片理解任务

对于图片理解任务，建议明确说明希望模型关注的内容，例如整体描述、文字提取、界面分析、物体识别或结构化输出。

```text
Analyze this screenshot. Identify the main UI elements, explain the possible issue, and provide suggestions to improve the user experience.
```

* * *

### 推荐 Prompt 结构

建议使用以下结构组织 Prompt：

```text
[Role] + [Task] + [Context] + [Requirements] + [Output Format]
```

#### 示例

```text
You are a senior product manager. Analyze this feature idea for an AI assistant app. Consider user value, implementation complexity, risks, and return the result in a structured table.
```

#### 图片理解 Prompt 示例

```text
You are an image analysis assistant. Analyze the provided image URL, summarize the key information, identify potential issues, and return the result in a structured table.
```

* * *

### 图片 URL 使用建议

+   图片 URL 必须可公网访问。

+   如果图片 URL 需要登录、鉴权或存在防盗链，模型可能无法读取。

+   建议使用标准图片格式，例如 JPG、JPEG、PNG 或 WebP。

+   对于截图、报错图、产品界面图，建议在文本中补充你希望模型重点关注的问题。

+   图片 URL 输入可以与工具调用、流式输出和 Agent 工作流结合使用。

* * *

### 模型限制 （RPM ≤ 20）

<table class="notion-simple-table notion-block-3764a189eee580e8be4df997fadcdb5b"><tbody><tr class="notion-simple-table-row notion-simple-table-header-row notion-block-3764a189eee580cf9ba5db9e053a588c"><td class=""><p>项目</p></td><td class=""><p>数值</p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580fa9fa4f66b4ba9e33b"><td class=""><p>Context</p></td><td class=""><p><code class="notion-inline-code">1 M（如果超过256K报错就是未灰度到，写代码请求时请作Strong的兜底设计）</code></p></td></tr><tr class="notion-simple-table-row notion-block-3764a189eee580f985bbff06e51dd8bd"><td class=""><p>Max Output</p></td><td class=""><p><code class="notion-inline-code">65.5K</code></p></td></tr></tbody></table>

### 说明

+   使用 `agnes-2.0-flash` 作为模型名称。

+   基础 Chat Completion 请求必须包含 `model` 和 `messages`。

+   `messages[].content` 可使用纯文本字符串，也可使用包含文本和图片 URL 的内容数组。

+   如需输入图片，请使用 `image_url` 并提供公网可访问的图片 URL。

+   如需启用流式响应，请将 `stream` 设置为 `true`。

+   对于工具调用工作流，请提供 `tools`，并可按需提供 `tool_choice`。

+   `temperature` 用于控制随机性。较低值更适合确定性任务，较高值更适合创意生成。

+   Agnes-2.0-Flash 适合需要快速响应、强任务完成能力、图片理解能力和可靠智能体表现的生产级应用。