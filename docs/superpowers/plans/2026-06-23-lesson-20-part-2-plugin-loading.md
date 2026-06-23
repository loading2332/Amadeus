# Lesson 20 Part 2 Plugin Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Amadeus 中完成官方/用户插件的发现、配置、注入、优先级绑定、原子清理与应用启停，并用真实 passive turn 证明插件效果进入 provider prompt。

**Architecture:** 保持 `PluginRegistry` 只保存 import 副作用产生的声明状态，`PluginManager` 编排一个候选插件的加载事务，`PluginContext` 承载宿主注入依赖，`PassiveApp` 管理异步 start/aclose。官方目录先于 workspace 用户目录；单插件失败产生结构化报告并完整回滚，但不阻止其他插件加载。

**Tech Stack:** Python 3.11、asyncio、PyYAML、pytest、ruff、mypy、现有 Amadeus EventBus/Lifecycle/PassiveRuntime。

> **执行状态摘要（权威，2026-06-23）：** Tasks 1–6 已完成；Task 7 的实现产物、正式 Teach 0018 Part 2 artifact、结构验证、全量测试与静态质量门也已完成并进入当前 `main` commit chain。Task 7 的最终代码精读、用户复述 gate 与 Lesson 20 learning record 仍待完成；在用户证明理解前，不得标记 retell 完成、创建 learning record 或进入 Lesson 21。下文逐步 checkbox 保留为经批准的执行 checklist 与历史操作说明，未逐项回填不代表权威进度；如与本摘要冲突，以本摘要为准。

---

## Scope and working-tree guard

本计划在项目协议指定的 `main` 分支执行，不创建额外 worktree。当前工作树已经包含 Lesson 20 Part 1 和 Plugin 第一版未提交文件；实现时必须逐文件修订并只暂存当前 Task 的文件，不能使用 `git add .`，不能覆盖用户已有注释。

明确不进入本计划：

- `requires / produces / slots`
- prompt section plugin
- tool decorator / tool hook
- PluginKVStore 并发与崩溃原子写
- plugin allowlist / signature / sandbox
- channel bot 和长期运行 `App.run()`

## File responsibility map

- `amadeus/plugin/base.py`：Plugin 基类和 class 注册入口。
- `amadeus/plugin/config.py`：只读式 PluginConfig 值包装。
- `amadeus/plugin/context.py`：PluginContext 与 PluginKVStore。
- `amadeus/plugin/types.py`：PluginCandidate、发现记录、加载状态和 PluginLoadReport。
- `amadeus/plugin/registry.py`：handler metadata、每 module 的 class 列表、instance。
- `amadeus/plugin/decorators.py`：三个 Lesson 19 Lifecycle decorator。
- `amadeus/plugin/manager.py`：discovery、配置、加载事务、binding ledger、cleanup。
- `amadeus/plugin/__init__.py`：稳定公共导出。
- `amadeus/events.py`：带 priority 的注册和精确 off。
- `amadeus/bootstrap.py`：官方/用户目录装配和 PassiveApp 生命周期。
- `amadeus/workspace.py`：初始化用户 `plugins/` 目录。
- `amadeus/cli.py`：临时 CLI 显式 start/aclose。
- `amadeus/builtin_plugins/__init__.py`：可打包的官方插件目录占位，不放假插件。
- `tests/test_plugin_config.py`：PluginConfig、Context、KV 单元合同。
- `tests/test_events.py`：EventBus priority/off 回归。
- `tests/test_plugin_manager.py`：discovery、配置、identity、事务和报告。
- `tests/test_bootstrap.py`：App 生命周期与真实 passive turn。
- `tests/fixtures/plugins/`：仅测试边界使用的插件模块和配置文件。
- `pyproject.toml`、`uv.lock`：PyYAML 运行依赖。
- `lessons/0018-lesson-20-plugin-registry-loader-config-part-2.html`：实现后正式课程和 gap audit。

---

### Task 1: Establish PluginConfig, PluginContext, and PluginKVStore contracts

**Files:**
- Create: `amadeus/plugin/config.py`
- Create: `amadeus/plugin/context.py`
- Modify: `amadeus/plugin/base.py`
- Modify: `amadeus/plugin/__init__.py`
- Create: `tests/test_plugin_config.py`

- [ ] **Step 1: Write failing tests for config absence, defensive copies, attribute access, dependency injection, and KV persistence**

Create tests with these concrete assertions:

```python
from pathlib import Path

import pytest

from amadeus.plugin import PluginConfig, PluginContext, PluginKVStore


def test_plugin_config_supports_get_attribute_and_defensive_copy() -> None:
    original = {"api_key": "secret", "max_results": 10}
    config = PluginConfig(original)
    original["api_key"] = "mutated"

    assert config.api_key == "secret"
    assert config.get("max_results") == 10
    assert config.get("missing", "fallback") == "fallback"
    copied = config.as_dict()
    copied["api_key"] = "changed"
    assert config.api_key == "secret"


def test_plugin_config_missing_attribute_raises_attribute_error() -> None:
    config = PluginConfig({})
    with pytest.raises(AttributeError, match="missing"):
        _ = config.missing


def test_plugin_kv_store_persists_values_across_instances(tmp_path: Path) -> None:
    path = tmp_path / ".kv.json"
    first = PluginKVStore(path)
    assert first.get("turn_count", 0) == 0
    assert first.increment("turn_count") == 1
    first.set("last_session", "cli:default")

    second = PluginKVStore(path)
    assert second.get("turn_count") == 1
    assert second.get("last_session") == "cli:default"
```

- [ ] **Step 2: Run the new tests and verify the contract is absent**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_plugin_config.py -q
```

Expected: collection fails because `PluginConfig` and `PluginKVStore` are not exported.

- [ ] **Step 3: Implement the focused config and context modules**

Implement `PluginConfig` with a private copied dictionary:

```python
from __future__ import annotations

from typing import Any


class PluginConfig:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = dict(values)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)

    def __getattr__(self, key: str) -> Any:
        try:
            return self._values[key]
        except KeyError as error:
            raise AttributeError(key) from error
```

Move Context out of `base.py` and define typed dependencies plus KVStore in `context.py`. The implementation must use `Path`, UTF-8, `ensure_ascii=False`, and a fresh read before every mutation:

```python
@dataclass
class PluginContext:
    event_bus: EventBus
    tool_registry: ToolRegistry
    plugin_id: str
    plugin_dir: Path
    kv_store: PluginKVStore
    config: PluginConfig | None = None
    workspace: Path | None = None
    session_manager: SessionManager | None = None
    memory_engine: MemoryEngine | None = None
```

`PluginKVStore._read()` returns `{}` for a missing file and rejects non-object JSON with `ValueError`. `_write()` creates the parent directory and writes indented JSON. Do not add locks or temporary-file replacement in this lesson.

Update `Plugin` to annotate `context: PluginContext` and keep `__init_subclass__()` registration. Export `PluginConfig`, `PluginContext`, and `PluginKVStore` from `amadeus.plugin`.

- [ ] **Step 4: Run focused tests and static checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_plugin_config.py -q
.\.venv\Scripts\ruff.exe check amadeus/plugin tests/test_plugin_config.py
.\.venv\Scripts\mypy.exe amadeus/plugin tests/test_plugin_config.py
```

Expected: all commands pass.

- [ ] **Step 5: Commit only the contract files**

```powershell
git add -- amadeus/plugin/base.py amadeus/plugin/config.py amadeus/plugin/context.py amadeus/plugin/__init__.py tests/test_plugin_config.py
git commit -m "feat: define plugin context and config contracts"
```

---

### Task 2: Add priority ordering and exact unsubscription to EventBus

**Files:**
- Modify: `amadeus/events.py`
- Create: `tests/test_events.py`
- Test: `tests/test_lifecycle.py`

- [ ] **Step 1: Write failing EventBus tests**

Add tests proving cross-handler ordering and exact removal:

```python
import asyncio
from dataclasses import dataclass

from amadeus.events import EventBus


@dataclass
class OrderedEvent:
    calls: list[str]


def test_event_bus_runs_higher_priority_first_and_keeps_stable_ties() -> None:
    bus = EventBus()

    def low(event: OrderedEvent) -> None:
        event.calls.append("low")

    def high_first(event: OrderedEvent) -> None:
        event.calls.append("high-first")

    def high_second(event: OrderedEvent) -> None:
        event.calls.append("high-second")

    bus.on(OrderedEvent, low, priority=0)
    bus.on(OrderedEvent, high_first, priority=100)
    bus.on(OrderedEvent, high_second, priority=100)

    result = asyncio.run(bus.emit(OrderedEvent(calls=[])))
    assert result.calls == ["high-first", "high-second", "low"]


def test_event_bus_off_removes_only_exact_handler() -> None:
    bus = EventBus()
    calls: list[str] = []

    def first(event: OrderedEvent) -> None:
        calls.append("first")

    def second(event: OrderedEvent) -> None:
        calls.append("second")

    bus.on(OrderedEvent, first)
    bus.on(OrderedEvent, second)
    bus.off(OrderedEvent, first)
    bus.off(OrderedEvent, first)
    asyncio.run(bus.emit(OrderedEvent(calls=[])))

    assert calls == ["second"]
```

- [ ] **Step 2: Run tests and verify the new keyword/off API fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_events.py -q
```

Expected: failures mention unexpected `priority` and missing `off`.

- [ ] **Step 3: Store ordered registrations instead of bare callables**

Add a private registration record containing `handler`, `priority`, and monotonically increasing `order`. `on()` appends and sorts with:

```python
handlers.sort(key=lambda item: (-item.priority, item.order))
```

Implement exact identity removal:

```python
def off(self, event_type: type[E], handler: EventHandler[E]) -> None:
    key = cast(type[object], event_type)
    handlers = self._handlers.get(key)
    if handlers is None:
        return
    self._handlers[key] = [item for item in handlers if item.handler is not handler]
    if not self._handlers[key]:
        self._handlers.pop(key, None)
```

Update `emit()` and `fanout()` to consume a snapshot of registrations and invoke `item.handler`. Keep Gate replacement and Tap exception isolation unchanged.

- [ ] **Step 4: Run EventBus and Lifecycle regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_events.py tests/test_lifecycle.py -q
```

Expected: priority/off tests pass and all Lesson 19 tests remain green.

- [ ] **Step 5: Commit the EventBus boundary**

```powershell
git add -- amadeus/events.py tests/test_events.py
git commit -m "feat: support ordered event subscriptions"
```

---

### Task 3: Make Registry and load-report types explicit

**Files:**
- Create: `amadeus/plugin/types.py`
- Modify: `amadeus/plugin/registry.py`
- Modify: `amadeus/plugin/decorators.py`
- Modify: `amadeus/plugin/__init__.py`
- Modify: `tests/test_plugin_manager.py`

- [ ] **Step 1: Write failing unit tests for class cardinality storage and report records**

Test Registry without invoking Manager, so this task establishes only the declaration-state contract:

```python
from amadeus.plugin import (
    PluginLoadRecord,
    PluginLoadReport,
    PluginLoadStatus,
    PluginRegistry,
)


def test_registry_preserves_every_class_registered_by_one_module() -> None:
    registry = PluginRegistry()
    first = type("First", (), {"__module__": "test_plugin_module"})
    second = type("Second", (), {"__module__": "test_plugin_module"})

    registry.register_class(first)
    registry.register_class(second)

    assert registry.get_classes("test_plugin_module") == [first, second]
    assert registry.class_count("test_plugin_module") == 2


def test_load_report_filters_records_by_status() -> None:
    loaded = PluginLoadRecord(
        name="hello",
        source="workspace",
        import_path="amadeus_plugin_workspace_hello",
        status=PluginLoadStatus.LOADED,
    )
    failed = PluginLoadRecord(
        name="broken",
        source="workspace",
        import_path="amadeus_plugin_workspace_broken",
        status=PluginLoadStatus.FAILED,
        stage="initialize",
        message="initialize failed",
    )
    report = PluginLoadReport(records=(loaded, failed))

    assert report.loaded == (loaded,)
    assert report.failed == (failed,)
    assert report.disabled == ()
    assert report.duplicate == ()
    assert report.already_loaded == ()
```

Add a pure report test proving secrets are not part of record repr/message.

- [ ] **Step 2: Run the cardinality test and verify current last-class-wins behavior fails it**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_plugin_manager.py -k "registry_preserves or load_report" -q
```

Expected: collection or assertions fail because report types/class-list accessors do not exist and current Registry overwrites a class.

- [ ] **Step 3: Define typed candidate and report records**

Create these stable shapes in `types.py`:

```python
class PluginLoadStatus(str, Enum):
    LOADED = "loaded"
    DISABLED = "disabled"
    DUPLICATE = "duplicate"
    ALREADY_LOADED = "already_loaded"
    FAILED = "failed"


@dataclass(frozen=True)
class PluginCandidate:
    name: str
    source: str
    plugin_dir: Path
    module_path: Path
    import_path: str


@dataclass(frozen=True)
class PluginLoadRecord:
    name: str
    source: str
    import_path: str
    status: PluginLoadStatus
    stage: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class PluginDiscoveryResult:
    candidates: tuple[PluginCandidate, ...]
    records: tuple[PluginLoadRecord, ...]


@dataclass(frozen=True)
class PluginLoadReport:
    records: tuple[PluginLoadRecord, ...]

    @property
    def loaded(self) -> tuple[PluginLoadRecord, ...]:
        return tuple(record for record in self.records if record.status is PluginLoadStatus.LOADED)

    @property
    def failed(self) -> tuple[PluginLoadRecord, ...]:
        return tuple(record for record in self.records if record.status is PluginLoadStatus.FAILED)

    @property
    def disabled(self) -> tuple[PluginLoadRecord, ...]:
        return tuple(record for record in self.records if record.status is PluginLoadStatus.DISABLED)

    @property
    def duplicate(self) -> tuple[PluginLoadRecord, ...]:
        return tuple(record for record in self.records if record.status is PluginLoadStatus.DUPLICATE)

    @property
    def already_loaded(self) -> tuple[PluginLoadRecord, ...]:
        return tuple(record for record in self.records if record.status is PluginLoadStatus.ALREADY_LOADED)
```

- [ ] **Step 4: Preserve all class registrations per import path**

Change Registry class storage to `dict[str, list[type]]`. `register_class()` appends, `get_classes()` returns a copy, `class_count()` returns an int, and `remove_plugin()` removes the whole list. Keep handler lookup/removal by exact module path.

Restore Akashic priority intent in `PluginHandlerRegistry.append()`:

```python
self._handlers.append(metadata)
self._handlers.sort(key=lambda item: -item.priority)
```

Export report types through `amadeus.plugin`.

- [ ] **Step 5: Run Registry-focused tests and static checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_plugin_manager.py -k "class or registry or report" -q
.\.venv\Scripts\ruff.exe check amadeus/plugin tests/test_plugin_manager.py
.\.venv\Scripts\mypy.exe amadeus/plugin tests/test_plugin_manager.py
```

Expected: focused tests and both static checks pass.

- [ ] **Step 6: Commit Registry and report contracts**

```powershell
git add -- amadeus/plugin/types.py amadeus/plugin/registry.py amadeus/plugin/decorators.py amadeus/plugin/__init__.py tests/test_plugin_manager.py
git commit -m "feat: define plugin registry and load reports"
```

---

### Task 4: Implement aligned discovery, config loading, and atomic PluginManager transactions

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `amadeus/plugin/manager.py`
- Modify: `tests/test_plugin_manager.py`
- Modify/Create: `tests/fixtures/plugins/**`

- [ ] **Step 1: Add PyYAML as a runtime dependency**

Change project dependencies to include `PyYAML>=6.0`, then update the lockfile with the project package manager:

```powershell
uv lock
```

Run:

```powershell
.\.venv\Scripts\python.exe -c "import yaml; print(yaml.__version__)"
```

Expected: a PyYAML version is printed.

- [ ] **Step 2: Replace fixtures with the approved Akashic contracts and add failure fixtures**

Use `plugin.disabled`, not `.disabled`. Change `_conf_schema.json` to top-level fields:

```json
{
  "greeting": {"type": "string", "default": "Hi there"},
  "volume": {"type": "integer", "default": 5}
}
```

Add a manifested fixture:

```yaml
name: manifest_name
version: 0.2.0
desc: from manifest
author: tester
```

Add separate fixtures whose import, constructor, initialize, and terminate paths fail. Exercise bind failure with a test-only `FailingEventBus` whose `on()` raises `RuntimeError("bind failed")`; this isolates the host boundary without creating an invalid production plugin contract. A fixture or failing bus may be a test double because it isolates failure behavior; no such fake enters production architecture.

Also add `noclass/plugin.py` with no Plugin subclass and `multiclass/plugin.py` with exactly two Plugin subclasses so Manager can enforce the cardinality contract established in Task 3.

- [ ] **Step 3: Write failing tests for discovery, config degradation, identity, priority, report statuses, and cleanup**

Tests must prove:

```python
assert [candidate.source for candidate in discovery.candidates][:1] == ["builtin"]
assert duplicate_record.status is PluginLoadStatus.DUPLICATE
assert disabled_record.status is PluginLoadStatus.DISABLED
assert manifested.context.plugin_id == "manifest_name"
assert configured.context.config is not None
assert configured.context.config.greeting == "G'day"
assert unconfigured.context.config is None
assert high_priority_effect_precedes_low_priority_effect
assert failed_import_path not in sys.modules
assert plugin_registry.get_instance(failed_import_path) is None
```

After initialize failure, emit a real `BeforeTurnContext` and assert the failed handler does not run. After `terminate_all()`, emit again and assert no plugin handler runs. Add plugin_id collision coverage using different directory names with the same manifest `name`.

- [ ] **Step 4: Run the expanded manager suite and verify failures match the missing contracts**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_plugin_manager.py -q
```

Expected: failures cover manifest, top-level schema, report, priority, class count, plugin_id uniqueness, EventBus cleanup, and module cleanup.

- [ ] **Step 5: Implement discovery without import side effects**

`PluginManager.__init__()` receives explicit dependencies and ordered `(source, Path)` plugin roots. `discover()` returns candidates plus duplicate records. Use a deterministic import path derived from source and directory name; sanitize non-identifier characters to `_`.

The discovery loop must not read manifest or import modules. It checks only directory shape and `plugin.py`. The second `plugin.disabled` check occurs immediately before import so a file created after discovery still prevents execution.

- [ ] **Step 6: Implement fail-open manifest and config helpers**

Use `yaml.safe_load()`. Catch parse/read exceptions locally and log without config values. `_load_plugin_config()` behavior must be:

```python
if not schema_path.exists():
    return None

try:
    loaded_schema = json.loads(schema_path.read_text(encoding="utf-8"))
except Exception as error:
    logger.warning("_conf_schema.json 读取失败 (%s): %s", plugin_dir, error)
    return None

if not isinstance(loaded_schema, dict):
    logger.warning("_conf_schema.json 格式错误，期望 dict (%s)", plugin_dir)
    return None
```

Extract top-level defaults. If override parsing fails, retain defaults. Return `PluginConfig(values)` whenever schema is a valid object, including an empty object.

- [ ] **Step 7: Implement one-plugin transaction and common cleanup**

Track the current stage (`import`, `register`, `instantiate`, `manifest`, `identity`, `config`, `bind`, `initialize`) so `PluginLoadRecord` identifies failure location. Save the exact bound partials returned by `_bind_handlers()`:

```python
for context_type, bound, priority in bindings:
    self._event_bus.on(context_type, bound, priority=priority)
self._bindings[import_path] = [
    (context_type, bound)
    for context_type, bound, _priority in bindings
]
```

Only after initialize succeeds:

```python
self._loaded.add(import_path)
self._plugin_ids[plugin_id] = import_path
```

Common cleanup must:

```python
if instance is not None:
    try:
        await instance.terminate()
    except Exception:
        logger.exception("插件 terminate 失败: %s", import_path)

for event_type, handler in reversed(self._bindings.pop(import_path, [])):
    self._event_bus.off(event_type, handler)

plugin_registry.remove_plugin(import_path)
for module_name in tuple(sys.modules):
    if module_name == import_path or module_name.startswith(f"{import_path}."):
        sys.modules.pop(module_name, None)
self._loaded.discard(import_path)
```

Remove plugin_id ownership only when it points to the same import path. `terminate_all()` iterates loaded import paths in reverse load order and reuses this cleanup.

- [ ] **Step 8: Run manager tests, then prove idempotent reload and no ghost handler**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_plugin_manager.py -q
```

Expected: all manager tests pass. The second `load_all()` report contains `already_loaded`; after cleanup, a fresh load initializes exactly once and binds exactly one handler.

- [ ] **Step 9: Commit the complete Manager transaction**

```powershell
git add -- pyproject.toml uv.lock amadeus/plugin/manager.py tests/test_plugin_manager.py tests/fixtures/plugins
git commit -m "feat: load plugins with atomic cleanup"
```

---

### Task 5: Wire official/user plugins into PassiveApp lifecycle

**Files:**
- Create: `amadeus/builtin_plugins/__init__.py`
- Modify: `amadeus/workspace.py`
- Modify: `amadeus/bootstrap.py`
- Modify: `amadeus/cli.py`
- Modify: `tests/test_workspace.py`
- Modify: `tests/test_bootstrap.py`

- [ ] **Step 1: Write failing workspace and App lifecycle tests**

Add workspace assertion:

```python
def test_initialize_workspace_creates_user_plugin_directory(tmp_path) -> None:
    initialize_workspace(tmp_path)
    assert (tmp_path / "plugins").is_dir()
```

Add async bootstrap tests proving:

- build leaves App in NEW and no plugin instance exists.
- start loads from builtin before workspace.
- sequential and `asyncio.gather()` duplicate start initialize once.
- sequential and concurrent duplicate aclose terminate/close once.
- CLOSED + start raises a clear RuntimeError.

- [ ] **Step 2: Run lifecycle tests and verify PassiveApp lacks the contract**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workspace.py tests/test_bootstrap.py -q
```

Expected: failures mention missing user plugin directory, PluginManager field, start, and aclose.

- [ ] **Step 3: Add packaged official plugin namespace and workspace directory creation**

Create an empty documented `amadeus/builtin_plugins/__init__.py`. Do not add a sample plugin. Update workspace initialization to create `<workspace_root>/plugins` alongside memory directories.

- [ ] **Step 4: Implement PassiveApp state machine under one asyncio.Lock**

Define:

```python
class AppState(str, Enum):
    NEW = "new"
    STARTED = "started"
    CLOSED = "closed"
```

Add `plugin_manager`, `_state`, `_lifecycle_lock`, and `_plugin_report` fields. `start()` returns the saved report on repeated calls. `aclose()` calls `terminate_all()` before closing the Session Store and sets CLOSED in a `finally` path. CLOSED cannot restart.

Build the Manager with ordered roots:

```python
plugin_roots = [
    ("builtin", Path(__file__).resolve().parent / "builtin_plugins"),
    ("workspace", config.workspace_root / "plugins"),
]
```

Inject the exact EventBus, ToolRegistry, workspace, SessionManager, and MemoryEngine instances already built by bootstrap.

- [ ] **Step 5: Update the temporary CLI adapter**

Replace synchronous close with explicit lifecycle:

```python
app = build_passive_app(
    workspace_root=args.workspace_root,
    env_path=args.env,
)
await app.start()
try:
    result = await app.runtime.run_turn(
        session_key=session_key,
        user_message=args.message,
        retrieved_memory=args.retrieved_memory,
        active_skills=args.skill,
    )
finally:
    await app.aclose()
```

Keep CLI as a one-turn development adapter; do not add `PassiveApp.run_turn()`.

- [ ] **Step 6: Run workspace/bootstrap tests and commit lifecycle wiring**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workspace.py tests/test_bootstrap.py -q
```

Expected: all tests pass.

Commit:

```powershell
git add -- amadeus/builtin_plugins/__init__.py amadeus/workspace.py amadeus/bootstrap.py amadeus/cli.py tests/test_workspace.py tests/test_bootstrap.py
git commit -m "feat: start plugins with passive app"
```

---

### Task 6: Prove the complete user-plugin-to-provider path

**Files:**
- Modify: `tests/test_bootstrap.py`
- Modify/Create: `tests/fixtures/plugins/prompt_marker/plugin.py`
- Test: `tests/test_runtime.py`
- Test: `tests/test_plugin_manager.py`

- [ ] **Step 1: Add an end-to-end user plugin fixture**

The fixture uses only the formal decorator and modifies real `runtime_metadata`:

```python
from amadeus.plugin import Plugin, on_before_turn


class PromptMarker(Plugin):
    name = "prompt_marker"

    @on_before_turn(priority=50)
    async def mark_prompt(self, context):
        context.runtime_metadata["plugin_marker"] = "loaded through PassiveApp.start"
        return context
```

- [ ] **Step 2: Write the end-to-end test before implementation adjustments**

Copy the fixture to `<tmp_path>/plugins/prompt_marker/plugin.py`, build with the existing fake OpenAI client, call `await app.start()`, run one real turn, and inspect `client.completions.calls[0]["messages"]`:

```python
rendered_text = "\n".join(
    str(message["content"])
    for message in client.completions.calls[0]["messages"]
)
assert "loaded through PassiveApp.start" in rendered_text
assert [record.name for record in report.loaded] == ["prompt_marker"]
```

After `await app.aclose()`, emit a new `BeforeTurnContext` through the same EventBus and assert no `plugin_marker` is added.

- [ ] **Step 3: Run the end-to-end test and fix only real integration mismatches**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_bootstrap.py -k "user_plugin_reaches_provider_prompt" -q
```

Expected: PASS after bootstrap, binding, Context rendering, and cleanup agree. Do not insert a production-only prompt helper or hard-coded marker to make this test pass.

- [ ] **Step 4: Run the complete behavioral suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_plugin_config.py tests/test_events.py tests/test_plugin_manager.py tests/test_lifecycle.py tests/test_bootstrap.py tests/test_runtime.py -q
```

Expected: all focused and adjacent runtime tests pass.

- [ ] **Step 5: Commit the acceptance slice**

```powershell
git add -- tests/test_bootstrap.py tests/fixtures/plugins/prompt_marker/plugin.py
git commit -m "test: verify plugin passive turn integration"
```

---

### Task 7: Full quality gate, Part 2 lesson, and gap audit

**Files:**
- Modify: `assets/lesson.css` only if the existing uncommitted responsive fix is required by the rendered Part 2 page
- Create: `lessons/0018-lesson-20-plugin-registry-loader-config-part-2.html`
- Modify: `NOTES.md` only if a new durable teaching preference was discovered; otherwise leave it unchanged
- Do not create: `learning-records/0009-*.md` until the user completes the Lesson 20 retell gate

- [ ] **Step 1: Run full tests and static analysis**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check amadeus tests dev_utils
.\.venv\Scripts\mypy.exe amadeus tests dev_utils
```

Expected: all commands exit 0. Record exact test counts and relevant CLI output for the lesson; do not write “all passed” without evidence.

- [ ] **Step 2: Perform the manual one-turn smoke path**

Using a temporary workspace and safe fake provider boundary, execute the same order as CLI:

```text
build_passive_app
→ await app.start
→ inspect PluginLoadReport
→ await app.runtime.run_turn
→ inspect provider prompt marker
→ await app.aclose
→ verify handler no longer fires
```

Document what output is normal and what each abnormal result means.

- [ ] **Step 3: Create the formal Part 2 lesson HTML**

Create `0018` using existing `assets/lesson.css` and `assets/python-highlight.js`. It must contain:

- 本课目标与 `MISSION.md` 关系。
- 当前阶段地图。
- Part 1 Akashic chain recap。
- Part 2 Amadeus implementation chain。
- concrete code locations and call path。
- config vs KV 对照。
- EventBus shared ownership and priority。
- load transaction/rollback diagram。
- exact test and smoke evidence。
- common mistakes and troubleshooting。
- Akashic gap audit and intentional Amadeus deviations。
- resume-ready explanation。
- required retell questions。
- prompt inviting follow-up questions。

The Part 2 lesson must explicitly record:

```text
PluginKVStore concurrency/atomic-write gap
→ Lesson 23
→ concurrent increment, valid JSON after failed write, per-plugin isolation
```

It must also record signature/allowlist/sandbox in Lesson 40 safety audit.

- [ ] **Step 4: Validate the lesson artifact**

Check local links and required headings:

```powershell
rg -n "MISSION|Part 1|Part 2|Akashic|Amadeus|验证|必须复述|Gap Audit|简历" lessons/0018-lesson-20-plugin-registry-loader-config-part-2.html
```

Open the HTML locally, inspect desktop and narrow/mobile layouts, and verify Python syntax highlighting works without network access.

- [ ] **Step 5: Commit code-quality and lesson artifacts without creating a learning record**

Stage only files that belong to Lesson 20. Include `assets/lesson.css` only after reviewing its existing change and confirming the Part 2 page needs it:

```powershell
git add -- lessons/0018-lesson-20-plugin-registry-loader-config-part-2.html
git commit -m "docs: teach lesson 20 plugin loading part 2"
```

- [ ] **Step 6: Conduct code reading and retell gate**

Walk the user through the actual chain:

```text
PassiveApp.start
→ PluginManager.load_all
→ discover/import/register
→ manifest/config/context
→ bind/initialize/commit
→ PassiveRuntime.run_turn
→ BeforeTurnContext
→ provider prompt
→ PassiveApp.aclose
→ terminate/off/registry/sys.modules cleanup
```

Require the user to explain:

1. Registry and Manager ownership.
2. Why import path and plugin_id are different identities.
3. Config and KV semantics.
4. Why loaded commits only after initialize.
5. Which cleanup is host-managed and which is plugin-owned.
6. Why priority must be enforced by EventBus, not only Registry sorting.
7. How App lifecycle prepares for future channel bots.

Only after the user can explain these responsibilities should a new Lesson 20 learning record be created and Lesson 21 begin.

---

## Final requirement audit

Before declaring implementation complete, verify each approved decision against current evidence:

- PyYAML manifest contract implemented.
- top-level `_conf_schema.json` implemented; no `properties` compatibility layer.
- `PluginConfig | None` implemented.
- config parse fail-open and executable chain fail-closed.
- `plugin.disabled` only.
- import path internal identity and unique plugin_id.
- official-first plus workspace user plugins.
- complete PluginContext and simple PluginKVStore.
- per-plugin failure isolation and safe structured report.
- exact-one Plugin class.
- cross-plugin priority and stable ties.
- common cleanup for failure and normal close.
- decorator handlers host-owned; manual EventBus subscriptions plugin-owned.
- sequential and concurrent App lifecycle idempotency.
- CLI remains a temporary adapter; no `PassiveApp.run_turn()`.
- real user plugin effect reaches provider prompt.
- Lesson 23 and Lesson 40 gaps have concrete validation destinations.
- no fake/stub production mechanism introduced.
