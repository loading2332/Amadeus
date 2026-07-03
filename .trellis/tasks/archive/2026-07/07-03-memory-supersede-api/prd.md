# Clarify memory supersede API

## Goal

把 Amadeus memory mutation API 从含混的 `replace_many` 收敛为更可解释的 supersede lifecycle：

- 写入新记忆仍由 `memorize(MemoryWriteRequest)` 负责。
- 退休旧记忆由明确的 `supersede_many(...)` 负责。
- 新旧记忆之间的 replacement relation 由 store 层显式记录，保证 `undo_by_source` 可恢复。

这支撑的简历 claim 是：Akashic-inspired memory system 不只是“覆盖旧内容”，而是保留 source-backed correction、supersede 状态和可回滚 replacement trace。

## Confirmed Facts

- 当前 `MemoryMemorizer.replace_many` 位于 `amadeus/memory/memorizer.py`，它同时写入新记忆、标记旧条目 `superseded`、写 `replacement_id` extra，并调用 `store.record_replacement(...)`。
- `PostResponseMemoryWorker` 仍调用 `memorizer.replace_many(...)` 来执行 LLM 决策出的 `replace` action。
- `MemoryStore` 已有 `memory_replacements` 表、`record_replacement(...)`、`find_replacements_by_source_ref(...)` 和 `list_replacements_for(...)`。
- `undo_by_source` 依赖 `find_replacements_by_source_ref(source_ref)` 恢复 old item，并把 replacement item 标记为 superseded。
- Akashic 参考设计公开的是 `supersede_batch(ids)` 状态动作；replacement relation 在 store 层通过 `record_replacements(...)` 记录。
- 当前工作树已有大量未提交改动，本任务必须只改 memory supersede API 相关文件和对应测试。

## Requirements

1. `MemoryMemorizer` 必须提供明确的 `supersede_many(...)` API，用于把一组旧 memory ids 标记为 `superseded`。
2. replacement flow 必须显式分成三步：`memorize` 新条目、`supersede_many` 旧条目、记录 replacement relation。
3. `PostResponseMemoryWorker` 的 `replace` action 必须使用新的明确 API，不再调用 `replace_many`。
4. `replace_many` 必须从代码中删除；replacement flow 只能显式使用 `memorize` + `supersede_many`。
5. `undo_by_source` 行为不能回退：用 replacement source_ref 仍能恢复旧条目、退休 replacement item。
6. mutation trace 必须继续暴露 `replacement_id` 和被 supersede 的 old ids，保持 evaluation 和 interview 证据可观察。
7. 不引入新的 LLM 判断、memory quality case 或 Telegram/proactive 行为。

## Acceptance Criteria

- AC1: `PostResponseMemoryWorker` replace decision 会写入新 memory，并通过新 supersede API 将目标 memory 标记为 `superseded`。
- AC2: replacement relation 写入 `memory_replacements`，`undo_by_source(new_source_ref)` 能恢复 old memory 并 retire new memory。
- AC3: `replace_many` 名称不再出现在 `amadeus` 或 `tests` 代码路径。
- AC4: Existing memory tests for replace, undo, forget, post-response correction, and memory quality eval continue passing.
- AC5: Focused search confirms no stale references to `replace_many` in `amadeus` or `tests`.

## Out Of Scope

- 不重做 `memory_replacements` schema。
- 不迁移 Akashic 的完整 replacement snapshot columns。
- 不增加 merge semantics。
- 不改 memory-quality YAML case 语义，除非测试名或 trace 字段必须同步。
