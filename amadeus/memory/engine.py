from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class MemoryScope:
    session_key: str = ""
    user_id: str = ""
    thread_id: str = ""
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


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
class MemoryRecallRequest:
    text: str
    scope: MemoryScope = field(default_factory=MemoryScope)
    intent: str = "answer"
    kinds: tuple[str, ...] = ()
    limit: int = 8
    time_start: datetime | None = None
    time_end: datetime | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryQuery:
    text: str
    intent: str = "answer"
    kinds: tuple[str, ...] = ()
    limit: int = 8
    time_start: datetime | None = None
    time_end: datetime | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryContextResult:
    records: list[MemoryRecord] = field(default_factory=list)
    rendered: str = ""
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryQueryResult:
    records: list[MemoryRecord] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryWriteRequest:
    summary: str
    scope: MemoryScope = field(default_factory=MemoryScope)
    kind: str = "event"
    source_ref: str = ""
    happened_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


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


@dataclass(frozen=True)
class MemoryMutation:
    kind: str
    ids: tuple[str, ...] = ()
    corrected_summary: str = ""
    source_ref: str = ""
    replacement_kind: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryMutationResult:
    accepted: bool = False
    status: str = "skipped"
    affected_ids: list[str] = field(default_factory=list)
    missing_ids: list[str] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


class MemoryEngine(Protocol):
    async def recall(self, request: MemoryRecallRequest) -> MemoryQueryResult: ...

    async def memorize(self, request: MemoryWriteRequest) -> MemoryIngestResult: ...

    def forget(self, ids: list[str]) -> MemoryMutationResult: ...

    async def undo_by_source(self, source_ref: str) -> MemoryMutationResult: ...

    def build_context(self, result: MemoryQueryResult) -> MemoryContextResult: ...

    async def run_post_response(self) -> None: ...

    # Legacy compatibility during the migration.
    async def ingest(self, request: MemoryIngestRequest) -> MemoryIngestResult: ...

    async def query(self, query: MemoryQuery) -> MemoryQueryResult: ...

    async def mutate(self, request: MemoryMutation) -> MemoryMutationResult: ...

    def render_context_block(self, result: MemoryQueryResult) -> str: ...
