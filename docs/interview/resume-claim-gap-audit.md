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
| Akashic-inspired memory system with retrieval, source references, correction, and forgetting | `amadeus/memory/markdown.py`、`amadeus/memory/akashic.py`、`amadeus/memory/retriever.py`、`amadeus/tools/recall_memory.py`、`amadeus/tools/forget_memory.py`、`tests/memory/test_memory_retrieval_acceptance.py` | "我把长期记忆写入、SQLite 检索、source_ref/evidence 回源、更正、遗忘做成了统一闭环；写入、检索和 post-response worker 都通过公开 memory engine 收口。" |
| Akashic-aligned memory write quality | `amadeus/memory/post_response_worker.py`、`amadeus/memory/memorizer.py`、`tests/memory/test_memory_post_response_worker.py`、`tests/evaluation/cases/memory_quality_v1.yaml` | "写入链不是把 LLM 摘要直接落库，而是先形成 typed candidate，再做 source-backed validation、duplicate/conflict decision 和 replacement lifecycle；eval 能看到 candidate_decisions、active/superseded state 和 source_ref 回源。" |
| Retrieval ranking、time filters、typed memory lanes 已可验证 | `amadeus/memory/ranking.py`、`tests/memory/test_memory_ranking.py`、`tests/memory/test_session_memory_runtime.py` | "当前 retrieval 支持 semantic/lexical 双路、RRF 融合、reinforcement tie-break、时间窗口过滤，以及从 markdown pending 到 profile/preference/correction 的类型化摄入。" |
| Runtime/CLI 已公开 memory retrieval trace | `amadeus/runtime/before_turn.py`、`amadeus/runtime/passive.py`、`amadeus/app/cli.py`、`tests/memory/test_runtime_memory.py`、`tests/app/test_cli.py` | "memory recall 的 candidate_count、fallback、injected/omitted ids 不藏在 helper 里，而是能从 runtime result 和 CLI trace 直接展示。" |
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
| SQLite/sqlite-vec | 当前 embedding 是 JSON 存在 SQLite 里 | 要么迁移 sqlite-vec，要么把简历措辞改成 SQLite long-term memory store | "SQLite-backed long-term memory store。" |
| DashScope Embedding | 当前是 OpenAI-compatible embedding config | 增加 DashScope-compatible provider，或使用中性措辞 | "pluggable embedding provider。" |
| AnyActionGate / online / busy / cooldown | 还没有实现 | 增加 cooldown、busy guard、简单 quota/presence gate | 完成前只说 "cooldown and busy gating"。 |
| emotional_weight 和 time decay | 还没有实现 | 增加 scoring 字段，并用 eval 证明它影响排序 | 完成前删除该表述，或说成未来 scoring work。 |
| memory merge / retire lifecycle 扩展 | correction/forget/supersede/replacement 已完成；merge、retire scoring 还没有产品需求和验证 | 只有在真实场景需要时，再补 merge/retire 规则和 focused verification | "目前支持 source-backed correction、replacement 和 forgetting；merge/retire 是后续扩展。" |
| 产品化 Evaluation | memory recall 和 memory quality runner 已存在；更上层 proactive/tool-loop eval 还没覆盖 | 继续扩展 context isolation、tool loop、proactive send/skip cases | "memory 行为已有产品化 eval；Phase 3 后续扩展到 proactive/outbound。" |

## 最高优先级证据

1. Evaluation runner：已覆盖 memory recall/write quality/source_ref fetch；下一步扩到 context isolation、tool loop、proactive send/skip。
2. 真实 LLM passive smoke：能证明 session commit、memory maintenance 和 retrieval trace。
3. Telegram outbound adapter：支持 dry-run 和 real-send。
4. 最小 ProactiveLoop：基于本地 alert/content/context fixtures，完成 memory/context 注入、send/skip 决策和 eval cases。
5. Scheduler + OutboundPort 链路：为后续 proactive 和 Drift 提供稳定触发边界。

## 面试回答边界

- 如果被问 Akashic，要说它是参考设计，不是直接复制的 base class。
- 如果 ProactiveLoop 还没实现，就说当前正在对齐架构，passive/memory/plugin 层已经存在。
- 如果被问怎么证明行为正确，要指向 Evaluation cases 和 trace outputs，不要只说单元测试。
- 如果被问 Telegram/QQ，要说明 Telegram 是第一条生产 adapter，QQ 是有意延后的多 adapter 扩展。
- 如果被问 Phase 1 完成了什么：Reasoner 边界、Akashic-style 文件工具（read/write/edit/list_dir）、filesystem hook policy、tool loop guard、SQLite session trace、CLI trace 模式。301 个测试覆盖。
- 如果被问哪些是 Phase 2：完整记忆能力，包括 Markdown memory、long-term memory retrieval、embedding、source_ref/evidence 回源、recall/forget、replacement、reinforcement ranking、retrieval trace、context-frame injection，以及 focused Phase 2 pytest 证据。产品化 Evaluation runner 和 memory-quality 行为证明是 Phase 3。
