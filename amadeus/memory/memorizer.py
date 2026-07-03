from __future__ import annotations

from dataclasses import dataclass

from amadeus.memory.engine import (
    MemoryIngestResult,
    MemoryMutationResult,
    MemoryWriteRequest,
)
from amadeus.memory.providers import EmbeddingProvider
from amadeus.memory.store import MemoryStore


@dataclass
class MemoryMemorizer:
    store: MemoryStore
    embedding_provider: EmbeddingProvider

    async def memorize(self, request: MemoryWriteRequest) -> MemoryIngestResult:
        summary = request.summary.strip()
        source_ref = request.source_ref.strip()
        memory_type = request.memory_type.strip()
        if not summary or not source_ref or not memory_type:
            return MemoryIngestResult(
                status="invalid",
                trace={"reason": "summary_memory_type_and_source_ref_required"},
            )
        embedding = await self.embedding_provider.embed(summary)
        item_id, status = self.store.upsert_item(
            memory_type=memory_type,
            summary=summary,
            embedding=embedding,
            source_ref=source_ref,
            happened_at=request.happened_at,
            scope_channel=request.scope.channel,
            scope_chat_id=request.scope.chat_id,
            emotional_weight=float(request.extra.get("emotional_weight", 0.0) or 0.0),
            extra=dict(request.extra),
        )
        return MemoryIngestResult(item_id=item_id or None, status=status)

    async def replace(
        self,
        *,
        target_id: str,
        request: MemoryWriteRequest,
    ) -> MemoryMutationResult:
        target = self.store.get_item_by_id(target_id)
        if target is None:
            return MemoryMutationResult(
                accepted=False,
                status="missing",
                missing_ids=[target_id],
            )
        replacement = await self.memorize(request)
        replacement_id = replacement.item_id
        if replacement_id is None:
            return MemoryMutationResult(
                accepted=False,
                status=replacement.status,
                affected_ids=[target_id],
            )
        mutation = self.supersede_many(
            target_ids=[target_id],
            reason="replacement",
            replacement_id=replacement_id,
            replacement_source_ref=request.source_ref,
        )
        affected_ids = [target_id, replacement_id]
        return MemoryMutationResult(
            accepted=mutation.accepted,
            status="replaced" if mutation.accepted else mutation.status,
            affected_ids=affected_ids,
            missing_ids=mutation.missing_ids,
            items=self.store.get_items_by_ids(affected_ids),
            trace={
                **dict(mutation.trace),
                "replacement_id": replacement_id,
                "replaced_ids": mutation.affected_ids,
            },
        )

    def supersede_many(
        self,
        *,
        target_ids: list[str],
        reason: str,
        replacement_id: str | None = None,
        replacement_source_ref: str | None = None,
    ) -> MemoryMutationResult:
        clean_target_ids = _dedupe_ids(target_ids)
        targets = self.store.get_items_by_ids(clean_target_ids)
        found_ids = [str(item["id"]) for item in targets]
        found_set = set(found_ids)
        missing_ids = [
            item_id for item_id in clean_target_ids if item_id not in found_set
        ]
        if not found_ids:
            return MemoryMutationResult(
                accepted=False,
                status="missing",
                missing_ids=missing_ids,
                trace={
                    "superseded_ids": [],
                    "replacement_id": replacement_id,
                    "replacement_count": 0,
                },
            )

        extra_patch = {"superseded_reason": reason}
        if replacement_id:
            extra_patch["replacement_id"] = replacement_id
        self.store.mark_items_status(
            found_ids,
            status="superseded",
            extra_patch=extra_patch,
        )

        replacement_count = 0
        if replacement_id and replacement_source_ref:
            for target_id in found_ids:
                self.store.record_replacement(
                    target_id,
                    replacement_id,
                    replacement_source_ref,
                )
                replacement_count += 1

        return MemoryMutationResult(
            accepted=True,
            status="superseded",
            affected_ids=found_ids,
            missing_ids=missing_ids,
            items=self.store.get_items_by_ids(found_ids),
            trace={
                "superseded_ids": found_ids,
                "replacement_id": replacement_id,
                "replacement_count": replacement_count,
            },
        )

    def forget(self, ids: list[str]) -> MemoryMutationResult:
        clean_ids = _dedupe_ids(ids)
        items = self.store.get_items_by_ids(clean_ids)
        found_ids = [str(item["id"]) for item in items]
        missing_ids = [item_id for item_id in clean_ids if item_id not in set(found_ids)]
        if found_ids:
            self.store.mark_items_status(
                found_ids,
                status="superseded",
                extra_patch={"superseded_reason": "forget"},
            )
        return MemoryMutationResult(
            accepted=bool(found_ids),
            status="superseded" if found_ids else "skipped",
            affected_ids=found_ids,
            missing_ids=missing_ids,
            items=self.store.get_items_by_ids(found_ids),
        )

    def undo_by_source(self, source_ref: str) -> MemoryMutationResult:
        source = source_ref.strip()
        if not source:
            return MemoryMutationResult(
                accepted=False,
                status="invalid",
                trace={"reason": "source_ref_required"},
            )

        replacement_rows = self.store.find_replacements_by_source_ref(source)
        restored_ids: list[str] = []
        removed_ids: list[str] = []
        for row in replacement_rows:
            restored_ids.append(row["old_item_id"])
            removed_ids.append(row["new_item_id"])

        for item in self.store.find_items_by_source_ref(source):
            removed_ids.append(str(item["id"]))

        restored_ids = _dedupe_ids(restored_ids)
        removed_ids = _dedupe_ids(removed_ids)
        if removed_ids:
            self.store.mark_items_status(
                removed_ids,
                status="superseded",
                extra_patch={
                    "superseded_reason": "undo_by_source",
                    "undo_source_ref": source,
                },
            )
        if restored_ids:
            self.store.mark_items_status(
                restored_ids,
                status="active",
                extra_patch={
                    "restored_by_source_ref": source,
                    "replacement_id": None,
                },
            )

        affected_ids = [*restored_ids, *[item_id for item_id in removed_ids if item_id not in set(restored_ids)]]
        return MemoryMutationResult(
            accepted=bool(affected_ids),
            status="undone" if affected_ids else "skipped",
            affected_ids=affected_ids,
            items=self.store.get_items_by_ids(affected_ids),
        )


def _dedupe_ids(ids: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        item_id = str(raw).strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            result.append(item_id)
    return result
