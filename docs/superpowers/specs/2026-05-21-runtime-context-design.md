# Runtime Context Phase 1 Design

## Goal

Build the first Amadeus system prompt and runtime context assembly layer as a small Python package with pytest coverage.

The phase 1 system must compose fixed identity, behavior rules, self model, long-term memory, recent context, retrieved memory, active skills, and runtime metadata into an OpenAI-style `messages` list. It must also explain how each prompt block contributed to the final system prompt.

## Source Material

The design is based on:

- `dev_docs/requirements01.md`
- `dev_docs/prompt_framework.md`
- User-approved defaults from the May 21, 2026 planning discussion

## Non-Goals

Phase 1 does not implement:

- LLM provider calls
- persona migration
- automatic self model updates
- memory update gates
- database-backed self model storage
- dashboard editing
- LLM behavior judge evals
- direct conversation-driven edits to `SELF.md`

## Architecture

The package exposes a pure prompt assembly pipeline:

```text
RuntimeContext
-> PromptBlock.render(context)
-> SystemPromptBuilder.build(context)
-> MessageEnvelopeBuilder.build(...)
-> ContextBuilder.render(context)
-> messages[0].content
```

The important design rule is separation of source-of-truth boundaries. `SELF.md` describes Amadeus, `MEMORY.md` describes the user, `RECENT_CONTEXT.md` describes recent session state, and retrieval contains dynamic per-request material.

## Files And Responsibilities

### `amadeus/persona.py`

Contains short, stable code-level identity material for Amadeus.

This is the source of truth for default identity/personality. It is not user memory and should not contain workspace-specific relationship facts.

### `amadeus/prompts.py`

Contains functions that build stable identity and behavior-rule prompt text:

- `build_static_identity_prompt()`
- `build_behavior_rules_prompt()`

These functions produce code-owned prompt material used by the corresponding prompt blocks.

### `amadeus/prompt_block.py`

Defines the prompt block abstraction and concrete block implementations:

- `PromptBlock`
- `IdentityPromptBlock`
- `BehaviorRulesPromptBlock`
- `SelfModelPromptBlock`
- `LongTermMemoryPromptBlock`
- `RecentContextPromptBlock`
- `RetrievedMemoryPromptBlock`
- `ActiveSkillsPromptBlock`
- `RuntimeMetadataPromptBlock`

Each block has:

- `label`
- `priority`
- `is_static`
- `render(context) -> PromptBlockRenderResult`

`render()` returns either rendered text or an empty result with an explicit reason.

### `amadeus/context.py`

Defines the runtime data model and builders:

- `Message`
- `RuntimeContext`
- `PromptDebugEntry`
- `SystemPromptResult`
- `ContextRenderResult`
- `SystemPromptBuilder`
- `MessageEnvelopeBuilder`
- `ContextBuilder`

`SystemPromptBuilder` sorts blocks by priority, renders each block, skips empty content, joins rendered content with a stable separator, and returns debug breakdown.

`MessageEnvelopeBuilder` produces:

```python
[
    {"role": "system", "content": system_prompt},
    *history,
    {"role": "user", "content": current_user_message},
]
```

It rejects history entries with `role == "system"` so callers cannot accidentally inject a second system prompt.

### `amadeus/workspace.py`

Defines workspace initialization:

- `DEFAULT_SELF_MD`
- `initialize_workspace(workspace_root)`

Initialization creates `{workspace_root}/memory/SELF.md` if missing. It never overwrites an existing file.

Rendering never writes files. This keeps prompt generation free of hidden filesystem side effects.

### `tests/`

Contains pytest tests for initialization, block rendering, builder behavior, message ordering, and structure-level retrieval isolation.

## Runtime Context

`RuntimeContext` accepts:

- `workspace_root`
- `history`
- `current_user_message`
- `retrieved_memory`
- `active_skills`
- `runtime_metadata`
- `recent_context_override`

Default file-backed sources are:

- `{workspace_root}/memory/SELF.md`
- `{workspace_root}/memory/MEMORY.md`
- `{workspace_root}/memory/RECENT_CONTEXT.md`

`recent_context_override` is reserved for future runtime-provided summaries. When present, it should take precedence over the default recent-context file.

## Prompt Block Priorities

Phase 1 uses the priorities from `requirements01.md`:

```text
10 IdentityPromptBlock
20 BehaviorRulesPromptBlock
30 SelfModelPromptBlock
40 LongTermMemoryPromptBlock
50 RecentContextPromptBlock
60 RetrievedMemoryPromptBlock
70 ActiveSkillsPromptBlock
80 RuntimeMetadataPromptBlock
```

This order places stable identity and hard behavior rules before dynamic user or retrieval material.

## Caching

`SystemPromptBuilder` supports caching static blocks, but only truly static code-owned blocks should use it in phase 1:

- `IdentityPromptBlock`
- `BehaviorRulesPromptBlock`

File-backed and runtime-backed blocks remain dynamic:

- `SelfModelPromptBlock`
- `LongTermMemoryPromptBlock`
- `RecentContextPromptBlock`
- `RetrievedMemoryPromptBlock`
- `ActiveSkillsPromptBlock`
- `RuntimeMetadataPromptBlock`

This trades tiny performance gains for correctness. A markdown file can change between requests, so caching it by default would create stale prompts.

## Debug Breakdown

The builder returns one debug entry for every block, including skipped blocks.

Each entry includes:

- block label
- priority
- whether it rendered
- output character count
- estimated token count
- empty reason, if skipped

Token estimation is approximate and dependency-free in phase 1. A later provider-specific layer can replace this with a real tokenizer if needed.

## Retrieval Isolation

Phase 1 verifies retrieval isolation structurally, not behaviorally.

Tests should prove:

- retrieval renders after identity and self model
- retrieval has its own block label and section
- retrieval content is not merged into identity or self model sections
- debug breakdown exposes retrieval as a separate block

Phase 1 does not claim that an LLM can never be influenced by retrieval text. That belongs to later eval or judge work.

## Testing Requirements

The test suite must cover:

- existing `SELF.md` is not overwritten by initialization
- missing `SELF.md` is created by initialization
- empty `SELF.md` is not injected
- `SelfModelPromptBlock` reads and renders `SELF.md`
- missing or empty memory files are skipped
- `RecentContextPromptBlock` reads `{workspace_root}/memory/RECENT_CONTEXT.md`
- `recent_context_override` takes precedence over file content
- blocks are sorted by priority
- static blocks can be cached
- dynamic blocks render each time
- `messages[0]` is the system prompt
- history appears after the system prompt
- current user message appears last
- history with an existing system role is rejected
- retrieval is structurally isolated from identity and self model
- debug breakdown shows every block state

## Acceptance

Phase 1 is complete when a developer can answer:

- Which blocks make up the system prompt?
- What is each block's source of truth?
- Where does `SELF.md` enter `messages[0]`?
- Are persona and self model responsibilities separated?
- Are user facts kept out of self model code paths?
- Is retrieval structurally prevented from replacing identity or self model sections?
- Can a prompt render be debugged block by block?
