# Tool Runtime V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only Tool Runtime foundation to Amadeus so tools become schema-exportable, executable, traceable runtime capabilities without introducing the full multi-step agent loop yet.

**Architecture:** Keep the current passive single-shot runtime intact. Add a narrow `Tool` protocol, a `ToolRegistry` that owns tool definitions plus OpenAI-compatible schema export, and a `ToolExecutor` that runs tools through pre/post hooks and produces structured execution traces. Start with read-only tools built on top of existing session and filesystem capabilities so later passive-loop work can reuse stable tool boundaries.

**Tech Stack:** Python 3.11+, pytest, SQLite-backed session store, local filesystem reads, OpenAI-compatible tool schema dictionaries.

---

## File Structure

- Create: `amadeus/tools/__init__.py`
  - Public exports for tool runtime types and default read-only tools.
- Create: `amadeus/tools/base.py`
  - Core dataclasses/protocols: tool definition, execution request/result, trace, hook protocol.
- Create: `amadeus/tools/registry.py`
  - Register/unregister tools, lookup by name, schema export.
- Create: `amadeus/tools/executor.py`
  - Execute tools through hook pipeline, normalize failures, produce traces.
- Create: `amadeus/tools/defaults.py`
  - Read-only tool implementations for `fetch_messages`, `search_messages`, and `read_file`.
- Create: `amadeus/tools/hooks.py`
  - Default safety hooks for read-only tools and simple trace recording helpers.
- Modify: `amadeus/bootstrap.py`
  - Build and expose a default registry/executor for the app without changing `PassiveRuntime` behavior yet.
- Modify: `amadeus/__init__.py`
  - Export tool runtime entry points used by tests and future runtime wiring.
- Test: `tests/test_tool_registry.py`
  - Registry behavior and schema export.
- Test: `tests/test_tool_executor.py`
  - Hook ordering, success/failure normalization, denial behavior.
- Test: `tests/test_readonly_tools.py`
  - Real tool execution against session store and local files.

## Learning Goals

- Learn the difference between an internal Python function and a model-facing tool contract.
- Learn why `ToolRegistry` and `ToolExecutor` are separate responsibilities.
- Learn how hook systems centralize safety policy instead of scattering checks across tool implementations.
- Learn how to keep today’s single-shot runtime stable while building tomorrow’s agent loop foundation.

## Scope Guardrails

- This plan does **not** add OpenAI tool-calling orchestration to `PassiveRuntime`.
- This plan does **not** add shell write tools, filesystem write tools, plugin tool injection, or proactive flows.
- This plan does **not** persist tool-call messages into session history yet.
- This plan intentionally starts with read-only tools only.

## Task 1: Define Tool Runtime Types

**Files:**
- Create: `amadeus/tools/base.py`
- Create: `amadeus/tools/__init__.py`
- Modify: `amadeus/__init__.py`
- Test: `tests/test_tool_registry.py`

- [ ] **Step 1: Write the failing tool-shape test**

Add this to `tests/test_tool_registry.py`:

```python
from __future__ import annotations

from amadeus.tools.base import ToolExecutionRequest, ToolResult


def test_tool_result_exposes_structured_output():
    result = ToolResult(
        tool_name="fetch_messages",
        output={"messages": [{"id": "chat:1:0"}]},
        is_error=False,
        metadata={"source": "session"},
    )
    request = ToolExecutionRequest(tool_name="fetch_messages", arguments={"source_ref": '["chat:1:0"]'})

    assert result.tool_name == "fetch_messages"
    assert result.output["messages"][0]["id"] == "chat:1:0"
    assert request.arguments["source_ref"] == '["chat:1:0"]'
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_tool_registry.py::test_tool_result_exposes_structured_output -q
```

Expected: FAIL because `amadeus.tools` modules do not exist yet.

- [ ] **Step 3: Implement the runtime dataclasses and protocols**

Create `amadeus/tools/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolExecutionRequest:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    output: Any
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolTrace:
    tool_name: str
    arguments: dict[str, Any]
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]

    def execute(self, **kwargs: Any) -> ToolResult: ...


class ToolHook(Protocol):
    def before_execute(self, request: ToolExecutionRequest) -> ToolExecutionRequest: ...

    def after_execute(
        self,
        request: ToolExecutionRequest,
        result: ToolResult,
    ) -> ToolResult: ...
```

Create `amadeus/tools/__init__.py`:

```python
from amadeus.tools.base import Tool, ToolExecutionRequest, ToolHook, ToolResult, ToolTrace

__all__ = [
    "Tool",
    "ToolExecutionRequest",
    "ToolHook",
    "ToolResult",
    "ToolTrace",
]
```

Update `amadeus/__init__.py`:

```python
from amadeus.tools import Tool, ToolExecutionRequest, ToolHook, ToolResult, ToolTrace

__all__ = [
    "Tool",
    "ToolExecutionRequest",
    "ToolHook",
    "ToolResult",
    "ToolTrace",
]
```

- [ ] **Step 4: Run the focused test**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_tool_registry.py::test_tool_result_exposes_structured_output -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add amadeus/tools/base.py amadeus/tools/__init__.py amadeus/__init__.py tests/test_tool_registry.py
git commit -m "feat: add tool runtime base types"
```

## Task 2: Build ToolRegistry and Schema Export

**Files:**
- Create: `amadeus/tools/registry.py`
- Create: `tests/test_tool_registry.py`

- [ ] **Step 1: Add registry behavior tests**

Append to `tests/test_tool_registry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from amadeus.tools.base import ToolResult
from amadeus.tools.registry import ToolRegistry


@dataclass
class EchoTool:
    name: str = "echo"
    description: str = "Echo the provided text."
    parameters: dict = None

    def __post_init__(self) -> None:
        if self.parameters is None:
            self.parameters = {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                },
                "required": ["text"],
            }

    def execute(self, **kwargs):
        return ToolResult(tool_name=self.name, output={"echo": kwargs["text"]})


def test_registry_registers_and_fetches_tools():
    registry = ToolRegistry()
    tool = EchoTool()

    registry.register(tool)

    assert registry.get("echo") is tool
    assert list(registry.names()) == ["echo"]


def test_registry_exports_openai_tool_schema():
    registry = ToolRegistry()
    registry.register(EchoTool())

    schema = registry.export_openai_tools()

    assert schema == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo the provided text.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }
    ]
```

- [ ] **Step 2: Run the failing registry tests**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_tool_registry.py -q
```

Expected: FAIL because `ToolRegistry` does not exist.

- [ ] **Step 3: Implement the registry**

Create `amadeus/tools/registry.py`:

```python
from __future__ import annotations

from collections import OrderedDict

from amadeus.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: "OrderedDict[str, Tool]" = OrderedDict()

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self):
        return self._tools.keys()

    def export_openai_tools(self) -> list[dict]:
        exported: list[dict] = []
        for tool in self._tools.values():
            exported.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return exported
```

Update `amadeus/tools/__init__.py`:

```python
from amadeus.tools.base import Tool, ToolExecutionRequest, ToolHook, ToolResult, ToolTrace
from amadeus.tools.registry import ToolRegistry

__all__ = [
    "Tool",
    "ToolExecutionRequest",
    "ToolHook",
    "ToolRegistry",
    "ToolResult",
    "ToolTrace",
]
```

- [ ] **Step 4: Re-run the registry tests**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_tool_registry.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add amadeus/tools/registry.py amadeus/tools/__init__.py tests/test_tool_registry.py
git commit -m "feat: add tool registry and schema export"
```

## Task 3: Build ToolExecutor and Hook Pipeline

**Files:**
- Create: `amadeus/tools/executor.py`
- Create: `amadeus/tools/hooks.py`
- Test: `tests/test_tool_executor.py`

- [ ] **Step 1: Add hook/executor tests**

Create `tests/test_tool_executor.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import pytest

from amadeus.tools.base import ToolExecutionRequest, ToolResult
from amadeus.tools.executor import ToolExecutor, ToolExecutionDenied
from amadeus.tools.registry import ToolRegistry


@dataclass
class EchoTool:
    name: str = "echo"
    description: str = "Echo the provided text."
    parameters: dict = None

    def __post_init__(self) -> None:
        if self.parameters is None:
            self.parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

    def execute(self, **kwargs):
        return ToolResult(tool_name=self.name, output={"echo": kwargs["text"]})


class DenySecretHook:
    def before_execute(self, request: ToolExecutionRequest) -> ToolExecutionRequest:
        if request.arguments.get("text") == "secret":
            raise ToolExecutionDenied("secret not allowed")
        return request

    def after_execute(self, request: ToolExecutionRequest, result: ToolResult) -> ToolResult:
        return result


def test_executor_runs_tool_and_returns_trace():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(registry=registry)

    result, trace = executor.execute("echo", {"text": "hello"})

    assert result.output == {"echo": "hello"}
    assert trace.status == "success"


def test_executor_denies_via_pre_hook():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(registry=registry, hooks=[DenySecretHook()])

    result, trace = executor.execute("echo", {"text": "secret"})

    assert result.is_error is True
    assert "secret not allowed" in result.output["error"]
    assert trace.status == "denied"


def test_executor_wraps_tool_exceptions():
    @dataclass
    class BrokenTool:
        name: str = "broken"
        description: str = "Always fails."
        parameters: dict = None

        def __post_init__(self) -> None:
            if self.parameters is None:
                self.parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(BrokenTool())
    executor = ToolExecutor(registry=registry)

    result, trace = executor.execute("broken", {})

    assert result.is_error is True
    assert result.output["error"] == "boom"
    assert trace.status == "error"
```

- [ ] **Step 2: Run the failing executor tests**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_tool_executor.py -q
```

Expected: FAIL because `ToolExecutor` and `ToolExecutionDenied` do not exist.

- [ ] **Step 3: Implement the executor and denial type**

Create `amadeus/tools/executor.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from amadeus.tools.base import ToolExecutionRequest, ToolHook, ToolResult, ToolTrace
from amadeus.tools.registry import ToolRegistry


class ToolExecutionDenied(RuntimeError):
    pass


@dataclass
class ToolExecutor:
    registry: ToolRegistry
    hooks: list[ToolHook] | None = None

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> tuple[ToolResult, ToolTrace]:
        request = ToolExecutionRequest(tool_name=tool_name, arguments=dict(arguments))
        try:
            for hook in self.hooks or []:
                request = hook.before_execute(request)
            tool = self.registry.get(tool_name)
            if tool is None:
                raise KeyError(f"unknown tool: {tool_name}")
            result = tool.execute(**request.arguments)
            for hook in self.hooks or []:
                result = hook.after_execute(request, result)
            return result, ToolTrace(tool_name=tool_name, arguments=request.arguments, status="success")
        except ToolExecutionDenied as error:
            return (
                ToolResult(tool_name=tool_name, output={"error": str(error)}, is_error=True),
                ToolTrace(tool_name=tool_name, arguments=request.arguments, status="denied"),
            )
        except Exception as error:
            return (
                ToolResult(tool_name=tool_name, output={"error": str(error)}, is_error=True),
                ToolTrace(tool_name=tool_name, arguments=request.arguments, status="error"),
            )
```

Create `amadeus/tools/hooks.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from amadeus.tools.base import ToolExecutionRequest, ToolResult
from amadeus.tools.executor import ToolExecutionDenied


@dataclass
class ReadOnlyFilesystemHook:
    workspace_root: Path

    def before_execute(self, request: ToolExecutionRequest) -> ToolExecutionRequest:
        if request.tool_name != "read_file":
            return request
        raw_path = str(request.arguments.get("path") or "").strip()
        resolved = (self.workspace_root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
        try:
            resolved.relative_to(self.workspace_root.resolve())
        except ValueError as error:
            raise ToolExecutionDenied(f"path escapes workspace: {resolved}") from error
        request.arguments["path"] = str(resolved)
        return request

    def after_execute(self, request: ToolExecutionRequest, result: ToolResult) -> ToolResult:
        return result
```

- [ ] **Step 4: Re-run the executor tests**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_tool_executor.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add amadeus/tools/executor.py amadeus/tools/hooks.py tests/test_tool_executor.py
git commit -m "feat: add tool executor and hook pipeline"
```

## Task 4: Add Read-Only Default Tools

**Files:**
- Create: `amadeus/tools/defaults.py`
- Test: `tests/test_readonly_tools.py`

- [ ] **Step 1: Add default-tool tests**

Create `tests/test_readonly_tools.py`:

```python
from __future__ import annotations

from pathlib import Path

from amadeus.session import SessionManager
from amadeus.tools.defaults import FetchMessagesTool, ReadFileTool, SearchMessagesTool


def test_fetch_messages_tool_reads_session_messages(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    session.add_message("user", "hello")
    session.add_message("assistant", "hi")
    manager.save(session)

    tool = FetchMessagesTool(store=manager.store)
    result = tool.execute(source_ref='["chat:1:0","chat:1:1"]')

    assert result.is_error is False
    assert [item["content"] for item in result.output["messages"]] == ["hello", "hi"]


def test_search_messages_tool_returns_matches(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    session.add_message("user", "tool runtime")
    session.add_message("assistant", "copy that")
    manager.save(session)

    tool = SearchMessagesTool(store=manager.store)
    result = tool.execute(query="tool", session_key="chat:1")

    assert result.is_error is False
    assert result.output["count"] == 1


def test_read_file_tool_reads_utf8_text(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello world", encoding="utf-8")

    tool = ReadFileTool()
    result = tool.execute(path=str(path))

    assert result.is_error is False
    assert result.output["content"] == "hello world"
```

- [ ] **Step 2: Run the failing read-only tool tests**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_readonly_tools.py -q
```

Expected: FAIL because the default tools do not exist yet.

- [ ] **Step 3: Implement the tools**

Create `amadeus/tools/defaults.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from amadeus.session import SessionStore, fetch_messages, search_messages
from amadeus.tools.base import ToolResult


@dataclass
class FetchMessagesTool:
    store: SessionStore
    name: str = "fetch_messages"
    description: str = "Fetch persisted session messages by ids or source_ref."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "source_ref": {"type": "string"},
                "context": {"type": "integer"},
            },
        }
    )

    def execute(self, **kwargs):
        messages = fetch_messages(
            self.store,
            ids=kwargs.get("ids"),
            source_ref=kwargs.get("source_ref"),
            context=int(kwargs.get("context", 0)),
        )
        return ToolResult(tool_name=self.name, output={"messages": messages})


@dataclass
class SearchMessagesTool:
    store: SessionStore
    name: str = "search_messages"
    description: str = "Search persisted session messages by substring."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "session_key": {"type": "string"},
                "role": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
            "required": ["query"],
        }
    )

    def execute(self, **kwargs):
        payload = search_messages(
            self.store,
            query=str(kwargs["query"]),
            session_key=kwargs.get("session_key"),
            role=kwargs.get("role"),
            limit=int(kwargs.get("limit", 10)),
            offset=int(kwargs.get("offset", 0)),
        )
        return ToolResult(tool_name=self.name, output=payload)


@dataclass
class ReadFileTool:
    name: str = "read_file"
    description: str = "Read a UTF-8 text file from disk."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
    )

    def execute(self, **kwargs):
        path = Path(str(kwargs["path"]))
        return ToolResult(
            tool_name=self.name,
            output={"path": str(path), "content": path.read_text(encoding="utf-8")},
        )
```

Update `amadeus/tools/__init__.py`:

```python
from amadeus.tools.base import Tool, ToolExecutionRequest, ToolHook, ToolResult, ToolTrace
from amadeus.tools.defaults import FetchMessagesTool, ReadFileTool, SearchMessagesTool
from amadeus.tools.registry import ToolRegistry

__all__ = [
    "FetchMessagesTool",
    "ReadFileTool",
    "SearchMessagesTool",
    "Tool",
    "ToolExecutionRequest",
    "ToolHook",
    "ToolRegistry",
    "ToolResult",
    "ToolTrace",
]
```

- [ ] **Step 4: Re-run the read-only tool tests**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_readonly_tools.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add amadeus/tools/defaults.py amadeus/tools/__init__.py tests/test_readonly_tools.py
git commit -m "feat: add read-only default tools"
```

## Task 5: Wire Default Tool Runtime Through Bootstrap

**Files:**
- Modify: `amadeus/bootstrap.py`
- Test: `tests/test_bootstrap_tool_runtime.py`

- [ ] **Step 1: Add bootstrap wiring tests**

Create `tests/test_bootstrap_tool_runtime.py`:

```python
from __future__ import annotations

from amadeus.bootstrap import build_passive_app


class FakeCompletions:
    async def create(self, **kwargs):
        raise AssertionError("chat should not run in this bootstrap test")


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = type("Chat", (), {"completions": self.completions})()


def test_build_passive_app_exposes_readonly_tool_runtime(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
            ]
        ),
        encoding="utf-8",
    )

    app = build_passive_app(workspace_root=tmp_path, env_path=env_path, client=FakeClient())

    assert app.tool_registry is not None
    assert sorted(app.tool_registry.names()) == ["fetch_messages", "read_file", "search_messages"]
```

- [ ] **Step 2: Run the failing bootstrap test**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_bootstrap_tool_runtime.py -q
```

Expected: FAIL because `PassiveApp` does not expose `tool_registry`.

- [ ] **Step 3: Wire the registry and executor into bootstrap**

Update `amadeus/bootstrap.py`:

```python
from amadeus.tools.defaults import FetchMessagesTool, ReadFileTool, SearchMessagesTool
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.hooks import ReadOnlyFilesystemHook
from amadeus.tools.registry import ToolRegistry
```

Extend `PassiveApp`:

```python
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
```

Inside `build_passive_app(...)`, after `session_manager = SessionManager(...)`:

```python
    tool_registry = ToolRegistry()
    tool_registry.register(FetchMessagesTool(store=session_manager.store))
    tool_registry.register(SearchMessagesTool(store=session_manager.store))
    tool_registry.register(ReadFileTool())
    tool_executor = ToolExecutor(
        registry=tool_registry,
        hooks=[ReadOnlyFilesystemHook(workspace_root=config.workspace_root)],
    )
```

Return them in `PassiveApp(...)`:

```python
        tool_registry=tool_registry,
        tool_executor=tool_executor,
```

- [ ] **Step 4: Run the bootstrap test**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_bootstrap_tool_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add amadeus/bootstrap.py tests/test_bootstrap_tool_runtime.py
git commit -m "feat: expose read-only tool runtime from bootstrap"
```

## Task 6: End-to-End Verification and Boundary Audit

**Files:**
- Modify: `docs/superpowers/plans/2026-06-11-tool-runtime-v1.md`
  - Mark completed steps during execution only.

- [ ] **Step 1: Run the focused tool-runtime suite**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_tool_registry.py tests/test_tool_executor.py tests/test_readonly_tools.py tests/test_bootstrap_tool_runtime.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the existing regression suite that should stay stable**

Run:

```bash
$env:TEMP=(Resolve-Path '.pytest_tmp').Path; $env:TMP=$env:TEMP; uv run --extra dev pytest tests/test_runtime.py tests/test_session_memory_runtime.py tests/test_runtime_vector_memory.py tests/test_bootstrap.py tests/test_bootstrap_vector_memory.py -q
```

Expected: PASS. No retrieval or passive-runtime regressions.

- [ ] **Step 3: Review architecture boundaries before moving to passive loop**

Manual checklist:

```text
- PassiveRuntime still does single-shot chat only.
- No tool-call orchestration was added to provider or runtime.
- ToolRegistry owns schemas and lookup only.
- ToolExecutor owns hooks and failure normalization.
- Read-only tools contain no embedded safety policy except basic type conversion.
- Filesystem path safety lives in hook code, not in ReadFileTool itself.
```

- [ ] **Step 4: Commit the verification pass**

Run:

```bash
git add amadeus/tools amadeus/bootstrap.py tests/test_tool_registry.py tests/test_tool_executor.py tests/test_readonly_tools.py tests/test_bootstrap_tool_runtime.py
git commit -m "test: verify tool runtime v1 boundaries"
```

## Self-Review

- Spec coverage: this plan covers the next intended stage from the migration roadmap, namely Tool Runtime with read-only tools, schema export, executor hooks, and bootstrap exposure. It intentionally excludes passive loop, plugin lifecycle, shell writes, and proactive work.
- Placeholder scan: no `TODO`, `TBD`, or unresolved file references remain.
- Type consistency: `ToolExecutionRequest`, `ToolResult`, `ToolTrace`, `ToolRegistry`, and `ToolExecutor` are introduced before later tasks depend on them; bootstrap wiring reuses the same names.

## What You Should Learn While Executing

1. `Tool` is a model-facing contract, not just a Python helper function.
2. `ToolRegistry` and `ToolExecutor` split “what exists” from “how it runs”.
3. Hook systems are how you keep safety policy centralized and composable.
4. A stable tool runtime is the prerequisite for a clean passive-loop migration.

