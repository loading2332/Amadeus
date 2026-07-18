# 工具过程与最终回答流式协议方案研究

> 2026-07-18 最终产品决策：本文研究的“过程文本/最终回答边界”不是产品所需约束，因此方案 A-E 均不作为当前实现。普通文本按到达顺序直接追加；工具调用使用独立卡片，完成或失败后立即折叠；后续文本继续追加。不存在 `answer_started`、撤回或步骤结束后二次分类。详见 `official-sdk-agent-streaming-patterns.md` 的最终决策补充。

## 1. 研究问题

本研究回答以下尚未决策的问题：

1. 当模型可能先调用一个或多个工具、最后才给出正式回答时，如何把“正在处理 / 工具调用”与“最终回答”可靠地区分？
2. React 如何在过程进行时展开显示，正式回答开始时自动收起，同时在刷新和 SSE 重连后恢复一致状态？
3. Amadeus 当前实现与 Akashic 的真实实现分别解决了什么、没有解决什么？
4. 在正确性、首 token 延迟、模型调用成本、跨供应商兼容性和实现复杂度之间有哪些可选方案？

本轮只做只读研究和方案比较，不修改 Akashic，不实现新协议，也不提前修改已批准设计。

## 2. 必要前置知识：四层问题不能混为一谈

### 2.1 模型流

模型供应商发出的原始 chunk 可能包含：

- 面向用户的正文片段；
- 工具调用 ID、名称和分片参数；
- 供应商私有 reasoning/thinking 字段；
- usage、finish reason 等控制数据。

在一个仍允许工具调用的请求里，正文片段先出现不等于“模型已经决定不调用工具”。后续 chunk 仍可能出现工具调用。因此，系统只有在以下任一条件成立时才能确定正式回答边界：

- 整个请求已经结束，并确认没有工具调用；
- 供应商协议提前给出具有可靠语义的输出项类型；
- runtime 使用显式控制协议，让“工具决策”和“最终回答生成”属于不同请求或不同阶段。

这是本问题的第一性原理约束。SSE、React 或动画无法补回模型层尚未提供的信息。

### 2.2 Runtime 语义事件

Runtime 必须把供应商 chunk 转换成产品可理解的事件，例如：

- 工具活动开始、完成、失败；
- 正式回答开始；
- 正文累计快照；
- turn 终态。

这里决定“某段内容是什么”，不负责浏览器动画。

### 2.3 SSE 传输

SSE 只解决服务器向浏览器单向推送。Amadeus 还使用 PostgreSQL 单调序号和累计快照解决断线恢复。SSE 本身不知道什么是工具过程，也不知道何时应该收起 UI。

### 2.4 React 展示状态

展开、自动收起、用户手动重新展开属于前端展示状态。前端应消费明确的后端事实，不能根据“暂时没有新工具事件”或“好像出现正文了”猜测 runtime 已进入最终回答阶段。

## 3. Amadeus 当前真实行为

### 3.1 已具备的能力

- `amadeus/provider.py` 可以累计流式正文和工具调用分片，最后仍返回完整 `LLMResponse`。
- `amadeus/runtime/streaming.py::TurnStreamSink` 目前提供正文、工具活动、取消检查和 finalization 边界。
- `amadeus/runtime/reasoner.py` 在工具执行前后发布 `started/completed/failed`。
- worker 将累计正文和工具活动写入 PostgreSQL；SSE 按单调 `seq` 恢复。
- 工具参数、工具结果、隐藏提示词和原始推理不进入 Web 事件。

### 3.2 当前最重要的语义限制

`Reasoner._chat_with_stream()` 在传入工具 schema 时先把正文 delta 放入内存缓冲区：

```text
模型流 -> buffered[]
请求结束 -> 检查 response.tool_calls
  有工具调用：丢弃本轮缓冲正文，不发布为正式回答
  无工具调用：再把 buffered[] 发布给 TurnStreamSink
```

该实现保证工具决策轮的中间正文不会污染最终回答，但意味着：

- 只要该请求带工具 schema，即使它最终没有调用工具，也必须等整个模型请求结束后才开始向 Web 发布正文；
- 浏览器收到的是快速回放的 delta，而不是真正的首 token 实时流；
- 无工具 schema 的普通请求仍可直接逐 delta 发布；
- 当前 `tool_activity` 没有稳定 `activity_id/call_id`，连续调用同名工具时，前端不能可靠配对开始与结束事件；
- 当前没有独立的 `answer_started` 产品事件。

## 4. Akashic 真实设计

### 4.1 Provider：正文、thinking 与工具调用在同一流中解析

证据路径：

- `../akashic-agent/agent/provider.py::chat()`
- `../akashic-agent/agent/provider.py::_chat_streaming()`
- `../akashic-agent/tests/test_more_support_modules.py`

Akashic 的回调 payload 使用：

```python
{"content_delta": "..."}
{"thinking_delta": "..."}
```

provider 同时累计正文、thinking 和工具调用分片，最后返回完整 `LLMResponse`。它维护 `tool_call_seen`：尚未看到工具调用时会立即发布正文/thinking；看到工具调用后停止继续发布。

优点：

- 低延迟；
- provider 仍返回完整结果；
- content 与 thinking 类型明确。

边界：

- 如果供应商先发送正文、后发送工具调用，先前正文已经交给 channel，无法撤回产品语义；
- `tool_call_seen` 只能阻止“看到工具调用之后”的内容，不能证明之前的内容是最终回答；
- thinking 被作为可展示数据传播，这不符合 Amadeus 当前“不公开 chain-of-thought”的安全边界。

### 4.2 Runtime：用内部事件总线连接 reasoner 与 channel

证据路径：

- `../akashic-agent/agent/looping/core.py::_build_stream_event_sink()`
- `../akashic-agent/bus/events_lifecycle.py`
- `../akashic-agent/agent/core/passive_turn.py`

主要事件包括：

- `TurnStarted`
- `StreamDeltaReady(content_delta, thinking_delta)`
- `ToolCallStarted(iteration, call_id, tool_name, arguments)`
- `ToolCallCompleted(iteration, call_id, tool_name, ..., status, result_preview)`
- 最终的 `OutboundMessage` / `TurnCommitted`

值得迁移的设计：

- 工具活动有稳定 `call_id`，相同工具的多次调用仍能一一配对；
- 有 `iteration`，可以按模型步骤组织工具过程；
- channel 只订阅事件，不进入 reasoner 内部；
- 最终出站消息仍是权威答案，而不是把临时缓冲直接当最终结果。

不能直接迁移的部分：

- 生命周期事件包含原始 arguments、final_arguments 和 result_preview；Amadeus Web 产品边界不能直接暴露这些字段；
- `session_key` 和 channel/chat_id 是 Akashic 的通道身份模型，不等同于 Amadeus 的 owner/session/turn UUID；
- stream buffer 和工具行主要保存在 channel 进程内存中，不支持像 Amadeus 一样从 PostgreSQL 断线恢复；
- 没有显式 `answer_started` 事件。

### 4.3 Telegram：临时过程消息与最终消息替换，而不是 React 式折叠

证据路径：

- `../akashic-agent/infra/channels/telegram_channel.py`
- `../akashic-agent/tests/test_channel_clients.py`

Telegram channel 在内存中维护：

- `_thinking_buffers`
- `_tool_lines`
- `_reply_buffers`
- 以 `call_id` 对应的工具状态行

流式阶段会把“思考过程、工具调用、临时回复”合并成一条可编辑 live message。最终 `OutboundMessage` 到达后：

1. 取消尚未结束的 live edit task；
2. 删除 live preview；
3. 可选地另发 thinking block；
4. 另发工具快照；
5. 发送或 finalize 最终回答。

这和用户想要的体验在意图上相似：过程先展示，最终回答到达后过程退出主视觉。但 Telegram 没有网页折叠容器，因此实现方式是“删除临时消息 + 另发快照”，不是原地自动收起。

### 4.4 QQBot：平台原生 replace + terminal

`../akashic-agent/infra/channels/qqbot_channel.py` 只消费 `content_delta`，用平台 `input_mode=replace` 更新累计内容，并用 `input_state=10` 表示终止。它不显示 thinking 和工具事件。

这证明 Akashic 已经按 channel 能力采用不同策略；不存在一个所有通道共享的 UI 行为。但 QQBot 的平台 terminal 仍然只是传输终止，不等于“正式回答开始”。

## 5. 可选方案

### 方案 A：用第一个 `content_snapshot` 隐式触发自动收起

流程：

```text
tool_activity* -> first content_snapshot -> React 自动收起过程区
```

优点：

- 不新增事件类型；
- React 实现最少；
- 与 Amadeus 当前缓冲策略基本兼容。

缺点：

- 把“正文已出现”和“runtime 已进入最终回答阶段”混为一谈；
- 异常前保留的部分正文、未来允许的阶段性说明或供应商草稿都可能误触发；
- 重连后需要从事件历史推断是否已经自动收起；
- 协议语义脆弱，后续修改 provider 策略可能静默破坏 UI。

结论：不推荐作为长期协议，只适合一次性原型。

### 方案 B：保持单请求缓冲，新增显式 `answer_started`

流程：

```text
带工具 schema 的模型请求
  -> 内存缓冲正文
  -> 请求结束且确认 tool_calls 为空
  -> 持久化 answer_started
  -> 回放正文 delta / 快照
```

优点：

- 最终回答边界正确、可持久化、可重连；
- React 不需要猜测；
- 不增加模型调用次数；
- 与当前 Amadeus 架构改动最小。

缺点：

- 工具可用请求必须等完整响应结束，首 token 延迟等于完整生成耗时；
- 用户看到过程区长时间停留，然后最终回答快速出现，名义上有 delta，体验上不是真正流式；
- 大回答需要先完整缓存在 worker 内存。

适用：优先保证正确性、成本和 MVP 交付，接受工具可用场景暂时不具备真实首 token 流。

### 方案 C：单请求乐观展示，发现工具调用后撤回

流程：

```text
正文 delta -> 立即展示为候选回答
后续发现 tool_calls -> 清空/标记该候选回答为过程草稿
最后再展示正式回答
```

优点：

- 单请求、低首 token 延迟；
- 最接近 Akashic provider 当前的即时转发方式。

缺点：

- 用户可能看到随后消失的文字；
- 屏幕阅读器、复制、审计、截图和重连回放都会观察到不稳定事实；
- 必须新增 `segment_retracted` 或草稿状态，数据库和 React 都更复杂；
- 中间正文可能包含本不应展示的工具决策文字；
- 不符合 Amadeus “持久事件代表可恢复事实”的方向。

结论：不推荐用于正式单用户客户端。

### 方案 D：显式“工具阶段 -> 最终回答阶段”两阶段生成

核心思想：最终回答由一个明确禁止工具调用的模型请求生成。runtime 在该请求产生第一个可展示正文 delta 时，先持久化 `answer_started`，再发布正文；之后正文可以真正逐 token 发布。这样不会在模型尚未产出任何正文时提前收起过程区。

一种稳定控制协议：

```text
工具阶段：tools = 业务工具 + finish 控制工具
  模型继续调用业务工具
  或调用 finish 表示工具阶段结束

回答阶段：tools = []
  模型基于用户问题、工具结果和过程上下文生成最终回答
  first content delta -> 持久化 answer_started
  content delta -> 直接流向 PostgreSQL/SSE
```

优点：

- 正式回答边界明确；
- 最终回答是真正首 token 流式；
- 不需要展示后撤回；
- React、重连和审计语义稳定；
- 可以保持供应商无关，只依赖普通工具调用能力。

缺点：

- 至少增加一次最终模型调用；
- 无工具简单问题如果也走该协议，会增加延迟和费用；
- 必须设计 finish 控制工具、最大迭代、空结果和模型拒绝 finish 的兜底；
- 工具阶段已经生成的自然语言不能直接作为最终答案，需要丢弃或仅作为内部上下文；
- 需要验证多供应商在 `tool_choice`、空 content 和控制工具上的兼容性。

适用：产品目标明确要求“工具过程可见 + 正式回答开始即自动收起 + 最终回答真实流式”。

### 方案 E：能力协商的混合策略

根据 provider 能力选择路径：

- 能提前给出可靠输出项类型的 provider：收到正式 message item 后直接 `answer_started` 并流式正文；
- 只有通用 Chat Completions chunk 的 provider：回退到方案 B；
- 对高价值工具任务或用户配置：选择方案 D。

优点：

- 对能力强的供应商取得更低延迟；
- 保留跨供应商回退；
- 可以逐步演进。

缺点：

- provider capability matrix、测试矩阵和行为差异明显增加；
- 同一产品在不同模型下体验可能不同；
- 如果能力判断错误，会重新引入草稿泄漏。

适用：未来多供应商成熟阶段，不适合作为第一个稳定协议。

## 6. 方案比较

| 方案 | 边界正确 | 工具场景真实首 token | 额外模型调用 | 可持久化重连 | 跨供应商 | 复杂度 |
|---|---:|---:|---:|---:|---:|---:|
| A 首正文隐式推断 | 较弱 | 否 | 0 | 可推断但脆弱 | 高 | 低 |
| B 缓冲 + `answer_started` | 强 | 否 | 0 | 强 | 高 | 低到中 |
| C 乐观展示后撤回 | 弱 | 是 | 0 | 复杂 | 高 | 高 |
| D 两阶段生成 | 强 | 是 | +1 最终调用 | 强 | 中到高 | 高 |
| E 能力协商混合 | 取决于适配器 | 部分 | 0 或 +1 | 强 | 最高但差异大 | 最高 |

## 7. 与生成策略无关、建议稳定下来的产品协议

无论选择 B、D 还是未来 E，Web 产品协议都可以保持一致：

```text
turn_status(processing)
activity_started(activity_id, kind=tool, label, iteration)
activity_completed(activity_id, status)
answer_started(answer_id)
content_snapshot(content, version)
turn_status(finalizing)
turn_terminal(done|failed|cancelled)
```

### 7.1 `activity_id`

- 采用 runtime 生成的稳定不透明 ID，或经过安全处理的 provider call ID；
- 开始/完成/失败事件使用同一 ID；
- Web payload 不包含 arguments、result、hidden prompt 或原始 reasoning；
- `iteration` 可选，用于把同一模型步骤中的多个工具分组。

这是从 Akashic `call_id + iteration` 值得迁移的部分。

### 7.2 `answer_started`

- 必须是持久化事件，并分配 turn 内单调 `seq`；
- 由 runtime 在“正式回答边界已经确定”后发布；
- React 收到后只自动收起一次；
- 刷新或重连时，历史中存在该事件就默认把过程区设为已完成/收起；
- `turn_terminal(done)` 可作为漏事件防御，但不替代 `answer_started`。

### 7.3 “正在思考”的安全含义

UI 中的“正在思考”应是根据 turn 正在处理、但当前没有活跃工具而渲染的通用状态，不是模型 chain-of-thought。不得新增 thinking delta 的 Web 事件。

### 7.4 React 展示状态

建议区分服务端事实和本地偏好：

- 服务端事实：有哪些 activity、是否已经 `answer_started`、turn 是否终态；
- 本地 UI：过程区当前是否被用户手动展开、是否已经执行过自动收起动画。

收到 `answer_started` 时自动收起一次；如果用户随后手动展开，后续 `content_snapshot` 和 `done` 不得再次强制收起。

失败/取消建议：

- 在 `answer_started` 前失败或取消：过程区保持可见，显示安全失败/取消状态，不伪造最终回答；
- 在 `answer_started` 后失败或取消：保留部分回答并标为不完整，过程区默认保持已收起但允许展开查看已完成工具。

### 7.5 深模块与 seam 放置复核

`codebase-design` 的删除测试可以验证 seam 应放在哪里：如果删掉 `TurnStreamSink`/未来的语义进度 interface，provider chunk 分类、工具调用配对、取消检查、PostgreSQL 序号和 SSE 事件规则会重新散落到 Reasoner、worker、Web 与 React。因此这个 module 正在提供真实 depth，而不是透传。

建议保持以下知识局部化：

- provider adapter：只负责把供应商 chunk 还原成完整响应和内部增量，不让 React 了解供应商字段；
- runtime 进度 module：决定 activity 与正式回答的产品语义；
- PostgreSQL adapter：隐藏累计快照、单调 seq、事务和重连事实；
- SSE adapter：只编码已经确定的 typed event；
- React：只理解 `activity_*`、`answer_started`、`content_snapshot` 和终态。

方案 B、D、E 应当是 runtime 进度 module 背后的可替换 implementation，而不是三套 Web interface。这样先用 B、以后换 D 时，SSE 与 React 不需要重写，获得 leverage 和 locality。

接口形状上有两种可行形式：

1. 延续当前语义方法：`publish_content`、`publish_activity`、`begin_answer`；调用简单，但每增加一种事件都要扩展 interface。
2. 使用封闭 typed union：`publish(TurnProgressEvent)`；入口更小，但必须禁止调用方构造任意 JSON，并让合法事件仍由 runtime 的明确操作产生。

当前事件种类有限，研究不要求立即把现有 sink 重构成 union。无论采用哪一种，都不应把 provider 原始 chunk、数据库 cursor 或 React 折叠布尔值放进该 interface。

## 8. 建议的决策路径

### 如果优先完成 React MVP

选择方案 B，同时把协议设计成未来可无缝切换 D：

- 先加入稳定 `activity_id` 和持久化 `answer_started`；
- 接受工具可用场景暂时在模型完整返回后快速回放正文；
- 不把这种行为宣传为工具场景的真实首 token 流。

### 如果第一版就要求接近 ChatGPT 的真实体验

选择方案 D：

- 显式工具阶段；
- `finish` 控制动作；
- 持久化 `answer_started`；
- 最终 `tools=[]` 请求真正逐 token 输出。

需要先原型验证模型调用成本、简单问题延迟、finish 遵循率和多供应商兼容性，再进入正式实现。

### 不建议

- 不建议用第一个正文快照作为长期折叠协议；
- 不建议迁移 Akashic 的 thinking 展示；
- 不建议把原始工具参数和结果放入 Web SSE；
- 不建议用乐观正文撤回来换取表面首 token 延迟。

## 9. 当前研究结论

1. Akashic 提供了有价值的 runtime/channel 解耦、`call_id`、`iteration` 和最终权威消息思路，但没有可直接复制的 React 自动折叠协议。
2. Akashic 的 Telegram 行为是删除临时过程消息、另发工具/思考快照、再发最终回答；它是产品意图参考，不是实现模板。
3. Amadeus 的 PostgreSQL 事件日志比 Akashic 的 channel 内存缓冲更适合 Web 刷新与断线恢复，应继续作为事实源。
4. `answer_started` 和稳定 `activity_id` 是值得独立于生成策略固定下来的深模块接口。
5. 真正需要用户抉择的是生成策略：
   - 方案 B：无额外模型调用、正确但工具场景不是真正首 token 流；
   - 方案 D：额外模型调用与更高复杂度，换取明确边界和真实最终回答流。
6. 在未完成该抉择前，不应实现 React 自动收起，也不应声称第四点已经完成。

## 10. 证据索引

### Amadeus

- `amadeus/provider.py`
- `amadeus/runtime/reasoner.py::_chat_with_stream()`
- `amadeus/runtime/streaming.py::TurnStreamSink`
- `amadeus/worker/turn_worker.py::PersistedTurnStream`
- `amadeus/turns/postgres.py`
- `amadeus/web/sse.py`
- `tests/app/test_provider.py`
- `tests/runtime/test_reasoner_tool_loop.py`
- `tests/integration/test_web_stream_cross_process.py`

### Akashic（只读）

- `../akashic-agent/agent/provider.py::_chat_streaming()`
- `../akashic-agent/agent/looping/core.py::_build_stream_event_sink()`
- `../akashic-agent/agent/core/passive_turn.py::Reasoner.run()`
- `../akashic-agent/bus/events_lifecycle.py`
- `../akashic-agent/infra/channels/telegram_channel.py`
- `../akashic-agent/infra/channels/qqbot_channel.py`
- `../akashic-agent/tests/test_more_support_modules.py`
- `../akashic-agent/tests/test_channel_clients.py`
