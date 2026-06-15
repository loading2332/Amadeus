# Lesson 9.5：Passive Reasoner Loop 前的 Akashic 对齐审计

## 目标

这份审计用于把前面已经完成的 Amadeus tool-loop 代码重新放回 Akashic 的真实设计坐标系里。

目标不是推翻前面的代码，而是给每一块代码贴上清晰标签：

1. 哪些已经贴近 Akashic 的真实设计。
2. 哪些结构方向兼容，但还不完整。
3. 哪些只是过渡位置，后续应该被 Akashic 对齐实现吸收。
4. Lesson 10 前必须先理解 Akashic 的哪些关键设计。

## 已精读的 Akashic 源码

本次对照阅读了这些 Akashic 文件：

- `../akashic-agent/agent/provider.py`
- `../akashic-agent/agent/core/types.py`
- `../akashic-agent/agent/tool_runtime.py`
- `../akashic-agent/agent/core/passive_turn.py`
- `../akashic-agent/agent/tool_hooks/types.py`
- `../akashic-agent/agent/tool_hooks/executor.py`
- `../akashic-agent/agent/tools/base.py`
- `../akashic-agent/agent/tools/registry.py`

Akashic 的核心流程可以概括为：

```text
Reasoner.run(initial_messages)
-> provider.chat(messages, tools=schemas, tool_choice="auto")
-> 如果 response.tool_calls 存在：
   -> append_assistant_tool_calls(messages, response.tool_calls)
   -> tool_call_batch_snapshot(response.tool_calls)
   -> 逐个执行 tool_call：
      -> ToolExecutor.execute(ToolExecutionRequest(...), ToolRegistry.execute)
      -> append_tool_result(messages, exec_result.output)
      -> 把调用事实记录进 tool_chain
   -> AfterStep hooks
   -> continue，进入下一轮 LLM
-> 如果没有 tool_calls：
   -> 追加最终 assistant content
   -> build ReasonerResult(reply, invocations, metadata.tool_chain, react_stats)
-> 如果达到 max_iterations：
   -> 生成 incomplete progress summary
```

## Amadeus 当前实现对照

### Provider 返回结构

Amadeus 文件：

- `amadeus/provider.py`

Akashic 对应：

- `agent/provider.py`
- `agent/core/types.py`

状态：可以保留，后续扩展。

Amadeus 当前的 `LLMToolCall` / `LLMResponse.tool_calls` 与 Akashic 的 `ToolCall` / `LLMResponse.tool_calls` 思路一致。这一层不是偏离点。

缺口：

- Akashic 还携带 `thinking`、`provider_fields`、cache token 字段。
- Amadeus 当前有 `raw`、`model`、`response_id`、`usage`，但还没有保存 provider-specific fields。
- `provider_fields` 在 Akashic 中会影响 `append_assistant_tool_calls()`，尤其是某些 provider 的 reasoning/thinking 字段兼容。

Lesson 10 含义：

- 不需要重写 provider。
- 只在 passive reasoner loop 真正需要时补齐缺失字段。

### Tool 消息运行时

Amadeus 文件：

- `amadeus/tool_runtime.py`

Akashic 对应：

- `agent/tool_runtime.py`

状态：方向基本对齐，但不完整。

Amadeus 已经复现了 Akashic 的关键想法：

- 追加带 `tool_calls` 的 assistant 消息。
- 追加带 `tool_call_id` 的 tool 消息。
- 在下一轮 LLM 前把 tool result 回灌进消息列表。

缺口：

- 没有 `tool_call_batch_snapshot()`。
- 没有独立的 `format_tool_calls()` helper。
- `append_assistant_tool_calls()` 不支持 `provider_fields`。
- 没有 Akashic 风格的 `ToolResult(text, content_blocks)` 标准化结果。
- 还没有处理文件内容、多模态 content block 这类 tool result。

Lesson 10 含义：

- 保留 `amadeus/tool_runtime.py`。
- 后续按 Akashic 的 helper 集合扩展，不要继续把消息格式化逻辑散落进 runtime。

### Passive Runtime / Reasoner 边界

Amadeus 文件：

- `amadeus/runtime.py`

Akashic 对应：

- `agent/core/passive_turn.py`，尤其是 `Reasoner.run()`

状态：当前是过渡位置。

Amadeus 现在把单步 tool loop 放在 `PassiveRuntime._run_single_tool_step()` 中。

这对学习和验证有价值，但它不是 Akashic 的最终边界。Akashic 中，多步循环属于 reasoner-like component，返回 `ReasonerResult`；外层 passive pipeline 负责 turn 生命周期、持久化、出站消息和 after-turn 行为。

Lesson 10 含义：

- `_run_single_tool_step()` 不能继续无限扩张。
- Lesson 10 应该引入或准备一个 reasoner-shaped boundary，再实现多步 loop。
- session 仍然只持久化 user message 和最终 assistant reply；tool 中间消息仍属于 runtime-loop state，除非后续 Lesson 专门处理 trace 持久化。

### Tool Executor 和 Hook 结构

Amadeus 文件：

- `amadeus/tools/base.py`
- `amadeus/tools/executor.py`

Akashic 对应：

- `agent/tool_hooks/types.py`
- `agent/tool_hooks/executor.py`

状态：结构方向兼容，但还没有对齐。

Amadeus 当前有：

- `ToolExecutionRequest(tool_name, arguments)`
- `ToolResult(tool_name, output, is_error, metadata)`
- `ToolTrace(tool_name, arguments, status)`
- 同步的 `ToolExecutor.execute(tool_name, arguments)`

Akashic 的执行契约更完整：

- `ToolExecutionRequest(call_id, tool_name, arguments, source, session_key, channel, chat_id, tool_batch, tool_batch_index)`
- `ToolExecutionResult(status, output, final_arguments, extra_messages, pre_hook_trace, post_hook_trace)`
- 异步 `ToolExecutor.execute(request, invoker)`
- 独立 `preflight()` 路径

Lesson 10 含义：

- Amadeus 当前 executor 可以作为起点保留。
- 进入多步 loop 复现时，必须向 Akashic 的 request/result shape 靠拢。
- `call_id`、`source`、`tool_batch`、`tool_batch_index`、`final_arguments`、hook traces 不是可有可无的细节，它们是 Akashic 让工具执行可观察、可拦截、可复盘的关键。

### Tool Registry

Amadeus 文件：

- `amadeus/tools/registry.py`

Akashic 对应：

- `agent/tools/registry.py`
- `agent/tool_runtime.py`

状态：基础 schema registry 可用，但缺 metadata 层。

Amadeus 已经有注册、查找、工具名列表和 OpenAI schema export。

缺口：

- 没有 `ToolMeta`。
- 没有 `always_on`。
- 没有 deferred tool discovery。
- 没有 progress description 注入。
- 没有 `get_schemas(names=...)`。
- 没有 registry-level `execute()` invoker。

Lesson 10 含义：

- 不需要因为 deferred discovery 没完成就阻塞多步 loop。
- 但 loop 调用工具时，要走一个以后能承接 `get_schemas(names=...)`、deferred tools、registry execution 的边界，避免后续重写 loop。

### Tests / Eval

当前 Amadeus 测试已经覆盖：

- provider 可以解析 tool calls。
- runtime 能执行一次 tool call，并发起第二次 provider 请求。
- tool 中间消息不会持久化进 session。
- bootstrap 能把 registry/executor 接进 runtime。

状态：保留，并升级为早期 eval seeds。

距离完整 Akashic 对齐还缺：

- 多步 tool loop。
- max iteration summary。
- tool error 作为 tool result 回灌。
- 一个 LLM response 中的 batch tool calls。
- hook-denied tool call。
- repeated tool-call guard。
- 最终 `ReasonerResult` metadata 和 `tool_chain`。

## 保留 / 修改 / 后续重做清单

可以保留：

- `LLMToolCall`
- `LLMResponse.tool_calls`
- `amadeus/tool_runtime.py` 作为 tool message formatting 的归属位置
- `ToolRegistry` 作为工具目录概念
- 单步 tool-loop 测试作为 regression/eval seed

需要修改：

- 增加 reasoner-shaped boundary，不要继续把所有 loop 行为塞进 `PassiveRuntime`。
- tool execution request/result shape 要向 Akashic 靠拢。
- loop result 路径要加入 `tool_chain` / invocation metadata。
- 补 tool batch snapshot 行为。

后续可能重做：

- `PassiveRuntime._run_single_tool_step()` 应该变成新 reasoner 下的临时 helper，或者被正式 loop 实现替换。
- `ToolResult(tool_name, output, is_error)` 可能需要拆成 Akashic 风格的 tool output normalization 和 execution result metadata。

不能作为最终设计继续扩张：

- 只知道一次 follow-up tool call 的 loop。
- 不能表达 `call_id`、final arguments、hook traces、batch position 的 executor。
- 只检查 SDK payload 形状、不验证行为级 loop 结果的测试。

## Lesson 10 进入门槛

进入 Lesson 10 实现前，用户需要能说明：

1. 为什么 Akashic 把重复 tool loop 放在 `Reasoner.run()`，而不是 provider。
2. 为什么必须先 `append_assistant_tool_calls()`，再追加 tool results。
3. `tool_chain` 记录了哪些 LLM message list 本身不够表达的信息。
4. 为什么 `ToolExecutionRequest` 需要 `call_id`、`source`、`tool_batch`、`tool_batch_index`。
5. 达到 `max_iterations` 后 Akashic 怎么收尾。

能讲清这些以后，再进入 Amadeus 的多步 passive reasoner 复现。
