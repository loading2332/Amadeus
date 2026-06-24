# Lifecycle seam、Gate/Tap 与重试隔离

用户已经能沿 `PassiveRuntime.run_turn()` 复述 `BeforeTurnContext → PromptRenderContext → AfterTurnContext` 的创建位置、下一消费者和持久化边界，并能区分 Gate 的有序可修改语义与 Tap 的返回值忽略、异常隔离语义。用户还理解 prompt retry 的单位是重新构建整个 Prompt，因此每次 attempt 必须创建新的 `RuntimeContext`，不能复用已被 handler 修改的对象；后续可以进入 plugin registry / loader / config，而无需重新教授 lifecycle 挂载点。
