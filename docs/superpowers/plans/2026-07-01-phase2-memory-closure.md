# Phase 2 Memory Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Phase 2 so Amadeus can credibly demonstrate an Akashic-inspired memory system with long-term write, retrieval, source references, correction, forgetting, ranking, context injection, and runnable verification evidence.

**Architecture:** Keep the existing Phase 1 runtime boundaries intact. Extend the current `MarkdownMemoryRuntime -> AkashicMemoryEngine -> BeforeTurn context injection -> public memory tools` path instead of inventing a parallel subsystem. Treat Akashic `memory2/retriever.py` as the reference for retrieval contracts and traceability, but keep Amadeus smaller and interview-oriented.

**Tech Stack:** Python 3.11, SQLite, existing `SessionStore`, `MarkdownMemoryRuntime`, `AkashicMemoryEngine`, pytest

---

## File Map

- Modify: `amadeus/memory/vector.py`
  Retrieval core, SQLite query filters, ranking, context block rendering, retrieval trace, mutation lifecycle.
- Modify: `amadeus/memory/engine.py`
  Shared memory protocol types for correction/mutation trace.
- Modify: `amadeus/memory/markdown.py`
  Markdown consolidation lifecycle, pending/profile/preference/correction ingest path into long-term memory.
- Modify: `amadeus/runtime/before_turn.py`
  Capture retrieval trace at the public runtime boundary.
- Modify: `amadeus/runtime/lifecycle.py`
  Carry memory trace through typed lifecycle context.
- Modify: `amadeus/runtime/passive.py`
  Expose retrieval trace on the public turn result.
- Modify: `amadeus/app/cli.py`
  Print memory retrieval trace in `--trace` mode as interview evidence.
- Modify: `amadeus/app/bootstrap.py`
  Register new memory tool and keep Phase 2 behavior on the default app path.
- Modify: `amadeus/prompts/__init__.py`
  Update behavior rules so correction flow uses the new public tool contract.
- Modify: `amadeus/tools/__init__.py`
  Export the new tool.
- Create: `amadeus/tools/correct_memory.py`
  Public correction tool: verify source_ref, supersede old memory, write corrected memory, return trace.
- Test: `tests/memory/test_memory_ranking.py`
  Retrieval, ranking, filters, trace, lifecycle storage behavior.
- Test: `tests/memory/test_session_memory_runtime.py`
  Markdown consolidation and pending/profile/preference/correction lifecycle.
- Test: `tests/memory/test_memory_retrieval_acceptance.py`
  Public recall -> fetch -> correct/forget -> follow-up recall acceptance behavior.
- Test: `tests/memory/test_runtime_memory.py`
  Runtime context injection and memory trace exposure.
- Test: `tests/app/test_cli.py`
  CLI `--trace` output for retrieval evidence.
- Test: `tests/app/test_bootstrap_tool_runtime.py`
  Tool registry exposes the full Phase 2 memory path.
- Modify: `docs/interview/resume-claim-gap-audit.md`
  Move completed Phase 2 claims from gap to evidence.
- Modify: `docs/interview/interview-delivery-roadmap.md`
  Mark Phase 2 accepted only after verification lands.

### Task 1: Harden retrieval filters, ranking, and trace

**Resume claim supported:** “Akashic-inspired memory system with retrieval, source references, and explainable ranking.”

**Public behavior proof:** `recall_memory` can filter by time, carries score signals/trace, and prioritizes reinforced memories deterministically.

**Akashic reference:** `../akashic-agent/memory2/retriever.py` retrieval lanes, RRF, and injection trace mentality.

**Files:**
- Modify: `amadeus/memory/vector.py`
- Test: `tests/memory/test_memory_ranking.py`

- [ ] **Step 1: Write the failing tests for time-window filtering and reinforcement-aware ranking**

```python
def test_long_term_memory_query_respects_happened_at_window(tmp_path):
    store = MemoryStore(tmp_path / "long_term_memory.db")
    engine = AkashicMemoryEngine(store=store, embedding_provider=FakeEmbeddingProvider())
    asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="[2026-06-01 09:00] 用户开始实现 Phase 2。",
                kind="event",
                source_ref='["chat:1:0"]#h:early',
                happened_at="2026-06-01T09:00:00",
            )
        )
    )
    asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="[2026-06-20 09:00] 用户完成 Phase 2 smoke。",
                kind="event",
                source_ref='["chat:1:1"]#h:late',
                happened_at="2026-06-20T09:00:00",
            )
        )
    )

    result = asyncio.run(
        engine.query(
            MemoryQuery(
                text="Phase 2",
                time_start=datetime.fromisoformat("2026-06-10T00:00:00"),
                time_end=datetime.fromisoformat("2026-06-30T00:00:00"),
            )
        )
    )

    assert [record.source_ref for record in result.records] == ['["chat:1:1"]#h:late']
    assert result.trace["time_filters"] == {
        "start": "2026-06-10T00:00:00",
        "end": "2026-06-30T00:00:00",
    }


def test_long_term_memory_reinforcement_breaks_same_lane_ties(tmp_path):
    store = MemoryStore(tmp_path / "long_term_memory.db")
    engine = AkashicMemoryEngine(store=store, embedding_provider=FakeEmbeddingProvider())

    first = MemoryIngestRequest(
        summary="用户偏好中文输出",
        kind="preference",
        source_ref='["chat:1:0"]#h:pref1',
    )
    second = MemoryIngestRequest(
        summary="用户偏好中文输出",
        kind="preference",
        source_ref='["chat:1:1"]#h:pref2',
    )

    asyncio.run(engine.ingest(first))
    asyncio.run(engine.ingest(second))
    result = asyncio.run(engine.query(MemoryQuery(text="中文输出", kinds=("preference",))))

    assert result.records[0].signals["reinforcement"] >= 2
    assert "reinforcement_boost" in result.records[0].signals
    assert result.trace["records"][0]["id"] == result.records[0].id
```

- [ ] **Step 2: Run the narrow retrieval tests and confirm they fail first**

Run: `.\.venv\Scripts\python.exe -m pytest tests/memory/test_memory_ranking.py -k "time_window or reinforcement" -v`

Expected: FAIL because `MemoryStore.list_active()` ignores `time_start/time_end`, and `signals` / `trace` do not yet expose reinforcement-aware ranking.

- [ ] **Step 3: Implement store filtering, ranking boost, and trace detail in `amadeus/memory/vector.py`**

```python
def list_active(
    self,
    *,
    kinds: tuple[str, ...] = (),
    time_start: datetime | None = None,
    time_end: datetime | None = None,
) -> list[dict[str, Any]]:
    clauses = ["status = 'active'"]
    params: list[Any] = []
    clean_kinds = tuple(kind.strip() for kind in kinds if kind.strip())
    if clean_kinds:
        placeholders = ",".join("?" for _ in clean_kinds)
        clauses.append(f"kind IN ({placeholders})")
        params.extend(clean_kinds)
    if time_start is not None:
        clauses.append("(happened_at IS NOT NULL AND happened_at >= ?)")
        params.append(time_start.isoformat())
    if time_end is not None:
        clauses.append("(happened_at IS NOT NULL AND happened_at <= ?)")
        params.append(time_end.isoformat())
    with self._lock:
        rows = self._conn.execute(
            f'''
            SELECT *
            FROM memory_items
            WHERE {" AND ".join(clauses)}
            ORDER BY updated_at DESC
            ''',
            tuple(params),
        ).fetchall()
    return [_row_to_item(row) for row in rows]


def _reinforcement_boost(value: int) -> float:
    reinforcement = max(1, int(value))
    return min(reinforcement - 1, 10) * 0.0025


def _build_record(
    item_id: str,
    row_map: dict[str, dict[str, Any]],
    vec_scores: dict[str, float],
    kw_scores: dict[str, float],
    rrf_score: float,
) -> MemoryRecord:
    row = row_map[item_id]
    reinforcement = int(row.get("reinforcement") or 1)
    reinforcement_boost = _reinforcement_boost(reinforcement)
    lanes = [
        name
        for name, score in (
            ("vector", vec_scores.get(item_id, 0.0)),
            ("lexical", kw_scores.get(item_id, 0.0)),
        )
        if score > 0
    ]
    return MemoryRecord(
        id=item_id,
        kind=str(row["kind"]),
        summary=str(row["summary"]),
        score=rrf_score + reinforcement_boost,
        source_ref=str(row["source_ref"]),
        evidence=_evidence_from_source_ref(str(row["source_ref"])),
        signals={
            "lanes": lanes,
            "vector_score": vec_scores.get(item_id, 0.0),
            "lexical_score": kw_scores.get(item_id, 0.0),
            "rrf_score": rrf_score,
            "reinforcement": reinforcement,
            "reinforcement_boost": reinforcement_boost,
            "extra": dict(row.get("extra") or {}),
        },
    )


async def query(self, query: MemoryQuery) -> MemoryQueryResult:
    rows = self.store.list_active(
        kinds=kinds,
        time_start=query.time_start,
        time_end=query.time_end,
    )
    trace = {
        "intent": query.intent,
        "queries": queries,
        "candidate_count": len(rows),
        "lane_counts": lane_counts,
        "fused_count": sum(len(items) for items in result_sets),
        "record_count": len(records),
        "time_filters": {
            "start": query.time_start.isoformat() if query.time_start else None,
            "end": query.time_end.isoformat() if query.time_end else None,
        },
        "records": [
            {
                "id": record.id,
                "kind": record.kind,
                "score": record.score,
                "source_ref_present": bool(record.source_ref),
                "evidence_count": len(record.evidence),
                "signals": dict(record.signals),
            }
            for record in records
        ],
        "fallbacks": _dedupe_texts(fallbacks),
        "errors": errors,
    }
    return MemoryQueryResult(records=records, trace=trace)
```

- [ ] **Step 4: Re-run the focused retrieval suite and then the whole memory vector suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/memory/test_memory_ranking.py -v`

Expected: PASS, including the new time filter and reinforcement trace tests.

- [ ] **Step 5: Commit the retrieval-core slice**

```bash
git add amadeus/memory/vector.py tests/memory/test_memory_ranking.py
git commit -m "feat: harden memory retrieval filters and ranking trace"
```

### Task 2: Ingest markdown profile/preference/correction data into long-term memory

**Resume claim supported:** “Long-term memory write and retrieval form a closed loop instead of only event recall.”

**Public behavior proof:** user profile/preferences captured in markdown become queryable memory candidates and can enter context via `MemoryEngine`, not only raw event history.

**Akashic reference:** markdown-like durable memory plus retriever-friendly typed memory lanes; adapt the contract, not the folder structure.

**Files:**
- Modify: `amadeus/memory/markdown.py`
- Modify: `amadeus/memory/vector.py`
- Test: `tests/memory/test_session_memory_runtime.py`
- Test: `tests/memory/test_memory_ranking.py`

- [ ] **Step 1: Write the failing tests for pending-item ingestion and retrieval by kind**

```python
def test_consolidation_ingests_pending_profile_and_preference_items(tmp_path):
    manager, session = _session_ready_for_consolidation(tmp_path)
    vector = AkashicMemoryEngine(
        store=MemoryStore(tmp_path / "long_term_memory.db"),
        embedding_provider=FakeEmbeddingProvider(),
    )
    maintenance = MarkdownMemoryMaintenance(
        store=MarkdownMemoryStore(tmp_path),
        provider=FakeConsolidationProvider(
            """
            {
              "history_entries": [{"summary":"[2026-06-06 10:00] 用户推进 Phase 2。"}],
              "pending_items": [
                {"tag":"identity","content":"用户正在把 Amadeus 打造成面试项目"},
                {"tag":"preference","content":"用户偏好中文解释"},
                {"tag":"correction","content":"更正：用户不是在做 Telegram，而是先做 Memory Phase 2"}
              ]
            }
            """
        ),
        model="fake",
        keep_count=4,
        session_manager=manager,
        long_term_memory=vector,
    )

    asyncio.run(maintenance.consolidate(ConsolidateRequest(session=session)))

    profile = asyncio.run(vector.query(MemoryQuery(text="面试项目", kinds=("profile",))))
    preference = asyncio.run(vector.query(MemoryQuery(text="中文解释", kinds=("preference",))))
    correction = asyncio.run(vector.query(MemoryQuery(text="先做 Memory Phase 2", kinds=("fact",))))

    assert profile.records[0].kind == "profile"
    assert preference.records[0].kind == "preference"
    assert correction.records[0].signals["extra"]["lifecycle"] == "correction"
```

- [ ] **Step 2: Run the markdown/vector lifecycle tests and confirm the new behavior is currently missing**

Run: `.\.venv\Scripts\python.exe -m pytest tests/memory/test_session_memory_runtime.py tests/memory/test_memory_ranking.py -k "pending_profile or correction" -v`

Expected: FAIL because `_ingest_long_term_memory()` only ingests `history_entries` as `event`.

- [ ] **Step 3: Implement pending-item mapping and vector ingest requests in `amadeus/memory/markdown.py`**

```python
def _pending_line_to_ingest_request(
    source_ref: str,
    line: str,
) -> MemoryIngestRequest | None:
    match = re.match(r"^- \[(?P<tag>[a-z_]+)\] (?P<content>.+)$", line.strip())
    if not match:
        return None
    tag = match.group("tag")
    content = match.group("content").strip()
    if not content:
        return None
    kind_map = {
        "identity": "profile",
        "preference": "preference",
        "key_info": "fact",
        "health_long_term": "fact",
        "requested_memory": "fact",
        "agent_context": "constraint",
        "correction": "fact",
    }
    extra = {"memory_tag": tag}
    if tag == "correction":
        extra["lifecycle"] = "correction"
    return MemoryIngestRequest(
        summary=content,
        kind=kind_map[tag],
        source_ref=build_entry_source_ref(source_ref, line),
        extra=extra,
    )


async def _ingest_long_term_memory(
    self,
    draft: _ConsolidationDraft,
    entries: list[str],
) -> dict[str, Any]:
    trace = {"attempted": 0, "succeeded": 0, "failed": 0, "errors": []}
    if self.long_term_memory is None:
        return trace
    requests = [
        *[
            MemoryIngestRequest(
                summary=entry,
                kind="event",
                source_ref=build_entry_source_ref(draft.source_ref, entry),
            )
            for entry in entries
        ],
        *[
            request
            for request in (
                _pending_line_to_ingest_request(draft.source_ref, line)
                for line in draft.pending_items.splitlines()
            )
            if request is not None
        ],
    ]
    for request in requests:
        trace["attempted"] += 1
        try:
            result = await self.long_term_memory.ingest(request)
        except Exception as error:
            trace["failed"] += 1
            trace["errors"].append(
                {
                    "source_ref": request.source_ref,
                    "kind": request.kind,
                    "error": str(error),
                }
            )
            continue
        if result.status in {"new", "reinforced", "skipped"}:
            trace["succeeded"] += 1
            continue
        trace["failed"] += 1
        trace["errors"].append(
            {
                "source_ref": request.source_ref,
                "kind": request.kind,
                "status": result.status,
            }
        )
    return trace
```

- [ ] **Step 4: Extend context rendering expectations for profile/preference kinds**

```python
def render_context_block(self, result: MemoryQueryResult) -> str:
    sections = (
        ("Applicable Procedures", {"procedure", "constraint"}),
        ("User Profile", {"profile", "preference", "fact"}),
        ("Relevant History", {"event"}),
    )
    selected_parts: list[str] = []
    for title, kinds in sections:
        entries = [
            _format_context_record(record)
            for record in result.records
            if record.kind in kinds
        ]
        if entries:
            selected_parts.append(f"## {title}\n" + "\n".join(entries))
    return "\n\n".join(selected_parts)
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/memory/test_session_memory_runtime.py tests/memory/test_memory_ranking.py -v`

Expected: PASS, and `long_term_memory_ingest.attempted` now counts both history and pending-derived records.

- [ ] **Step 5: Commit the markdown/vector closed-loop slice**

```bash
git add amadeus/memory/markdown.py amadeus/memory/vector.py tests/memory/test_session_memory_runtime.py tests/memory/test_memory_ranking.py
git commit -m "feat: ingest markdown profile and preference memory into vector store"
```

### Task 3: Add a public `correct_memory` tool and supersession lifecycle

**Resume claim supported:** “Memory system supports correction and forgetting with source-backed verification.”

**Public behavior proof:** the runtime exposes a correction tool that supersedes the old memory id, writes a corrected replacement, and leaves original session messages fetchable.

**Akashic reference:** correction is a lifecycle mutation on retrieved memory, not direct storage editing from the proactive/runtime layer.

**Files:**
- Create: `amadeus/tools/correct_memory.py`
- Modify: `amadeus/memory/engine.py`
- Modify: `amadeus/memory/vector.py`
- Modify: `amadeus/app/bootstrap.py`
- Modify: `amadeus/prompts/__init__.py`
- Modify: `amadeus/tools/__init__.py`
- Test: `tests/memory/test_memory_retrieval_acceptance.py`
- Test: `tests/app/test_bootstrap_tool_runtime.py`

- [ ] **Step 1: Write the failing acceptance tests for correction lifecycle**

```python
def test_correct_memory_tool_supersedes_old_item_and_creates_replacement(tmp_path):
    manager, engine, memory_id = _memory_fixture(tmp_path)
    tool = CorrectMemoryTool(memory_engine=engine)

    fetched = FetchMessagesTool(store=manager.store).execute(source_ref='["chat:1:0","chat:1:1"]')
    assert fetched.output["count"] == 2

    corrected = asyncio.run(
        tool.execute(
            memory_id=memory_id,
            corrected_summary="用户正在实现完整的 Phase 2 memory closure",
            source_ref='["chat:1:0","chat:1:1"]#h:acceptance',
            kind="event",
        )
    )
    recalled = asyncio.run(RecallMemoryTool(memory_engine=engine).execute(query="Phase 2 memory closure"))

    assert corrected.output["superseded_id"] == memory_id
    assert corrected.output["replacement_id"] is not None
    assert recalled.output["items"][0]["id"] == corrected.output["replacement_id"]


def test_correct_memory_tool_rejects_source_ref_mismatch(tmp_path):
    _, engine, memory_id = _memory_fixture(tmp_path)
    tool = CorrectMemoryTool(memory_engine=engine)

    result = asyncio.run(
        tool.execute(
            memory_id=memory_id,
            corrected_summary="错误修正",
            source_ref='["chat:999:0"]#h:wrong',
        )
    )

    assert result.is_error is True
    assert result.output["error"] == "source_ref does not match target memory"
```

- [ ] **Step 2: Run the public-memory acceptance tests and confirm the missing tool / lifecycle**

Run: `.\.venv\Scripts\python.exe -m pytest tests/memory/test_memory_retrieval_acceptance.py tests/app/test_bootstrap_tool_runtime.py -k "correct_memory or correction" -v`

Expected: FAIL because `CorrectMemoryTool` does not exist, the tool registry does not expose it, and the vector store cannot produce replacement lifecycle trace.

- [ ] **Step 3: Extend the memory protocol and vector store mutation helpers**

```python
@dataclass(frozen=True)
class MemoryMutationResult:
    accepted: bool = False
    status: str = "skipped"
    affected_ids: list[str] = field(default_factory=list)
    missing_ids: list[str] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


def get_item_by_id(self, item_id: str) -> dict[str, Any] | None:
    rows = self.get_items_by_ids([item_id])
    return rows[0] if rows else None


def mark_superseded_batch(
    self,
    ids: list[str],
    *,
    replacement_id: str | None = None,
    reason: str = "forget",
) -> None:
    if not ids:
        return
    now = datetime.now().astimezone().isoformat()
    indexed = {item["id"]: item for item in self.get_items_by_ids(ids)}
    payloads: list[tuple[str, str, str]] = []
    for item_id in ids:
        item = indexed.get(item_id)
        if item is None:
            continue
        extra = dict(item.get("extra") or {})
        extra.update(
            {
                "superseded_reason": reason,
                "replacement_id": replacement_id,
                "superseded_at": now,
            }
        )
        payloads.append((now, json.dumps(extra, ensure_ascii=False), item_id))
    with self._lock:
        self._conn.executemany(
            """
            UPDATE memory_items
            SET status = 'superseded',
                updated_at = ?,
                extra_json = ?
            WHERE id = ?
            """,
            payloads,
        )
        self._conn.commit()
```

- [ ] **Step 4: Implement `CorrectMemoryTool` and wire it through bootstrap/prompt rules**

```python
@dataclass
class CorrectMemoryTool:
    memory_engine: MemoryEngine | None
    name: str = "correct_memory"
    description: str = (
        "用 recall_memory 返回的 memory id 更正一条长期记忆。"
        "调用前必须先用 fetch_messages 核对原始 source_ref。"
    )

    async def execute(self, **kwargs: object) -> ToolResult:
        if self.memory_engine is None:
            return ToolResult(tool_name=self.name, output={"error": "long-term memory is not configured"}, is_error=True)
        memory_id = str(kwargs.get("memory_id") or "").strip()
        corrected_summary = str(kwargs.get("corrected_summary") or "").strip()
        source_ref = str(kwargs.get("source_ref") or "").strip()
        kind = str(kwargs.get("kind") or "event").strip()
        if not memory_id or not corrected_summary or not source_ref:
            return ToolResult(tool_name=self.name, output={"error": "memory_id, corrected_summary, and source_ref are required"}, is_error=True)

        engine = cast(AkashicMemoryEngine, self.memory_engine)
        target = engine.store.get_item_by_id(memory_id)
        if target is None:
            return ToolResult(tool_name=self.name, output={"error": "memory id not found", "memory_id": memory_id}, is_error=True)
        if str(target["source_ref"]).strip() != source_ref:
            return ToolResult(tool_name=self.name, output={"error": "source_ref does not match target memory", "memory_id": memory_id}, is_error=True)

        replacement = await engine.ingest(
            MemoryIngestRequest(
                summary=corrected_summary,
                kind=kind,
                source_ref=source_ref,
                extra={"lifecycle": "correction", "corrects": memory_id},
            )
        )
        engine.store.mark_superseded_batch([memory_id], replacement_id=replacement.item_id, reason="correction")
        return ToolResult(
            tool_name=self.name,
            output={
                "memory_id": memory_id,
                "superseded_id": memory_id,
                "replacement_id": replacement.item_id,
                "replacement_status": replacement.status,
            },
        )
```

```python
tool_registry.register(CorrectMemoryTool(memory_engine=long_term_memory))
```

```python
- 用户纠正记忆时，先定位 memory id，再用 fetch_messages 核对原文，最后调用 correct_memory 或 forget_memory。
```

- [ ] **Step 5: Run the full public-memory acceptance suite and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/memory/test_memory_retrieval_acceptance.py tests/app/test_bootstrap_tool_runtime.py -v`

Expected: PASS, including correction -> recall replacement -> original message still fetchable.

```bash
git add amadeus/memory/engine.py amadeus/memory/vector.py amadeus/tools/correct_memory.py amadeus/tools/__init__.py amadeus/app/bootstrap.py amadeus/prompts/__init__.py tests/memory/test_memory_retrieval_acceptance.py tests/app/test_bootstrap_tool_runtime.py
git commit -m "feat: add source-backed memory correction workflow"
```

### Task 4: Expose retrieval trace through runtime and CLI

**Resume claim supported:** “Behavior is proved with recorded traces, not only internal helpers.”

**Public behavior proof:** a passive turn can show injected/omitted ids, candidate counts, fallbacks, and retrieval plan in runtime/CLI trace output.

**Akashic reference:** retrieval trace belongs to the observable runtime path, not buried in helper-local state.

**Files:**
- Modify: `amadeus/runtime/lifecycle.py`
- Modify: `amadeus/runtime/before_turn.py`
- Modify: `amadeus/runtime/passive.py`
- Modify: `amadeus/app/cli.py`
- Test: `tests/memory/test_runtime_memory.py`
- Test: `tests/app/test_cli.py`

- [ ] **Step 1: Write the failing runtime and CLI trace tests**

```python
def test_runtime_exposes_memory_trace_on_turn_result(tmp_path):
    vector = AkashicMemoryEngine(
        store=MemoryStore(tmp_path / "long_term_memory.db"),
        embedding_provider=FakeEmbeddingProvider(),
    )
    asyncio.run(
        vector.ingest(
            MemoryIngestRequest(
                summary="[2026-06-06 10:00] 用户完成 Memory Phase 2 设计。",
                source_ref='["chat:1:0"]#h:trace',
            )
        )
    )
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(LLMProviderConfig(api_key="secret", model="fake"), client=FakeClient()),
        session_manager=SessionManager(tmp_path),
        memory_engine=vector,
    )

    result = asyncio.run(runtime.run_turn(session_key="chat:1", user_message="Memory Phase 2 到哪了？"))

    assert result.memory_trace["record_count"] >= 1
    assert result.memory_trace["injected_ids"]


def test_format_trace_includes_memory_retrieval_section():
    output = _format_trace(
        PassiveTurnResult(
            session_key="trace:1",
            user_message_id="trace:1:0",
            assistant_message_id="trace:1:1",
            assistant_response="done",
            context=SimpleNamespace(),
            tool_chain=[],
            context_retry={},
            memory_trace={
                "intent": "context",
                "candidate_count": 4,
                "record_count": 2,
                "fallbacks": ["lexical_only"],
                "injected_ids": ["mem_a"],
                "omitted_ids": ["mem_b"],
            },
        ),
        None,
    )

    assert "Memory intent:      context" in output
    assert "Memory candidates:  4" in output
    assert "Memory injected:    mem_a" in output
```

- [ ] **Step 2: Run the runtime/CLI tests and confirm the trace is not yet exposed**

Run: `.\.venv\Scripts\python.exe -m pytest tests/memory/test_runtime_memory.py tests/app/test_cli.py -k "memory_trace" -v`

Expected: FAIL because `BeforeTurnContext`, `PassiveTurnResult`, and CLI trace formatting do not carry memory retrieval trace yet.

- [ ] **Step 3: Carry memory trace through the typed runtime boundary**

```python
@dataclass
class BeforeTurnContext:
    session_key: str
    user_message: str
    history: list[Message]
    retrieved_memory: str | None
    memory_trace: dict[str, Any] = field(default_factory=dict)
    active_skills: list[str] = field(default_factory=list)
    runtime_metadata: dict[str, str] = field(default_factory=dict)
    extra_hints: list[str] = field(default_factory=list)
    abort_reply: str | None = None


@dataclass(frozen=True)
class PassiveTurnResult:
    session_key: str
    user_message_id: str
    assistant_message_id: str
    assistant_response: str
    context: ContextRenderResult
    provider_raw: Any = None
    tool_chain: list[dict[str, Any]] = field(default_factory=list)
    context_retry: dict[str, Any] = field(default_factory=dict)
    memory_trace: dict[str, Any] = field(default_factory=dict)
```

```python
@dataclass(frozen=True)
class _BeforeTurnContextBundle:
    session: Session
    history: tuple[Message, ...]
    retrieved_memory: str | None
    memory_trace: dict[str, Any]


async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
    memory_trace: dict[str, Any] = {}
    if retrieved_memory is None and self._memory_engine is not None:
        try:
            memory_result = await self._memory_engine.query(
                MemoryQuery(
                    text=frame.input.user_message,
                    intent="context",
                    context={
                        "history": history,
                        "session_key": frame.input.session_key,
                    },
                )
            )
            retrieved_memory = self._memory_engine.render_context_block(memory_result)
            memory_trace = dict(memory_result.trace)
        except Exception as error:
            memory_trace = {"errors": [f"context_query: {error}"], "record_count": 0}
            retrieved_memory = None
    frame.slots[_CONTEXT_BUNDLE_SLOT] = _BeforeTurnContextBundle(
        session=session,
        history=tuple(history),
        retrieved_memory=retrieved_memory,
        memory_trace=memory_trace,
    )
```

- [ ] **Step 4: Print the retrieval section in CLI trace and verify it end to end**

```python
memory_trace = getattr(result, "memory_trace", {}) or {}
if memory_trace:
    parts.append(f"  Memory intent:      {memory_trace.get('intent', 'N/A')}")
    parts.append(f"  Memory candidates:  {memory_trace.get('candidate_count', 0)}")
    parts.append(f"  Memory records:     {memory_trace.get('record_count', 0)}")
    injected = ",".join(memory_trace.get("injected_ids", [])) or "-"
    omitted = ",".join(memory_trace.get("omitted_ids", [])) or "-"
    fallbacks = ",".join(memory_trace.get("fallbacks", [])) or "-"
    parts.append(f"  Memory injected:    {injected}")
    parts.append(f"  Memory omitted:     {omitted}")
    parts.append(f"  Memory fallbacks:   {fallbacks}")
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/memory/test_runtime_memory.py tests/app/test_cli.py -v`

Expected: PASS, and the runtime now has a public retrieval evidence surface.

- [ ] **Step 5: Commit the runtime trace slice**

```bash
git add amadeus/runtime/lifecycle.py amadeus/runtime/before_turn.py amadeus/runtime/passive.py amadeus/app/cli.py tests/memory/test_runtime_memory.py tests/app/test_cli.py
git commit -m "feat: expose memory retrieval trace in runtime and cli"
```

### Task 5: Finish Phase 2 verification and interview docs

**Resume claim supported:** the repository has runnable evidence, not just implementation prose.

**Public behavior proof:** one command suite proves recall, source fetch, correction, forgetting, context injection, and CLI trace.

**Akashic reference:** none required beyond confirming behavior parity goals; this is Amadeus-specific delivery evidence.

**Files:**
- Modify: `docs/interview/resume-claim-gap-audit.md`
- Modify: `docs/interview/interview-delivery-roadmap.md`
- Test: full focused Phase 2 suite

- [ ] **Step 1: Add the focused Phase 2 verification command to the docs note and local checklist**

```markdown
Phase 2 verification command:
.\.venv\Scripts\python.exe -m pytest `
  tests/memory/test_memory_ranking.py `
  tests/memory/test_session_memory_runtime.py `
  tests/memory/test_memory_retrieval_acceptance.py `
  tests/memory/test_runtime_memory.py `
  tests/app/test_cli.py `
  tests/app/test_bootstrap_tool_runtime.py -v
```

- [ ] **Step 2: Run the full focused Phase 2 suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/memory/test_memory_ranking.py tests/memory/test_session_memory_runtime.py tests/memory/test_memory_retrieval_acceptance.py tests/memory/test_runtime_memory.py tests/app/test_cli.py tests/app/test_bootstrap_tool_runtime.py -v`

Expected: PASS. If any test fails, fix the code before touching the docs.

- [ ] **Step 3: Update the interview roadmap and gap audit only after tests pass**

```markdown
| 简历亮点 | 当前证据 | 面试口径 |
| --- | --- | --- |
| Akashic-inspired memory system with retrieval, source references, correction, and forgetting | `amadeus/memory/markdown.py`、`amadeus/memory/vector.py`、`amadeus/tools/recall_memory.py`、`amadeus/tools/correct_memory.py`、`amadeus/tools/forget_memory.py`、Phase 2 focused pytest suite | "我把长期记忆写入、SQLite 检索、source_ref 回源、更正、遗忘和 context injection 做成了统一闭环，并且能用 trace 和测试证明。" |
```

```markdown
## 阶段 2：完整记忆能力 ✅

- recall / fetch_messages / correct_memory / forget_memory 已形成公开行为闭环。
- reinforcement ranking、time filters、retrieval trace、context-frame injection 都有 focused tests。
```

- [ ] **Step 4: Re-run the two changed doc-adjacent smoke tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/memory/test_memory_retrieval_acceptance.py tests/app/test_cli.py -v`

Expected: PASS again after the docs-only follow-up.

- [ ] **Step 5: Commit the Phase 2 closeout**

```bash
git add docs/interview/resume-claim-gap-audit.md docs/interview/interview-delivery-roadmap.md
git commit -m "docs: close phase 2 memory delivery evidence"
```

## Self-Review

- Spec coverage:
  - Markdown memory lifecycle: Task 2
  - Long-term memory filters, source refs, reinforcement, ranking trace: Task 1
  - Correction + forgetting lifecycle: Task 3
  - Context injection and retrieval trace visibility: Task 4
  - Verification + interview evidence: Task 5
- Placeholder scan:
  - No `TODO` / `TBD` placeholders remain.
  - Every task lists concrete files, pytest commands, and code snippets.
- Type consistency:
  - `memory_trace` is introduced consistently on `BeforeTurnContext` and `PassiveTurnResult`.
  - Correction flow uses one public name: `CorrectMemoryTool` / `correct_memory`.

