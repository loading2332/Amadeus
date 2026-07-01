from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from amadeus.memory.engine import (
    MemoryContextResult,
    MemoryIngestRequest,
    MemoryIngestResult,
    MemoryMutation,
    MemoryMutationResult,
    MemoryQuery,
    MemoryQueryResult,
    MemoryRecallRequest,
    MemoryWriteRequest,
)
from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.post_response_worker import PostResponseMemoryWorker
from amadeus.memory.retriever import MemoryRetriever, _render_priority_sections
from amadeus.memory.store import MemoryStore


@dataclass
class AkashicMemoryEngine:
    store: MemoryStore
    retriever: MemoryRetriever
    memorizer: MemoryMemorizer
    worker: PostResponseMemoryWorker

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

    async def run_post_response(
        self,
        *,
        session_key: str,
        messages: list[dict[str, Any]],
        explicit_memory_ids: list[str],
    ) -> dict[str, Any]:
        return await self.worker.run(
            session_key=session_key,
            messages=messages,
            explicit_memory_ids=explicit_memory_ids,
        )

    async def ingest(self, request: MemoryIngestRequest) -> MemoryIngestResult:
        return await self.memorize(
            MemoryWriteRequest(
                summary=request.summary,
                memory_type=request.kind,
                source_ref=request.source_ref,
                happened_at=request.happened_at,
                extra=dict(request.extra),
            )
        )

    async def query(self, query: MemoryQuery) -> MemoryQueryResult:
        return await self.recall(
            MemoryRecallRequest(
                text=query.text,
                intent=query.intent,
                memory_types=query.kinds,
                limit=query.limit,
                time_start=query.time_start,
                time_end=query.time_end,
                context=dict(query.context),
            )
        )

    async def mutate(self, request: MemoryMutation) -> MemoryMutationResult:
        if request.kind == "forget":
            return self.forget(list(request.ids))
        return MemoryMutationResult(
            accepted=False,
            status="unsupported",
            missing_ids=list(request.ids),
            trace={"reason": "unsupported_mutation", "kind": request.kind},
        )

    def render_context_block(self, result: MemoryQueryResult) -> str:
        block, injected_ids, omitted_ids = _render_priority_sections(
            result.records,
            self.retriever.context_char_budget,
        )
        result.trace["injected_ids"] = list(injected_ids)
        result.trace["omitted_ids"] = list(omitted_ids)
        result.trace["injection_char_count"] = len(block)
        return block
