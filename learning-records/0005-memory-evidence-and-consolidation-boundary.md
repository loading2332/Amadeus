# Learning Record 0005: Memory evidence and consolidation boundary

用户已经能够区分 Lesson 15 的核心回源链：`search_messages` 通过子串定位候选消息，`fetch_messages` 通过 `id` / `source_ref` / `evidence` 回源读取原始 message；`evidence` 不是原文证据，而是指向原始消息的结构化索引，必须配合 `fetch_messages` 才能变成可引用的事实证据。

用户也已经澄清 Markdown memory 与 vector memory 的边界：`history_entries` 是 consolidation 从旧对话中抽出的历史事件摘要，进入 `HISTORY.md` / journal，并可同步进入 vector DB 供 `recall_memory` 检索；`pending_items` 是长期画像候选，进入 `PENDING.md`，后续由 optimizer 合并进 `MEMORY.md`。这意味着后续 Lesson 可以继续推进 Akashic 的 message lookup / evidence 回源强化，而不需要重新解释 history 与 pending 的基本分工。
