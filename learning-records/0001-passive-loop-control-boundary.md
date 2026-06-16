# Passive loop 的主控边界已经建立

用户已经能够正确复述 Passive loop 的几个关键边界：provider 只负责单次请求/响应解析，loop 主控权在 reasoner/runtime；`assistant(tool_calls)` 先于 `tool(result)` 是协议约束；`tool_chain` 是执行记录而不是执行器；`max_iterations` 返回的是阶段性未完成但可继续、可复盘的结果。这意味着后续课程可以从“概念辨析”进入“代码精读与边界收口”，不用再回到最基础的 loop 归属问题。
