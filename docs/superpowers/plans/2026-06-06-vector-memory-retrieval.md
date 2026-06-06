# Vector Memory Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an evidence-backed vector memory retrieval layer to Amadeus and inject retrieved memories into the existing context frame.

**Architecture:** Keep Markdown memory as the readable source of maintained memory, add a small `MemoryEngine` API, implement SQLite-backed vector memory behind it, and wire retrieval into `PassiveRuntime` only when configured. Tests use fake embeddings; production code uses an injectable embedding provider.

**Tech Stack:** Python 3.11+, pytest, SQLite, OpenAI Python SDK already present in the project.

---

## File Structure

- Create: `amadeus/memory_engine.py`
  - Public memory engine protocol and result dataclasses.
- Create: `amadeus/vector_memory.py`
  - SQLite vector-memory store, embedding provider protocol, OpenAI embedding provider, engine implementation.
- Modify: `amadeus/memory.py`
  - Add optional vector ingest callback after Markdown consolidation commits.
- Modify: `amadeus/runtime.py`
  - Add optional retrieval before provider call.
- Modify: `amadeus/bootstrap.py`
  - Build vector memory from explicit config.
- Modify: `amadeus/__init__.py`
  - Export the memory engine API.
- Test: `tests/test_vector_memory.py`
  - Store, ingest, dedupe, retrieval, keyword fallback, evidence rendering.
- Test: `tests/test_runtime_vector_memory.py`
  - Runtime context-frame injection and retrieval failure behavior.
- Test: `tests/test_bootstrap_vector_memory.py`
  - Config defaults and explicit enablement.

## Task 1: Memory Engine API

**Files:**

- Create: `amadeus/memory_engine.py`
- Modify: `amadeus/__init__.py`
- Test: `tests/test_vector_memory.py`

- [ ] **Step 1: Write the API shape test**

Add this to `tests/test_vector_memory.py`:

```python
from __future__ import annotations

from amadeus.memory_engine import EvidenceRef, MemoryRecord, MemoryQueryResult


def test_memory_record_carries_resolvable_evidence():
    record = MemoryRecord(
        id="mem_1",
        kind="event",
        summary="用户确认正在迁移 Amadeus 检索记忆。",
        score=0.9,
        source_ref='["chat:1:0","chat:1:1"]',
        evidence=[
            EvidenceRef(
                kind="session_messages",
                refs=["chat:1:0", "chat:1:1"],
                resolver="amadeus.session.fetch_messages",
                source_ref='["chat:1:0","chat:1:1"]',
                metadata={},
            )
        ],
        signals={"lane": "vector"},
    )
    result = MemoryQueryResult(records=[record], trace={"mode": "ok"})

    assert result.records[0].evidence[0].refs == ["chat:1:0", "chat:1:1"]
    assert result.records[0].source_ref == '["chat:1:0","chat:1:1"]'
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/test_vector_memory.py::test_memory_record_carries_resolvable_evidence -q
```

Expected: FAIL because `amadeus.memory_engine` does not exist.

- [ ] **Step 3: Implement the dataclasses and protocol**

Create `amadeus/memory_engine.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    refs: list[str]
    resolver: str
    source_ref: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    kind: str
    summary: str
    score: float
    source_ref: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryQuery:
    text: str
    kinds: tuple[str, ...] = ()
    limit: int = 8
    time_start: datetime | None = None
    time_end: datetime | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryQueryResult:
    records: list[MemoryRecord] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryIngestRequest:
    summary: str
    kind: str = "event"
    source_ref: str = ""
    happened_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryIngestResult:
    item_id: str | None = None
    status: str = "skipped"
    trace: dict[str, Any] = field(default_factory=dict)


class MemoryEngine(Protocol):
    async def ingest(self, request: MemoryIngestRequest) -> MemoryIngestResult: ...

    async def query(self, query: MemoryQuery) -> MemoryQueryResult: ...

    def render_context_block(self, result: MemoryQueryResult) -> str: ...
```

- [ ] **Step 4: Export API**

Modify `amadeus/__init__.py` to export:

```python
from amadeus.memory_engine import (
    EvidenceRef,
    MemoryEngine,
    MemoryIngestRequest,
    MemoryIngestResult,
    MemoryQuery,
    MemoryQueryResult,
    MemoryRecord,
)
```

- [ ] **Step 5: Verify**

Run:

```bash
uv run pytest tests/test_vector_memory.py::test_memory_record_carries_resolvable_evidence -q
```

Expected: PASS.

## Task 2: SQLite Vector Memory Store

**Files:**

- Create: `amadeus/vector_memory.py`
- Test: `tests/test_vector_memory.py`

- [ ] **Step 1: Add store tests**

Append:

```python
import asyncio

from amadeus.memory_engine import MemoryIngestRequest, MemoryQuery
from amadeus.vector_memory import VectorMemoryEngine, VectorMemoryStore


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "amadeus" in lowered or "检索" in lowered:
            return [1.0, 0.0, 0.0]
        if "dr pepper" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def test_vector_memory_ingests_and_retrieves_with_evidence(tmp_path):
    store = VectorMemoryStore(tmp_path / "vector_memory.db")
    engine = VectorMemoryEngine(store=store, embedding_provider=FakeEmbeddingProvider())

    result = asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="[2026-06-06 10:00] 用户确认正在迁移 Amadeus 检索记忆。",
                kind="event",
                source_ref='["chat:1:0","chat:1:1"]',
            )
        )
    )
    found = asyncio.run(engine.query(MemoryQuery(text="Amadeus 检索", limit=3)))

    assert result.status == "new"
    assert found.records
    assert found.records[0].source_ref == '["chat:1:0","chat:1:1"]'
    assert found.records[0].evidence[0].refs == ["chat:1:0", "chat:1:1"]


def test_vector_memory_deduplicates_source_ref(tmp_path):
    store = VectorMemoryStore(tmp_path / "vector_memory.db")
    engine = VectorMemoryEngine(store=store, embedding_provider=FakeEmbeddingProvider())
    request = MemoryIngestRequest(
        summary="[2026-06-06 10:00] 用户确认正在迁移 Amadeus 检索记忆。",
        kind="event",
        source_ref='["chat:1:0"]',
    )

    first = asyncio.run(engine.ingest(request))
    second = asyncio.run(engine.ingest(request))

    assert first.status == "new"
    assert second.status == "skipped"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/test_vector_memory.py -q
```

Expected: FAIL because `amadeus.vector_memory` does not exist.

- [ ] **Step 3: Implement store and engine**

Create `amadeus/vector_memory.py` with:

```python
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from openai import AsyncOpenAI

from amadeus.memory_engine import (
    EvidenceRef,
    MemoryIngestRequest,
    MemoryIngestResult,
    MemoryQuery,
    MemoryQueryResult,
    MemoryRecord,
)


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class OpenAIEmbeddingConfig:
    api_key: str
    model: str
    base_url: str | None = None
    timeout_seconds: float = 90


class OpenAIEmbeddingProvider:
    def __init__(self, config: OpenAIEmbeddingConfig, *, client: Any | None = None) -> None:
        self.config = config
        self._client = client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self.config.model,
            input=text,
        )
        return list(response.data[0].embedding)


class VectorMemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    happened_at TEXT,
                    extra_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'active',
                    reinforcement INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(content_hash, kind),
                    UNIQUE(source_ref, kind)
                );
                CREATE INDEX IF NOT EXISTS ix_memory_items_status
                    ON memory_items(status);
                CREATE INDEX IF NOT EXISTS ix_memory_items_kind
                    ON memory_items(kind);
                """
            )
            self._conn.commit()

    def upsert_item(
        self,
        *,
        kind: str,
        summary: str,
        embedding: list[float],
        source_ref: str,
        happened_at: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        now = datetime.now().astimezone().isoformat()
        digest = _content_hash(summary, kind)
        item_id = f"mem_{digest}"
        with self._lock:
            existing = self._conn.execute(
                """
                SELECT id FROM memory_items
                WHERE source_ref = ? AND kind = ?
                """,
                (source_ref, kind),
            ).fetchone()
            if existing is not None:
                return str(existing["id"]), "skipped"
            try:
                self._conn.execute(
                    """
                    INSERT INTO memory_items (
                        id, kind, summary, content_hash, embedding, source_ref,
                        happened_at, extra_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        kind,
                        summary,
                        digest,
                        json.dumps(embedding),
                        source_ref,
                        happened_at,
                        json.dumps(extra or {}, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                row = self._conn.execute(
                    """
                    SELECT id, reinforcement FROM memory_items
                    WHERE content_hash = ? AND kind = ?
                    """,
                    (digest, kind),
                ).fetchone()
                if row is None:
                    raise
                item_id = str(row["id"])
                self._conn.execute(
                    """
                    UPDATE memory_items
                    SET reinforcement = reinforcement + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, item_id),
                )
                self._conn.commit()
                return item_id, "reinforced"
            self._conn.commit()
        return item_id, "new"

    def list_active(self, *, kinds: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        clauses = ["status = 'active'"]
        params: list[Any] = []
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            clauses.append(f"kind IN ({placeholders})")
            params.extend(kinds)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM memory_items
                WHERE {" AND ".join(clauses)}
                ORDER BY updated_at DESC
                """,
                tuple(params),
            ).fetchall()
        return [_row_to_item(row) for row in rows]


class VectorMemoryEngine:
    def __init__(
        self,
        *,
        store: VectorMemoryStore,
        embedding_provider: EmbeddingProvider,
        score_threshold: float = 0.35,
    ) -> None:
        self.store = store
        self.embedding_provider = embedding_provider
        self.score_threshold = score_threshold

    async def ingest(self, request: MemoryIngestRequest) -> MemoryIngestResult:
        summary = request.summary.strip()
        source_ref = request.source_ref.strip()
        if not summary or not source_ref:
            return MemoryIngestResult(status="skipped", trace={"reason": "empty_input"})
        embedding = await self.embedding_provider.embed(summary)
        item_id, status = self.store.upsert_item(
            kind=request.kind,
            summary=summary,
            embedding=embedding,
            source_ref=source_ref,
            happened_at=request.happened_at,
            extra=request.extra,
        )
        return MemoryIngestResult(item_id=item_id, status=status)

    async def query(self, query: MemoryQuery) -> MemoryQueryResult:
        text = query.text.strip()
        if not text:
            return MemoryQueryResult(trace={"reason": "empty_query"})
        try:
            query_vector = await self.embedding_provider.embed(text)
            vector_failed = False
        except Exception as error:
            query_vector = []
            vector_failed = True
            vector_error = str(error)
        rows = self.store.list_active(kinds=query.kinds)
        records = _rank_rows(rows, query_vector, text, limit=query.limit, threshold=self.score_threshold)
        trace: dict[str, Any] = {
            "candidate_count": len(rows),
            "record_count": len(records),
        }
        if vector_failed:
            trace["vector_error"] = vector_error
        return MemoryQueryResult(records=records, trace=trace)

    def render_context_block(self, result: MemoryQueryResult) -> str:
        if not result.records:
            return ""
        lines = ["## Retrieved Memory"]
        for record in result.records:
            lines.append(
                f"- [{record.id}] ({record.kind}, score={record.score:.3f}) "
                f"{record.summary} source_ref={record.source_ref}"
            )
        return "\n".join(lines)


def _rank_rows(
    rows: list[dict[str, Any]],
    query_vector: list[float],
    query_text: str,
    *,
    limit: int,
    threshold: float,
) -> list[MemoryRecord]:
    terms = [term for term in query_text.lower().split() if term]
    ranked: list[tuple[float, dict[str, Any], str]] = []
    for row in rows:
        lane = "keyword"
        keyword_score = _keyword_score(row["summary"], terms)
        vector_score = 0.0
        if query_vector:
            vector_score = _cosine(query_vector, row["embedding"])
        score = max(vector_score, keyword_score)
        if score < threshold and keyword_score <= 0:
            continue
        if vector_score >= keyword_score:
            lane = "vector"
        ranked.append((score, row, lane))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        MemoryRecord(
            id=str(row["id"]),
            kind=str(row["kind"]),
            summary=str(row["summary"]),
            score=float(score),
            source_ref=str(row["source_ref"]),
            evidence=_evidence_from_source_ref(str(row["source_ref"])),
            signals={"lane": lane},
        )
        for score, row, lane in ranked[: max(1, int(limit))]
    ]


def _content_hash(summary: str, kind: str) -> str:
    normalized = " ".join(summary.lower().split())
    return hashlib.sha256(f"{kind}:{normalized}".encode("utf-8")).hexdigest()[:16]


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "kind": str(row["kind"]),
        "summary": str(row["summary"]),
        "embedding": json.loads(row["embedding"]),
        "source_ref": str(row["source_ref"]),
        "happened_at": row["happened_at"],
        "extra": json.loads(row["extra_json"] or "{}"),
        "reinforcement": int(row["reinforcement"] or 1),
    }


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / left_norm / right_norm


def _keyword_score(summary: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    lowered = summary.lower()
    hits = sum(1 for term in terms if term in lowered)
    return min(1.0, hits / len(terms))


def _evidence_from_source_ref(source_ref: str) -> list[EvidenceRef]:
    refs = _source_ref_message_ids(source_ref)
    if not refs:
        return []
    return [
        EvidenceRef(
            kind="session_messages",
            refs=refs,
            resolver="amadeus.session.fetch_messages",
            source_ref=source_ref,
            metadata={},
        )
    ]


def _source_ref_message_ids(source_ref: str) -> list[str]:
    base = source_ref.split("#", 1)[0].strip()
    try:
        loaded = json.loads(base)
    except json.JSONDecodeError:
        return [base] if base else []
    if isinstance(loaded, list):
        return [str(item).strip() for item in loaded if str(item).strip()]
    text = str(loaded).strip()
    return [text] if text else []
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_vector_memory.py -q
```

Expected: PASS.

## Task 3: Markdown Consolidation Ingest Hook

**Files:**

- Modify: `amadeus/memory.py`
- Test: `tests/test_vector_memory.py`

- [ ] **Step 1: Add ingest-after-commit test**

Append:

```python
from types import SimpleNamespace

from amadeus.memory import ConsolidateRequest, MarkdownMemoryMaintenance, MarkdownMemoryStore
from amadeus.session import SessionManager


class FakeChatProvider:
    async def chat(self, messages, **kwargs):
        return SimpleNamespace(
            content='{"history_entries":[{"summary":"[2026-06-06 10:00] 用户确认迁移检索记忆。"}],"pending_items":[]}'
        )


def test_markdown_consolidation_ingests_vector_memory_after_commit(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    for index in range(8):
        session.add_message("user", f"user {index}")
        session.add_message("assistant", f"assistant {index}")
    manager.save(session)
    vector_store = VectorMemoryStore(tmp_path / "vector_memory.db")
    vector = VectorMemoryEngine(store=vector_store, embedding_provider=FakeEmbeddingProvider())
    markdown = MarkdownMemoryStore(tmp_path)
    maintenance = MarkdownMemoryMaintenance(
        store=markdown,
        provider=FakeChatProvider(),
        model="fake",
        keep_count=4,
        vector_memory=vector,
    )

    asyncio.run(maintenance.consolidate(ConsolidateRequest(session=session)))
    found = asyncio.run(vector.query(MemoryQuery(text="迁移 检索记忆")))

    assert "用户确认迁移检索记忆" in markdown.read_history()
    assert found.records
```

- [ ] **Step 2: Run failing test**

Run:

```bash
uv run pytest tests/test_vector_memory.py::test_markdown_consolidation_ingests_vector_memory_after_commit -q
```

Expected: FAIL because `MarkdownMemoryMaintenance` has no `vector_memory` argument.

- [ ] **Step 3: Add optional vector memory dependency**

Modify `MarkdownMemoryMaintenance.__init__`:

```python
from amadeus.memory_engine import MemoryEngine, MemoryIngestRequest
```

Add the parameter and attribute:

```python
vector_memory: MemoryEngine | None = None,
```

```python
self.vector_memory = vector_memory
```

In `_commit_draft`, after existing Markdown writes succeed, schedule ingest requests by returning committed entries to `consolidate()`. Keep the async ingest outside `_commit_draft` because `_commit_draft` is synchronous.

Use this pattern:

```python
committed_entries = self._commit_draft(request.session, draft)
for entry in committed_entries:
    if self.vector_memory is not None:
        await self.vector_memory.ingest(
            MemoryIngestRequest(
                summary=entry,
                kind="event",
                source_ref=build_entry_source_ref(draft.source_ref, entry),
            )
        )
```

Make `_commit_draft` return `list[str]` containing only history entries that were actually appended to Markdown.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_vector_memory.py::test_markdown_consolidation_ingests_vector_memory_after_commit -q
uv run pytest tests/test_session_memory_runtime.py -q
```

Expected: PASS.

## Task 4: Runtime Retrieval Injection

**Files:**

- Modify: `amadeus/runtime.py`
- Test: `tests/test_runtime_vector_memory.py`

- [ ] **Step 1: Add runtime injection tests**

Create `tests/test_runtime_vector_memory.py`:

```python
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from amadeus.memory_engine import MemoryIngestRequest, MemoryQuery
from amadeus.provider import LLMProvider, LLMProviderConfig
from amadeus.runtime import PassiveRuntime
from amadeus.session import SessionManager
from amadeus.vector_memory import VectorMemoryEngine, VectorMemoryStore


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "Amadeus" in text or "检索" in text else [0.0, 1.0, 0.0]


class FakeCompletions:
    def __init__(self) -> None:
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="assistant reply"))],
            usage={},
        )


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def test_runtime_retrieves_memory_into_context_frame(tmp_path):
    vector = VectorMemoryEngine(
        store=VectorMemoryStore(tmp_path / "vector_memory.db"),
        embedding_provider=FakeEmbeddingProvider(),
    )
    asyncio.run(
        vector.ingest(
            MemoryIngestRequest(
                summary="[2026-06-06 10:00] 用户确认正在迁移 Amadeus 检索记忆。",
                source_ref='["chat:1:0"]',
            )
        )
    )
    client = FakeClient()
    provider = LLMProvider(LLMProviderConfig(api_key="secret", model="fake"), client=client)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path),
        memory_engine=vector,
    )

    result = asyncio.run(runtime.run_turn(session_key="chat:1", user_message="Amadeus 检索做到哪了？"))

    sent_messages = client.completions.calls[0]["messages"]
    assert result.assistant_response == "assistant reply"
    assert any("Retrieved Memory" in message["content"] for message in sent_messages)
    assert not any(
        message["role"] == "system" and "Retrieved Memory" in message["content"]
        for message in sent_messages
    )


def test_runtime_continues_when_memory_retrieval_fails(tmp_path):
    class BrokenMemory:
        async def query(self, query: MemoryQuery):
            raise RuntimeError("embedding unavailable")

        def render_context_block(self, result):
            return "should not render"

    client = FakeClient()
    provider = LLMProvider(LLMProviderConfig(api_key="secret", model="fake"), client=client)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path),
        memory_engine=BrokenMemory(),
    )

    result = asyncio.run(runtime.run_turn(session_key="chat:1", user_message="hello"))

    assert result.assistant_response == "assistant reply"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/test_runtime_vector_memory.py -q
```

Expected: FAIL because `PassiveRuntime` has no `memory_engine`.

- [ ] **Step 3: Wire retrieval into runtime**

Modify `amadeus/runtime.py`:

```python
from amadeus.memory_engine import MemoryEngine, MemoryQuery
```

Add dataclass field:

```python
memory_engine: MemoryEngine | None = None
```

Before building `RuntimeContext`, add:

```python
resolved_retrieved_memory = retrieved_memory
if resolved_retrieved_memory is None and self.memory_engine is not None:
    try:
        memory_result = await self.memory_engine.query(MemoryQuery(text=user_message))
        resolved_retrieved_memory = self.memory_engine.render_context_block(memory_result)
    except Exception:
        resolved_retrieved_memory = None
```

Then pass:

```python
retrieved_memory=resolved_retrieved_memory,
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_runtime_vector_memory.py -q
uv run pytest tests/test_runtime.py -q
```

Expected: PASS.

## Task 5: Bootstrap Configuration

**Files:**

- Modify: `amadeus/bootstrap.py`
- Test: `tests/test_bootstrap_vector_memory.py`

- [ ] **Step 1: Add bootstrap tests**

Create `tests/test_bootstrap_vector_memory.py`:

```python
from __future__ import annotations

from amadeus.bootstrap import load_runtime_config


def test_vector_memory_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AMADEUS_VECTOR_MEMORY_ENABLED", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")

    config = load_runtime_config(workspace_root=tmp_path)

    assert config.vector_memory_enabled is False


def test_vector_memory_config_can_be_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_VECTOR_MEMORY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    config = load_runtime_config(workspace_root=tmp_path)

    assert config.vector_memory_enabled is True
    assert config.embedding_model == "text-embedding-3-small"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/test_bootstrap_vector_memory.py -q
```

Expected: FAIL because `RuntimeConfig` has no vector memory fields.

- [ ] **Step 3: Add config fields**

Modify `RuntimeConfig`:

```python
vector_memory_enabled: bool = False
embedding_model: str | None = None
vector_memory_top_k: int = 8
```

In `load_runtime_config()`, parse:

```python
vector_enabled = (_config_value("AMADEUS_VECTOR_MEMORY_ENABLED", file_values) or "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
embedding_model = _config_value("OPENAI_EMBEDDING_MODEL", file_values)
top_k = _int_config("AMADEUS_VECTOR_MEMORY_TOP_K", file_values, default=8)
if vector_enabled and not embedding_model:
    raise ValueError("Missing Amadeus runtime config: OPENAI_EMBEDDING_MODEL")
```

Pass these values into `RuntimeConfig`.

- [ ] **Step 4: Build vector memory when enabled**

In `build_passive_app()`, import:

```python
from amadeus.vector_memory import OpenAIEmbeddingConfig, OpenAIEmbeddingProvider, VectorMemoryEngine, VectorMemoryStore
```

Create:

```python
vector_memory = None
if config.vector_memory_enabled and config.embedding_model:
    embedding_provider = OpenAIEmbeddingProvider(
        OpenAIEmbeddingConfig(
            api_key=config.provider.api_key,
            base_url=config.provider.base_url,
            model=config.embedding_model,
            timeout_seconds=config.provider.timeout_seconds,
        )
    )
    vector_memory = VectorMemoryEngine(
        store=VectorMemoryStore(config.workspace_root / "memory" / "vector_memory.db"),
        embedding_provider=embedding_provider,
    )
```

Pass `vector_memory` into both `build_markdown_memory_runtime(..., vector_memory=vector_memory)` and `PassiveRuntime(..., memory_engine=vector_memory)`.

- [ ] **Step 5: Verify**

Run:

```bash
uv run pytest tests/test_bootstrap_vector_memory.py -q
uv run pytest tests/test_bootstrap.py -q
```

Expected: PASS.

## Task 6: Full Verification

**Files:**

- All modified files.

- [ ] **Step 1: Run all tests**

Run:

```bash
uv run pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Inspect context-frame behavior manually**

Run a small runtime test or use `dev_utils/inspect_context.py` after inserting one vector memory item.

Expected:

```text
Retrieved Memory appears inside <system-reminder data-system-context-frame="true">
Retrieved Memory does not appear in the system message
```

- [ ] **Step 3: Review fake boundary**

Check that fake embedding providers only appear in tests.

Run:

```bash
rg "FakeEmbedding|fake embedding|Fake.*Embedding" amadeus tests
```

Expected: matches only under `tests/`.

- [ ] **Step 4: Commit**

```bash
git add amadeus tests docs/superpowers/specs/2026-06-06-vector-memory-retrieval-design.md docs/superpowers/plans/2026-06-06-vector-memory-retrieval.md
git commit -m "feat: add vector memory retrieval plan"
```
