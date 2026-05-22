# Lesson3 Prompt Context Design

## Goal

Implement Amadeus lesson3 prompt context layering on top of the phase 1 runtime context builder.

The design refines the phase 1 model. Phase 1 proved that prompt blocks can render source-specific sections and produce OpenAI-style messages. Lesson3 adds a second assembly step so stable sections remain in the system prompt while per-turn dynamic sections move into a marked context frame before the current user message.

## Source Material

This design is based on:

- `dev_docs/requirements02.md`
- `dev_docs/requirements01.md`
- Akashic lesson3 notes in `/Users/didi/develop/akashic-agent/tutorial/QA/lesson3.md`
- Akashic prompt assembler pattern in `/Users/didi/develop/akashic-agent/agent/prompting/assembler.py`

Akashic is a reference implementation only. Amadeus keeps its smaller package shape and does not inherit Akashic's runtime architecture.

## Non-Goals

This design does not implement:

- production agent loop
- proactive/drift/scheduler flows
- memory optimizer
- automatic writes to `SELF.md`, `MEMORY.md`, or `RECENT_CONTEXT.md`
- vector retrieval or embedding
- tool calling orchestration
- provider retry on context length error
- OpenAI SDK dependency

The development provider utilities remain under `dev_utils` and are not part of the core package runtime.

## Architecture

The lesson3 pipeline is:

```text
RuntimeContext
-> PromptBlock.render(context)
-> SystemPromptBuilder.build(context)
-> PromptAssembler.assemble(sections, disabled_sections, turn_injection_context)
-> MessageEnvelopeBuilder.build(system_prompt, history_window, context_frame, current_user_message)
-> ContextRenderResult.messages
```

The important change from phase 1 is that `SystemPromptBuilder` still renders blocks in priority order, but its non-empty outputs are also preserved as named `PromptSectionRender` values. `PromptAssembler` then decides which sections belong to `system_prompt` and which belong to `context_frame`.

This keeps block rendering simple while making final message routing explicit and testable.

## Components

### `amadeus.prompt_block`

`PromptBlock` uses a stable `label` field as the section id.

Expected default labels:

```text
identity
behavior_rules
self_model
long_term_memory
recent_context
retrieved_memory
active_skills
runtime_metadata
```

`label` is the routing key and the visible context-frame heading. Amadeus intentionally does not keep a second hand-written `name` field because it would duplicate the same section identity.

`RecentContextPromptBlock` strips `## Recent Turns` and everything after it before rendering. If the remaining content is empty, it returns an empty result with a clear reason.

### `amadeus.context`

`RuntimeContext` includes:

```python
disabled_sections: set[str]
turn_injection_context: dict[str, str]
history_window: int | None
```

`SystemPromptBuilder.build()` returns:

```python
SystemPromptResult(
    prompt=str,
    breakdown=list[PromptDebugEntry],
    sections=list[PromptSectionRender],
)
```

`ContextBuilder.render()` coordinates the full flow:

```text
1. Build block sections.
2. Assemble system and frame sections.
3. Build destination-specific debug breakdowns.
4. Slice history if history_window is set.
5. Build final messages.
```

`MessageEnvelopeBuilder` appends the context frame only when it has non-empty content.

### `amadeus.prompting.assembler`

`PromptAssembler` owns section routing.

Default context frame section labels:

```python
{
    "recent_context",
    "retrieved_memory",
    "active_skills",
    "runtime_metadata",
}
```

Everything else remains in the system prompt unless disabled.

`build_context_frame_content()` wraps frame sections in:

```text
<system-reminder data-system-context-frame="true">
...
</system-reminder>
```

The marker text tells the model that the content is system-provided candidate context, not user speech or assistant conclusions.

`turn_injection_context` entries are appended to frame sections with low priority after normal block-rendered sections. They are skipped if empty or disabled by name.

### `amadeus.prompting.budget`

The budget module provides candidate trim attempts only. It does not call providers or retry requests.

The first trim plan protects:

```python
{"identity", "behavior_rules", "self_model"}
```

The default attempts first remove lower-priority dynamic material, then shrink history:

```text
full
trim_runtime_metadata
trim_active_skills
trim_long_term_memory
trim_retrieved_memory
trim_retrieved_memory_history at smaller history windows
```

This is intentionally conservative. It keeps Amadeus' identity and behavior boundaries available even when a future provider layer has to recover from a context length error.

### `dev_utils.openai_provider`

The provider utility is a minimal OpenAI-compatible chat completions client.

It supports:

```text
OPENAI_BASE_URL
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_TIMEOUT_SECONDS
```

The transport is injectable so tests can assert payloads without making network calls.

### `dev_utils.run_context_llm`

This script renders Amadeus context messages and optionally sends them to the configured OpenAI-compatible provider.

It is a development verification path:

```text
workspace markdown + runtime flags
-> ContextBuilder.render()
-> optional printed messages and breakdown
-> provider.chat(messages)
```

It should not become the production agent loop.

## Data Flow

### Normal Render

```text
RuntimeContext(
  workspace_root,
  history,
  current_user_message,
  retrieved_memory,
  active_skills,
  runtime_metadata,
  recent_context_override,
)
```

Each block renders independently:

```text
identity              -> code-owned identity prompt
behavior_rules        -> code-owned behavior prompt
self_model            -> memory/SELF.md
long_term_memory      -> memory/MEMORY.md
recent_context        -> override or memory/RECENT_CONTEXT.md, minus Recent Turns
retrieved_memory      -> runtime retrieved memory
active_skills         -> runtime active skills
runtime_metadata      -> runtime metadata
```

`PromptAssembler` then produces:

```text
system_prompt:
  identity
  behavior_rules
  self_model
  long_term_memory

context_frame:
  recent_context
  retrieved_memory
  active_skills
  runtime_metadata
  turn_injection_context
```

The final message order is:

```text
system prompt
history slice
context frame, if non-empty
current user message
```

### Recent Context

`RECENT_CONTEXT.md` may contain `## Recent Turns` because the file can serve future background workflows and human debugging. Passive response prompt injection strips that section because recent raw turns already arrive through `history`.

The design separates file completeness from prompt injection suitability:

```text
file can keep Recent Turns
prompt block strips Recent Turns
history carries raw recent conversation
```

## Error Handling

Missing or empty markdown files do not raise. Their blocks return empty render results with explicit reasons.

History containing a `system` role raises `ValueError`, because Amadeus should have a single system prompt boundary.

Malformed provider responses raise `ValueError` when assistant content is absent. HTTP and URL errors are wrapped as `RuntimeError` with response details where available.

Malformed CLI metadata items raise `ValueError` if they are not `KEY=VALUE`.

## Debugging

`PromptDebugEntry` includes `destination`.

System prompt breakdown only contains entries routed to `system`. Context frame breakdown only contains entries routed to `context_frame`. Disabled sections are omitted from the destination-specific breakdown, because they were intentionally excluded from final messages.

Injected context entries appear in context frame breakdown even though they did not originate from a prompt block.

This lets a developer answer:

```text
Was a block empty, disabled, or routed elsewhere?
How many approximate tokens did each destination receive?
Which dynamic materials were sent to the model this turn?
```

## Testing Strategy

Unit tests should cover:

- `PromptAssembler` routes sections by name
- context frame marker is present
- empty frame sections produce no context frame
- disabled sections remove both block sections and matching turn injections
- context frame sections are placed before the current user message
- empty context frame is omitted from messages
- `ContextBuilder` routes dynamic context away from system prompt
- `history_window` slices history
- recent context strips `## Recent Turns`
- recent context skips when only Recent Turns remain
- default trim plans never drop core sections
- trim attempts generate section disable sets and smaller history windows
- provider config loads from `.env`
- environment values override `.env`
- provider sends expected `/chat/completions` payload
- provider rejects missing assistant content
- debug CLI render path uses the project `ContextBuilder`

## Acceptance

The lesson3 migration is complete when:

```text
uv run pytest -q passes
retrieved_memory is absent from system_prompt and present in context_frame
context_frame is inserted after history and before current user message
recent_context prompt content excludes ## Recent Turns
debug breakdown shows destination for routed sections
core trim sections are protected
dev provider tests do not require network access
```

## Teaching Notes

The key engineering move is to avoid treating "prompt" as one giant string too early.

Phase 1 built a useful block renderer. Lesson3 keeps that renderer and adds a named section layer before final assembly. That small intermediate representation makes routing, disabling, trimming, and debugging much easier without forcing every block to know where it will end up.

The tradeoff is more moving parts: `SystemPromptBuilder` no longer tells the whole final-message story by itself. In exchange, each class has a clearer role:

```text
PromptBlock renders source-specific content.
SystemPromptBuilder orders and records block renders.
PromptAssembler routes named sections.
MessageEnvelopeBuilder owns message order.
ContextBuilder coordinates the workflow.
```

This is the pattern worth carrying forward from Akashic, not its full directory structure.
