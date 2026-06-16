# 当前 Amadeus passive loop 的代码边界已经讲顺

用户已经能够用自己的话准确说明当前 Amadeus passive loop 的核心代码边界：`provider` 负责单次请求/响应发送与解析，`tool_runtime` 负责把 tool 协议消息追加回 `messages`，而 `runtime` 负责把 assistant tool call 和 tool result 回灌进 `loop_messages` 并再次调用 `provider.chat()`，形成多轮 `LLM -> tool -> LLM` 循环。这说明后续课程可以从“loop 是否存在”前进到“tool message 持久化边界与 session history 边界”的精读与收口。
