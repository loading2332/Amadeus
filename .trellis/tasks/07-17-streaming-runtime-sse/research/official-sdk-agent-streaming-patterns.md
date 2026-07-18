# 官方 AI SDK 的工具调用与流式展示模式研究

> 最终产品决策（2026-07-18）：后续讨论确认产品不需要区分“过程文本”和“最终回答文本”。所有普通文本按到达顺序直接追加；工具调用作为另一种 part 插入，完成或失败后立即折叠；之后的文本继续追加。本文第 9 节早期提出的 provisional/process/final 重分类方案已被该更简单的交错 parts 模型取代。

## 1. 研究范围与结论先行

本研究补充比较以下官方实现：

- OpenAI Responses API / OpenAI Agents SDK；
- Anthropic Messages API / Tool Runner；
- Google Gemini Interactions API / Generate Content；
- Vercel AI SDK Core / AI SDK UI。

研究时间：2026-07-18。只采用官方文档和官方 SDK 文档作为实现事实来源。

结论是：主流方案普遍不把一次 Agent 运行建模为“一个不断增长、必要时删除的字符串”，而是建模为**多步骤、类型化、可关联的事件或消息部件**。工具调用、工具结果、文本和错误都保留自己的类型与 ID；工具执行后，SDK 通常把结果交回模型并开启下一次生成，直到某一步只产生最终文本、不再产生工具调用。

因此，用户接受工具过程和工具前文本无需撤回后，Amadeus 没有必要坚持此前方案 B 的整轮正文缓冲，也没有必要直接采用方案 D 中人为新增 `finish` 控制工具。最终讨论进一步确认，不需要在步骤结束后把文本重分类为 process/final；更贴近实际需求的方案是：

1. runtime 持久化追加式、类型化的 part 事件；
2. 普通文本 delta 到达即追加到当前 text part；
3. 工具开始时插入 tool part，完成或失败时更新并折叠该 tool part；
4. 工具后的普通文本创建新的 text part并继续流式追加；
5. turn 终态只结束流，不承担文本分类。

这里没有文本撤回或事后重分类，只有事件到达时即可确定的 `text` 与 `tool` 两种渲染方式。

## 2. 第一性原理：为什么工具调用天然是多步骤生成

模型本身不能执行本地函数。一次完整工具任务至少包含：

```text
用户问题
-> 模型生成 tool call
-> 应用校验并执行工具
-> 应用把 tool result 交回模型
-> 模型结合结果生成回答，或继续调用工具
```

所以“工具后再次调用模型”通常是标准循环的一部分，不应笼统计为额外的最终回答调用。真正额外的是：在模型本来已经给出无工具最终文本后，再强制增加一次仅用于改写或确认的模型请求。

另一个不可消除的约束是：在同一个模型步骤尚未结束时，先到达的文本并不能证明后面一定不会出现工具调用。Anthropic 的官方流式工具示例就先产生一段文本，再产生 `tool_use` block。这意味着通用实现只能三选一：

- 缓冲到步骤结束，牺牲首字延迟；
- 立即展示为临时候选，步骤结束后按结果重分类；
- 使用供应商或模型特有的严格阶段协议。

当产品接受第二种体验时，追加式 typed parts 是成本和体验最平衡的方案。

## 3. OpenAI：原始 token 事件与 Agent 语义事件并存

### 3.1 数据模型

OpenAI Agents SDK 暴露两层流：

- `RawResponsesStreamEvent`：直接转发 Responses API 的细粒度事件，例如 `response.output_text.delta`；
- `RunItemStreamEvent`：完成后的语义事件，例如 `message_output_created`、`tool_called`、`tool_output`、`reasoning_item_created`。

这是一种典型的双层接口：底层满足低延迟，上层满足稳定产品语义。应用不需要把 provider 原始 JSON 直接泄漏给 UI。

### 3.2 最终回答如何判定

Agents SDK 的运行循环规则非常明确：

```text
模型输出包含 tool calls
-> 执行工具
-> 追加结果
-> 再运行模型

模型输出产生目标类型文本，且没有 tool calls
-> final_output
-> 结束 run
```

`final_output` 在流结束前保持为空；但应用仍可通过 raw response events 实时显示 token，通过 run item events显示工具进度。官方文档也明确把“展示每一个新 item”还是“只展示 final output”留给应用选择。

### 3.3 对 Amadeus 的启发

- 内部保留 provider delta 层，Web 只消费 runtime 语义层；
- `tool_called`、`tool_output` 和最终 message 是不同 item，不需要撤回；
- turn 是一个逻辑用户轮次，内部可以包含多次 LLM 调用；
- 最终性来自“当前生成没有工具调用”，不是来自第一个 text delta。

官方资料：

- [OpenAI Agents SDK：Streaming](https://openai.github.io/openai-agents-python/streaming/)
- [OpenAI Agents SDK：Running agents](https://openai.github.io/openai-agents-python/running_agents/)
- [OpenAI Responses API：Streaming events](https://platform.openai.com/docs/api-reference/responses-streaming)

## 4. Anthropic：有序 content blocks，允许文本先于工具调用

### 4.1 数据模型

Anthropic Messages 流由以下事件组成：

```text
message_start
content_block_start(index, type)
content_block_delta(index, typed delta)*
content_block_stop(index)
message_delta(stop_reason)
message_stop
```

文本 block 使用 `text_delta`；工具 block 使用 `input_json_delta`；两者都通过 `index` 对应最终 Message 的 `content` 数组。SDK 可以在消费 SSE 的同时累积出完整 Message。

### 4.2 重要证据：过程文本不一定是最终回答

Anthropic 官方“streaming request with tool use”示例的顺序是：

```text
text: "Okay, let's check the weather for San Francisco, CA:"
tool_use: get_weather(...)
stop_reason: tool_use
```

这直接证明：只看到 text block 不能判定整条 message 已经是最终回答。最自然的 UI 是保留顺序和类型，把这段文本视为工具步骤的一部分，而不是删除它。

### 4.3 Tool Runner 如何结束循环

Anthropic Tool Runner 会自动执行工具、追加 tool results、继续请求 Claude；直到 Claude 返回不含 tool use 的 message，或达到 `max_iterations`。工具抛错时，runner 把错误包装成 `is_error: true` 的 tool result 交回 Claude；不会把完整堆栈作为模型可见结果。

这再次说明最终回答是最后一个“无工具 message”，不是人为插入一个 finish 工具才得到的。

官方资料：

- [Anthropic：Streaming Messages](https://platform.claude.com/docs/en/build-with-claude/streaming)
- [Anthropic：Tool Runner](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner)

## 5. Google Gemini：typed steps / Parts 与 requires_action

### 5.1 Interactions API

Gemini Interactions 的流式工具调用使用 typed steps：

- `step.start` 给出 function 名称；
- `step.delta` 流式给出 `arguments_delta`；
- 客户端工具调用结束后，interaction 进入 `requires_action`；
- 应用执行函数并提交 `function_result`；
- 后续 interaction 生成最终回答或继续调用工具。

服务端工具也以 `google_search_call`、`google_search_result` 等步骤出现在流中。这里同样没有“先把一切拼成字符串，再猜字符串含义”的做法。

### 5.2 Generate Content API

Generate Content 使用有类型的 `Part`：`text`、`functionCall`、`functionResponse` 等。官方提醒不能假设 function call 永远是 parts 数组最后一项，解析器应遍历所有 parts。这进一步支持按 part ID/类型建模，而不是依赖到达位置做最终性判断。

### 5.3 异常与高风险操作

Gemini 官方建议检查 `finishReason`、校验工具参数，并对下单等高后果调用请求用户确认。也就是说：显示工具活动不等于自动授权工具副作用；执行权限仍应由 runtime/approval 边界控制。

官方资料：

- [Gemini：Streaming interactions](https://ai.google.dev/gemini-api/docs/streaming)
- [Gemini：Function calling](https://ai.google.dev/gemini-api/docs/function-calling)

## 6. Vercel AI SDK：最接近 React 产品层的 typed parts

### 6.1 UIMessage 是 UI 事实模型

Vercel AI SDK 区分：

- `ModelMessage`：发给模型的上下文；
- `UIMessage`：前端渲染所需的完整应用状态。

`UIMessage.parts` 中可以同时存在 text、tool、reasoning、source、data 等部件。tool part 具有显式生命周期：

```text
input-streaming
-> input-available
-> output-available | output-error
```

多步骤调用还会产生 `step-start` part，前端可以按步骤渲染边界。它没有要求工具完成后撤销相应 part；相反，工具调用和结果是消息历史的一部分。

### 6.2 Agent loop

`streamText` 配置 `stopWhen` 后，如果模型生成工具调用，AI SDK 会执行工具、传入结果并触发下一次 generation，直到不再有工具调用或满足停止条件。每一次 generation 是一个 step；`onStepFinish` 可获得该 step 的 text、tool calls、tool results、finish reason 和 usage。

工具失败会成为 `tool-error` content part，用于后续自动模型轮次，而不是静默丢失。

### 6.3 对 Amadeus 的启发与边界

Vercel AI SDK 的 UI 数据模型很适合作为参考，但 Amadeus 不应直接采用其传输协议或把 React 状态当后端领域模型：

- Amadeus 已有 PostgreSQL 单调 `seq`、累计快照和 SSE 重连语义；
- 应迁移的是 typed parts、稳定 ID、step boundary 和 tool state；
- 不必为此引入 Vercel AI SDK，它更适合 Node/Next.js 全栈，而 Amadeus 的 runtime 是 Python/FastAPI；
- React Query/axios 仍负责 HTTP 数据访问，typed stream reducer 负责把 SSE 事件投影成 UIMessage 类似的视图，两者职责不同。

官方资料：

- [Vercel AI SDK：Tool Calling](https://ai-sdk.dev/docs/ai-sdk-core/tools-and-tool-calling)
- [Vercel AI SDK：Chatbot Tool Usage](https://ai-sdk.dev/docs/ai-sdk-ui/chatbot-tool-usage)
- [Vercel AI SDK：UIMessage](https://ai-sdk.dev/docs/reference/ai-sdk-core/ui-message)
- [Vercel AI SDK：Stream Protocols](https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol)

## 7. 横向比较

| 方案 | 基本单位 | 工具循环终止 | 工具过程是否保留 | 前端展示抽象 |
|---|---|---|---|---|
| OpenAI Agents SDK | raw event + run item | 文本符合输出类型且无 tool call | 是，`new_items`/stream events | SDK 不规定，应用选择全部 item 或 final |
| Anthropic | message + ordered content blocks | message 无 tool use | 是，text/tool_use/tool_result 都进历史 | 按 content block/type 展示 |
| Gemini | interaction step / content Part | interaction 完成且无需 action | 是，function call/result 为 typed step/Part | 按 step/Part 展示 |
| Vercel AI SDK | step + UIMessagePart | 无 tool call 或满足 `stopWhen` | 是，tool part 状态持续演进 | `message.parts.map(...)` |

共同点：

1. append-only 的事实流比可撤销字符串更自然；
2. 每个工具调用有稳定 call ID；
3. 工具参数是分片 JSON，需要累积、校验后才能执行；
4. 一次用户 turn 可包含多个模型 generation；
5. 最终答案由最后的无工具步骤确定；
6. UI 自动收起属于产品策略，不属于供应商协议；
7. 工具结果、错误和推理内容需要分别做脱敏策略，不能因“过程可见”就全部公开。

## 8. 对“无法撤回没关系”的精确定义

可以接受的是：

- 已发生的安全工具活动永久留在事件历史；
- 工具前的用户可见安全文本留在过程区；
- 工具失败留下一条安全失败状态；
- 最终回答开始后过程区自动收起，但仍可重新展开。

仍然不能接受的是：

- 把原始 chain-of-thought 当“正在思考”展示；
- 把密钥、完整工具参数、原始工具结果、堆栈或隐藏提示词推给浏览器；
- 把“已显示工具调用”误解为工具副作用可以不做授权、幂等与超时控制；
- 在重试时无条件重复执行有副作用工具。

所以“无需撤回”解决的是 UI 一致性取舍，不会降低执行安全要求。

## 9. 最终采用的 Amadeus 推荐方案

### 9.1 推荐：按时间交错的 typed parts 事件流

不再采用此前 C2 的结束后重分类，直接按事件类型追加：

```text
turn_started
text_started(part_id)
text_snapshot(part_id, content, version)
tool_started(activity_id, name)
tool_completed(activity_id, status)
text_started(next_part_id)
text_snapshot(next_part_id, content, version)
turn_completed
```

投影规则：

- `text_snapshot` 到达即更新对应 text part；
- `tool_started` 插入工具卡片并结束当前 text part；
- `tool_completed/failed` 更新同一 `activity_id` 并立即折叠卡片；
- 工具后的新文本使用新 `part_id`，继续显示在卡片之后；
- 所有事件保持追加式，不发 `retract`，刷新与重连可以确定性重建；
- 不需要 `step_completed(outcome=...)` 或 final text 判定。

### 9.2 为什么不再首选人为 `finish` 工具

官方 Agent loops 已经具有可靠的自然终止条件：最后一步没有工具调用。人为 `finish` 工具会增加模型契约、跨供应商测试和拒绝 finish 的兜底，却没有解决官方 typed step 模型已经解决的问题。

只有未来验证某个 provider 无法可靠结束工具循环，或必须在模型生成前明确切换 `tools=[]`，才考虑把 finish 作为 provider strategy，而不是 Web 协议的一部分。

### 9.3 不需要 `answer_started`

工具卡片是否折叠只由自身的 `completed/failed` 状态决定，与后续文本是否属于最终回答无关。turn 终态只负责停止 streaming、标记完整或不完整，并提供最终聚合文本。

## 10. 需要原型验证的三个问题

1. Amadeus 当前 provider 在同一步内是否可能稳定产出“text 后 tool call”；需要为 OpenAI-compatible、Gemini、Anthropic adapter 分别建立 fixture。
2. `text -> tool -> text` 历史重放是否与直播 reducer 产生完全相同的 parts 顺序和折叠状态。
3. PostgreSQL 是否持久化每个 delta，还是继续使用节流后的累计 snapshot；建议保留累计 snapshot，但 step/part 生命周期事件必须独立持久化。

完成这些原型前，不应直接实现最终 UI 动画；但协议方向已经可以从“整轮字符串”收敛到“追加式 typed parts”。
