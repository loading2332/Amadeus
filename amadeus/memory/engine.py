from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class MemoryScope:
    channel: str | None = None
    chat_id: str | None = None


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
    intent: str = "answer"
    memory_types: tuple[str, ...] = ()
    limit: int = 8
    time_start: datetime | None = None
    time_end: datetime | None = None
    scope: MemoryScope = field(default_factory=MemoryScope)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryContextResult:
    text: str = ""
    injected_ids: list[str] = field(default_factory=list)
    omitted_ids: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryQueryResult:
    records: list[MemoryRecord] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryWriteRequest:
    summary: str
    memory_type: str
    source_ref: str
    happened_at: str | None = None
    scope: MemoryScope = field(default_factory=MemoryScope)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryIngestResult:
    item_id: str | None = None
    status: str = "skipped"
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryMutationResult:
    accepted: bool = False
    status: str = "skipped"
    affected_ids: list[str] = field(default_factory=list)
    missing_ids: list[str] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


class MemoryStoreProtocol(Protocol):
    def insert_item(
        self,
        *,
        item_id: str,
        memory_type: str,
        summary: str,
        content_hash: str,
        embedding: list[float],
        source_ref: str,
        happened_at: str | None,
        scope_channel: str | None,
        scope_chat_id: str | None,
        emotional_weight: float,
        extra: dict[str, Any],
    ) -> None: ...

    def upsert_item(
        self,
        *,
        memory_type: str,
        summary: str,
        embedding: list[float],
        source_ref: str,
        happened_at: str | None = None,
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        emotional_weight: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> tuple[str, str]: ...

    def record_replacement(
        self,
        old_item_id: str,
        new_item_id: str,
        source_ref: str,
    ) -> None: ...

    def mark_items_status(
        self,
        ids: list[str],
        *,
        status: str,
        extra_patch: dict[str, Any],
    ) -> None: ...

    def list_replacements_for(self, old_item_id: str) -> list[dict[str, str]]: ...

    def find_replacements_by_source_ref(
        self,
        source_ref: str,
    ) -> list[dict[str, str]]: ...

    def list_active_items(
        self,
        *,
        memory_types: tuple[str, ...] = (),
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    def find_items_by_source_ref(self, source_ref: str) -> list[dict[str, Any]]: ...

    def get_items_by_ids(self, ids: list[str]) -> list[dict[str, Any]]: ...

    def get_item_by_id(self, item_id: str) -> dict[str, Any] | None: ...


class MemoryEngine(Protocol):
    async def recall(self, request: MemoryRecallRequest) -> MemoryQueryResult: ...

    async def memorize(self, request: MemoryWriteRequest) -> MemoryIngestResult: ...

    def forget(self, ids: list[str]) -> MemoryMutationResult: ...

    def undo_by_source(self, source_ref: str) -> MemoryMutationResult: ...

    async def build_context(self, request: MemoryRecallRequest) -> MemoryContextResult: ...

    async def run_post_response(
        self,
        *,
        session_key: str,
        messages: list[dict[str, Any]],
        explicit_memory_ids: list[str],
    ) -> dict[str, Any]: ...
