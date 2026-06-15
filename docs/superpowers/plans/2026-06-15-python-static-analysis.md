# Python Static Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Amadeus-specific `ruff` and `mypy` configuration, make the runtime core pass strict static analysis, and keep tests plus developer scripts usable through intentional boundary-aware overrides.

**Architecture:** Keep all configuration in `pyproject.toml`, because the repository already uses `uv` and project-local metadata there. Enforce strict `mypy` on `amadeus/`, lint `amadeus/`, `tests/`, and `dev_utils/` with `ruff`, and relax only the dynamic support layers where strict production-style rules would create chronic noise.

**Tech Stack:** Python 3.11, `uv`, `pyproject.toml`, `ruff`, `mypy`, pytest, OpenAI-compatible provider payloads, SQLite-backed runtime/session code.

---

## File Structure

- Modify: `pyproject.toml`
  - Add `ruff` configuration, `mypy` configuration, and directory-specific overrides.
- Create: `dev_utils/__init__.py`
  - Give `mypy` an explicit package base for script helpers if duplicate module discovery persists.
- Modify: `amadeus/__init__.py`
  - Remove or align re-exports so lint/static analysis matches the intended public surface.
- Modify: `amadeus/cli.py`
  - Remove unused imports and keep CLI entry typing clean.
- Modify: `amadeus/memory.py`
  - Remove unused imports and keep the file compatible with selected lint rules.
- Modify: `amadeus/provider.py`
  - Narrow dynamic OpenAI response parsing and payload typing so strict `mypy` can reason about the provider boundary.
- Modify: `amadeus/runtime.py`
  - Tighten tool-loop and provider payload typing where strict mode currently loses information.
- Modify: `amadeus/tool_runtime.py`
  - Align helper signatures with strict `mypy` expectations for message payload shapes.
- Modify: `amadeus/tools/base.py`
  - Strengthen tool-facing payload and result types if strict mode requires it.
- Modify: `amadeus/tools/executor.py`
  - Keep execution boundary types explicit under strict mode.
- Modify: `dev_utils/run_context_llm.py`
  - Only if needed to align with package-base resolution after `mypy` configuration.
- Modify: `dev_utils/inspect_context.py`
  - Only if needed to align with package-base resolution after `mypy` configuration.

## Scope Guardrails

- This plan does **not** refactor `dev_utils/` into a reusable package design.
- This plan does **not** remove every `Any` from Amadeus.
- This plan does **not** add formatters, hooks, CI, or pre-commit integration.
- This plan does **not** change runtime behavior except where type/lint cleanup reveals a real bug or malformed boundary.

## Task 1: Establish Static Analysis Boundaries

**Files:**
- Modify: `pyproject.toml`
- Create: `dev_utils/__init__.py`

- [ ] **Step 1: Run the raw baseline commands and capture the current failures**

Run:

```powershell
uv run ruff check amadeus tests dev_utils
uv run mypy amadeus tests dev_utils
```

Expected:

```text
- ruff reports current unused imports plus E402 in dev_utils scripts
- mypy stops early on duplicate module discovery for dev_utils/run_context_llm.py
```

- [ ] **Step 2: Add Amadeus-specific `ruff` and `mypy` configuration to `pyproject.toml`**

Append these sections to `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.ruff.lint.per-file-ignores]
"dev_utils/*.py" = ["E402"]

[tool.mypy]
python_version = "3.11"
files = ["amadeus", "tests", "dev_utils"]
strict = true
explicit_package_bases = true

[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
disallow_incomplete_defs = false
disallow_untyped_calls = false
warn_return_any = false

[[tool.mypy.overrides]]
module = ["dev_utils.*"]
disallow_untyped_defs = false
disallow_incomplete_defs = false
disallow_untyped_calls = false
warn_return_any = false
```

- [ ] **Step 3: Add an explicit package marker for `dev_utils`**

Create `dev_utils/__init__.py`:

```python
"""Developer helper scripts for local Amadeus inspection and experiments."""
```

- [ ] **Step 4: Re-run the boundary checks**

Run:

```powershell
uv run ruff check amadeus tests dev_utils
uv run mypy amadeus tests dev_utils
```

Expected:

```text
- ruff no longer fails on E402 in dev_utils
- mypy no longer stops on duplicate module discovery
- mypy now reports real strict-typing issues inside amadeus runtime-core modules
```

- [ ] **Step 5: Commit the boundary configuration**

Run:

```powershell
git add pyproject.toml dev_utils/__init__.py
git commit -m "build: configure ruff and mypy boundaries"
```

## Task 2: Clear the Repository-Wide Ruff Baseline

**Files:**
- Modify: `amadeus/__init__.py`
- Modify: `amadeus/cli.py`
- Modify: `amadeus/memory.py`
- Modify: `dev_utils/run_context_llm.py` only if the new config surfaces import-order or hygiene issues beyond `E402`
- Modify: `dev_utils/inspect_context.py` only if the new config surfaces import-order or hygiene issues beyond `E402`

- [ ] **Step 1: Run the focused `ruff` command and isolate the remaining violations**

Run:

```powershell
uv run ruff check amadeus tests dev_utils
```

Expected:

```text
- unused re-export/import in amadeus/__init__.py
- unused import in amadeus/cli.py
- unused imports in amadeus/memory.py
- any other low-risk F/I hygiene issues surfaced by the new config
```

- [ ] **Step 2: Remove the known unused imports**

Apply these edits:

`amadeus/cli.py`

```python
from amadeus.bootstrap import build_passive_app
```

`amadeus/memory.py`

```python
from collections.abc import ...
```

Delete the unused `Awaitable` and `Callable` names from that import list.

`amadeus/__init__.py`

```python
__all__ = [
    ...,
    "ContextLengthError",
    ...,
]
```

If `ContextLengthError` is intended as a public re-export, keep it and add it to `__all__`. If it is not intended as part of the public API, remove the import instead of hiding the warning.

- [ ] **Step 3: Re-run `ruff` until the lint baseline is clean**

Run:

```powershell
uv run ruff check amadeus tests dev_utils
```

Expected:

```text
All checks passed!
```

- [ ] **Step 4: Commit the lint cleanup**

Run:

```powershell
git add amadeus/__init__.py amadeus/cli.py amadeus/memory.py
git commit -m "style: clear static analysis lint baseline"
```

## Task 3: Make the Runtime Core Pass Strict Mypy

**Files:**
- Modify: `amadeus/provider.py`
- Modify: `amadeus/runtime.py`
- Modify: `amadeus/tool_runtime.py`
- Modify: `amadeus/tools/base.py`
- Modify: `amadeus/tools/executor.py`

- [ ] **Step 1: Run strict `mypy` on the runtime core and capture the first real type errors**

Run:

```powershell
uv run mypy amadeus
```

Expected:

```text
- strict-mode complaints around OpenAI response parsing in provider.py
- strict-mode complaints around message/tool payload dicts in runtime.py and tool_runtime.py
- possibly broad `dict[str, Any]` / untyped protocol boundaries in tool runtime types
```

- [ ] **Step 2: Tighten provider parsing around the OpenAI response boundary**

Refactor `amadeus/provider.py` toward helper functions that narrow unknown payloads before they flow inward:

```python
from collections.abc import Mapping
from typing import Any


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None
```

Use those helpers when building `LLMResponse`, instead of letting raw `Any` propagate through `choice`, `message`, `content`, and tool-call parsing.

- [ ] **Step 3: Tighten runtime/tool payload shapes so strict mode can follow the tool loop**

Refactor `amadeus/runtime.py` and `amadeus/tool_runtime.py` toward explicit aliases for message payloads:

```python
type MessagePayload = dict[str, object]
type ToolSchema = dict[str, object]
```

Then update helper signatures such as:

```python
messages: list[MessagePayload]
tool_schemas: list[ToolSchema] | None
tool_steps: list[dict[str, object]]
```

Keep dynamic boundaries at the edge, but stop using unconstrained `Any` for internal loop variables that have a known structure.

- [ ] **Step 4: Tighten tool runtime type definitions where strict mode still complains**

Update `amadeus/tools/base.py` and `amadeus/tools/executor.py` only where needed to make the execution boundary explicit:

```python
class Tool(Protocol):
    name: str
    description: str
    parameters: Mapping[str, object]

    def execute(self, **kwargs: object) -> ToolResult: ...
```

and:

```python
def execute(
    self,
    tool_name: str,
    arguments: dict[str, object],
) -> tuple[ToolResult, ToolTrace]:
    ...
```

Use the narrowest practical object/mapping types that still match the real payload boundary.

- [ ] **Step 5: Re-run strict `mypy` on `amadeus/` until it passes**

Run:

```powershell
uv run mypy amadeus
```

Expected:

```text
Success: no issues found in ... source files
```

- [ ] **Step 6: Commit the runtime-core typing pass**

Run:

```powershell
git add amadeus/provider.py amadeus/runtime.py amadeus/tool_runtime.py amadeus/tools/base.py amadeus/tools/executor.py
git commit -m "refactor: make runtime core pass strict mypy"
```

## Task 4: Verify Support-Layer Overrides and End-to-End Commands

**Files:**
- Modify: `pyproject.toml` only if the initial test/dev-utils overrides still generate non-actionable noise
- Modify: `dev_utils/run_context_llm.py` only if package-base resolution still requires a small import adjustment
- Modify: `dev_utils/inspect_context.py` only if package-base resolution still requires a small import adjustment

- [ ] **Step 1: Run `mypy` across the full configured repository**

Run:

```powershell
uv run mypy amadeus tests dev_utils
```

Expected:

```text
- amadeus stays clean under strict mode
- tests and dev_utils pass under the intentional overrides
```

- [ ] **Step 2: If tests or scripts still emit non-actionable strict errors, adjust only the override boundary**

Keep the fix localized to `pyproject.toml` overrides, for example:

```toml
[[tool.mypy.overrides]]
module = ["tests.*"]
warn_unused_ignores = false
```

or:

```toml
[[tool.mypy.overrides]]
module = ["dev_utils.*"]
check_untyped_defs = false
```

Do **not** weaken the global strict core just to make support-layer noise disappear.

- [ ] **Step 3: Run the full verification set**

Run:

```powershell
uv run ruff check amadeus tests dev_utils
uv run mypy amadeus tests dev_utils
uv run pytest
```

Expected:

```text
- ruff passes
- mypy passes
- pytest passes
```

- [ ] **Step 4: Perform the final boundary audit**

Manual checklist:

```text
- amadeus/ remains the strict enforcement target
- tests/ are still checked, but fake fixtures are not forcing production-style abstractions
- dev_utils/ still works as script-oriented support code
- the final config lives in pyproject.toml and matches the repository’s uv workflow
- no repository-wide looseners were added just to silence one dynamic edge
```

- [ ] **Step 5: Commit the final static-analysis integration pass**

Run:

```powershell
git add pyproject.toml dev_utils/__init__.py amadeus/__init__.py amadeus/cli.py amadeus/memory.py amadeus/provider.py amadeus/runtime.py amadeus/tool_runtime.py amadeus/tools/base.py amadeus/tools/executor.py dev_utils/run_context_llm.py dev_utils/inspect_context.py
git commit -m "build: integrate static analysis for amadeus"
```

## Self-Review

- Spec coverage: the plan covers all accepted design points from the approved static-analysis spec: repository-local config, strict core runtime checking, support-layer overrides, explicit `dev_utils` package handling, and end-to-end verification with `ruff`, `mypy`, and `pytest`.
- Placeholder scan: no `TODO`, `TBD`, or unresolved path references remain. Optional file edits are scoped to concrete situations that will be observed during execution.
- Type consistency: the plan keeps `amadeus/` as the strict core target throughout, and all override adjustments are explicitly limited to `tests.*` and `dev_utils.*`.

## What You Should Learn While Executing

1. Strict static analysis should follow architectural boundaries, not directory count or aesthetic preference.
2. `Any` is acceptable at real dynamic edges, but it should not leak inward and blind the rest of the runtime.
3. Support scripts and test fakes are not “bad code” by default; they just need a different analysis boundary from the production runtime.
4. A good static-analysis setup is one that developers will keep running, not one that looks maximalist on paper.
