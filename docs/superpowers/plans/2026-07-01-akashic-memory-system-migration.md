# Akashic Memory System Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Amadeus 现有 phase2 过渡态 memory 重构为 Akashic 风格主链路，完成 `long_term_memory.db`、`memorizer`、`retriever`、`post-response worker` 与新 memory tool contract 的落地。

**Architecture:** 这次不是在旧 `AkashicMemoryEngine` 上叠加逻辑，而是原地拆分出 `store / memorizer / retriever / post_response_worker / engine-owned tools`。`MarkdownMemoryStore` 保留人类可读审计职责，长期语义检索真源迁移到 `memory/long_term_memory.db`，`before_turn` 和 `after_turn` 通过新 `MemoryEngine` 高层接口接入。

**Tech Stack:** Python 3.12、SQLite、pytest、现有 PassiveRuntime/EventBus/ToolRegistry、OpenAI embeddings provider

---

## File Map

### New files

- `amadeus/memory/store.py`
- `amadeus/memory/retriever.py`
- `amadeus/memory/memorizer.py`
- `amadeus/memory/post_response_worker.py`
- `amadeus/tools/memorize.py`
- `amadeus/tools/undo_memory_by_source.py`
- `tests/memory/test_memory_store.py`
- `tests/memory/test_memory_memorizer.py`
- `tests/memory/test_memory_retriever.py`
- `tests/memory/test_memory_post_response_worker.py`
- `tests/tools/test_memorize_tool.py`
- `tests/tools/test_undo_memory_by_source_tool.py`

### Primary modified files

- `amadeus/memory/engine.py`
- `amadeus/memory/__init__.py`
- `amadeus/memory/markdown.py`
- `amadeus/memory/vector.py`
- `amadeus/runtime/before_turn.py`
- `amadeus/runtime/after_turn.py`
- `amadeus/runtime/passive.py`
- `amadeus/app/bootstrap.py`
- `amadeus/tools/recall_memory.py`
- `amadeus/tools/forget_memory.py`
- `amadeus/prompts/personality_rules.py`
- `tests/memory/test_bootstrap_long_term_memory.py`
- `tests/memory/test_memory_retrieval_acceptance.py`
- `tests/runtime/test_before_turn.py`
- `tests/app/test_bootstrap.py`
- `tests/app/test_bootstrap_tool_runtime.py`

### Removed files

- `amadeus/tools/correct_memory.py`

## Resume Claims And Proof Targets

- Claim: `Akashic-inspired memory system with retrieval, source references, correction, and forgetting`
  - Public proof: `recall_memory / memorize / forget_memory / undo_memory_by_source`
  - Verification: memory acceptance tests + passive runtime smoke
- Claim: `passive agent runtime that can run real LLM turns`
  - Public proof: `before_turn` 自动注入长期记忆，`after_turn` 自动触发 post-response worker
  - Verification: runtime/bootstrap integration tests

## Task 1: Redefine Memory Protocol And Bootstrap Contract

**Files:**
- Modify: `amadeus/memory/engine.py`
- Modify: `amadeus/memory/__init__.py`
- Modify: `amadeus/app/bootstrap.py`
- Modify: `tests/memory/test_bootstrap_long_term_memory.py`
- Modify: `tests/app/test_bootstrap.py`

- [ ] **Step 1: Write the failing bootstrap and protocol tests**

```python
from amadeus.app.bootstrap import load_runtime_config


def test_memory_runtime_config_can_target_memory2_db(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_LONG_TERM_MEMORY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    config = load_runtime_config(workspace_root=tmp_path)

    assert config.long_term_memory_enabled is True
    assert config.long_term_memory_db_path == tmp_path / "memory" / "long_term_memory.db"
```

```python
def test_build_passive_app_registers_memory_tools_without_correct_memory(tmp_path):
    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=_env_path(tmp_path),
        client=FakeClient(),
    )

    tool_names = set(app.tool_registry.names())

    assert "recall_memory" in tool_names
    assert "memorize" in tool_names
    assert "forget_memory" in tool_names
    assert "undo_memory_by_source" in tool_names
    assert "correct_memory" not in tool_names
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```powershell
pytest tests/memory/test_bootstrap_long_term_memory.py tests/app/test_bootstrap.py -k "memory2_db or memory_tools_without_correct_memory" -v
```

Expected:

```text
FAILED tests/memory/test_bootstrap_long_term_memory.py::test_memory_runtime_config_can_target_memory2_db
FAILED tests/app/test_bootstrap.py::test_build_passive_app_registers_memory_tools_without_correct_memory
```

- [ ] **Step 3: Redefine the memory protocol types in `amadeus/memory/engine.py`**

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class MemoryScope:
    channel: str | None = None
    chat_id: str | None = None


@dataclass(frozen=True)
class MemoryRecallRequest:
    text: str
    intent: str = "answer"
    memory_types: tuple[str, ...] = ()
    limit: int = 8
    time_start: datetime | None = None
    time_end: datetime | None = None
    scope: MemoryScope = field(default_factory=MemoryScope)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryWriteRequest:
    summary: str
    memory_type: str
    source_ref: str
    happened_at: str | None = None
    scope: MemoryScope = field(default_factory=MemoryScope)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryContextResult:
    text: str
    injected_ids: list[str] = field(default_factory=list)
    omitted_ids: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


class MemoryEngine(Protocol):
    async def recall(self, request: MemoryRecallRequest) -> MemoryQueryResult:
        pass

    async def memorize(self, request: MemoryWriteRequest) -> MemoryIngestResult:
        pass

    def forget(self, ids: list[str]) -> MemoryMutationResult:
        pass

    def undo_by_source(self, source_ref: str) -> MemoryMutationResult:
        pass

    async def build_context(self, request: MemoryRecallRequest) -> MemoryContextResult:
        pass

    async def run_post_response(self, *, session_key: str, messages: list[dict[str, Any]],
                                explicit_memory_ids: list[str]) -> dict[str, Any]:
        pass
```

- [ ] **Step 4: Update bootstrap composition to target `memory/long_term_memory.db` and new tools**

```python
embedding_provider = OpenAIEmbeddingProvider(
    OpenAIEmbeddingConfig(
        api_key=config.provider.api_key,
        base_url=config.provider.base_url,
        model=config.embedding_model,
        timeout_seconds=config.provider.timeout_seconds,
    )
)
store = MemoryStore(config.long_term_memory_db_path)
memorizer = MemoryMemorizer(store=store, embedding_provider=embedding_provider)
retriever = MemoryRetriever(
    store=store,
    embedding_provider=embedding_provider,
    hypothesis_provider=LLMHypothesisProvider(provider=provider),
    top_k=config.long_term_memory_top_k,
)
worker = PostResponseMemoryWorker(
    memorizer=memorizer,
    extractor=LLMMemoryExtractor(provider=provider, model=config.provider.model),
)
long_term_memory = AkashicMemoryEngine(
    store=store,
    retriever=retriever,
    memorizer=memorizer,
    worker=worker,
)

tool_registry.register(RecallMemoryTool(memory_engine=long_term_memory))
tool_registry.register(MemorizeTool(memory_engine=long_term_memory))
tool_registry.register(ForgetMemoryTool(memory_engine=long_term_memory))
tool_registry.register(UndoMemoryBySourceTool(memory_engine=long_term_memory))
```

- [ ] **Step 5: Re-export the new protocol types from `amadeus/memory/__init__.py`**

```python
from amadeus.memory.engine import (
    MemoryContextResult,
    MemoryEngine,
    MemoryRecallRequest,
    MemoryScope,
    MemoryWriteRequest,
)
```

- [ ] **Step 6: Run the targeted tests again**

Run:

```powershell
pytest tests/memory/test_bootstrap_long_term_memory.py tests/app/test_bootstrap.py -k "memory2_db or memory_tools_without_correct_memory" -v
```

Expected:

```text
2 passed
```

- [ ] **Step 7: Commit the contract/bootstrap slice**

```powershell
git add amadeus/memory/engine.py amadeus/memory/__init__.py amadeus/app/bootstrap.py tests/memory/test_bootstrap_long_term_memory.py tests/app/test_bootstrap.py
git commit -m "refactor: redefine memory engine contract"
```

## Task 2: Build The `long_term_memory.db` Store With Replacement Support

**Files:**
- Create: `amadeus/memory/store.py`
- Modify: `amadeus/memory/__init__.py`
- Create: `tests/memory/test_memory_store.py`

- [ ] **Step 1: Write the failing store tests**

```python
from amadeus.memory.store import MemoryStore


def test_store_creates_memory2_schema(tmp_path):
    store = MemoryStore(tmp_path / "long_term_memory.db")

    names = store.list_table_names()

    assert "memory_items" in names
    assert "memory_replacements" in names


def test_store_can_record_and_read_replacement_chain(tmp_path):
    store = MemoryStore(tmp_path / "long_term_memory.db")
    store.insert_item(
        item_id="mem_old",
        memory_type="fact",
        summary="旧事实",
        content_hash="old",
        embedding=[1.0, 0.0],
        source_ref='["chat:1:0"]#h:old',
        happened_at=None,
        scope_channel="telegram",
        scope_chat_id="100",
        emotional_weight=0.0,
        extra={},
    )
    store.insert_item(
        item_id="mem_new",
        memory_type="fact",
        summary="新事实",
        content_hash="new",
        embedding=[1.0, 0.1],
        source_ref='["chat:1:1"]#h:new',
        happened_at=None,
        scope_channel="telegram",
        scope_chat_id="100",
        emotional_weight=0.0,
        extra={},
    )

    store.record_replacement("mem_old", "mem_new", '["chat:1:1"]#h:new')

    assert store.list_replacements_for("mem_old") == [
        {"old_item_id": "mem_old", "new_item_id": "mem_new"}
    ]
```

- [ ] **Step 2: Run the store tests to confirm they fail**

Run:

```powershell
pytest tests/memory/test_memory_store.py -v
```

Expected:

```text
ERROR tests/memory/test_memory_store.py
```

- [ ] **Step 3: Implement the new SQLite store in `amadeus/memory/store.py`**

```python
class MemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                '''
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    happened_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    reinforcement INTEGER NOT NULL DEFAULT 1,
                    emotional_weight REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    extra_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS memory_replacements (
                    old_item_id TEXT NOT NULL,
                    new_item_id TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                '''
            )
            self._conn.commit()
```

- [ ] **Step 4: Add query helpers needed by memorizer and retriever**

```python
def list_active_items(
    self,
    *,
    memory_types: tuple[str, ...] = (),
    scope_channel: str | None = None,
    scope_chat_id: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["status = 'active'"]
    params: list[Any] = []
    if memory_types:
        clauses.append(f"memory_type IN ({','.join('?' for _ in memory_types)})")
        params.extend(memory_types)
    if scope_channel is not None:
        clauses.append("json_extract(extra_json, '$.scope_channel') = ?")
        params.append(scope_channel)
    if scope_chat_id is not None:
        clauses.append("json_extract(extra_json, '$.scope_chat_id') = ?")
        params.append(scope_chat_id)
    rows = self._conn.execute(
        f"SELECT * FROM memory_items WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC",
        tuple(params),
    ).fetchall()
    return [self._row_to_item(row) for row in rows]


def find_items_by_source_ref(self, source_ref: str) -> list[dict[str, Any]]:
    rows = self._conn.execute(
        "SELECT * FROM memory_items WHERE source_ref = ? ORDER BY updated_at DESC",
        (source_ref,),
    ).fetchall()
    return [self._row_to_item(row) for row in rows]


def mark_items_status(self, ids: list[str], *, status: str, extra_patch: dict[str, Any]) -> None:
    now = datetime.now().astimezone().isoformat()
    for item in self.get_items_by_ids(ids):
        extra = dict(item["extra"])
        extra.update(extra_patch)
        self._conn.execute(
            "UPDATE memory_items SET status = ?, updated_at = ?, extra_json = ? WHERE id = ?",
            (status, now, json.dumps(extra, ensure_ascii=False), item["id"]),
        )
    self._conn.commit()
```

- [ ] **Step 5: Export `MemoryStore` from `amadeus/memory/__init__.py`**

```python
from amadeus.memory.store import MemoryStore
```

- [ ] **Step 6: Run the store tests again**

Run:

```powershell
pytest tests/memory/test_memory_store.py -v
```

Expected:

```text
2 passed
```

- [ ] **Step 7: Commit the store slice**

```powershell
git add amadeus/memory/store.py amadeus/memory/__init__.py tests/memory/test_memory_store.py
git commit -m "feat: add memory2 sqlite store"
```

## Task 3: Implement The Memorizer And Replacement / Undo Lifecycle

**Files:**
- Create: `amadeus/memory/memorizer.py`
- Modify: `amadeus/memory/markdown.py`
- Create: `tests/memory/test_memory_memorizer.py`

- [ ] **Step 1: Write the failing memorizer tests**

```python
import asyncio

from amadeus.memory.engine import MemoryScope, MemoryWriteRequest
from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.store import MemoryStore


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


def test_memorizer_reinforces_same_content(tmp_path):
    memorizer = MemoryMemorizer(
        store=MemoryStore(tmp_path / "long_term_memory.db"),
        embedding_provider=StableEmbeddingProvider(),
    )

    first = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户偏好中文输出",
                memory_type="preference",
                source_ref='["chat:1:0"]#h:a',
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )
    second = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户偏好中文输出",
                memory_type="preference",
                source_ref='["chat:1:1"]#h:b',
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )

    assert first.status == "new"
    assert second.status == "reinforced"
    assert first.item_id == second.item_id
```

```python
def test_memorizer_can_replace_and_undo_by_source(tmp_path):
    memorizer = MemoryMemorizer(
        store=MemoryStore(tmp_path / "long_term_memory.db"),
        embedding_provider=StableEmbeddingProvider(),
    )

    original = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户现在住在上海",
                memory_type="fact",
                source_ref='["chat:1:0"]#h:old',
            )
        )
    )
    replacement = asyncio.run(
        memorizer.replace(
            target_id=original.item_id,
            request=MemoryWriteRequest(
                summary="用户现在住在杭州",
                memory_type="fact",
                source_ref='["chat:1:1"]#h:new',
            ),
        )
    )

    undone = memorizer.undo_by_source('["chat:1:1"]#h:new')

    assert replacement.accepted is True
    assert undone.accepted is True
    assert undone.affected_ids == [original.item_id, replacement.affected_ids[-1]]
```

- [ ] **Step 2: Run the memorizer tests to verify they fail**

Run:

```powershell
pytest tests/memory/test_memory_memorizer.py -v
```

Expected:

```text
ERROR tests/memory/test_memory_memorizer.py
```

- [ ] **Step 3: Implement `MemoryMemorizer`**

```python
class MemoryMemorizer:
    def __init__(self, *, store: MemoryStore, embedding_provider: EmbeddingProvider) -> None:
        self.store = store
        self.embedding_provider = embedding_provider

    async def memorize(self, request: MemoryWriteRequest) -> MemoryIngestResult:
        summary = request.summary.strip()
        source_ref = request.source_ref.strip()
        if not summary or not source_ref:
            return MemoryIngestResult(status="invalid", trace={"reason": "summary_and_source_ref_required"})
        embedding = await self.embedding_provider.embed(summary)
        return self.store.upsert_memory_item(request=request, embedding=embedding)

    async def replace(self, *, target_id: str, request: MemoryWriteRequest) -> MemoryMutationResult:
        replacement = await self.memorize(request)
        replacement_id = replacement.item_id
        if replacement_id is None:
            return MemoryMutationResult(accepted=False, status="skipped")
        self.store.mark_items_status([target_id], status="superseded", extra_patch={"replacement_id": replacement_id})
        self.store.record_replacement(target_id, replacement_id, request.source_ref)
        return MemoryMutationResult(
            accepted=True,
            status="replaced",
            affected_ids=[target_id, replacement_id],
        )

    def undo_by_source(self, source_ref: str) -> MemoryMutationResult:
        return self.store.undo_source_mutations(source_ref)
```

- [ ] **Step 4: Route markdown consolidation writes through the memorizer**

```python
async def _ingest_long_term_memory(
    self,
    draft: _ConsolidationDraft,
    entries: list[str],
) -> dict[str, Any]:
    trace = {"attempted": 0, "succeeded": 0, "failed": 0, "errors": []}
    for request in requests:
        trace["attempted"] += 1
        result = await self.long_term_memory.memorize(request)
        if result.status in {"new", "reinforced"}:
            trace["succeeded"] += 1
        else:
            trace["failed"] += 1
            trace["errors"].append(
                {"source_ref": request.source_ref, "memory_type": request.memory_type, "status": result.status}
            )
    return trace
```

- [ ] **Step 5: Add forgetting behavior through status mutation instead of direct engine logic**

```python
def forget(self, ids: list[str]) -> MemoryMutationResult:
    return self.store.soft_forget(ids, reason="forget")
```

- [ ] **Step 6: Run the memorizer tests again**

Run:

```powershell
pytest tests/memory/test_memory_memorizer.py -v
```

Expected:

```text
2 passed
```

- [ ] **Step 7: Commit the memorizer slice**

```powershell
git add amadeus/memory/memorizer.py amadeus/memory/markdown.py tests/memory/test_memory_memorizer.py
git commit -m "feat: add memorizer replacement lifecycle"
```

## Task 4: Implement Scope-Aware Retriever And Context Builder

**Files:**
- Create: `amadeus/memory/retriever.py`
- Modify: `amadeus/runtime/before_turn.py`
- Modify: `tests/runtime/test_before_turn.py`
- Create: `tests/memory/test_memory_retriever.py`

- [ ] **Step 1: Write the failing retriever and before_turn tests**

```python
import asyncio

from amadeus.memory.engine import MemoryContextResult, MemoryRecallRequest, MemoryScope, MemoryWriteRequest
from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.retriever import MemoryRetriever
from amadeus.memory.store import MemoryStore


def test_retriever_prefers_scope_matched_procedure_then_preference(tmp_path):
    store = MemoryStore(tmp_path / "long_term_memory.db")
    memorizer = MemoryMemorizer(store=store, embedding_provider=StableEmbeddingProvider())
    asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="部署前先运行 smoke tests",
                memory_type="procedure",
                source_ref='["chat:1:0"]#h:p',
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )
    asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户偏好中文输出",
                memory_type="preference",
                source_ref='["chat:1:1"]#h:f',
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )

    retriever = MemoryRetriever(store=store, embedding_provider=StableEmbeddingProvider())
    result = asyncio.run(
        retriever.build_context(
            MemoryRecallRequest(
                text="怎么继续这个任务",
                intent="context",
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )

    assert result.injected_ids
    assert "部署前先运行 smoke tests" in result.text
    assert result.text.index("部署前先运行 smoke tests") < result.text.index("用户偏好中文输出")
```

```python
class _BuildContextMemory:
    def __init__(self) -> None:
        self.requests = []

    async def build_context(self, request):
        self.requests.append(request)
        return MemoryContextResult(
            text="memory from build_context",
            injected_ids=["mem_1"],
            omitted_ids=[],
            trace={"record_count": 1},
        )
```

- [ ] **Step 2: Run the retriever-related tests to confirm failure**

Run:

```powershell
pytest tests/memory/test_memory_retriever.py tests/runtime/test_before_turn.py -k "scope_matched or build_context" -v
```

Expected:

```text
FAILED tests/runtime/test_before_turn.py::test_before_turn_uses_build_context_when_caller_did_not_supply_it
ERROR tests/memory/test_memory_retriever.py
```

- [ ] **Step 3: Implement `MemoryRetriever` with fused retrieval**

```python
class MemoryRetriever:
    def __init__(
        self,
        *,
        store: MemoryStore,
        embedding_provider: EmbeddingProvider,
        hypothesis_provider: HypothesisProvider | None = None,
        score_threshold: float = 0.35,
        top_k: int = 8,
        context_char_budget: int = 4000,
    ) -> None:
        self.store = store
        self.embedding_provider = embedding_provider
        self.hypothesis_provider = hypothesis_provider
        self.score_threshold = score_threshold
        self.top_k = top_k
        self.context_char_budget = context_char_budget

    async def recall(self, request: MemoryRecallRequest) -> MemoryQueryResult:
        query_vector = await self.embedding_provider.embed(request.text.strip())
        rows = self.store.list_active_items(
            memory_types=request.memory_types,
            scope_channel=request.scope.channel,
            scope_chat_id=request.scope.chat_id,
        )
        ranked = _rank_rows(
            rows,
            query_vector,
            request.text,
            limit=request.limit if request.limit > 0 else self.top_k,
            threshold=self.score_threshold,
        )
        trace = {
            "intent": request.intent,
            "scope": {"channel": request.scope.channel, "chat_id": request.scope.chat_id},
            "record_count": len(ranked),
        }
        return MemoryQueryResult(records=ranked, trace=trace)

    async def build_context(self, request: MemoryRecallRequest) -> MemoryContextResult:
        result = await self.recall(request)
        block, injected_ids, omitted_ids = _render_priority_sections(result.records, self.context_char_budget)
        return MemoryContextResult(text=block, injected_ids=injected_ids, omitted_ids=omitted_ids, trace=result.trace)
```

- [ ] **Step 4: Update `before_turn` to call `build_context` instead of `query -> render_context_block`**

```python
context_result = await self._memory_engine.build_context(
    MemoryRecallRequest(
        text=frame.input.user_message,
        intent="context",
        scope=MemoryScope(chat_id=frame.input.session_key),
        context={
            "history": history,
            "session_key": frame.input.session_key,
        },
    )
)
retrieved_memory = context_result.text
memory_trace = dict(context_result.trace)
memory_trace["injected_ids"] = list(context_result.injected_ids)
memory_trace["omitted_ids"] = list(context_result.omitted_ids)
```

- [ ] **Step 5: Run the retriever and before_turn tests again**

Run:

```powershell
pytest tests/memory/test_memory_retriever.py tests/runtime/test_before_turn.py -k "scope_matched or build_context" -v
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit the retriever slice**

```powershell
git add amadeus/memory/retriever.py amadeus/runtime/before_turn.py tests/memory/test_memory_retriever.py tests/runtime/test_before_turn.py
git commit -m "feat: add scope-aware memory retriever"
```

## Task 5: Add Post-Response Worker And After-Turn Integration

**Files:**
- Create: `amadeus/memory/post_response_worker.py`
- Modify: `amadeus/runtime/after_turn.py`
- Modify: `amadeus/runtime/passive.py`
- Modify: `amadeus/app/bootstrap.py`
- Create: `tests/memory/test_memory_post_response_worker.py`
- Modify: `tests/app/test_bootstrap.py`

- [ ] **Step 1: Write the failing post-response worker tests**

```python
import asyncio

from amadeus.memory.post_response_worker import LLMMemoryExtractor, PostResponseMemoryWorker


class FakeExtractor:
    async def extract(self, *, session_key: str, messages: list[dict[str, str]]):
        return [
            {
                "summary": "用户明确要求长期记住：默认用中文",
                "memory_type": "preference",
                "source_ref": '["chat:1:0"]#h:extract',
            }
        ]


def test_post_response_worker_writes_implicit_memory_once(tmp_path):
    worker = PostResponseMemoryWorker(
        memorizer=MemoryMemorizer(
            store=MemoryStore(tmp_path / "long_term_memory.db"),
            embedding_provider=StableEmbeddingProvider(),
        ),
        extractor=FakeExtractor(),
    )

    result = asyncio.run(
        worker.run(
            session_key="chat:1",
            messages=[{"role": "user", "content": "以后默认中文回复"}],
            explicit_memory_ids=[],
        )
    )

    assert result["written_count"] == 1
    assert result["skipped_duplicates"] == 0
```

- [ ] **Step 2: Run the worker tests to confirm failure**

Run:

```powershell
pytest tests/memory/test_memory_post_response_worker.py -v
```

Expected:

```text
ERROR tests/memory/test_memory_post_response_worker.py
```

- [ ] **Step 3: Implement `PostResponseMemoryWorker`**

```python
import json
from typing import Any


class LLMMemoryExtractor:
    def __init__(self, *, provider: Any, model: str) -> None:
        self.provider = provider
        self.model = model

    async def extract(self, *, session_key: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        transcript = "\n".join(
            f"{message['role'].upper()}: {str(message['content']).strip()}"
            for message in messages
            if str(message.get("content") or "").strip()
        )
        response = await self.provider.chat(
            [
                {"role": "system", "content": "你是长期记忆抽取器，只返回 JSON 数组。"},
                {"role": "user", "content": transcript},
            ],
            model=self.model,
            max_tokens=512,
            tools=[],
            disable_thinking=True,
        )
        parsed = json.loads(str(response.content or "[]"))
        return [item for item in parsed if isinstance(item, dict)]


class PostResponseMemoryWorker:
    def __init__(self, *, memorizer: MemoryMemorizer, extractor: LLMMemoryExtractor | Any) -> None:
        self.memorizer = memorizer
        self.extractor = extractor

    async def run(
        self,
        *,
        session_key: str,
        messages: list[dict[str, Any]],
        explicit_memory_ids: list[str],
    ) -> dict[str, Any]:
        candidates = await self.extractor.extract(session_key=session_key, messages=messages)
        written = 0
        skipped_duplicates = 0
        for candidate in candidates:
            result = await self.memorizer.memorize(MemoryWriteRequest(**candidate))
            if result.item_id in explicit_memory_ids:
                skipped_duplicates += 1
                continue
            if result.status in {"new", "reinforced"}:
                written += 1
        return {"written_count": written, "skipped_duplicates": skipped_duplicates}
```

- [ ] **Step 4: Trigger the worker from `after_turn` through the engine**

```python
from amadeus.session.store import SessionManager


class _RunPostResponseMemoryModule:
    slot = "after_turn.memory_worker"
    requires = ("after_turn.emit",)

    def __init__(
        self,
        memory_engine: MemoryEngine | None,
        session_manager: SessionManager,
    ) -> None:
        self._memory_engine = memory_engine
        self._session_manager = session_manager

    async def run(self, frame: AfterTurnFrame) -> AfterTurnFrame:
        if self._memory_engine is None:
            return frame
        session = self._session_manager.get_or_create(frame.input.context.session_key)
        trace = await self._memory_engine.run_post_response(
            session_key=frame.input.context.session_key,
            messages=list(session.messages),
            explicit_memory_ids=list(frame.input.context.memory_trace.get("explicit_memory_ids", [])),
        )
        frame.input.context.memory_trace["post_response"] = trace
        return frame
```

- [ ] **Step 5: Wire the worker into bootstrap**

```python
embedding_provider = OpenAIEmbeddingProvider(
    OpenAIEmbeddingConfig(
        api_key=config.provider.api_key,
        base_url=config.provider.base_url,
        model=config.embedding_model,
        timeout_seconds=config.provider.timeout_seconds,
    )
)
store = MemoryStore(config.long_term_memory_db_path)
memorizer = MemoryMemorizer(store=store, embedding_provider=embedding_provider)
long_term_memory = AkashicMemoryEngine(
    store=store,
    retriever=MemoryRetriever(
        store=store,
        embedding_provider=embedding_provider,
        hypothesis_provider=LLMHypothesisProvider(provider=provider),
        top_k=config.long_term_memory_top_k,
    ),
    memorizer=memorizer,
    worker=PostResponseMemoryWorker(
        memorizer=memorizer,
        extractor=LLMMemoryExtractor(provider=provider, model=config.provider.model),
    ),
)
```

- [ ] **Step 6: Run the worker/bootstrap tests again**

Run:

```powershell
pytest tests/memory/test_memory_post_response_worker.py tests/app/test_bootstrap.py -k "post_response" -v
```

Expected:

```text
2 passed
```

- [ ] **Step 7: Commit the worker slice**

```powershell
git add amadeus/memory/post_response_worker.py amadeus/runtime/after_turn.py amadeus/app/bootstrap.py tests/memory/test_memory_post_response_worker.py tests/app/test_bootstrap.py
git commit -m "feat: run post-response memory worker"
```

## Task 6: Rewrite Memory Tools Around The New Engine

**Files:**
- Create: `amadeus/tools/memorize.py`
- Create: `amadeus/tools/undo_memory_by_source.py`
- Modify: `amadeus/tools/recall_memory.py`
- Modify: `amadeus/tools/forget_memory.py`
- Delete: `amadeus/tools/correct_memory.py`
- Modify: `amadeus/prompts/personality_rules.py`
- Create: `tests/tools/test_memorize_tool.py`
- Create: `tests/tools/test_undo_memory_by_source_tool.py`
- Modify: `tests/memory/test_memory_retrieval_acceptance.py`

- [ ] **Step 1: Write the failing tool tests**

```python
import asyncio

from amadeus.tools.memorize import MemorizeTool
from amadeus.tools.recall_memory import RecallMemoryTool
from amadeus.tools.undo_memory_by_source import UndoMemoryBySourceTool


class FakeExtractor:
    async def extract(
        self,
        *,
        session_key: str,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return []


def _build_memory_engine(tmp_path):
    provider = StableEmbeddingProvider()
    store = MemoryStore(tmp_path / "long_term_memory.db")
    memorizer = MemoryMemorizer(store=store, embedding_provider=provider)
    retriever = MemoryRetriever(store=store, embedding_provider=provider)
    worker = PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor())
    return AkashicMemoryEngine(
        store=store,
        retriever=retriever,
        memorizer=memorizer,
        worker=worker,
    )


def _seed_replaced_memory(engine):
    original = asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="旧事实",
                memory_type="fact",
                source_ref='["chat:1:0"]#h:old',
            )
        )
    )
    asyncio.run(
        engine.memorizer.replace(
            target_id=original.item_id,
            request=MemoryWriteRequest(
                summary="新事实",
                memory_type="fact",
                source_ref='["chat:1:1"]#h:new',
            ),
        )
    )
    return original.item_id, '["chat:1:1"]#h:new'


def test_memorize_tool_writes_long_term_memory(tmp_path):
    engine = _build_memory_engine(tmp_path)

    result = asyncio.run(
        MemorizeTool(memory_engine=engine).execute(
            summary="用户明确要求长期记住：默认中文输出",
            memory_type="preference",
            source_ref='["chat:1:0"]#h:memorize',
        )
    )

    assert result.is_error is False
    assert result.output["status"] in {"new", "reinforced"}
    assert result.output["memory_id"]
```

```python
def test_undo_memory_by_source_tool_restores_replaced_item(tmp_path):
    engine = _build_memory_engine(tmp_path)
    original_id, source_ref = _seed_replaced_memory(engine)

    result = UndoMemoryBySourceTool(memory_engine=engine).execute(source_ref=source_ref)
    recalled = asyncio.run(RecallMemoryTool(memory_engine=engine).execute(query="旧事实"))

    assert result.is_error is False
    assert original_id in result.output["restored_ids"]
    assert original_id in [item["id"] for item in recalled.output["items"]]
```

- [ ] **Step 2: Run the tool tests to confirm failure**

Run:

```powershell
pytest tests/tools/test_memorize_tool.py tests/tools/test_undo_memory_by_source_tool.py tests/memory/test_memory_retrieval_acceptance.py -k "memorize or undo_memory_by_source" -v
```

Expected:

```text
ERROR tests/tools/test_memorize_tool.py
ERROR tests/tools/test_undo_memory_by_source_tool.py
FAILED tests/memory/test_memory_retrieval_acceptance.py::test_behavior_rules_require_fetch_before_factual_use_and_memory_mutation
```

- [ ] **Step 3: Implement `MemorizeTool` and `UndoMemoryBySourceTool`**

```python
@dataclass
class MemorizeTool:
    memory_engine: MemoryEngine | None
    name: str = "memorize"
    description: str = "把明确的用户长期事实写入长期记忆。"
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "memory_type": {"type": "string"},
                "source_ref": {"type": "string"},
            },
            "required": ["summary", "memory_type", "source_ref"],
        }
    )

    async def execute(self, **kwargs: object) -> ToolResult:
        if self.memory_engine is None:
            return ToolResult(tool_name=self.name, output={"error": "memory engine is not configured"}, is_error=True)
        result = await self.memory_engine.memorize(
            MemoryWriteRequest(
                summary=str(kwargs["summary"]).strip(),
                memory_type=str(kwargs["memory_type"]).strip(),
                source_ref=str(kwargs["source_ref"]).strip(),
            )
        )
        return ToolResult(tool_name=self.name, output={"status": result.status, "memory_id": result.item_id})
```

```python
@dataclass
class UndoMemoryBySourceTool:
    memory_engine: MemoryEngine | None
    name: str = "undo_memory_by_source"

    def execute(self, **kwargs: object) -> ToolResult:
        if self.memory_engine is None:
            return ToolResult(tool_name=self.name, output={"error": "memory engine is not configured"}, is_error=True)
        source_ref = str(kwargs.get("source_ref") or "").strip()
        if not source_ref:
            return ToolResult(tool_name=self.name, output={"error": "source_ref is required"}, is_error=True)
        result = self.memory_engine.undo_by_source(source_ref)
        return ToolResult(
            tool_name=self.name,
            output={
                "accepted": result.accepted,
                "status": result.status,
                "restored_ids": result.affected_ids,
                "missing_ids": result.missing_ids,
            },
        )
```

- [ ] **Step 4: Rewrite `RecallMemoryTool` and `ForgetMemoryTool` against the new API**

```python
result = await self.memory_engine.recall(
    MemoryRecallRequest(
        text=query_text.strip(),
        intent=str(kwargs.get("intent", "answer")),
        memory_types=_string_list(kwargs.get("memory_types") or kwargs.get("kinds")),
        limit=_positive_limit(kwargs.get("limit")),
        time_start=datetime.fromisoformat(time_start) if time_start else None,
        time_end=datetime.fromisoformat(time_end) if time_end else None,
    )
)
```

- [ ] **Step 5: Update prompting rules and acceptance tests**

```python
assert "memorize" in prompt
assert "undo_memory_by_source" in prompt
assert "correct_memory" not in prompt
assert prompt.index("fetch_messages") < prompt.index("memorize")
assert prompt.index("memorize") < prompt.index("forget_memory")
```

- [ ] **Step 6: Remove `correct_memory.py` and its bootstrap references**

```powershell
git rm amadeus/tools/correct_memory.py
```

- [ ] **Step 7: Run the tool/acceptance tests again**

Run:

```powershell
pytest tests/tools/test_memorize_tool.py tests/tools/test_undo_memory_by_source_tool.py tests/memory/test_memory_retrieval_acceptance.py -k "memorize or undo_memory_by_source or behavior_rules" -v
```

Expected:

```text
3 passed
```

- [ ] **Step 8: Commit the tool contract slice**

```powershell
git add amadeus/tools/memorize.py amadeus/tools/undo_memory_by_source.py amadeus/tools/recall_memory.py amadeus/tools/forget_memory.py amadeus/prompts/personality_rules.py tests/tools/test_memorize_tool.py tests/tools/test_undo_memory_by_source_tool.py tests/memory/test_memory_retrieval_acceptance.py
git commit -m "refactor: replace correct memory tool flow"
```

## Task 7: Compose The New Akashic-Style Engine

**Files:**
- Modify: `amadeus/memory/vector.py`
- Modify: `amadeus/memory/engine.py`
- Modify: `amadeus/app/bootstrap.py`
- Modify: `tests/memory/test_memory_retrieval_acceptance.py`
- Modify: `tests/app/test_bootstrap_tool_runtime.py`

- [ ] **Step 1: Write the failing composition tests**

```python
from amadeus.memory.post_response_worker import PostResponseMemoryWorker
from amadeus.memory.engine import MemoryWriteRequest


class FakeExtractor:
    async def extract(
        self,
        *,
        session_key: str,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return []


def _build_memory_engine(tmp_path):
    provider = StableEmbeddingProvider()
    store = MemoryStore(tmp_path / "long_term_memory.db")
    memorizer = MemoryMemorizer(store=store, embedding_provider=provider)
    retriever = MemoryRetriever(store=store, embedding_provider=provider)
    worker = PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor())
    return AkashicMemoryEngine(
        store=store,
        retriever=retriever,
        memorizer=memorizer,
        worker=worker,
    )


def test_memory_engine_composes_store_retriever_memorizer_and_worker(tmp_path):
    engine = _build_memory_engine(tmp_path)

    assert engine.store.__class__.__name__ == "MemoryStore"
    assert engine.retriever.__class__.__name__ == "MemoryRetriever"
    assert engine.memorizer.__class__.__name__ == "MemoryMemorizer"
    assert engine.worker.__class__.__name__ == "PostResponseMemoryWorker"
```

- [ ] **Step 2: Run the composition tests to confirm failure**

Run:

```powershell
pytest tests/app/test_bootstrap_tool_runtime.py tests/memory/test_memory_retrieval_acceptance.py -k "composes_store_retriever_memorizer_and_worker" -v
```

Expected:

```text
FAILED tests/app/test_bootstrap_tool_runtime.py::test_memory_engine_composes_store_retriever_memorizer_and_worker
```

- [ ] **Step 3: Replace `AkashicMemoryEngine` with a thin composition root**

```python
class AkashicMemoryEngine:
    def __init__(
        self,
        *,
        store: MemoryStore,
        retriever: MemoryRetriever,
        memorizer: MemoryMemorizer,
        worker: PostResponseMemoryWorker,
    ) -> None:
        self.store = store
        self.retriever = retriever
        self.memorizer = memorizer
        self.worker = worker

    async def recall(self, request: MemoryRecallRequest) -> MemoryQueryResult:
        return await self.retriever.recall(request)

    async def memorize(self, request: MemoryWriteRequest) -> MemoryIngestResult:
        return await self.memorizer.memorize(request)

    def forget(self, ids: list[str]) -> MemoryMutationResult:
        return self.memorizer.forget(ids)

    def undo_by_source(self, source_ref: str) -> MemoryMutationResult:
        return self.memorizer.undo_by_source(source_ref)

    async def build_context(self, request: MemoryRecallRequest) -> MemoryContextResult:
        return await self.retriever.build_context(request)

    async def run_post_response(self, *, session_key: str, messages: list[dict[str, Any]],
                                explicit_memory_ids: list[str]) -> dict[str, Any]:
        return await self.worker.run(
            session_key=session_key,
            messages=messages,
            explicit_memory_ids=explicit_memory_ids,
        )
```

- [ ] **Step 4: Keep compatibility helpers only where needed for embeddings and source parsing**

```python
from amadeus.memory.vector import (
    LLMHypothesisProvider,
    OpenAIEmbeddingConfig,
    OpenAIEmbeddingProvider,
    build_entry_source_ref,
    parse_history_entry_happened_at,
)
```

- [ ] **Step 5: Run the composition tests again**

Run:

```powershell
pytest tests/app/test_bootstrap_tool_runtime.py tests/memory/test_memory_retrieval_acceptance.py -k "composes_store_retriever_memorizer_and_worker" -v
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Commit the engine composition slice**

```powershell
git add amadeus/memory/vector.py amadeus/memory/engine.py amadeus/app/bootstrap.py tests/app/test_bootstrap_tool_runtime.py tests/memory/test_memory_retrieval_acceptance.py
git commit -m "refactor: compose akashic-style memory engine"
```

## Task 8: Run End-To-End Verification And Clean Up Phase2 Artifacts

**Files:**
- Modify: `tests/memory/test_memory_retrieval_acceptance.py`
- Modify: `tests/app/test_bootstrap.py`
- Modify: `tests/runtime/test_before_turn.py`
- Modify: `tests/memory/test_session_memory_runtime.py`
- Modify: `tests/memory/test_runtime_memory.py`

- [ ] **Step 1: Add final acceptance coverage for replacement, forget, undo, and passive runtime injection**

```python
def test_passive_runtime_recall_forget_and_undo_flow(tmp_path):
    app = _build_memory_enabled_app(tmp_path)
    engine = app.runtime.memory_engine

    remembered = asyncio.run(
        MemorizeTool(memory_engine=engine).execute(
            summary="用户长期偏好中文输出",
            memory_type="preference",
            source_ref='["chat:1:0"]#h:pref',
        )
    )
    forgotten = ForgetMemoryTool(memory_engine=engine).execute(ids=[remembered.output["memory_id"]])
    restored = UndoMemoryBySourceTool(memory_engine=engine).execute(source_ref='["chat:1:0"]#h:pref')

    assert forgotten.output["superseded_ids"] == [remembered.output["memory_id"]]
    assert restored.output["restored_ids"] == [remembered.output["memory_id"]]
```

- [ ] **Step 2: Run the focused memory/runtime suite**

Run:

```powershell
pytest tests/memory/test_memory_store.py tests/memory/test_memory_memorizer.py tests/memory/test_memory_retriever.py tests/memory/test_memory_post_response_worker.py tests/memory/test_memory_retrieval_acceptance.py tests/runtime/test_before_turn.py tests/app/test_bootstrap.py tests/app/test_bootstrap_tool_runtime.py -v
```

Expected:

```text
process exits with code 0
no FAILED lines
no ERROR lines
```

- [ ] **Step 3: Run the broader regression suite**

Run:

```powershell
pytest tests/memory tests/runtime tests/app tests/tools -v
```

Expected:

```text
process exits with code 0
no FAILED lines
no ERROR lines
```

- [ ] **Step 4: Remove or rewrite any stale phase2-only assertions**

```python
assert "correct_memory" not in prompt
assert "render_context_block" not in inspect.getsource(default_before_turn_modules)
```

- [ ] **Step 5: Commit the final migration verification slice**

```powershell
git add tests/memory tests/runtime tests/app tests/tools
git commit -m "test: verify akashic memory migration"
```

## Self-Review Checklist

- Spec coverage:
  - `long_term_memory.db` schema: Task 2
  - memorizer unifies writes: Task 3
  - retriever + before_turn injection: Task 4
  - post-response worker: Task 5
  - tools `recall_memory / memorize / forget_memory / undo_memory_by_source`: Task 6
  - engine composition root: Task 7
  - acceptance + regression verification: Task 8
- Placeholder scan:
  - No `TODO` / `TBD`
  - Every task includes exact files, code snippets, commands, expected outcomes
- Type consistency:
  - Unified names: `MemoryRecallRequest`, `MemoryWriteRequest`, `MemoryScope`, `MemoryContextResult`, `MemoryStore`, `MemoryMemorizer`, `MemoryRetriever`, `PostResponseMemoryWorker`

## Notes For Execution

- 不要保留 `correct_memory` 兼容层。
- 旧 `long_term_memory.db` 可以直接废弃；如果测试依赖它，改成 `long_term_memory.db` fixture。
- `observation durability` 不在本轮范围，任何 trace 只需要存在于 runtime/test observable 输出中。
- 如果 `vector.py` 在最后只剩 provider/helper，可以在实现阶段把文件缩成 utility module，但不要在同一任务里做无关整理。

