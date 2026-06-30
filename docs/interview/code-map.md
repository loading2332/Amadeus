# Amadeus 代码地图

这份地图用于把当前目录结构和面试讲解路径对齐。当前代码只使用能力分包后的新路径，不保留旧顶层模块 shim。

## 被动运行时

- 代码：`amadeus/runtime/`
- 简历 claim：Passive runtime 能准备上下文、执行 LLM turn、运行 tool loop、提交 session trace。
- 公共行为：`PassiveRuntime.run_turn()` 形成 `context -> Reasoner.reason() -> tool loop -> commit`。
- 验证：`uv run pytest tests/runtime`
- Akashic 参考：`../akashic-agent/agent/core`、`../akashic-agent/agent/turns`、`../akashic-agent/agent/lifecycle`

## 记忆系统

- 代码：`amadeus/memory/`、`amadeus/tools/recall_memory.py`、`amadeus/tools/forget_memory.py`
- 简历 claim：Akashic-inspired memory 支持检索、source references、forget/supersede 和 context 注入。
- 公共行为：`MemoryEngine.query()` 返回 records + trace，`render_context_block()` 生成可注入上下文。
- 验证：`uv run pytest tests/memory`
- Akashic 参考：`../akashic-agent/core/memory`、`../akashic-agent/agent/retrieval`、`../akashic-agent/agent/tools/recall_memory.py`

## 应用装配

- 代码：`amadeus/app/`
- 简历 claim：runtime 不是测试拼装，而是可通过 CLI 启动的真实应用边界。
- 公共行为：`build_passive_app()` 连接 provider、session、memory、tools、plugins；`amadeus chat --trace` 输出可解释 trace。
- 验证：`uv run pytest tests/app`
- Akashic 参考：`../akashic-agent/bootstrap`

## 扩展和工具边界

- 代码：`amadeus/plugin/`、`amadeus/tools/`
- 简历 claim：插件和工具通过受管理 seam 接入 runtime，不直接 patch 主循环。
- 公共行为：插件贡献 phase modules；工具通过 registry/executor/hooks 运行。
- 验证：`uv run pytest tests/plugins tests/tools`
- Akashic 参考：`../akashic-agent/agent/plugins`、`../akashic-agent/agent/tools`、`../akashic-agent/agent/tool_hooks`

## 后续交付槽位

- Evaluation：新增时放在 `amadeus/evaluation/` 和 `tests/evaluation/`。
- Outbound/Telegram：先定义 `amadeus/outbound/`，Telegram adapter 放在 infra 层，不让 proactive 直接依赖。
- Scheduler：放在 `amadeus/scheduler/`，只触发 runtime 或 outbound boundary。
- ProactiveLoop：放在 `amadeus/proactive/`，只能通过 MemoryEngine/context/outbound seam 工作。
- DriftRunner：放在 `amadeus/drift/`，必须有 runnable task 和验证 trace。
