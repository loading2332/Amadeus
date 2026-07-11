from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from amadeus.memory.engine import (
    MemoryContextResult,
    MemoryQueryResult,
    MemoryRecallRequest,
    MemoryRecord,
    MemoryRetrievalStoreProtocol,
    MemoryScope,
)
from amadeus.memory.providers import EmbeddingProvider, HypothesisProvider
from amadeus.memory.ranking import (
    MemoryCandidateLanes,
    RetrievalLaneTrace,
    build_query_plan,
    dedupe_texts,
    extract_terms,
    format_context_record,
    normalize_datetime,
    rank_candidate_lanes,
    trace_record,
)


@dataclass
class MemoryRetriever:
    store: MemoryRetrievalStoreProtocol
    embedding_provider: EmbeddingProvider
    hypothesis_provider: HypothesisProvider | None = None
    lexical_retrieval_enabled: bool = True
    lexical_rrf_weight: float = 1.0
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

        (
            ranked,
            scope_mode,
            lane_trace,
            lane_status,
            lexical_terms,
            retrieval_fallbacks,
            retrieval_errors,
        ) = await self._load_ranked_candidates(
            request=request,
            queries=queries,
            memory_types=plan.memory_types,
            limit=limit,
        )
        fallbacks.extend(retrieval_fallbacks)
        errors.extend(retrieval_errors)
        trace: dict[str, Any] = {
            "intent": request.intent,
            "queries": queries,
            "scope": {
                "channel": request.scope.channel,
                "chat_id": request.scope.chat_id,
            },
            "scope_mode": scope_mode,
            "time_filters": {
                "start": normalize_datetime(request.time_start)
                if request.time_start
                else None,
                "end": normalize_datetime(request.time_end)
                if request.time_end
                else None,
            },
            "candidate_count": lane_trace.candidate_counts["union"],
            "candidate_counts": dict(lane_trace.candidate_counts),
            "lane_counts": lane_trace.lane_counts,
            "lane_status": lane_status,
            "lexical_query": {"terms": list(lexical_terms)},
            "record_count": len(ranked),
            "records": [
                trace_record(record, rank=index) for index, record in enumerate(ranked)
            ],
            "fallbacks": dedupe_texts(fallbacks),
            "errors": errors,
            "hypothesis_retrieval": hypothesis_trace,
        }
        return MemoryQueryResult(records=ranked, trace=trace)

    def _can_generate_hypotheses(self) -> bool:
        return (
            self.hypothesis_retrieval_enabled and self.hypothesis_provider is not None
        )

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

    async def _load_ranked_candidates(
        self,
        *,
        request: MemoryRecallRequest,
        queries: list[str],
        memory_types: tuple[str, ...],
        limit: int,
    ) -> tuple[
        list[MemoryRecord],
        str,
        RetrievalLaneTrace,
        dict[str, str],
        tuple[str, ...],
        list[str],
        list[str],
    ]:
        query_vectors, embedding_errors = await self._embed_queries(queries)
        lexical_terms = tuple(extract_terms(request.text))
        scoped = self._search_candidate_lanes(
            request=request,
            memory_types=memory_types,
            query_vectors=query_vectors,
            lexical_terms=lexical_terms,
            limit=limit,
            inherited_vector_errors=embedding_errors,
        )
        ranked, lane_trace = self._rank_candidate_set(
            candidates=scoped.candidates,
            queries=queries,
            query_vectors=query_vectors,
            limit=limit,
        )
        if ranked or (request.scope.channel is None and request.scope.chat_id is None):
            return (
                ranked,
                "scoped",
                lane_trace,
                scoped.lane_status,
                lexical_terms,
                scoped.fallbacks,
                scoped.errors,
            )

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
        global_result = self._search_candidate_lanes(
            request=global_request,
            memory_types=memory_types,
            query_vectors=query_vectors,
            lexical_terms=lexical_terms,
            limit=limit,
            inherited_vector_errors=embedding_errors,
        )
        global_ranked, global_lane_trace = self._rank_candidate_set(
            candidates=global_result.candidates,
            queries=queries,
            query_vectors=query_vectors,
            limit=limit,
        )
        return (
            global_ranked,
            "global-fallback",
            global_lane_trace,
            _merge_lane_statuses(scoped.lane_status, global_result.lane_status),
            lexical_terms,
            dedupe_texts([*scoped.fallbacks, *global_result.fallbacks]),
            dedupe_texts([*scoped.errors, *global_result.errors]),
        )

    async def _embed_queries(
        self,
        queries: list[str],
    ) -> tuple[list[list[float]], list[str]]:
        generated = await asyncio.gather(
            *(self.embedding_provider.embed(query_text) for query_text in queries),
            return_exceptions=True,
        )
        vectors: list[list[float]] = []
        errors: list[str] = []
        for value in generated:
            if isinstance(value, asyncio.CancelledError):
                raise value
            if isinstance(value, BaseException):
                vectors.append([])
                errors.append(f"vector_retrieval: {type(value).__name__}")
                continue
            if not value:
                vectors.append([])
                errors.append("vector_retrieval: EmptyEmbedding")
                continue
            vectors.append(value)
        return vectors, dedupe_texts(errors)

    def _search_candidate_lanes(
        self,
        *,
        request: MemoryRecallRequest,
        memory_types: tuple[str, ...],
        query_vectors: list[list[float]],
        lexical_terms: tuple[str, ...],
        limit: int,
        inherited_vector_errors: list[str],
    ) -> _LaneSearchResult:
        vector_groups: list[tuple[dict[str, Any], ...]] = []
        vector_errors = list(inherited_vector_errors)
        vector_successes = 0
        vector_limit = max(self.top_k, limit) * 4
        for query_vector in query_vectors:
            if not query_vector:
                vector_groups.append(())
                continue
            try:
                rows = self.store.search_vector_candidates(
                    query_embedding=query_vector,
                    memory_types=memory_types,
                    scope_channel=request.scope.channel,
                    scope_chat_id=request.scope.chat_id,
                    time_start=request.time_start,
                    time_end=request.time_end,
                    limit=vector_limit,
                )
            except Exception as exc:
                vector_groups.append(())
                vector_errors.append(f"vector_retrieval: {type(exc).__name__}")
            else:
                vector_successes += 1
                vector_groups.append(tuple(_normalize_rows(rows)))

        if vector_errors:
            vector_status = "degraded" if vector_successes else "error"
        else:
            vector_status = "ok"

        lexical_rows: tuple[dict[str, Any], ...] = ()
        lexical_error: str | None = None
        if not self.lexical_retrieval_enabled:
            lexical_status = "disabled"
        elif not lexical_terms:
            lexical_status = "no_terms"
        else:
            try:
                rows = self.store.search_lexical_candidates(
                    terms=lexical_terms,
                    memory_types=memory_types,
                    scope_channel=request.scope.channel,
                    scope_chat_id=request.scope.chat_id,
                    time_start=request.time_start,
                    time_end=request.time_end,
                    limit=max(30, limit * 2),
                )
            except Exception as exc:
                lexical_status = "error"
                lexical_error = f"lexical_retrieval: {type(exc).__name__}"
            else:
                lexical_status = "ok"
                lexical_rows = tuple(_normalize_rows(rows))

        fallbacks: list[str] = []
        errors = dedupe_texts(vector_errors)
        if vector_errors:
            fallbacks.append("vector_retrieval_failed")
        if lexical_error is not None:
            fallbacks.append("lexical_retrieval_failed")
            errors.append(lexical_error)
        return _LaneSearchResult(
            candidates=MemoryCandidateLanes(
                vector_groups=tuple(vector_groups),
                lexical=lexical_rows,
                lexical_terms=lexical_terms,
            ),
            lane_status={"vector": vector_status, "lexical": lexical_status},
            fallbacks=fallbacks,
            errors=errors,
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

    def _rank_candidate_set(
        self,
        *,
        candidates: MemoryCandidateLanes,
        queries: list[str],
        query_vectors: list[list[float]],
        limit: int,
    ) -> tuple[list[MemoryRecord], RetrievalLaneTrace]:
        return rank_candidate_lanes(
            candidates,
            query_vectors,
            queries,
            limit=limit,
            threshold=self.score_threshold,
            lexical_weight=self.lexical_rrf_weight,
        )


def _render_priority_sections(
    records: list[Any],
    char_budget: int,
) -> tuple[str, list[str], list[str]]:
    if not records:
        return "", [], []

    title_by_kind = {
        "procedure": "Applicable Procedures",
        "constraint": "Applicable Procedures",
        "profile": "User Profile",
        "preference": "User Profile",
        "event": "Relevant History",
        "fact": "Relevant History",
    }
    selected_sections: list[tuple[str, list[str]]] = []
    injected_ids: list[str] = []
    omitted_ids: list[str] = []

    def render(sections: list[tuple[str, list[str]]]) -> str:
        return "\n\n".join(
            f"## {title}\n" + "\n".join(entries) for title, entries in sections
        )

    for record in records:
        title = title_by_kind.get(record.kind, "Relevant Memory")
        entry = format_context_record(record)
        if selected_sections and selected_sections[-1][0] == title:
            candidate_sections = [
                *selected_sections[:-1],
                (title, [*selected_sections[-1][1], entry]),
            ]
        else:
            candidate_sections = [*selected_sections, (title, [entry])]
        if len(render(candidate_sections)) <= char_budget:
            selected_sections = candidate_sections
            injected_ids.append(record.id)
        else:
            omitted_ids.append(record.id)

    return render(selected_sections), injected_ids, omitted_ids


def _normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "kind": str(row.get("memory_type") or "event"),
        }
        for row in rows
    ]


@dataclass(frozen=True)
class _LaneSearchResult:
    candidates: MemoryCandidateLanes
    lane_status: dict[str, str]
    fallbacks: list[str]
    errors: list[str]


def _merge_lane_statuses(
    first_attempt: dict[str, str],
    second_attempt: dict[str, str],
) -> dict[str, str]:
    lanes = tuple(dict.fromkeys((*first_attempt, *second_attempt)))
    return {
        lane: _merge_lane_status(
            first_attempt.get(lane, "error"),
            second_attempt.get(lane, "error"),
        )
        for lane in lanes
    }


def _merge_lane_status(first: str, second: str) -> str:
    if first == second:
        return first
    statuses = {first, second}
    if "degraded" in statuses or ("error" in statuses and "ok" in statuses):
        return "degraded"
    if "error" in statuses:
        return "error"
    return second
