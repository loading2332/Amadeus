# ADR 0001: Akashic-Aligned Memory Write Chain

## Status

Accepted

## Context

Phase 3 的 `memory-quality` eval 暴露了一个关键问题：旧 post-response 写入链只做薄 LLM 抽取，然后直接 `memorize`。这能证明“查得出来吗”，但不能稳定证明“记得对吗”。典型失败包括短期状态误写、历史和当前偏好冲突、实体属性冲突、噪音中漏抽关键事实，以及 assistant 复述被当成用户证据。

Akashic 的参考设计把记忆写入拆成候选抽取、类型边界、去重/冲突判定、replacement lifecycle 和回源证据。Amadeus 不复制目录结构，但迁移这些设计契约。

## Decision

- post-response 立即处理用户明确表达的 `preference`、`procedure`、当前事实更正和显式纠错。
- `profile` 和普通长期事实仍可由 markdown/consolidation 承担，但 post-response 允许写入明确的当前实体属性更新。
- 抽取候选必须是 typed candidate，并记录 `summary`、`memory_type`、`source_message_ids/source_ref`、`extra.category`、`confidence`、`reason`。
- assistant 消息不能作为记忆证据；候选 source id 必须解析到 user message。
- 候选进入 store 前先经过 decision provider，判定 `create`、`skip` 或 `replace`。
- replacement 通过 `memory_replacements` 记录，新记忆可 supersede 多个旧记忆，`undo_by_source` 保持可恢复。
- LLM 抽取失败时允许保守不写；不允许因为抽取/判定失败执行破坏性 supersede。

## Consequences

- `memory-quality` 不再只看 recall，而能断言 active/superseded state、source_ref/fetch 和 write trace。
- 写入链变成可观察的公开行为：`write_trace.candidate_decisions` 记录每个候选的 action、reason、target ids。
- 规则兜底只覆盖明确用户自述，避免把真实生产能力伪装成 eval-only fake。
- 当前 decision provider 是保守规则实现，后续可以替换为 Akashic 风格的向量预筛 + LLM judge，而不改变 `MemoryEngine` 六方法 contract。
