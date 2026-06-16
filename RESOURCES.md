# Amadeus / Akashic 学习资源

## Knowledge

- Local source: `../akashic-agent/agent/core/passive_turn.py`
  Passive Reasoner 主循环的核心实现。用于：理解 `Reasoner.run()`、多步 tool loop、阶段性总结和循环边界。
- Local source: `../akashic-agent/agent/core/types.py`
  Akashic 运行时结果类型与结构定义。用于：理解 `ReasonerResult`、元信息和调用链输出。
- Local source: `../akashic-agent/agent/tool_runtime.py`
  Tool message 回灌辅助函数。用于：理解 `assistant(tool_calls)` 和 `tool(result)` 的协议顺序。
- Local source: `../akashic-agent/agent/tool_hooks/types.py`
  Tool hook 请求/结果结构。用于：理解为什么 hook 不该和具体 tool 耦合。
- Local source: `../akashic-agent/agent/tool_hooks/executor.py`
  Tool hook 执行器。用于：理解 Akashic 的工具执行 trace、前后处理和拒绝路径。
- Local source: `amadeus/runtime.py`
  Amadeus 当前 passive runtime 与基础多步 tool loop。用于：对照 Akashic 当前已经复现到哪里。
- Local source: `amadeus/provider.py`
  Amadeus provider 的 `LLMToolCall` / `LLMResponse` 形状。用于：对照 provider 层已经完成的 Lesson 8。
- Local source: `amadeus/tool_runtime.py`
  Amadeus 当前 tool message 回灌工具。用于：对照 Lesson 9 的复现方式。
- Local source: `tests/test_runtime.py`
  当前 runtime 的行为测试。用于：确认多步 tool loop、iteration limit、tool_chain 持久化等已经到哪一步。

## Wisdom (Communities)

- 当前阶段先以本地源码、测试和对照实现为主
  用途：降低学习噪音，先把 Akashic 与 Amadeus 主链讲清。社区型资源等到后续需要扩展 transport、生态插件或对外发布时再补。

## Gaps

- 还没有一份稳定的 Akashic glossary / 调用链速查文档
- 还没有把 Lesson 10 之后的课程沉淀为正式 HTML 教学产物
- 还没有行为级 eval 资源索引页，后续要随着课程一起补齐
