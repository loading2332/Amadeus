# Learning Record 0006: Retrieval ranking and async tool boundary

用户已经能够说明被动检索结果最终进入带系统标记的 context frame，而不是稳定 system prompt；也能区分主动 answer 路径中的 event hypothesis、general hypothesis 与 raw query fallback。

用户已经掌握 RRF 的核心：融合的是 dense / lexical 两路名次，而不是直接混合两种原始相似度。Amadeus 保留 `vector_score`、`lexical_score`、`lanes` 和 `rrf_score`，用于解释检索结果、生成 trace 和支持未来策略；当前 `render_context_block()` 仍按 memory kind 与字符预算决定注入，不会根据这些 signals 自动降权。

用户还主动审计了 Akashic 的事件循环边界，确认 Akashic 工具链原生 async，QQ channel 的 `run_coroutine_threadsafe` 属于跨线程/跨 loop 桥接，不存在 same-loop `.result()` 死锁。Lesson 17 中修复的是 Amadeus 修改前的同步 `ToolExecutor` / `RecallMemoryTool` 组合：当前已改为 `await ToolExecutor.execute_async()` 和 async `RecallMemoryTool.execute()`，从而对齐 Akashic 的异步工具边界。

用户知道 `QueryRewriter`、`SufficiencyChecker`、`HyDEEnhancer` 当前只有 Akashic 源码与独立测试，没有接入生产检索主链，因此 Amadeus 不把它们伪装成对齐能力。

这份理解允许 Lesson 18 提高难度：不再重复讲单个 memory tool，而是进行 passive injection、recall、search、fetch、evidence/source_ref 和 retrieval quality 的联合验收。
