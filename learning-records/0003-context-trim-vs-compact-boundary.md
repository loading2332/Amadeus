# Context trim 和 compact 的边界已经分清

用户已经能够把 Lesson 12 的关键概念区分开：LLM 的 context window 是模型固定上限，每轮应用层会把 system prompt、context frame、history window、当前用户消息、tool schemas/tool results 拼成 payload；trim 裁剪的是本轮 payload 中的 prompt block 或 history window，是 `ContextLengthError` 后的 runtime fallback；compact/consolidation 是长期状态维护链，用来把旧 history 或动态大块压缩成更短的 memory/recent context，降低未来触发 trim 的概率。用户也已经指出长期 block fallback 需要 trace 次数并进入压缩/摘要治理，这意味着后续可以进入 Lesson 13 的 Passive Loop 回归、预算观测和 Akashic gap audit，而不用继续停留在 trim 与 compact 的概念辨析。
