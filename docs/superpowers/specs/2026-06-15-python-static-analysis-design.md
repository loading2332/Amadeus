# Python Static Analysis Design

## Goal

Adapt `mypy` and `ruff` to Amadeus as project-level engineering guardrails, with strict enforcement on the runtime core and pragmatic boundaries for tests and developer scripts.

The target is not "add generic config files." The target is to make the current Amadeus mainline safer to change while keeping the signal-to-noise ratio high enough that the checks will actually be used.

## Current Stage Map

Amadeus is already past the bootstrap stage:

- `amadeus/` contains the real product code path: CLI, runtime, provider, prompt assembly, session persistence, memory, and tool runtime.
- `tests/` has broad pytest coverage and uses fake providers, fake tools, and `SimpleNamespace`-style fixtures to isolate external dependencies.
- `dev_utils/` contains script-style developer helpers that bootstrap imports with `sys.path.insert(...)` and are not shaped like package code.
- The project already uses `uv`, `.venv`, `pyproject.toml`, and `uv.lock`.

That means the next missing capability is not another runtime feature. It is static analysis that reflects the actual structure of the repository.

## Problem Statement

The current repository has two kinds of code with different needs:

1. Core runtime code in `amadeus/`
2. Dynamic support code in `tests/` and `dev_utils/`

Treating those areas as if they were identical creates bad pressure:

- if all directories are held to the same strictness, tests and scripts create noise that hides real runtime issues
- if everything is configured loosely, the runtime core loses the type and lint protection it now needs

The design therefore needs boundary-aware strictness rather than one global setting.

## Non-Goals

This stage does not:

- refactor Amadeus architecture for the sake of static analysis
- eliminate every `Any` from the repository
- convert `dev_utils/` from script helpers into a full package architecture
- rewrite test fixtures to look like production objects
- introduce formatters or pre-commit hooks
- enforce style rules unrelated to maintainability signal

## Current Baseline

The initial raw baseline shows the shape of the problem:

- `ruff` currently reports mostly unused imports and `E402` import-order errors in `dev_utils/`
- `mypy` currently stops early on duplicate module discovery for `dev_utils/run_context_llm.py`
- the production package uses a meaningful amount of `Any` at provider, tool payload, session serialization, and memory boundaries, which is expected because these modules sit at JSON and OpenAI API edges

This tells us the first task is not to chase every dynamic edge. The first task is to make the tooling understand the repository layout and enforce the right rules in the right places.

## Design Principles

### Strictness follows architectural value

The stricter boundary should be the runtime core in `amadeus/`, because that is where interface drift, payload-shape confusion, and cross-module breakage are most expensive.

### Dynamic edges stay explicit

`tests/` and `dev_utils/` are allowed to be more dynamic, but that looseness must be intentional and limited by config, not accidental.

### Configuration should fit current workflow

The repository already uses `uv` and `pyproject.toml`, so all static-analysis configuration should live in `pyproject.toml` unless there is a concrete reason not to.

### Real signal before completeness

It is better to have a strict, trusted core check that developers will keep running than a theoretically purer setup that produces so much noise it gets ignored.

## Proposed Architecture

### `ruff`

`ruff` should run across:

- `amadeus`
- `tests`
- `dev_utils`

The initial enabled rule families should be:

- `E`
- `F`
- `I`
- `B`
- `UP`

Reasoning:

- `E` and `F` catch real correctness and hygiene issues
- `I` keeps imports deterministic and reviewable
- `B` catches common bug-prone constructs
- `UP` keeps the code aligned with the Python 3.11 baseline already required by the project

`ruff` should use per-file ignores for `dev_utils/*.py` on `E402`.

This is intentional, because those files currently modify `sys.path` before importing project code. Forcing them into normal import order without redesigning their bootstrap path would create fake compliance rather than a better design.

### `mypy`

`mypy` should treat `amadeus/` as the strict core package.

Base settings should include:

- `python_version = "3.11"`
- `files = ["amadeus", "tests", "dev_utils"]`
- `explicit_package_bases = true`
- `strict = true`

The strict default is important because the mainline target is the runtime package, not a "best effort" type check.

Then use module overrides to relax checks for:

- `tests.*`
- `dev_utils.*`

The overrides should allow the test and script layers to keep using fake clients, `SimpleNamespace`, ad-hoc payloads, and script-style entry code without forcing production-style abstractions into those directories.

If module discovery remains unstable for `dev_utils`, add a minimal `dev_utils/__init__.py` so `mypy` can resolve it as an explicit package instead of a duplicate module path.

## File-Level Responsibilities

### `pyproject.toml`

Becomes the source of truth for:

- `ruff` target version and selected rules
- `ruff` per-file ignores
- `mypy` base strictness
- `mypy` directory-specific overrides

It should also expose convenient scriptable entry points through documented commands, even if not formalized as `[project.scripts]`.

### `amadeus/`

Must be made clean under the configured `ruff` and `mypy` rules.

Expected work here includes:

- removing unused imports
- clarifying import/export surfaces
- fixing type signatures that are currently ambiguous under strict mode
- adding local narrowing where provider/tool/session payloads cross dynamic boundaries

This is the main enforcement target of the whole stage.

### `tests/`

Remains checked, but with looser type rules where needed.

The goal is:

- tests still benefit from basic static analysis
- fake objects are not treated as a design failure
- test ergonomics do not collapse under strict production rules

### `dev_utils/`

Remains linted and type-checked, but as script-oriented support code rather than product runtime code.

The design does not require these files to be refactored into library modules in this stage.

## Verification Workflow

This stage is only complete when the following commands all run successfully in the real repository:

```powershell
uv run ruff check amadeus tests dev_utils
uv run mypy amadeus tests dev_utils
uv run pytest
```

Verification is intentionally end-to-end:

- `ruff` proves repository-wide lint compatibility
- `mypy` proves the configured package boundaries are understood correctly
- `pytest` proves the static-analysis adaptations did not break the current runtime and test workflow

## Tradeoffs

### One strict policy everywhere vs boundary-aware strictness

One strict policy everywhere is simpler on paper, but it fits this repository poorly because `dev_utils/` and parts of `tests/` are intentionally dynamic.

Boundary-aware strictness is slightly more configuration-heavy, but it protects the runtime core without generating chronic false positives in the support layers.

### Fix script import shape now vs targeted `E402` ignore

Refactoring the `dev_utils` bootstrap flow now would create extra work outside the main objective.

Ignoring `E402` only for those script files is the better current tradeoff because it keeps lint signal high while deferring script packaging cleanup to a stage where it is actually the goal.

This tradeoff fails if `dev_utils/` starts being imported as reusable library code. If that happens, the directory should be redesigned rather than permanently exempted.

### Eliminate `Any` broadly vs narrow dynamic boundaries

Eliminating `Any` everywhere would be expensive and would likely push artificial abstractions into provider and serialization edges.

The better tradeoff is to keep dynamic boundaries explicit and typed as narrowly as practical, while demanding much stronger guarantees inside the runtime core.

## Acceptance Criteria

This design is successful when:

- `pyproject.toml` contains Amadeus-specific `ruff` and `mypy` configuration
- `amadeus/` passes strict `mypy`
- `amadeus/`, `tests/`, and `dev_utils/` pass `ruff`
- `tests/` and `dev_utils/` are checked with intentionally looser `mypy` boundaries where needed
- `mypy` no longer fails on duplicate module discovery for `dev_utils`
- the current pytest suite still passes
- the resulting commands are realistic enough to become the default local verification path for future Amadeus changes

## Implementation Notes

The first implementation slice should proceed in this order:

1. Add `ruff` and `mypy` configuration to `pyproject.toml`
2. Resolve repository-layout issues that block `mypy` module discovery
3. Fix low-risk `ruff` issues first
4. Tighten `amadeus/` until strict `mypy` passes
5. Add or adjust overrides for `tests/` and `dev_utils/` only where the strict core policy creates non-actionable noise
6. Run full verification with `ruff`, `mypy`, and `pytest`

That order keeps the repository understandable while preventing test and script noise from driving the design of the production package.
