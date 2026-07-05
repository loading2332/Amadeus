from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from amadeus.memory.engine import (
    MemoryContextResult,
    MemoryIngestResult,
    MemoryMutationResult,
    MemoryQueryResult,
    MemoryRecallRequest,
    MemoryStoreProtocol,
    MemoryWriteRequest,
)
from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.post_response_worker import PostResponseMemoryWorker
from amadeus.memory.retriever import MemoryRetriever
from amadeus.session.identity import SessionRef


@dataclass
class LongTermMemoryEngine:
    store: MemoryStoreProtocol
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
        session: SessionRef,
        messages: list[dict[str, Any]],
        explicit_memory_ids: list[str],
    ) -> dict[str, Any]:
        return await self.worker.run(
            session=session,
            messages=messages,
            explicit_memory_ids=explicit_memory_ids,
        )
