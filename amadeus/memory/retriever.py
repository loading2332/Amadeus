from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from amadeus.memory.engine import (
    MemoryContextResult,
    MemoryQueryResult,
    MemoryRecallRequest,
)
from amadeus.memory.store import MemoryStore
from amadeus.memory.vector import (
    EmbeddingProvider,
    HypothesisProvider,
    _format_context_record,
    _normalize_datetime,
    _rank_rows,
    _trace_record,
)


@dataclass
class MemoryRetriever:
    store: MemoryStore
    embedding_provider: EmbeddingProvider
    hypothesis_provider: HypothesisProvider | None = None
    score_threshold: float = 0.35
    top_k: int = 8
    context_char_budget: int = 4000

    async def recall(self, request: MemoryRecallRequest) -> MemoryQueryResult:
        text = request.text.strip()
        if not text:
            return MemoryQueryResult(trace={"reason": "empty_query"})

        query_vector = await self.embedding_provider.embed(text)
        rows = [
            {
                **row,
                "kind": str(row.get("memory_type") or "event"),
            }
            for row in self.store.list_active_items(
                memory_types=request.memory_types,
                scope_channel=request.scope.channel,
                scope_chat_id=request.scope.chat_id,
                time_start=request.time_start,
                time_end=request.time_end,
            )
        ]
        limit = request.limit if request.limit > 0 else self.top_k
        ranked = _rank_rows(
            rows,
            query_vector,
            text,
            limit=limit,
            threshold=self.score_threshold,
        )
        trace: dict[str, Any] = {
            "intent": request.intent,
            "scope": {
                "channel": request.scope.channel,
                "chat_id": request.scope.chat_id,
            },
            "time_filters": {
                "start": _normalize_datetime(request.time_start)
                if request.time_start
                else None,
                "end": _normalize_datetime(request.time_end) if request.time_end else None,
            },
            "candidate_count": len(rows),
            "record_count": len(ranked),
            "records": [
                _trace_record(record, rank=index)
                for index, record in enumerate(ranked)
            ],
        }
        return MemoryQueryResult(records=ranked, trace=trace)

    async def build_context(self, request: MemoryRecallRequest) -> MemoryContextResult:
        result = await self.recall(request)
        block, injected_ids, omitted_ids = _render_priority_sections(
            result.records,
            self.context_char_budget,
        )
        trace = dict(result.trace)
        trace["injected_ids"] = list(injected_ids)
        trace["omitted_ids"] = list(omitted_ids)
        trace["injection_char_count"] = len(block)
        return MemoryContextResult(
            text=block,
            injected_ids=injected_ids,
            omitted_ids=omitted_ids,
            trace=trace,
        )


def _render_priority_sections(
    records: list[Any],
    char_budget: int,
) -> tuple[str, list[str], list[str]]:
    if not records:
        return "", [], []

    sections = (
        ("Applicable Procedures", {"procedure", "constraint"}),
        ("User Profile", {"profile", "preference"}),
        ("Relevant History", {"event", "fact"}),
    )
    selected_parts: list[str] = []
    injected_ids: list[str] = []
    omitted_ids: list[str] = []
    handled: set[str] = set()

    for title, kinds in sections:
        entries: list[str] = []
        for record in records:
            if record.id in handled or record.kind not in kinds:
                continue
            handled.add(record.id)
            entry = _format_context_record(record)
            candidate_entries = [*entries, entry]
            candidate_section = f"## {title}\n" + "\n".join(candidate_entries)
            candidate = "\n\n".join([*selected_parts, candidate_section])
            if len(candidate) <= char_budget:
                entries.append(entry)
                injected_ids.append(record.id)
            else:
                omitted_ids.append(record.id)
        if entries:
            selected_parts.append(f"## {title}\n" + "\n".join(entries))

    for record in records:
        if record.id in handled:
            continue
        entry = _format_context_record(record)
        candidate_section = f"## Relevant Memory\n{entry}"
        candidate = "\n\n".join([*selected_parts, candidate_section])
        if len(candidate) <= char_budget:
            selected_parts.append(candidate_section)
            injected_ids.append(record.id)
        else:
            omitted_ids.append(record.id)
        handled.add(record.id)

    return "\n\n".join(selected_parts), injected_ids, omitted_ids
