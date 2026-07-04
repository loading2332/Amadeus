from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from amadeus.memory.engine import (
    MemoryContextResult,
    MemoryQueryResult,
    MemoryRecallRequest,
    MemoryScope,
    MemoryStoreProtocol,
)
from amadeus.memory.providers import EmbeddingProvider, HypothesisProvider
from amadeus.memory.ranking import (
    build_query_plan,
    dedupe_texts,
    format_context_record,
    normalize_datetime,
    rank_multi_query_rows,
    trace_record,
)


@dataclass
class MemoryRetriever:
    store: MemoryStoreProtocol
    embedding_provider: EmbeddingProvider
    hypothesis_provider: HypothesisProvider | None = None
    hypothesis_retrieval_enabled: bool = True
    hypothesis_timeout_seconds: float = 2.0
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
        hypothesis_trace: dict[str, Any] = self._disabled_hypothesis_trace(
            intent=request.intent,
            use_hypotheses=plan.use_hypotheses,
        )
        if plan.use_hypotheses and self._can_generate_hypotheses():
            hypotheses = await self._generate_hypotheses(text)
            queries.extend(hypotheses["queries"])
            fallbacks.extend(hypotheses["fallbacks"])
            errors.extend(hypotheses["errors"])
            hypothesis_trace = {
                "enabled": True,
                "styles": ["event", "general"],
                "queries": hypotheses["queries_by_style"],
                "fallbacks": hypotheses["fallbacks"],
                "errors": hypotheses["errors"],
            }
        queries = dedupe_texts(queries)
        hypothesis_trace["query_texts"] = list(queries)

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
            "hypothesis_retrieval": hypothesis_trace,
        }
        return MemoryQueryResult(records=ranked, trace=trace)

    def _can_generate_hypotheses(self) -> bool:
        return self.hypothesis_retrieval_enabled and self.hypothesis_provider is not None

    def _disabled_hypothesis_trace(
        self,
        *,
        intent: str,
        use_hypotheses: bool,
    ) -> dict[str, Any]:
        if not use_hypotheses:
            reason = f"intent_{intent}"
        elif not self.hypothesis_retrieval_enabled:
            reason = "disabled"
        elif self.hypothesis_provider is None:
            reason = "missing_provider"
        else:
            reason = "not_generated"
        return {
            "enabled": False,
            "styles": ["event", "general"],
            "queries": {},
            "fallbacks": [],
            "errors": [],
            "reason": reason,
        }

    async def _load_ranked_rows(
        self,
        *,
        request: MemoryRecallRequest,
        queries: list[str],
        memory_types: tuple[str, ...],
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[Any], str, dict[str, dict[str, int]]]:
        query_vectors = await self._embed_queries(queries)
        scoped_rows = _normalize_rows(
            self._candidate_rows(
                request=request,
                memory_types=memory_types,
                query_vectors=query_vectors,
            )
        )
        ranked, lane_counts = self._rank_query_set(
            rows=scoped_rows,
            queries=queries,
            query_vectors=query_vectors,
            limit=limit,
        )
        if ranked or (
            request.scope.channel is None and request.scope.chat_id is None
        ):
            return scoped_rows, ranked, "scoped", lane_counts

        global_request = MemoryRecallRequest(
            text=request.text,
            intent=request.intent,
            memory_types=memory_types,
            limit=request.limit,
            time_start=request.time_start,
            time_end=request.time_end,
            scope=MemoryScope(),
            context=request.context,
        )
        global_rows = _normalize_rows(
            self._candidate_rows(
                request=global_request,
                memory_types=memory_types,
                query_vectors=query_vectors,
            )
        )
        global_ranked, global_lane_counts = self._rank_query_set(
            rows=global_rows,
            queries=queries,
            query_vectors=query_vectors,
            limit=limit,
        )
        return global_rows, global_ranked, "global-fallback", global_lane_counts

    async def _embed_queries(
        self,
        queries: list[str],
    ) -> list[list[float]]:
        return list(
            await asyncio.gather(
                *(self.embedding_provider.embed(query_text) for query_text in queries)
            )
        )

    def _candidate_rows(
        self,
        *,
        request: MemoryRecallRequest,
        memory_types: tuple[str, ...],
        query_vectors: list[list[float]],
    ) -> list[dict[str, Any]]:
        """Return candidate rows for ranking.

        When the store exposes a pgvector-backed ``search_active_items`` method,
        semantic candidates for every query are recalled through SQL ``<=>`` so the
        runtime never falls back to a Python full-table scan as the completion
        state. Stores without that method (e.g. legacy SQLite fakes) keep using
        ``list_active_items`` and the ranking layer still scores them in Python.
        """
        search = getattr(self.store, "search_active_items", None)
        if callable(search) and query_vectors:
            rows_by_id: dict[str, dict[str, Any]] = {}
            for query_vector in query_vectors:
                if not query_vector:
                    continue
                rows = search(
                    query_embedding=query_vector,
                    memory_types=memory_types,
                    scope_channel=request.scope.channel,
                    scope_chat_id=request.scope.chat_id,
                    time_start=request.time_start,
                    time_end=request.time_end,
                    limit=max(
                        self.top_k,
                        request.limit if request.limit > 0 else self.top_k,
                    )
                    * 4,
                )
                for row in rows:
                    rows_by_id.setdefault(str(row["id"]), row)
            return list(rows_by_id.values())
        return self.store.list_active_items(
            memory_types=memory_types,
            scope_channel=request.scope.channel,
            scope_chat_id=request.scope.chat_id,
            time_start=request.time_start,
            time_end=request.time_end,
        )

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

    async def _generate_hypotheses(self, text: str) -> dict[str, Any]:
        if self.hypothesis_provider is None:
            return {
                "queries": [],
                "queries_by_style": {},
                "fallbacks": [],
                "errors": [],
            }
        generated = await self._gather_hypotheses(text)
        queries: list[str] = []
        queries_by_style: dict[str, str] = {}
        fallbacks: list[str] = []
        errors: list[str] = []
        for style, value in generated:
            if isinstance(value, BaseException):
                fallbacks.append(f"hypothesis_{style}_failed")
                errors.append(f"hypothesis_{style}: {value}")
                continue
            text_value = value.strip()
            if not text_value:
                fallbacks.append(f"hypothesis_{style}_empty")
                continue
            queries.append(text_value)
            queries_by_style[style] = text_value
        return {
            "queries": queries,
            "queries_by_style": queries_by_style,
            "fallbacks": fallbacks,
            "errors": errors,
        }

    async def _gather_hypotheses(
        self,
        text: str,
    ) -> list[tuple[str, str | BaseException]]:
        if self.hypothesis_provider is None:
            return []
        generated = await asyncio.gather(
            self._generate_hypothesis_style(text, "event"),
            self._generate_hypothesis_style(text, "general"),
            return_exceptions=True,
        )
        return list(zip(("event", "general"), generated, strict=True))

    async def _generate_hypothesis_style(self, text: str, style: str) -> str:
        if self.hypothesis_provider is None:
            return ""
        return await asyncio.wait_for(
            self.hypothesis_provider.generate(text, style=style),
            timeout=max(0.001, float(self.hypothesis_timeout_seconds)),
        )

    def _rank_query_set(
        self,
        *,
        rows: list[dict[str, Any]],
        queries: list[str],
        query_vectors: list[list[float]],
        limit: int,
    ) -> tuple[list[Any], dict[str, dict[str, int]]]:
        return rank_multi_query_rows(
            rows,
            query_vectors,
            queries,
            limit=limit,
            threshold=self.score_threshold,
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
