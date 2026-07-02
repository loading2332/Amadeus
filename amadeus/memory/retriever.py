from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from amadeus.memory.engine import (
    MemoryContextResult,
    MemoryQueryResult,
    MemoryRecallRequest,
)
from amadeus.memory.providers import EmbeddingProvider, HypothesisProvider
from amadeus.memory.ranking import (
    build_query_plan,
    dedupe_texts,
    format_context_record,
    max_pool_records,
    normalize_datetime,
    rank_rows,
    trace_record,
)
from amadeus.memory.store import MemoryStore


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
        limit = request.limit if request.limit > 0 else self.top_k
        plan = build_query_plan(
            text=text,
            intent=request.intent,
            memory_types=request.memory_types,
            context=request.context,
        )
        queries = list(plan.queries)
        fallbacks: list[str] = []
        errors: list[str] = []
        if plan.use_hypotheses and self.hypothesis_provider is not None:
            hypotheses = await self._generate_hypotheses(text)
            queries.extend(hypotheses["queries"])
            fallbacks.extend(hypotheses["fallbacks"])
            errors.extend(hypotheses["errors"])
        queries = dedupe_texts(queries)

        rows, ranked, scope_mode, lane_counts = await self._load_ranked_rows(
            request=request,
            queries=queries,
            memory_types=plan.memory_types,
            limit=limit,
        )
        trace: dict[str, Any] = {
            "intent": request.intent,
            "queries": queries,
            "scope": {
                "channel": request.scope.channel,
                "chat_id": request.scope.chat_id,
            },
            "scope_mode": scope_mode,
            "time_filters": {
                "start": normalize_datetime(request.time_start) if request.time_start else None,
                "end": normalize_datetime(request.time_end) if request.time_end else None,
            },
            "candidate_count": len(rows),
            "lane_counts": lane_counts,
            "record_count": len(ranked),
            "records": [trace_record(record, rank=index) for index, record in enumerate(ranked)],
            "fallbacks": dedupe_texts(fallbacks),
            "errors": errors,
        }
        return MemoryQueryResult(records=ranked, trace=trace)

    async def _load_ranked_rows(
        self,
        *,
        request: MemoryRecallRequest,
        queries: list[str],
        memory_types: tuple[str, ...],
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[Any], str, dict[str, dict[str, int]]]:
        scoped_rows = _normalize_rows(
            self.store.list_active_items(
                memory_types=memory_types,
                scope_channel=request.scope.channel,
                scope_chat_id=request.scope.chat_id,
                time_start=request.time_start,
                time_end=request.time_end,
            )
        )
        ranked, lane_counts = await self._rank_query_set(
            rows=scoped_rows,
            queries=queries,
            limit=limit,
        )
        if ranked or (
            request.scope.channel is None and request.scope.chat_id is None
        ):
            return scoped_rows, ranked, "scoped", lane_counts

        global_rows = _normalize_rows(
            self.store.list_active_items(
                memory_types=memory_types,
                time_start=request.time_start,
                time_end=request.time_end,
            )
        )
        global_ranked, global_lane_counts = await self._rank_query_set(
            rows=global_rows,
            queries=queries,
            limit=limit,
        )
        return global_rows, global_ranked, "global-fallback", global_lane_counts

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

    async def _generate_hypotheses(self, text: str) -> dict[str, list[str]]:
        if self.hypothesis_provider is None:
            return {"queries": [], "fallbacks": [], "errors": []}
        generated = await self._gather_hypotheses(text)
        queries: list[str] = []
        fallbacks: list[str] = []
        errors: list[str] = []
        for style, value in generated:
            if isinstance(value, BaseException):
                fallbacks.append(f"hypothesis_{style}_failed")
                errors.append(f"hypothesis_{style}: {value}")
                continue
            queries.append(value)
        return {"queries": queries, "fallbacks": fallbacks, "errors": errors}

    async def _gather_hypotheses(
        self,
        text: str,
    ) -> list[tuple[str, str | BaseException]]:
        if self.hypothesis_provider is None:
            return []
        generated = await asyncio.gather(
            self.hypothesis_provider.generate(text, style="event"),
            self.hypothesis_provider.generate(text, style="general"),
            return_exceptions=True,
        )
        return list(zip(("event", "general"), generated, strict=True))

    async def _rank_query_set(
        self,
        *,
        rows: list[dict[str, Any]],
        queries: list[str],
        limit: int,
    ) -> tuple[list[Any], dict[str, dict[str, int]]]:
        result_sets: list[list[Any]] = []
        lane_counts: dict[str, dict[str, int]] = {}
        for query_text in queries:
            query_vector = await self.embedding_provider.embed(query_text)
            ranked = rank_rows(
                rows,
                query_vector,
                query_text,
                limit=limit,
                threshold=self.score_threshold,
            )
            result_sets.append(ranked)
            lane_counts[query_text] = {
                "vector": sum(
                    1 for record in ranked if "vector" in record.signals.get("lanes", [])
                ),
                "lexical": sum(
                    1 for record in ranked if "lexical" in record.signals.get("lanes", [])
                ),
            }
        return max_pool_records(result_sets, limit=limit), lane_counts


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
            entry = format_context_record(record)
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
        entry = format_context_record(record)
        candidate_section = f"## Relevant Memory\n{entry}"
        candidate = "\n\n".join([*selected_parts, candidate_section])
        if len(candidate) <= char_budget:
            selected_parts.append(candidate_section)
            injected_ids.append(record.id)
        else:
            omitted_ids.append(record.id)
        handled.add(record.id)

    return "\n\n".join(selected_parts), injected_ids, omitted_ids


def _normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "kind": str(row.get("memory_type") or "event"),
        }
        for row in rows
    ]
