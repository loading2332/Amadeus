# Runtime Context Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the phase 1 Amadeus Python prompt/runtime context assembly layer with pytest coverage.

**Architecture:** Implement a small Python package where `PromptBlock` instances render source-specific prompt sections, `SystemPromptBuilder` joins them with debug metadata, and `MessageEnvelopeBuilder` wraps the result into OpenAI-style messages. Workspace markdown files are read through a parameterized `workspace_root`; initialization is explicit and rendering has no filesystem write side effects.

**Tech Stack:** Python 3.11+, pytest, standard library only.

---

## File Structure

- Create: `pyproject.toml`
  - Defines package metadata and pytest configuration.
- Create: `amadeus/__init__.py`
  - Exposes the public API.
- Create: `amadeus/persona.py`
  - Holds stable identity text constants.
- Create: `amadeus/prompts.py`
  - Builds stable identity and behavior-rule prompt text.
- Create: `amadeus/workspace.py`
  - Provides `DEFAULT_SELF_MD` and `initialize_workspace(workspace_root)`.
- Create: `amadeus/prompt_block.py`
  - Defines `PromptBlock`, render result type, and concrete block classes.
- Create: `amadeus/context.py`
  - Defines runtime data classes and prompt/message builders.
- Create: `tests/test_workspace.py`
  - Tests workspace initialization.
- Create: `tests/test_prompt_blocks.py`
  - Tests file-backed and runtime-backed block rendering.
- Create: `tests/test_context_builders.py`
  - Tests system prompt builder, message envelope, and integrated context render.

## Task 1: Project Skeleton And Workspace Initialization

**Files:**

- Create: `pyproject.toml`
- Create: `amadeus/__init__.py`
- Create: `amadeus/workspace.py`
- Test: `tests/test_workspace.py`

- [ ] **Step 1: Write failing tests for workspace initialization**

```python
from amadeus.workspace import DEFAULT_SELF_MD, initialize_workspace


def test_initialize_workspace_creates_default_self_md(tmp_path):
    initialize_workspace(tmp_path)

    self_path = tmp_path / "memory" / "SELF.md"
    assert self_path.exists()
    assert self_path.read_text(encoding="utf-8") == DEFAULT_SELF_MD


def test_initialize_workspace_does_not_overwrite_existing_self_md(tmp_path):
    self_path = tmp_path / "memory" / "SELF.md"
    self_path.parent.mkdir()
    self_path.write_text("custom self model", encoding="utf-8")

    initialize_workspace(tmp_path)

    assert self_path.read_text(encoding="utf-8") == "custom self model"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_workspace.py -v`

Expected: FAIL because `amadeus.workspace` does not exist yet.

- [ ] **Step 3: Implement minimal package skeleton and initializer**

Create `pyproject.toml` with pytest config. Create `amadeus/workspace.py`:

```python
from pathlib import Path

DEFAULT_SELF_MD = """# Amadeus Self Model

Amadeus is a collaborative AI companion with a stable sense of identity, clear relationship boundaries, and a preference for honest, grounded help.
"""


def initialize_workspace(workspace_root: str | Path) -> None:
    root = Path(workspace_root)
    memory_dir = root / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    self_path = memory_dir / "SELF.md"
    if not self_path.exists():
        self_path.write_text(DEFAULT_SELF_MD, encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_workspace.py -v`

Expected: PASS.

## Task 2: Prompt Block Rendering

**Files:**

- Create: `amadeus/persona.py`
- Create: `amadeus/prompts.py`
- Create: `amadeus/prompt_block.py`
- Modify: `amadeus/__init__.py`
- Test: `tests/test_prompt_blocks.py`

- [ ] **Step 1: Write failing tests for block rendering**

Cover:

- `SelfModelPromptBlock` skips missing and empty `SELF.md`
- `SelfModelPromptBlock` renders non-empty `SELF.md`
- `LongTermMemoryPromptBlock` reads `MEMORY.md`
- `RecentContextPromptBlock` reads `RECENT_CONTEXT.md`
- `recent_context_override` takes precedence
- `RetrievedMemoryPromptBlock` renders runtime retrieval
- `ActiveSkillsPromptBlock` renders active skill names
- `RuntimeMetadataPromptBlock` renders metadata

Use `RuntimeContext` from `amadeus.context` in the test even though it does not exist yet; this preserves the intended API.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompt_blocks.py -v`

Expected: FAIL because prompt block and context modules do not exist yet.

- [ ] **Step 3: Implement minimal runtime context type**

Create `amadeus/context.py` with `Message` and `RuntimeContext` definitions only:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict


class Message(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


@dataclass(slots=True)
class RuntimeContext:
    workspace_root: Path
    history: list[Message]
    current_user_message: str
    retrieved_memory: str | None = None
    active_skills: list[str] = field(default_factory=list)
    runtime_metadata: dict[str, str] = field(default_factory=dict)
    recent_context_override: str | None = None
```

- [ ] **Step 4: Implement prompt text helpers and block classes**

Create:

- `amadeus/persona.py`
- `amadeus/prompts.py`
- `amadeus/prompt_block.py`

Core implementation requirements:

- `PromptBlockRenderResult(content: str, empty_reason: str | None = None)`
- `rendered` property returns `bool(content.strip())`
- file blocks read UTF-8 markdown and skip missing/empty files
- headings:
  - `## Amadeus Self Model`
  - `## User Long-Term Memory`
  - `## Recent Context`
  - `## Retrieved Memory`
  - `## Active Skills`
  - `## Runtime Metadata`

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_prompt_blocks.py -v`

Expected: PASS.

## Task 3: System Prompt Builder

**Files:**

- Modify: `amadeus/context.py`
- Test: `tests/test_context_builders.py`

- [ ] **Step 1: Write failing tests for system prompt building**

Cover:

- blocks render in priority order, independent of input order
- empty blocks appear in debug breakdown but not prompt text
- static blocks are cached
- dynamic blocks render every build
- debug entry contains label, priority, rendered, char count, estimated tokens, and empty reason
- retrieval appears after identity and self model

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_context_builders.py -v`

Expected: FAIL because `SystemPromptBuilder` does not exist yet.

- [ ] **Step 3: Implement `SystemPromptBuilder` and result types**

Add to `amadeus/context.py`:

- `PromptDebugEntry`
- `SystemPromptResult`
- `SystemPromptBuilder`

Implementation notes:

- Sort blocks by `priority`
- Cache rendered results for `block.is_static`
- Use a stable separator: `"\n\n---\n\n"`
- Estimate tokens with dependency-free heuristic: `(char_count + 3) // 4`
- Include debug entries for skipped blocks

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_context_builders.py -v`

Expected: PASS for system builder tests.

## Task 4: Message Envelope And Integrated Context Builder

**Files:**

- Modify: `amadeus/context.py`
- Modify: `amadeus/__init__.py`
- Test: `tests/test_context_builders.py`

- [ ] **Step 1: Write failing tests for message envelope**

Cover:

- `messages[0]` is the system prompt
- history appears after system prompt
- current user message is last
- history with `role == "system"` raises `ValueError`

- [ ] **Step 2: Write failing tests for integrated context render**

Cover:

- default `ContextBuilder` includes the eight required block types
- `SELF.md` enters `messages[0].content`
- debug breakdown includes every default block label

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_context_builders.py -v`

Expected: FAIL because `MessageEnvelopeBuilder` and `ContextBuilder` do not exist yet.

- [ ] **Step 4: Implement envelope and integrated builder**

Add to `amadeus/context.py`:

- `MessageEnvelopeBuilder`
- `ContextRenderResult`
- `ContextBuilder`

`ContextBuilder` default block order should instantiate:

- `IdentityPromptBlock`
- `BehaviorRulesPromptBlock`
- `SelfModelPromptBlock`
- `LongTermMemoryPromptBlock`
- `RecentContextPromptBlock`
- `RetrievedMemoryPromptBlock`
- `ActiveSkillsPromptBlock`
- `RuntimeMetadataPromptBlock`

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_context_builders.py -v`

Expected: PASS.

## Task 5: Full Verification And Cleanup

**Files:**

- Modify as needed based on test failures.

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`

Expected: all tests pass.

- [ ] **Step 2: Review public exports**

Inspect `amadeus/__init__.py` and ensure the intended public classes/functions are exported.

- [ ] **Step 3: Check git diff**

Run: `git diff --stat && git diff --check`

Expected:

- no whitespace errors
- only planned files changed

- [ ] **Step 4: Summarize the implementation**

Explain:

- what was built
- why rendering is read-only
- how prompt block source-of-truth boundaries are enforced
- what tests cover
- what phase 1 intentionally does not cover
