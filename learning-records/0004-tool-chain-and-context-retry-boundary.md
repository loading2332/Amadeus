# Tool chain 和 context retry 的职责边界已经分清

用户已经能够说明 `context_retry` 负责记录本轮 context fallback：有哪些 attempt、最后选中哪个 trim plan、裁掉了哪些 prompt block 或 history window。用户也已经理解 `tool_chain` 不是上下文 fallback 机制，而是工具执行事实的长期持久化形态：runtime 内部仍使用原始 `assistant(tool_calls)` 与 `tool(result)` 协议消息跑当前 API loop，但 session/history 长期保存时把工具调用、参数、结果、状态压进 assistant message 的 `tool_chain`，下轮再由 `session.get_history()` 还原成模型可消费的协议消息。这意味着后续可以进入 Lesson 14，把 retrieval 从“运行时预注入 context”推进到“模型可主动调用的 recall_memory tool”。
