# Lesson3 Prompt Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Amadeus lesson3 prompt context migration by routing stable prompt sections to the system prompt, dynamic per-turn sections to a marked context frame, and documenting/debugging the resulting message assembly.

**Architecture:** Keep the phase 1 `PromptBlock` rendering model, use stable section labels and a `PromptSectionRender` intermediate representation, then let `PromptAssembler` route labeled sections into `system_prompt` or `context_frame`. `ContextBuilder` coordinates assembly, history slicing, destination-aware debug breakdowns, and final message ordering.

**Tech Stack:** Python 3.11+, pytest, standard library only for core package; development provider utilities use `urllib` and injectable transport.

---

## File Structure

- Modify: `amadeus/prompt_block.py`
  - Keep stable `label` fields on prompt blocks.
  - Strip `## Recent Turns` from recent context before prompt injection.
- Modify: `amadeus/context.py`
  - Extend `RuntimeContext`.
  - Preserve rendered sections.
  - Route through `PromptAssembler`.
  - Build destination-specific debug results.
  - Insert context frame before current user message.
- Create/modify: `amadeus/prompting/__init__.py`
  - Export prompt-context assembly and budget helpers.
- Create/modify: `amadeus/prompting/assembler.py`
  - Define `PromptSectionRender`, `PromptAssemblyResult`, context frame marker helpers, and `PromptAssembler`.
- Create/modify: `amadeus/prompting/budget.py`
  - Define protected core sections and context trim attempts.
- Modify: `amadeus/__init__.py`
  - Export the new public prompt-context API.
- Modify: `amadeus/prompts/__init__.py`
  - Keep behavior rules as one stable section with nested subsections.
- Create/modify: `dev_utils/openai_provider.py`
  - Provide a minimal OpenAI-compatible debug provider with injectable transport.
- Create/modify: `dev_utils/run_context_llm.py`
  - Render context messages and optionally send them to the debug provider.
- Create/modify: `dev_utils/debug_llm_provider.py`
  - Minimal provider health-check script.
- Create/modify: `.env.example`
  - Document provider debug environment variables.
- Modify: `.gitignore`
  - Ignore local `.env` files while keeping `.env.example`.
- Test: `tests/test_prompt_blocks.py`
  - Cover recent context trimming.
- Test: `tests/test_context_builders.py`
  - Cover context frame routing, message order, history slicing, disabled sections, and turn injection.
- Test: `tests/test_prompt_assembler.py`
  - Cover section routing and marker generation.
- Test: `tests/test_prompt_budget.py`
  - Cover trim plans and protected core sections.
- Test: `tests/test_openai_provider.py`
  - Cover config loading, payload building, and response parsing.
- Test: `tests/test_debug_context_llm.py`
  - Cover CLI helper context rendering.
- Docs: `dev_docs/requirements02.md`
  - Requirement source for lesson3.
- Docs: `docs/superpowers/specs/2026-05-22-lesson3-prompt-context-design.md`
  - Design source for lesson3.

## Current State Note

This plan is written for a partially migrated workspace. Before adding new code, first inspect the current implementation and tests. If a step is already implemented and verified, mark it complete after confirming the referenced test passes.

## Task 1: Section Names And Recent Context Trimming

**Files:**

- Modify: `amadeus/prompt_block.py`
- Test: `tests/test_prompt_blocks.py`

- [x] **Step 1: Verify prompt blocks expose stable names**

Inspect `amadeus/prompt_block.py`.

Expected default block labels:

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

- [x] **Step 2: Add failing tests for recent context trimming if missing**

Ensure `tests/test_prompt_blocks.py` contains tests equivalent to:

```python
def test_recent_context_block_strips_recent_turns_section(tmp_path):
    recent_path = tmp_path / "memory" / "RECENT_CONTEXT.md"
    recent_path.parent.mkdir()
    recent_path.write_text(
        "Compact summary.\n\n"
        "## Ongoing Threads\n\n"
        "- context migration\n\n"
        "## Recent Turns\n\n"
        "- user: repeated raw history\n",
        encoding="utf-8",
    )

    result = RecentContextPromptBlock().render(make_context(tmp_path))

    assert result.rendered
    assert "Recent Turns" not in result.content
    assert "Compact summary." in result.content
```

Also ensure a test covers the case where only `## Recent Turns` remains and the block is skipped.

- [x] **Step 3: Run targeted prompt block tests**

Run:

```bash
uv run pytest tests/test_prompt_blocks.py -q
```

Expected: PASS.

- [x] **Step 4: Implement missing prompt block behavior**

If tests fail, update `RecentContextPromptBlock` so it:

```text
1. Reads override first, then RECENT_CONTEXT.md.
2. Splits at a line whose stripped text is exactly ## Recent Turns.
3. Renders only the preceding content.
4. Returns empty result with reason "recent context only contained recent turns" if nothing remains.
```

Do not change file-backed self model or long-term memory behavior.

- [x] **Step 5: Re-run targeted tests**

Run:

```bash
uv run pytest tests/test_prompt_blocks.py -q
```

Expected: PASS.

## Task 2: Prompt Assembler And Context Frame Routing

**Files:**

- Create/modify: `amadeus/prompting/assembler.py`
- Create/modify: `amadeus/prompting/__init__.py`
- Test: `tests/test_prompt_assembler.py`

- [x] **Step 1: Verify or write assembler tests**

Ensure tests cover:

```text
PromptAssembler routes sections by name.
context frame uses <system-reminder data-system-context-frame="true">.
empty frame sections return empty string.
disabled_sections removes matching sections.
turn_injection_context appends enabled non-empty entries to context frame.
```

- [x] **Step 2: Run assembler tests**

Run:

```bash
uv run pytest tests/test_prompt_assembler.py -q
```

Expected: PASS if already implemented, otherwise FAIL for missing assembler.

- [x] **Step 3: Implement minimal assembler behavior if needed**

Implement:

```python
CONTEXT_FRAME_SECTIONS = {
    "recent_context",
    "retrieved_memory",
    "active_skills",
    "runtime_metadata",
}
SYSTEM_CONTEXT_FRAME_MARKER = '<system-reminder data-system-context-frame="true">'
SYSTEM_CONTEXT_FRAME_END = "</system-reminder>"
```

`PromptAssembler.assemble()` should sort sections by priority, apply `disabled_sections`, split by `section.label`, append non-empty enabled `turn_injection_context`, and return `PromptAssemblyResult`.

- [x] **Step 4: Re-run assembler tests**

Run:

```bash
uv run pytest tests/test_prompt_assembler.py -q
```

Expected: PASS.

## Task 3: Context Builder Integration

**Files:**

- Modify: `amadeus/context.py`
- Modify: `amadeus/__init__.py`
- Test: `tests/test_context_builders.py`

- [x] **Step 1: Verify or write context builder tests**

Ensure tests cover:

```text
SystemPromptBuilder stores PromptSectionRender with block.label.
retrieved_memory is absent from system prompt and present in context frame.
system prompt breakdown contains system sections only.
context frame breakdown contains frame sections only.
MessageEnvelopeBuilder order is system -> history -> context frame -> current user.
empty context frame is omitted.
history_window slices history.
disabled_sections and turn_injection_context affect final frame.
```

- [x] **Step 2: Run context builder tests**

Run:

```bash
uv run pytest tests/test_context_builders.py -q
```

Expected: PASS if already implemented, otherwise FAIL for missing integration.

- [x] **Step 3: Implement missing context integration**

Update `ContextBuilder.render()` to:

```text
1. Build block sections using SystemPromptBuilder.
2. Pass sections to PromptAssembler with disabled_sections and turn_injection_context.
3. Convert assembly.system_sections into SystemPromptResult.
4. Convert assembly.frame_sections into ContextFrameResult.
5. Slice history using history_window.
6. Build messages with optional context_frame before current user message.
```

Update `PromptDebugEntry` with:

```text
name
destination
```

Keep `label` for human-facing class/debug identity.

- [x] **Step 4: Re-run context builder tests**

Run:

```bash
uv run pytest tests/test_context_builders.py -q
```

Expected: PASS.

## Task 4: Context Budget Trim Attempts

**Files:**

- Create/modify: `amadeus/prompting/budget.py`
- Modify: `amadeus/prompting/__init__.py`
- Modify: `amadeus/__init__.py`
- Test: `tests/test_prompt_budget.py`

- [x] **Step 1: Verify or write budget tests**

Ensure tests cover:

```text
DEFAULT_CONTEXT_TRIM_PLANS never drop identity, behavior_rules, or self_model.
build_context_trim_attempts(total_history=N) returns disabled_sections and history_window combinations.
duplicate attempts are removed.
```

- [x] **Step 2: Run budget tests**

Run:

```bash
uv run pytest tests/test_prompt_budget.py -q
```

Expected: PASS if already implemented, otherwise FAIL for missing budget module.

- [x] **Step 3: Implement budget helpers if needed**

Implement:

```python
CORE_SECTIONS = frozenset({"identity", "behavior_rules", "self_model"})
ContextTrimPlan
ContextTrimAttempt
DEFAULT_CONTEXT_TRIM_PLANS
build_context_trim_attempts(total_history: int)
```

Do not implement provider retry in this task.

- [x] **Step 4: Re-run budget tests**

Run:

```bash
uv run pytest tests/test_prompt_budget.py -q
```

Expected: PASS.

## Task 5: Dev Provider Debug Utilities

**Files:**

- Create/modify: `dev_utils/openai_provider.py`
- Create/modify: `dev_utils/run_context_llm.py`
- Create/modify: `dev_utils/debug_llm_provider.py`
- Create/modify: `.env.example`
- Modify: `.gitignore`
- Test: `tests/test_openai_provider.py`
- Test: `tests/test_debug_context_llm.py`

- [x] **Step 1: Verify or write provider tests**

Ensure provider tests cover:

```text
.env config loading.
environment variables override .env values.
missing required config raises ValueError.
chat() posts OpenAI-compatible /chat/completions payload.
extra request options are passed through.
missing assistant content raises ValueError.
```

- [x] **Step 2: Verify or write debug render tests**

Ensure debug render tests cover:

```text
parse_key_value_items parses KEY=VALUE.
parse_key_value_items rejects malformed items.
render_context_messages uses ContextBuilder and produces context frame before current user message.
```

- [x] **Step 3: Run provider/debug tests**

Run:

```bash
uv run pytest tests/test_openai_provider.py tests/test_debug_context_llm.py -q
```

Expected: PASS if already implemented, otherwise FAIL for missing utilities.

- [x] **Step 4: Implement missing utilities if needed**

Keep utilities standard-library only:

```text
urllib.request for HTTP.
Injectable transport for tests.
No OpenAI SDK dependency.
No network calls in tests.
```

- [x] **Step 5: Re-run provider/debug tests**

Run:

```bash
uv run pytest tests/test_openai_provider.py tests/test_debug_context_llm.py -q
```

Expected: PASS.

## Task 6: Public API And Documentation Alignment

**Files:**

- Modify: `amadeus/__init__.py`
- Modify: `amadeus/prompts/__init__.py`
- Docs: `dev_docs/requirements02.md`
- Docs: `docs/superpowers/specs/2026-05-22-lesson3-prompt-context-design.md`

- [x] **Step 1: Inspect public exports**

Run:

```bash
python - <<'PY'
import amadeus
print(sorted(amadeus.__all__))
PY
```

If `python` is not the project environment, use:

```bash
uv run python - <<'PY'
import amadeus
print(sorted(amadeus.__all__))
PY
```

Expected: new assembler, budget, and context frame result symbols are exported.

- [x] **Step 2: Confirm behavior rules remain one stable section**

Inspect `amadeus/prompts/__init__.py`.

Expected:

```text
build_behavior_rules_prompt() returns one "## Behavior Rules" section with nested subsections.
```

- [x] **Step 3: Confirm docs match implementation**

Inspect:

```text
dev_docs/requirements02.md
docs/superpowers/specs/2026-05-22-lesson3-prompt-context-design.md
```

Expected:

```text
Docs list runtime_metadata as a context frame section.
Docs state provider utilities are dev-only.
Docs exclude agent loop/proactive/memory optimizer from module2 scope.
```

## Task 7: Full Verification And Diff Review

**Files:**

- All changed lesson3 files.

- [x] **Step 1: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [x] **Step 2: Check whitespace**

Run:

```bash
git diff --check
```

Expected: no output.

- [x] **Step 3: Review changed files**

Run:

```bash
git status --short
git diff --stat
```

Expected:

```text
Only lesson3 implementation, tests, dev docs, and provider debug files are changed.
No Akashic files are modified.
```

- [x] **Step 4: Summarize final state**

Explain:

```text
what was built
why label is the single section id
why context frame is a marked user-role message
what tests verify
what remains out of scope
```

Do not claim provider live connectivity unless a real `.env` request was explicitly run.
