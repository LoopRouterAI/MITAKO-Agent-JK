# MITAKO 虾淘 OpenUI 前端重构与流式组件规范

> **版本**: v3.1  
> **日期**: 2026-06-14  
> **状态**: 实施完成并实机测试通过  
> **文档定位**: 整体项目交付文档 docs
> **参考标准**: [Spec-Kit](https://github.com/github/spec-kit)

---

## 1. 重构背景与设计语言确定

原有的 Vanilla JS 以及旧版 UI 演示界面在整体的视觉高级感、用户交互顺畅性以及核心二次元“情绪价值”的传递上存在明显缺陷。尤其是传统的对话气泡流对于结构化组件（卡片）的流式支持极弱，导致大模型在输出卡片数据时常面临严重的白屏或等待延迟。

经与甲方多轮对齐，我们废弃了传统的 ChatUI，完全倒向并引入了 **OpenUI (https://github.com/thesysdev/openui)** 生成式 UI 架构，借助其底层包 `@openuidev/react-lang`，确立了全新的流式卡片底座。

### 1.1 品牌与 Logo 视觉定位

*   **视觉风格特征比例**:
    *   **50% 年轻潮玩**: 强调高冲击力的色彩碰撞与现代感。
    *   **20% 二次元**: 精致的看板娘“虾饺”Q版形象与专属二次元动漫表情包。
    *   **20% 社区运营**: 亲切的社群化交互和快捷订单引用卡片，避免严肃的冷板面孔。
    *   **10% AI 科技**: 配备极客范的大模型原始 API 调试日志面板，在研发与调试期为用户提供绝对透明的底层流数据监控。
*   **多巴胺年轻配色体系**:
    *   **主色 (MITAKO Lime)**: `#C8FF1A`（高明度荧光绿，展现潮玩冲击力）
    *   **品牌绿**: `#B7F500`
    *   **辅助蓝**: `#42C8FF`
    *   **辅助紫**: `#7B61FF`
    *   **警告橙**: `#FF8B38`
    *   **背景大面积白色**: `#FFFFFF`，通过平滑的多色径向渐变，打破纯白板的单调，创造高端呼吸感。
*   **Logo 与 Avatar 定位**:
    *   **Logo 风格**: 选用斜体黑体搭配荧光绿渐变作为品牌标识，右上角包覆警告橙底的“虾淘”二次元专属胶囊。
    *   **看板娘头像**: `xiaojiao_avatar.png` 作为虾饺首席客服的官方认证头像。

### 1.2 前端技术栈升级

*   **框架**: React 18 + Vite 5。
*   **流式 UI 架构**: 引入 thesysdev 团队的 **OpenUI 架构 (`@openuidev/react-lang`)**。该架构以“流式优先”为准则，在结构化流的解析渲染、手势滚动以及移动端竖屏触摸适配上，具备一流的性能表现。
*   **基础图标**: `lucide-react` 提供高精致度的几何线条感，配合同步加载的 FontAwesome 6.4.0 字体图标。

---

## 2. 架构优化与突破：单次 LLM 调用合并

### 2.1 痛点诊断

在旧版设计中，用户输入一句话，系统需要先后向大模型发起两次调用（先请求 `intent_classify` 判定意图，再请求 `generate_reply` 生成回复），这导致首字响应延迟翻倍，且 Prompt 费用开销高居不下。

### 2.2 解决方案：前缀 JSON 提取与流式分流状态机

通过将意图分析、情绪评级与正式回复合并入单次大模型（Agnes-2.0-Flash）调用中，我们在 System Prompt 里做了严格的规范：
*   **格式规约**: 要求模型在输出回复的首行，必须用 `<analysis>{JSON}</analysis>` 包裹结构化数据，随后再换行输出正式文本。
*   **后端截获状态机**: 在 `agent.py` 的 `call_llm` 中，加装了基于字符匹配的流式前缀解析器：
    ```python
    if not has_sent_analysis:
        if "<analysis>" in full_content or is_parsing_analysis:
            is_parsing_analysis = True
            analysis_buffer += content
            if "</analysis>" in analysis_buffer:
                parsed = json.loads(json_part)
                # 实时向前端推送意图和情绪事件，更新胶囊组件
                await event_queue.put({"type": "unified_analysis", ...})
                # 剔除前缀，只把之后的文字作为 text_chunk 吐字
                await event_queue.put({"type": "text_chunk", "content": rest_clean})
    ```
*   **前端打字机防剧透**: 这样，发往前端的正式打字机数据流中，完全过滤掉了 `<analysis>...</analysis>` 部分，用户完全感知不到底层的 JSON 数据，完美体验秒级打字机。

### 2.3 状态机时序节点轻量化

为避免在合并调用后，之前的 `intent_classify` 节点报错，我们将此节点彻底简化为**毫秒级本地规则库匹配**。
*   **初步判定**: 节点依靠简单的敏感词规则（如“出荷”判定为物流，“退钱”判定为退款）来快速建立一个初步意图。
*   **目的**: 为后续 `query_order`（查订单）、`query_logistics`（查物流）和 `search_sop`（检索RAG）提供必要的查询键（Query Key）。
*   **最终矫正**: 查到的所有业务事实数据被一并喂给 Unified LLM，由 Unified LLM 完成最终的精准意图分类和情绪判定，实现逻辑的完整自洽。

---

## 3. 基于 `@openuidev/react-lang` 的卡片库定义

为使系统自定义卡片完全符合 OpenUI 的 Generative UI 契约规范，我们引入 `defineComponent` 与 `createLibrary` 接口，在 [src/App.jsx](file:///f:/AIGC/Jack-Code/Codex-Project/客服系统研究/src/App.jsx) 中重构定义了以下组件：

### 3.1 补偿申请卡片 `CompensationCard`
*   **Zod Schema 定义**:
    ```javascript
    z.object({
      type: z.string(),
      amount: z.number().optional(),
      msg: z.string()
    })
    ```
*   **用途**: 用于渲染“500 平台积分”与“优先发货标记”等安抚性补偿申请状态，支持根据 type 决定是虚拟包还是特定免邮券。

### 3.2 订单物流进度卡片 `OrderProgressCard`
*   **Zod Schema 定义**:
    ```javascript
    z.object({
      order_id: z.string(),
      item_name: z.string(),
      total_amount: z.number(),
      progress_steps: z.array(z.object({
        label: z.string(),
        status: z.string(),
        date: z.string()
      })),
      delay_reason: z.string().optional()
    })
    ```
*   **用途**: 用于在气泡流中展现带色彩状态标记的二次元进度轴，包含“下单、出荷、清关、入库、派送”等流程。

### 3.3 核实进度卡片 `QueryStatusCard`
*   **Zod Schema 定义**:
    ```javascript
    z.object({
      step: z.string()
    })
    ```
*   **用途**: 在 Loading 期间向用户提供查港口、向库房提交补偿方案等状态步进展现，舒缓用户焦虑。

### 3.4 人工客服转接状态卡片 `TransferStatusCard`
*   **Zod Schema 定义**:
    ```javascript
    z.object({
      status: z.string() // calling / connected
    })
    ```
*   **用途**: 用于流式展示系统正向专员主管连线的状态与最终接入提醒，过渡极其温和。

以上 4 款卡片组件经由 `createLibrary` 注册为 `mitakoOpenUILibrary`，由前端流式渲染逻辑进行动态消费，确立了干净的生成式 UI 交互基座。

---

## 4. 核心踩坑与避坑指南

### 4.1 坑 1：现代浏览器对剪贴板 `navigator.clipboard` 的安全限制
*   **现象**: 在局域网 IP 调试时复制日志失效，抛出 `TypeError: Cannot read properties of undefined (reading 'writeText')`。
*   **原因**: 现代浏览器规定 `navigator.clipboard` 仅在安全上下文 (Secure Context，如 localhost 或 HTTPS) 中才会被注入。
*   **避坑方案 (双保险 Fallback)**:
    前端加装了基于临时创建 `textarea` 并执行 `document.execCommand('copy')` 的备用逻辑，确保在非安全域下的 100% 复制成功率。

### 4.2 坑 2：Vite 生产打包时 `lucide-react` 的 `Headset` 图标未导出问题
*   **现象**: 执行 `npm run build` 时报错崩溃，提示找不到 Headset 模块。
*   **原因**: lucide-react 不同版本中可能因为映射更改而将 `Headset` 更名。
*   **避坑方案**: 统一替换为标准且多版本通用的 `Headphones` 图标。

### 4.3 坑 3：大模型 Prompt 别名变量在 Python 三引号内外侧冲突
*   **现象**: 启动 `main.py` 时报 `SyntaxError: invalid character`。
*   **原因**: Python 三引号字符串中途被非预期的变量声明闭合，导致后面的中文 Prompt 泄露为非法代码。
*   **避坑方案**: 确保三引号仅在 Prompt 首尾闭合，辅助别名全部在其外侧声明。

### 4.4 坑 4：高速流中的 React 异步闭包导致状态延迟
*   **现象**: 流已经走完，日志面板依旧显示为“正在请求”。
*   **原因**: SSE 异步流闭包捕获了 `activeLogCardId` 初始状态的快照，读取始终为 null。
*   **避坑方案**: 引入 `useRef` (即 `activeLogCardIdRef`)，借助其值的同步更新特性完美击碎闭包延迟。

### 4.5 坑 5：OpenUI (thesysdev) 依赖在 React 18 环境下的 peer 依赖冲突
*   **现象**: 运行 `npm install` 安装 `@openuidev/react-lang` 报错，提示 React 19 的 peer 限制。
*   **原因**: thesysdev/openui 架构的底层包优先支持 React 19。
*   **避坑方案**: 通过强制开启 `npm i @openuidev/react-ui @openuidev/react-lang --legacy-peer-deps` 解析，同时测试验证其 ES Modules 模块均能顺畅兼容导入运行。

### 4.6 坑 6：OpenUI 强制校验 Zod 4 导致运行时白屏报错
*   **现象**: 在本地 Vite 打包成功后，在浏览器访问时出现全白屏，且在控制台抛出致命报错：`Error: [OpenUI] Component "CompensationCard" was defined with a Zod 3 schema. OpenUI requires Zod 4 schemas.`
*   **原因**: thesysdev/openui 架构的组件在挂载时会校验 Props 是否为 Zod 4 规范。如果使用常规的 `import { z } from "zod";`，会因为 Zod 3 与 Zod 4 的结构差异而被拦截并直接报错挂起，造成 React 挂载白屏。
*   **避坑方案**: Zod 3.25+ 的新版本已支持向前预览 Zod 4。我们在 `src/App.jsx` 中，将 Zod 的引入方式修正为 `import { z } from "zod/v4";`。该操作彻底消除了 Zod 4 模式的限制，完美恢复了运行时加载和卡片渲染！

---

## 5. 新一轮体验迭代与功能规范沉淀（2026-06-14）

### 5.1 顶栏回归测试控制台折叠优化
原顶栏横向堆叠的测试场景按钮被整合进入带化学烧瓶 🧪 图标的 `一键测试控制台 ⚙️` 下拉菜单中。默认隐藏，点击时通过定位浮层展开，避免臃肿，提升整体工业设计的高级整洁度。

### 5.2 追踪器面板底部圆角遮挡与样式溢出修正
由于右栏追踪器使用了 `rounded-2xl overflow-hidden`，最后一项日志常被遮住。我们通过在时序容器及 API 日志容器增加 `pb-8` 内边距留出安全带，并将 Request/Response 文本展示区扩展为 `whitespace-pre-wrap break-all console-scroll rounded-xl max-h-48 overflow-y-auto`，既能自动换行又能平滑滚动，消除了展示不全的问题。

### 5.3 客服话术全面升级为温和真诚的“申请制”
废除了以往冰冷的“系统已自动赠送平台积分”描述。大模型回复话术与 Mock 数据均重塑为有商有量的“申请制”真人态度（如：*“虾饺这就在后台为您申请 500 平台积分安抚，并同步帮您向库房申请挂载优先发货标记”*），极大提升了二次元萌系客服的温度。
