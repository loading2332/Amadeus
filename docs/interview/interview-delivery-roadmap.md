# 面试交付路线图

这份路线图的目标是：保留简历项目的交付速度，但不破坏架构顺序。不能在底层契约还没有验证之前，提前实现上层的简历亮点。

## 阶段 0：执行协议切换

- 把旧的教学型工作区提示词切换成面试交付模式。
- 保留 Akashic 作为只读参考实现。
- 把本路线图和 `resume-claim-gap-audit.md` 作为当前主动规划来源。

验收标准：

- 根目录提示词不再默认生成课程产物。
- 新任务都能映射到一条简历亮点和一条验证路径。

## 阶段 1：Akashic-style passive agent runtime ✅

Phase 1 实现了一个可面试展示的被动 agent runtime，包括：

| Issue | 交付物 | 验证 |
|-------|--------|------|
| 01 | Reasoner 独立边界：提取 provider/tool-loop 到 Reasoner，PassiveRuntime 保持 lifecycle orchestration | 300+ 测试，13 个 Reasoner 专用测试 |
| 02 | 文件工具集：read_file（offset/limit）、write_file、edit_file（exact-match+diff）、list_dir | 22 个文件工具测试 |
| 03 | Runtime filesystem hook policy：read/list 全 workspace、write/edit 仅 artifacts/ 子目录 | 双层防御验证 |
| 04 | 把多步 tool loop 完整移入 Reasoner，before_step/after_step 生命周期由 Reasoner 执行 | 多步工具链测试 |
| 05 | Tool loop guard：重复 tool signature 检测、max iteration guard、stop reason 记录 | 重复检测和上限测试 |
| 06 | CLI trace 模式：显示 session key、message IDs、tool chain、provider model/usage、sessions DB path | CLI trace formatting 测试 |
| 07 | 面试文档更新：resume-claim-gap-audit 和 roadmap 反映 Phase 1 完成状态 | 文档可读审查 |

验收标准：

- 能讲清楚 `输入 -> context -> Reasoner.reason() -> tool loop -> commit -> memory event`。
- 能展示文件工具 write -> read -> edit 的文件操作 trace。
- 有一条命令或测试证明端到端链路工作。
- 能解释 Reasoner 与 PassiveRuntime 的边界划分理由。

## 阶段 2：完整记忆能力 ✅

Phase 2 的目标不是只补几个 retrieval 细节，而是把 Amadeus 的具体记忆能力交付完整：长期记忆写入、检索、回源、更正、遗忘、排序、注入和可验证行为都必须形成闭环。完成后，简历可以安全描述为“Akashic-inspired memory system with retrieval, source references, correction, and forgetting”。

Phase 2 verification command：

```powershell
uv run pytest -q tests/memory tests/evaluation tests/db
```

当前验收状态（2026-07-11）：通过。上述 memory/evaluation/database suite 本次运行结果为 `145 passed`；仓库全量为 `550 passed`。

交付范围：

- Markdown memory：保留可读的 SELF/MEMORY/HISTORY/PENDING/RECENT_CONTEXT 文件语义，明确 profile、history、pending、correction 等条目的生命周期。
- Long-term memory store：PostgreSQL + pgvector store 支持 embedding 写入、source_ref 去重、kind 过滤、happened_at、status、reinforcement、HNSW vector search 与 pg_trgm GIN lexical acceleration。
- Retrieval：vector 与 raw-query lexical 独立查询完整 eligible corpus，再做 stable-id RRF。lexical 使用 Akashic ASCII/CJK term extraction 与参数化 OR-ILIKE；显式 answer/recall_memory 默认生成只进入 vector lane 的 event/general auxiliary queries，passive context 保持 raw-query path。
- Ranking：retrieval 使用 Akashic-style hotness fusion：通过语义阈值后的向量候选按 `0.8 * semantic + 0.2 * hotness` 排序，其中 hotness 由 reinforcement、updated_at time decay 和 emotional_weight 半衰期修正组成；trace 暴露 semantic、hotness、final score 和各组成信号。
- Source references：`recall_memory` 返回的候选记忆必须带 `source_ref`/evidence，并能通过 `fetch_messages` 回源到原始 session messages。
- Correction：用户纠正记忆时，必须先定位 memory id，再回源核对，最后 soft-delete 或写入更正记忆；不能把 message id 当作 memory id。
- Forgetting：`forget_memory`/mutation 必须把错误记忆标记为 superseded，查询和 context 注入默认不再使用，同时原始消息仍可回源。
- Context injection：被动 runtime 只能通过 `MemoryEngine` 或明确 context contract 注入 retrieved memory，且 retrieved memory 进入 context frame，不污染稳定 system prompt。
- Retrieval trace：统一记录 query plan、vector/lexical/union/final candidate counts、lane status、逐 lane rank/RRF contribution、score signals、dual-hypothesis queries/fallbacks/errors、injected/omitted ids、source_ref/evidence 状态。
- Verification：用 focused tests 和 memory-specific eval/smoke cases 覆盖公开行为；完整产品化 Evaluation runner 仍属于阶段 3。

验收标准：

- 能演示一条完整记忆链路：session 消息 -> Markdown consolidation -> long-term memory ingest -> recall -> fetch_messages 回源 -> forget -> 后续 query 不再使用旧记忆。
- memory-specific eval 或 smoke 覆盖 vector-window 外 lexical-only recall、source_ref fetch、correction、forgetting、dual-hypothesis fallback、context-frame fusion-order injection、reinforcement ranking与 retrieval provenance trace。
- 所有记忆相关能力都有代码证据和验证命令，面试时能指向公开工具、runtime 行为或 trace，而不只解释内部 helper。
- 简历措辞不能写尚未实现的 sqlite-vec；hotness ranking 可以描述为已迁移 Akashic 的 scoring 思路，但不能说完整迁移了 Akashic memory2。

## 阶段 3：产品化 Evaluation

Phase 3 已落地 memory recall 和 memory quality 两条最小垂直切片。memory quality 的重点不是“能不能召回”，而是“写入是否正确”：类型识别、短期状态拒写、当前信息覆盖历史、实体属性冲突、噪音中提取关键事实、procedure 写入、重复表达 skip、assistant 复述不污染长期记忆。

已交付：

- Eval case schema 和 LangSmith runner。
- 本地 canonical case 文件作为 source of truth。
- 人类可读 summary 和机器可读 JSON 结果。
- `write_trace.candidate_decisions`、active/superseded memories、source_ref/fetched_messages 作为可观察证据。
- memory recall case 可以断言 lexical candidate count、lane status，并把公开 recall item id 关联到 trace 中的 lane rank 与 RRF contribution。
- 回归测试使用 deterministic fake；真实 LLM smoke 通过 `amadeus eval memory-quality --env .env` 运行。

后续扩展：

- context isolation eval。
- tool loop eval。
- proactive send/skip eval。

验收标准：

- Evaluation 能独立于普通单元测试运行。
- 失败报告能说明哪一个公开行为退化了，而不只是某个私有 helper 失败。

## 阶段 4：Telegram Outbound

- 在 Telegram adapter 之前先定义 `OutboundPort` 边界。
- 增加 Telegram adapter，支持 dry-run mode 和 real-send mode。
- 增加一个类似 `message_push` 的工具或 runtime service，统一走 outbound 边界。

验收标准：

- dry-run smoke 能证明消息可以被准备和记录。
- 配置凭据后可以做真实发送验证。
- 核心 runtime 不直接 import Telegram 具体实现。

## 阶段 5：Scheduler

- 增加 scheduled job model、JSON 或 SQLite store、fire-at parser、tick execution。
- 区分 instant jobs 和需要进入 agent/runtime 的 soft jobs。
- 先走 outbound dry-run，再在配置完整时接 Telegram。

验收标准：

- eval 或 smoke 覆盖 after/at/every、cancel、recovery、避免重复 in-flight execution。

## 阶段 6：ProactiveLoop

- 实现真实 pipeline：gate、DataGateway、LLM judge、resolve、outbound、ACK 或 dry-run trace。
- 第一版先使用本地 fixture sources：alert、content、context。
- memory/context 只能通过已有边界接入，不能直接读底层存储。

验收标准：

- proactive eval 覆盖 send、skip、duplicate suppression、no-content skip、source-bound message evidence。
- Telegram outbound 可以被使用，但 ProactiveLoop 不耦合 Telegram 内部实现。

## 阶段 7：DriftRunner

- 只在 ProactiveLoop 稳定之后增加可用 task runner。
- 第一版只做一个有价值的维护任务，例如 memory audit 或 proactive rule review。
- 必须有明确 finish state 和 trace。

验收标准：

- Drift 可以静默运行，或通过 outbound 边界产出一条 summary。
- 如果暂未实现，简历措辞必须保持为计划中或未来工作，不能写成已完成能力。
