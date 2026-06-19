# Learning Record 0007: Memory evidence 的运行时与 Prompt 边界

用户已经能够沿 consolidation → memory source_ref/evidence → fetch_messages → session store 复述记忆回源链，区分 memory ID、message ID 与 source_ref 的职责，并明确只有 memory ID 可以交给 forget_memory。用户也能区分确定性的运行时代码约束与可能被模型误判、上下文干扰或 jailbreak 绕过的 Prompt 工具顺序约束；同时理解 Lesson 18 的验收结论是“底层数据链已通，但 LLM 使用这些工具的语义合同还不完整”。这允许后续课程直接进入跨工具状态机与 citation runtime enforcement，而无需再重复单工具定义。

用户进一步从 Akashic 源码识别出 memory 工具描述并非硬编码在工具类中，而是由具体 memory engine 的 `tool_profile()` 提供 `MemoryToolSpec`，再在注册时注入工具实例并最终作为 function-calling schema 的 `tools` 参数传给 LLM。用户由此发现 Amadeus 当前只对齐了工具描述内容，尚未对齐 engine-owned tool profile 的插件扩展边界；behavior prompt 负责跨工具顺序，两者不能混为同一种注入。
