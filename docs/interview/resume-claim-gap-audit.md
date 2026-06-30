# 简历亮点缺口审计

这份审计把当前简历描述拆成三件事：当前代码证据、还缺什么、面试时应该怎么说。原则是：简历上能强讲的内容，仓库里必须有代码和验证证据支撑。

## 目前可以安全讲的亮点

| 简历亮点 | 当前证据 | 面试口径 |
| --- | --- | --- |
| AgentCore 被动链路能准备上下文、渲染 prompt、执行推理并提交状态 | `amadeus/runtime/passive.py`、`amadeus/runtime/before_turn.py`、`amadeus/prompt_render.py`、`amadeus/runtime/after_reasoning.py` | "我把被动 runtime 做成了分阶段 pipeline，围绕 context 准备、prompt 渲染、provider/tool 执行和 commit 收口。" |
| Reasoner 独立推理边界 | `amadeus/runtime/reasoner.py`、`tests/runtime/test_reasoner.py`、`tests/runtime/test_reasoner_tool_loop.py` | "把 provider 调用和 tool loop 提取到独立 Reasoner 边界。PassiveRuntime 只负责 turn-level lifecycle，Reasoner 负责 provider + step-level lifecycle。" |
| Akashic-style 文件工具集 | `amadeus/tools/defaults.py`（ReadFileTool/WriteFileTool/EditFileTool/ListDirTool）、`tests/tools/test_file_tools.py` | "文件工具支持 allowed_dir 路径安全、offset/limit 分页读取、exact-match 编辑返回 diff、mutation lock 防并发覆盖。" |
| Runtime filesystem hook policy | `amadeus/tools/hooks.py` | "双层防御：工具自身 allowed_dir 做局部兜底，hook 做全局 runtime policy。默认策略：读/list 可访问 workspace 内路径，写/edit 仅限 runtime-artifacts/。" |
| prompt 和动态上下文分离 | `amadeus/context.py`、`amadeus/prompting/assembler.py`、context-frame tests | "动态记忆和检索材料进入 context frame，不直接污染稳定 system prompt。" |
| Markdown + SQLite 的记忆基础已经存在 | `amadeus/memory/markdown.py`、`amadeus/memory/vector.py` | "可读长期记忆和机器检索记忆是分开的：Markdown 负责 profile/history，SQLite 存 retrieval items。" |
| retrieval 已有 vector、lexical、RRF、evidence、forget 支持 | `amadeus/memory/vector.py`、`amadeus/tools/recall_memory.py`、`amadeus/tools/forget_memory.py` | "当前 retrieval 层支持 dense/lexical 双路检索、RRF 融合和 source references；后续还要补更强的 scoring 和 eval 覆盖。" |
| tool loop 和 tool registry 已存在，tool loop guard 已实现 | `amadeus/runtime/reasoner.py`（_detect_repeated_signature）、`amadeus/tools/registry.py`、`tests/runtime/test_reasoner_tool_loop.py` | "Reasoner 实现了多步工具循环：检测重复 tool signature 自动停止、max iteration guard、保留已完成 tool_chain、记录 stop reason 到 trace。" |
| 多步工具循环的 session trace 持久化 | `tests/runtime/test_runtime.py` 中的 tool_chain tests、CLI `--trace` 模式 | "每个 turn 的 tool_chain 可以持久化到 SQLite session；CLI trace 模式显示 tool chain 步骤、provider model/usage、context retry 信息。" |
| plugin/phase 扩展机制已存在 | `amadeus/phase.py`、`amadeus/plugin/`、phase tests | "插件通过受管理的 phase module ownership 和 rollback 路径扩展 runtime，而不是直接 patch 主循环。" |

## 强表述前必须补齐的亮点

| 简历亮点 | 当前状态 | 必须补的工作 | 完成前更安全的说法 |
| --- | --- | --- | --- |
| ProactiveLoop 主动策略 pipeline | Amadeus 还没有实现 | 增加 gate、DataGateway、judge、resolve、outbound、ACK 或 dry-run trace，并补 proactive eval | "已对齐 Akashic 的设计，下一步实现主动策略 vertical slice。" |
| DriftRunner 自主探索 | Amadeus 还没有实现 | 增加最小 task runner，包含 scan、prepare、execute、finish 和一个真实维护任务 | "已规划 DriftRunner 边界，暂时不是已交付核心功能。" |
| Telegram/QQ Bot | 还没有实现 | 先接 Telegram outbound，QQ 延后 | "当前优先 Telegram-first outbound，QQ 是未来 adapter 工作。" |
| MCP 扩展 | 还不是产品路径 | 保持接口 MCP-ready，或后续补一个真实 MCP-backed fixture | "具备 MCP-ready 边界"，除非真的接入了 MCP。 |
| SQLite/sqlite-vec | 当前 embedding 是 JSON 存在 SQLite 里 | 要么迁移 sqlite-vec，要么把简历措辞改成 SQLite vector store | "SQLite-backed vector memory store。" |
| DashScope Embedding | 当前是 OpenAI-compatible embedding config | 增加 DashScope-compatible provider，或使用中性措辞 | "pluggable embedding provider。" |
| AnyActionGate / online / busy / cooldown | 还没有实现 | 增加 cooldown、busy guard、简单 quota/presence gate | 完成前只说 "cooldown and busy gating"。 |
| emotional_weight 和 time decay | 还没有实现 | 增加 scoring 字段，并用 eval 证明它影响排序 | 完成前删除该表述，或说成未来 scoring work。 |
| memory retire / merge lifecycle | superseded 已有，merge 和 lifecycle scoring 不完整 | 增加明确 memory lifecycle 操作和 trace | "forget/supersede with source_ref verification。" |
| 产品化 Evaluation | 还没有统一 runner | 增加 case schema、runner、report、确定性测试和真实 LLM smoke 路径 | 完成前只说 "已有 focused tests，正在建设 eval harness"。 |

## 最高优先级证据

1. Evaluation runner：能为 memory recall、source_ref fetch、context isolation、tool loop、proactive send/skip 产出报告。
2. 真实 LLM passive smoke：能证明 session commit 和 memory maintenance。
3. Telegram outbound adapter：支持 dry-run 和 real-send。
4. 最小 ProactiveLoop：基于本地 alert/content/context fixtures，完成 memory/context 注入、send/skip 决策和 eval cases。
5. 记忆 scoring 补强：reinforcement、time decay、retrieval trace、source-backed correction。

## 面试回答边界

- 如果被问 Akashic，要说它是参考设计，不是直接复制的 base class。
- 如果 ProactiveLoop 还没实现，就说当前正在对齐架构，passive/memory/plugin 层已经存在。
- 如果被问怎么证明行为正确，要指向 Evaluation cases 和 trace outputs，不要只说单元测试。
- 如果被问 Telegram/QQ，要说明 Telegram 是第一条生产 adapter，QQ 是有意延后的多 adapter 扩展。
- 如果被问 Phase 1 完成了什么：Reasoner 边界、Akashic-style 文件工具（read/write/edit/list_dir）、filesystem hook policy、tool loop guard、SQLite session trace、CLI trace 模式。301 个测试覆盖。
- 如果被问哪些是 Phase 2：Markdown memory + vector memory retrieval、embedding、recall/forget/correction、Evaluation harness。
