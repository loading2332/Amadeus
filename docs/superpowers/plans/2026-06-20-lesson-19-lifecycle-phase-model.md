# Lesson 19 Lifecycle Phase Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach Akashic's complete lifecycle map, then add three typed lifecycle seams to Amadeus without prematurely implementing the plugin manager or slot dependency system.

**Architecture:** Reuse the existing `EventBus`: ordered `emit()` remains the Gate primitive and a new failure-isolated `fanout()` becomes the Tap primitive. A new `TurnLifecycle` facade owns typed before-turn, prompt-render, and after-turn registration; `PassiveRuntime` invokes those seams while preserving its existing behavior when no handlers are registered.

**Tech Stack:** Python 3.11, dataclasses, asyncio, pytest, existing Amadeus EventBus/PassiveRuntime/ContextBuilder, HTML teaching artifacts, ruff, mypy.

---

## File map

- Create `lessons/0015-lesson-19-lifecycle-phase-model-part-1.html`: Akashic source lesson and Part 1 retelling gate.
- Create `amadeus/lifecycle.py`: typed contexts and `TurnLifecycle` facade.
- Modify `amadeus/events.py`: add failure-isolated `fanout()` for Tap observers.
- Modify `amadeus/runtime.py`: invoke before-turn, prompt-render, and after-turn at the approved boundaries.
- Modify `amadeus/__init__.py`: export the public lifecycle types.
- Create `tests/test_lifecycle.py`: EventBus and lifecycle facade unit tests.
- Modify `tests/test_runtime.py`: production-chain integration, retry isolation, order, and compatibility tests.
- Create `lessons/0016-lesson-19-lifecycle-phase-model-part-2.html`: Amadeus code walkthrough, verification, gap audit, and retelling.
- Do not create a Lesson 19 learning record until the user retells both the Akashic phase map and Amadeus responsibilities.

### Task 1: Create the formal Akashic Part 1 lesson

**Files:**
- Create: `lessons/0015-lesson-19-lifecycle-phase-model-part-1.html`
- Read: `../akashic-agent/agent/core/passive_turn.py`
- Read: `../akashic-agent/agent/lifecycle/phase.py`
- Read: `../akashic-agent/agent/lifecycle/types.py`
- Read: `../akashic-agent/agent/lifecycle/facade.py`
- Read: `../akashic-agent/agent/lifecycle/phases/before_turn.py`
- Read: `../akashic-agent/agent/lifecycle/phases/prompt_render.py`
- Read: `../akashic-agent/agent/lifecycle/phases/after_turn.py`
- Read: `../akashic-agent/bus/event_bus.py`
- Read: `../akashic-agent/tests/test_lifecycle_phase.py`
- Read: `../akashic-agent/tests/test_lifecycle_phases.py`
- Read: `../akashic-agent/tests/test_turn_pipelines.py`

- [ ] **Step 1: Write the current-stage map and complete seven-phase map**

The lesson must show the actual nesting:

```text
PassiveTurnPipeline
  before_turn
  before_reasoning
  Reasoner
    prompt_render
    loop:
      before_step
      provider/tools
      after_step
  after_reasoning
  after_turn
```

State that Amadeus currently has a monolithic `run_turn()`, scattered events, and tool hooks, but no formal turn lifecycle.

- [ ] **Step 2: Teach Gate versus Tap using real EventBus code**

Include this semantic comparison:

```text
Gate / emit:
  ordered
  next handler sees previous result
  may change later execution
  exception propagates

Tap / fanout:
  observe-only
  observers run independently
  one failure is logged and isolated
  cannot rewrite the committed result
```

Explicitly note that `after_reasoning` is a Gate despite its `after_` prefix.

- [ ] **Step 3: Deep-read the three Lesson 19 phases**

For each phase, include input, mutable/observable fields, built-in module order, output, and one source-backed test:

```text
before_turn  -> session/context preparation + Gate + optional Akashic abort
prompt_render -> sections/hints Gate -> ContextBuilder.render
after_turn -> TurnCommitted fanout -> AfterTurn fanout -> dispatch
```

- [ ] **Step 4: Add scope, gap audit, eval seeds, and retelling questions**

The retelling gate must ask the user to explain:

1. the full seven-phase order and nesting;
2. Gate versus Tap based on data flow and error behavior;
3. the exact responsibilities of before-turn, prompt-render, and after-turn;
4. why Lesson 19 excludes slots/plugin loading/tool discovery;
5. where commit and dispatch occur relative to after-turn.

- [ ] **Step 5: Validate the HTML and commit**

Run a local `HTMLParser` check that every `href="#..."` points to an existing ID and `../assets/lesson.css` exists.

Run: `git diff --check`

Expected: no whitespace errors and no missing lesson anchors/assets.

Commit:

```powershell
git add lessons/0015-lesson-19-lifecycle-phase-model-part-1.html
git commit -m "docs: teach lesson 19 lifecycle phases"
```

- [ ] **Step 6: Stop for the Part 1 retelling gate**

Do not start Task 2 until the user can retell the Akashic main chain. Do not create a learning record at this point.

### Task 2: Add Tap fanout semantics to EventBus

**Files:**
- Create: `tests/test_lifecycle.py`
- Modify: `amadeus/events.py`

- [ ] **Step 1: Write the failing fanout isolation test**

```python
@dataclass(frozen=True)
class _TapEvent:
    value: str


@pytest.mark.asyncio
async def test_event_bus_fanout_isolates_observer_failures(caplog):
    bus = EventBus()
    seen: list[str] = []

    async def broken(event: _TapEvent) -> None:
        raise RuntimeError("observer failed")

    async def healthy(event: _TapEvent) -> None:
        seen.append(event.value)

    bus.on(_TapEvent, broken)
    bus.on(_TapEvent, healthy)
    await bus.fanout(_TapEvent("reply"))

    assert seen == ["reply"]
    assert "observer failed" in caplog.text
```

This test deliberately uses a local event type so EventBus Tap semantics remain independent of the lifecycle facade introduced in Task 3.

- [ ] **Step 2: Run the focused test and verify red**

Run: `uv run --extra dev pytest tests/test_lifecycle.py::test_event_bus_fanout_isolates_observer_failures -v`

Expected: FAIL because `EventBus` has no `fanout` method.

- [ ] **Step 3: Implement failure-isolated fanout**

Add `asyncio` and logging imports, a module logger, and these methods to `EventBus`:

```python
async def fanout(self, event: object) -> None:
    handlers = list(self._handlers.get(type(event), []))
    if not handlers:
        return
    await asyncio.gather(*(self._run_observer(event, handler) for handler in handlers))

async def _run_observer(
    self,
    event: object,
    handler: EventHandler[object],
) -> None:
    try:
        result = handler(event)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.exception("observer error for %s", type(event).__name__)
```

Do not change `emit()`; Gate exceptions must still propagate.

- [ ] **Step 4: Run the focused test and verify green**

Run: `uv run --extra dev pytest tests/test_lifecycle.py::test_event_bus_fanout_isolates_observer_failures -v`

Expected: PASS, with the broken observer logged and the healthy observer still executed.

- [ ] **Step 5: Commit**

```powershell
git add amadeus/events.py tests/test_lifecycle.py
git commit -m "feat: add lifecycle tap fanout"
```

### Task 3: Add typed lifecycle contexts and facade

**Files:**
- Create: `amadeus/lifecycle.py`
- Modify: `tests/test_lifecycle.py`
- Modify: `amadeus/__init__.py`

- [ ] **Step 1: Write failing ordered-Gate and facade tests**

```python
@pytest.mark.asyncio
async def test_before_turn_gate_runs_handlers_in_order():
    lifecycle = TurnLifecycle(EventBus())

    def first(ctx: BeforeTurnContext) -> BeforeTurnContext:
        ctx.runtime_metadata["order"] = "first"
        return ctx

    def second(ctx: BeforeTurnContext) -> BeforeTurnContext:
        ctx.runtime_metadata["order"] += ":second"
        return ctx

    lifecycle.on_before_turn(first)
    lifecycle.on_before_turn(second)
    result = await lifecycle.before_turn(_before_turn_context())

    assert result.runtime_metadata["order"] == "first:second"
```

Also test that `on_prompt_render()` handlers use ordered Gate semantics and `on_after_turn()` handlers run through Tap semantics.

- [ ] **Step 2: Run tests and verify red**

Run: `uv run --extra dev pytest tests/test_lifecycle.py -v`

Expected: FAIL because the lifecycle module/facade does not exist.

- [ ] **Step 3: Implement typed contexts**

Create `amadeus/lifecycle.py` with these stable contracts:

```python
@dataclass
class BeforeTurnContext:
    session_key: str
    user_message: str
    history: list[Message]
    retrieved_memory: str | None
    active_skills: list[str]
    runtime_metadata: dict[str, str]

@dataclass
class PromptRenderContext:
    session_key: str
    attempt_index: int
    attempt_name: str
    runtime_context: RuntimeContext

@dataclass(frozen=True)
class AfterTurnContext:
    session_key: str
    user_message_id: str
    assistant_message_id: str
    assistant_response: str
    tool_chain: tuple[dict[str, Any], ...]
    context_retry: dict[str, Any]
```

Use fresh list/dict copies when constructing these objects in runtime. `AfterTurnContext` is frozen because it is an observation snapshot.

- [ ] **Step 4: Implement TurnLifecycle**

```python
class TurnLifecycle:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def on_before_turn(self, handler: EventHandler[BeforeTurnContext]) -> None:
        self._bus.on(BeforeTurnContext, handler)

    def on_prompt_render(self, handler: EventHandler[PromptRenderContext]) -> None:
        self._bus.on(PromptRenderContext, handler)

    def on_after_turn(self, handler: EventHandler[AfterTurnContext]) -> None:
        self._bus.on(AfterTurnContext, handler)

    async def before_turn(self, ctx: BeforeTurnContext) -> BeforeTurnContext:
        return await self._bus.emit(ctx)

    async def prompt_render(self, ctx: PromptRenderContext) -> PromptRenderContext:
        return await self._bus.emit(ctx)

    async def after_turn(self, ctx: AfterTurnContext) -> None:
        await self._bus.fanout(ctx)
```

Export the four public lifecycle types from `amadeus/__init__.py`.

- [ ] **Step 5: Run tests and static checks**

Run:

```powershell
uv run --extra dev pytest tests/test_lifecycle.py -q
uv run --extra dev ruff check amadeus/lifecycle.py amadeus/events.py tests/test_lifecycle.py
uv run --extra dev mypy
```

Expected: lifecycle tests pass; ruff and mypy report no errors.

- [ ] **Step 6: Commit**

```powershell
git add amadeus/lifecycle.py amadeus/__init__.py tests/test_lifecycle.py
git commit -m "feat: add typed turn lifecycle facade"
```

### Task 4: Integrate before-turn and prompt-render Gates

**Files:**
- Modify: `amadeus/runtime.py`
- Modify: `tests/test_runtime.py`

- [ ] **Step 1: Write the failing runtime Gate integration test**

Register two before-turn handlers. The first adds `"first"` to runtime metadata; the second asserts it and changes the retrieved-memory marker. Register a prompt-render handler that adds `"prompt_marker"` to `runtime_context.turn_injection_context`. Run a real passive turn and assert the provider payload contains both modifications.

Core assertions:

```python
assert order == ["before:first", "before:second", "prompt"]
assert "prompt lifecycle marker" in str(client.completions.calls[0]["messages"])
assert "before lifecycle memory" in str(client.completions.calls[0]["messages"])
```

- [ ] **Step 2: Run the new test and verify red**

Run: `uv run --extra dev pytest tests/test_runtime.py::test_runtime_runs_before_turn_and_prompt_render_gates -v`

Expected: FAIL because `PassiveRuntime` has no lifecycle facade or phase calls.

- [ ] **Step 3: Construct lifecycle in PassiveRuntime**

Add:

```python
lifecycle: TurnLifecycle = field(init=False)

def __post_init__(self) -> None:
    self.lifecycle = TurnLifecycle(self.event_bus)
```

This guarantees lifecycle registration and existing `TurnCommitted` subscriptions share one EventBus.

- [ ] **Step 4: Invoke before-turn after preparation**

After session/history/retrieval preparation, construct `BeforeTurnContext` with fresh copies, await `self.lifecycle.before_turn(...)`, and use its `history`, `retrieved_memory`, `active_skills`, and `runtime_metadata` for the rest of the turn. Do not implement abort and do not mutate the persisted original user message.

- [ ] **Step 5: Invoke prompt-render once per retry attempt**

Inside the retry loop, construct a new `RuntimeContext`, wrap it in a new `PromptRenderContext`, await the Gate, then pass `prompt_ctx.runtime_context` to `ContextBuilder.render()`. Never reuse a previous attempt's mutable context.

- [ ] **Step 6: Run the integration test and verify green**

Run: `uv run --extra dev pytest tests/test_runtime.py::test_runtime_runs_before_turn_and_prompt_render_gates -v`

Expected: PASS with exact order `before:first`, `before:second`, `prompt`.

- [ ] **Step 7: Commit**

```powershell
git add amadeus/runtime.py tests/test_runtime.py
git commit -m "feat: integrate lifecycle gates"
```

### Task 5: Prove prompt-render retry isolation

**Files:**
- Modify: `tests/test_runtime.py`

- [ ] **Step 1: Write the retry isolation test**

Use `ContextLengthThenSuccessCompletions`. The prompt handler records `(attempt_index, id(runtime_context))` and inserts one marker into that attempt's metadata. Assert:

```python
assert [item[0] for item in seen] == [0, 1]
assert seen[0][1] != seen[1][1]
assert sum("lifecycle retry marker" in str(call["messages"]) for call in client.completions.calls) == 2
```

- [ ] **Step 2: Run and verify behavior**

Run: `uv run --extra dev pytest tests/test_runtime.py::test_prompt_render_uses_fresh_context_for_each_retry -v`

Expected: PASS. A failure with identical object IDs or duplicated marker text means mutable prompt state leaked across attempts.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_runtime.py
git commit -m "test: cover lifecycle prompt retry isolation"
```

### Task 6: Integrate after-turn Tap after commit

**Files:**
- Modify: `amadeus/runtime.py`
- Modify: `tests/test_runtime.py`

- [ ] **Step 1: Write the failing commit/order/isolation test**

Register a `TurnCommitted` handler and two after-turn observers, one broken and one healthy. The healthy observer must verify the persisted session already contains both messages and record the final IDs.

Core assertions:

```python
assert order == ["commit", "after:healthy"]
assert seen_ids == [("chat:1:0", "chat:1:1")]
assert result.assistant_response == "assistant reply"
assert "observer failed" in caplog.text
```

- [ ] **Step 2: Run the test and verify red**

Run: `uv run --extra dev pytest tests/test_runtime.py::test_after_turn_runs_after_commit_and_isolates_observers -v`

Expected: FAIL because runtime does not invoke the after-turn lifecycle Tap.

- [ ] **Step 3: Build the result before returning**

Replace the inline return with:

```python
turn_result = PassiveTurnResult(...)
await self.lifecycle.after_turn(
    AfterTurnContext(
        session_key=session_key,
        user_message_id=turn_result.user_message_id,
        assistant_message_id=turn_result.assistant_message_id,
        assistant_response=turn_result.assistant_response,
        tool_chain=tuple(dict(step) for step in tool_chain),
        context_retry=dict(context_retry),
    )
)
return turn_result
```

The existing `TurnCommitted` emit must remain before this call.

- [ ] **Step 4: Run focused runtime/lifecycle tests**

Run:

```powershell
uv run --extra dev pytest tests/test_lifecycle.py tests/test_runtime.py tests/test_runtime_vector_memory.py -q
```

Expected: all focused tests pass; observer failure is logged but does not change the returned result.

- [ ] **Step 5: Commit**

```powershell
git add amadeus/runtime.py tests/test_runtime.py
git commit -m "feat: add after-turn lifecycle tap"
```

### Task 7: Create the Part 2 lesson and run stage gates

**Files:**
- Create: `lessons/0016-lesson-19-lifecycle-phase-model-part-2.html`
- Test: all existing tests

- [ ] **Step 1: Write the Amadeus code walkthrough**

Include:

- `EventBus.emit` versus `fanout`;
- typed contexts and facade;
- exact three runtime insertion points;
- Gate propagation and Tap isolation;
- context retry isolation;
- equivalence map from Akashic components to Amadeus components;
- why abort, slots, plugin loading, prompt injection, and tool discovery remain gaps.

- [ ] **Step 2: Add verification instructions and observed evidence**

Document exact focused/full commands, expected fields, actual counts, and how to inspect phase order. Do not claim browser/UI validation when only runtime payload and tests were exercised.

- [ ] **Step 3: Add gap audit, eval seeds, and retelling**

Require the user to explain:

1. each Amadeus lifecycle type and insertion point;
2. why Gate errors propagate while Tap errors isolate;
3. why prompt contexts must be fresh per retry;
4. one deliberate difference from Akashic and its reason;
5. the first file/test to inspect when adding a new phase.

- [ ] **Step 4: Validate HTML and run all quality gates**

Run:

```powershell
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev mypy
```

Also validate local HTML anchors and `../assets/lesson.css` using `HTMLParser`.

Expected: all tests pass; ruff/mypy clean; no missing lesson anchors/assets.

- [ ] **Step 5: Commit**

```powershell
git add lessons/0016-lesson-19-lifecycle-phase-model-part-2.html
git commit -m "docs: teach lesson 19 lifecycle implementation"
```

- [ ] **Step 6: Stop for final Lesson 19 retelling**

Only after the user can explain both Akashic and Amadeus chains should `learning-records/0008-*.md` be created and Lesson 20 begin.

## Plan self-review

- Spec coverage: the plan covers the full phase map, three-phase implementation, Gate/Tap semantics, retry isolation, compatibility, verification, teaching artifacts, gap audit, and eval seeds.
- Scope: abort, PhaseFrame slots, plugin loading, prompt section plugins, tool hooks, and tool discovery stay outside Lesson 19 implementation.
- Type consistency: all tasks use `BeforeTurnContext`, `PromptRenderContext`, `AfterTurnContext`, and `TurnLifecycle`; runtime uses the same EventBus instance.
- Safety: Gate failures propagate rather than continuing with partial state; Tap failures are isolated after persistence.
- Teaching gate: Task 1 must finish with user retelling before any production code task begins.
