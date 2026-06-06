# Vector Memory Retrieval Design

## Goal

Migrate Akashic's memory2 retrieval pattern into Amadeus as a narrow v1 event retrieval layer.

Markdown memory remains the human-readable long-term record. Vector memory adds a structured, queryable store for selected consolidated event entries, with evidence that can be resolved back to original session messages.

## Current State

Amadeus has already completed the foundation this layer needs:

- `amadeus.context` routes `retrieved_memory` into the context frame, not the system prompt.
- `amadeus.session` persists stable message ids such as `chat:1:0`.
- `amadeus.session.fetch_messages()` can resolve JSON-style `source_ref` values back to original messages.
- `amadeus.memory.MarkdownMemoryMaintenance` writes `HISTORY.md`, `PENDING.md`, `RECENT_CONTEXT.md`, and records consolidation source refs.
- `amadeus.runtime.PassiveRuntime` commits turns and emits `TurnCommitted`.
- The full current test suite passes: `67 passed`.

That means the next missing capability is not another prompt layer. It is retrieval: turning durable memory entries into evidence-backed context for future turns.

## Akashic Reference

Akashic corresponding implementation:

- `memory2/models.py`
  - `MemoryItem` shape: id, memory_type, summary, embedding, source_ref, happened_at, reinforcement, extra_json.
- `memory2/store.py`
  - SQLite-backed memory item store.
  - Deduplication by content hash and memory type.
  - Active/superseded status.
  - Vector search with keyword fallback.
- `memory2/memorizer.py`
  - Ingests consolidation output into memory2.
  - Saves event entries with `source_ref`.
  - Deduplicates repeated consolidation sources.
- `memory2/retriever.py`
  - Unified retrieval entry point.
  - Vector lane plus keyword lane.
  - Formats injection blocks for prompt use.
- `plugins/default_memory/engine.py`
  - Wraps memory2 behind a memory engine API.
  - Produces records with evidence refs.
- `agent/tools/recall_memory.py`
  - Tool-facing recall API, including citation requirements.

Amadeus should migrate the design pattern, not Akashic's full plugin/tool/dashboard shape.

## Non-Goals

This stage does not implement:

- LLM tool runtime.
- `recall_memory` as an OpenAI tool.
- `forget_memory` or undo.
- query rewriting / HyDE / sufficiency checking.
- plugin lifecycle.
- dashboard UI.
- proactive memory retrieval.
- automatic behavior/profile extraction beyond the existing Markdown consolidation output.
- fake production embeddings.

Testing may use fake embedding providers to isolate external services. Production code must use an injectable real embedding provider interface.

## Architecture

The first Amadeus vector memory layer migrates only Akashic's consolidation event lane:

```text
MarkdownMemoryMaintenance.consolidate()
-> ConsolidationCommitted-style callback inside Amadeus
-> VectorMemoryEngine.ingest(MemoryIngestRequest(kind="event", source_ref="<base>#h:<digest>"))
-> VectorMemoryStore.upsert_item(...)

PassiveRuntime.run_turn()
-> VectorMemoryEngine.query(raw_user_message)
-> RuntimeContext.retrieved_memory
-> PromptAssembler context frame
-> provider.chat(messages)
```

The important boundary is source ownership:

- Markdown memory owns readable summaries and long-term maintenance.
- Session DB owns raw messages.
- Vector memory owns indexed retrieval records.
- Evidence links vector records back to session message ids.

## Components

### `amadeus.memory_engine`

Defines Amadeus' small memory engine API:

```python
MemoryRecord
EvidenceRef
MemoryQuery
MemoryQueryResult
MemoryIngestRequest
MemoryIngestResult
MemoryEngine
```

This keeps the rest of the runtime from depending on a SQLite implementation.

### `amadeus.vector_memory`

Owns storage and retrieval:

- `VectorMemoryItem`
- `EmbeddingProvider`
- `OpenAIEmbeddingProvider`
- `VectorMemoryStore`
- `VectorMemoryEngine`

The store uses SQLite and stores embeddings as JSON for the first version. This avoids adding `sqlite-vec` / `numpy` as core dependencies while keeping the interface compatible with a future vector extension.

Retrieval has two lanes:

- cosine similarity over embeddings.
- keyword fallback over summaries.

The first version keeps scoring simple and testable. The core requirement is evidence correctness, not perfect semantic recall.

### `amadeus.memory`

After Markdown consolidation succeeds, Amadeus should optionally ingest each committed history entry into vector memory as an `event`.

This must happen after the Markdown draft has committed, because a failed Markdown consolidation should not create vector-only memories.

Each committed entry uses Akashic-style per-entry evidence:

```text
<base_source_ref>#h:<sha1(entry)[:12]>
```

This keeps entries from the same consolidation window independently deduplicatable while preserving the base message-id source ref for `fetch_messages`.

### `amadeus.runtime`

`PassiveRuntime.run_turn()` should accept an optional memory engine. If present and no explicit `retrieved_memory` was supplied, it retrieves memory for the current user message and passes the rendered block through `RuntimeContext.retrieved_memory`.

This preserves the existing debug escape hatch: callers can still provide `retrieved_memory` manually.

### `amadeus.bootstrap`

Builds vector memory when embedding config is available.

Suggested config:

```text
OPENAI_EMBEDDING_MODEL
AMADEUS_VECTOR_MEMORY_ENABLED
AMADEUS_VECTOR_MEMORY_TOP_K
```

The default should be disabled unless config is explicit. This avoids silently making network embedding calls in tests or local development.

## Data Flow

### Ingest

```text
session old messages
-> Markdown consolidation JSON
-> history_entries
-> HISTORY.md append with source_ref
-> VectorMemoryEngine.ingest(summary, source_ref="<base>#h:<digest>")
-> embedding provider
-> SQLite upsert by content_hash + kind
```

The base `source_ref` must stay the same evidence anchor used by Markdown writes. Vector memory appends `#h:<digest>` per entry for idempotency.

### Retrieve

```text
current user message, used as the raw v1 query
-> embedding provider
-> vector search
-> keyword fallback
-> dedupe / rank
-> MemoryQueryResult(records, trace)
-> rendered retrieved_memory block
-> context frame
```

Records should include:

- item id.
- kind.
- summary.
- score.
- source_ref.
- evidence refs.

Query rewrite, HyDE auxiliary queries, RRF fusion, and query gating are deferred to a later retrieval-quality stage.

### Evidence Resolution

Evidence resolution should reuse:

```python
amadeus.session.fetch_messages(store, source_ref=..., context=N)
```

Vector memory must not invent facts. If a retrieved summary is used for an answer, the source messages must remain resolvable.

## Error Handling

- Embedding failure during ingest should not roll back committed Markdown memory.
- Embedding failure during retrieval should return an empty result with a trace reason.
- Duplicate `source_ref` ingestion should be idempotent.
- Empty query should return an empty result.
- Missing vector memory config should disable automatic retrieval.
- Retrieval results must never enter the system prompt.

## Testing Strategy

Use fake embedding only in tests.

Minimum coverage:

- store schema initializes.
- ingest writes one event memory with source_ref.
- duplicate source_ref does not create duplicate items.
- retrieval can find a semantically close item with fake embeddings.
- keyword fallback works when embedding retrieval returns nothing.
- rendered retrieval block includes evidence metadata.
- `PassiveRuntime` injects retrieved memory into context frame.
- vector ingest only runs after Markdown consolidation succeeds.
- failed embedding does not break `run_turn()`.

## Tradeoffs

### SQLite JSON embeddings now vs `sqlite-vec` now

JSON embeddings are slower but keep this stage dependency-light and easy to test. `sqlite-vec` can be migrated later behind the same `VectorMemoryStore` interface.

This choice fails if the memory store grows large enough that full-scan cosine search becomes slow. At that point the store implementation should change, not the engine API.

### Real embedding interface vs fake first

Akashic has a real embedder path, so Amadeus should not make fake embeddings part of production architecture. Tests can use fakes because they isolate external network behavior.

### Retrieval before tools

Doing retrieval before tool runtime lets Amadeus improve passive answers without opening tool-execution risk. Tool-facing `recall_memory` should come later, after the Tool Runtime stage.

## Acceptance Criteria

- Consolidated history entries can be ingested into vector memory with stable source refs.
- Retrieval returns records with evidence that resolves to session messages.
- `retrieved_memory` appears in the context frame and not the system prompt.
- Automatic retrieval can be disabled by config.
- Existing prompt/session/Markdown memory tests still pass.
- New vector memory tests pass without network calls.
