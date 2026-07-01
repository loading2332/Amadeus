from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from amadeus.memory.engine import MemoryScope, MemoryWriteRequest
from amadeus.memory.memorizer import MemoryMemorizer


class MemoryExtractor(Protocol):
    async def extract(
        self,
        *,
        session_key: str,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...


@dataclass
class LLMMemoryExtractor:
    provider: Any
    model: str

    async def extract(
        self,
        *,
        session_key: str,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        transcript = "\n".join(
            f"{str(message.get('role') or '').upper()}: {str(message.get('content') or '').strip()}"
            for message in messages
            if str(message.get("content") or "").strip()
        )
        if not transcript:
            return []
        response = await self.provider.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是长期记忆抽取器。"
                        "只返回 JSON 数组；每个元素必须包含 "
                        "summary, memory_type, source_ref，可选 happened_at, extra。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"session_key={session_key}\n{transcript}",
                },
            ],
            model=self.model,
            max_tokens=512,
            tools=[],
            disable_thinking=True,
        )
        try:
            parsed = json.loads(str(response.content or "[]"))
        except json.JSONDecodeError:
            return []
        return [item for item in parsed if isinstance(item, dict)]


@dataclass
class PostResponseMemoryWorker:
    memorizer: MemoryMemorizer
    extractor: MemoryExtractor

    async def run(
        self,
        *,
        session_key: str,
        messages: list[dict[str, Any]],
        explicit_memory_ids: list[str],
    ) -> dict[str, Any]:
        candidates = await self.extractor.extract(
            session_key=session_key,
            messages=messages,
        )
        written_count = 0
        skipped_duplicates = 0
        written_ids: list[str] = []
        errors: list[str] = []

        for candidate in candidates:
            try:
                result = await self.memorizer.memorize(
                    MemoryWriteRequest(
                        summary=str(candidate.get("summary") or "").strip(),
                        memory_type=str(candidate.get("memory_type") or "event").strip()
                        or "event",
                        source_ref=str(candidate.get("source_ref") or "").strip(),
                        happened_at=str(candidate.get("happened_at") or "").strip()
                        or None,
                        scope=MemoryScope(),
                        extra=dict(candidate.get("extra") or {}),
                    )
                )
            except Exception as error:
                errors.append(str(error))
                continue

            if result.item_id and result.item_id in explicit_memory_ids:
                skipped_duplicates += 1
                continue
            if result.status in {"new", "reinforced"} and result.item_id:
                written_count += 1
                written_ids.append(result.item_id)

        return {
            "written_count": written_count,
            "skipped_duplicates": skipped_duplicates,
            "written_ids": written_ids,
            "candidate_count": len(candidates),
            "explicit_memory_ids": list(explicit_memory_ids),
            "errors": errors,
        }
