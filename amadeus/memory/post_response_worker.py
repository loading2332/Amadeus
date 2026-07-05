from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from amadeus.memory.engine import MemoryScope, MemoryWriteRequest
from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.ranking import rank_rows
from amadeus.memory.source_refs import (
    build_message_source_ref,
    source_ref_message_ids,
)
from amadeus.session.identity import SessionRef

ALLOWED_POST_RESPONSE_TYPES = {"profile", "preference", "procedure", "fact", "event"}


class MemoryExtractor(Protocol):
    async def extract(
        self,
        *,
        session: SessionRef,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class MemoryCandidate:
    summary: str
    memory_type: str
    source_ref: str
    source_message_ids: list[str] = field(default_factory=list)
    happened_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    reason: str = ""


@dataclass(frozen=True)
class MemoryDecision:
    action: str
    reason: str
    target_ids: list[str] = field(default_factory=list)


class MemoryDecisionProvider(Protocol):
    async def decide(self, candidate: MemoryCandidate) -> MemoryDecision: ...


@dataclass
class CreateOnlyMemoryDecisionProvider:
    async def decide(self, candidate: MemoryCandidate) -> MemoryDecision:
        del candidate
        return MemoryDecision(action="create", reason="no_decision_provider")


@dataclass
class LLMMemoryDecisionProvider:
    memorizer: MemoryMemorizer
    provider: Any
    model: str
    similarity_threshold: float = 0.35
    top_k: int = 5

    async def decide(self, candidate: MemoryCandidate) -> MemoryDecision:
        similar = await self._similar_memories(candidate)
        if not similar:
            return MemoryDecision(action="create", reason="no_similar_active_memory")
        payload = await self._ask_llm(candidate, similar)
        return self._parse_decision(payload, similar)

    async def _similar_memories(
        self,
        candidate: MemoryCandidate,
    ) -> list[dict[str, Any]]:
        query_vector = await self.memorizer.embedding_provider.embed(candidate.summary)
        active_rows = self.memorizer.store.list_active_items(
            memory_types=(candidate.memory_type,)
        )
        normalized_rows = [
            {
                **row,
                "kind": str(row.get("memory_type") or candidate.memory_type),
            }
            for row in active_rows
        ]
        ranked = rank_rows(
            normalized_rows,
            query_vector,
            candidate.summary,
            limit=self.top_k,
            threshold=self.similarity_threshold,
        )
        by_id = {str(row["id"]): row for row in normalized_rows}
        return [
            {
                **by_id[record.id],
                "_dedup_score": float(
                    record.signals.get("vector_score")
                    or record.signals.get("lexical_score")
                    or 0.0
                ),
            }
            for record in ranked
            if record.id in by_id
        ]

    async def _ask_llm(
        self,
        candidate: MemoryCandidate,
        similar: list[dict[str, Any]],
    ) -> dict[str, Any]:
        existing_block = "\n".join(
            f"{index + 1}. id={item['id']} score={float(item.get('_dedup_score') or 0.0):.4f}\n"
            f"   summary={item.get('summary', '')}"
            for index, item in enumerate(similar)
        )
        response = await self.provider.chat(
            [
                {
                    "role": "user",
                    "content": _DECISION_PROMPT.format(
                        candidate_type=candidate.memory_type,
                        candidate_summary=candidate.summary,
                        existing_memories=existing_block,
                    ),
                }
            ],
            model=self.model,
            max_tokens=256,
            tools=[],
            disable_thinking=True,
        )
        text = str(response.content or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"decision": "create", "reason": "invalid_llm_payload"}
        return parsed if isinstance(parsed, dict) else {"decision": "create", "reason": "invalid_llm_payload"}

    def _parse_decision(
        self,
        payload: dict[str, Any],
        similar: list[dict[str, Any]],
    ) -> MemoryDecision:
        decision = str(payload.get("decision") or "create").lower().strip()
        reason = str(payload.get("reason") or decision or "llm_decision").strip()
        valid_ids = {str(item["id"]) for item in similar}
        target_ids = [
            item_id
            for item_id in _string_list(payload.get("target_ids"))
            if item_id in valid_ids
        ]
        if decision == "skip":
            return MemoryDecision(action="skip", reason=reason, target_ids=target_ids)
        if decision == "replace" and target_ids:
            return MemoryDecision(
                action="replace",
                reason=reason,
                target_ids=_dedupe_ids(target_ids[:1]),
            )
        return MemoryDecision(action="create", reason=reason or "llm_create")


@dataclass
class LLMMemoryExtractor:
    provider: Any
    model: str

    async def extract(
        self,
        *,
        session: SessionRef,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        transcript = "\n".join(
            _format_message_for_prompt(message) for message in messages
        )
        if not transcript:
            return []
        response = await self.provider.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 Amadeus 风格长期记忆候选抽取器。只返回 JSON 数组。"
                        "只允许基于 USER 消息写入，ASSISTANT 只能作为上下文，不能作为证据。"
                        "输出字段：summary, memory_type, source_message_ids, happened_at, extra, confidence, reason。"
                        "memory_type 只能是 profile/preference/procedure/fact/event。"
                        "preference=用户希望我如何回答/推荐/服务；procedure=未来执行任务必须遵守的规则；"
                        "profile=用户稳定身份/状态事实；fact=项目或长期事实；event=历史事件。"
                        "不要写短期状态、今晚/这两天安排、普通寒暄、假设例子、工具执行噪音。"
                        "遇到“现在改了/以后/不再/不是...了”等纠错或新事实，要抽取当前真实表述。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"session_key={session.session_key}\n{transcript}",
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
            parsed = []
        return [item for item in parsed if isinstance(item, dict)]


@dataclass
class PostResponseMemoryWorker:
    memorizer: MemoryMemorizer
    extractor: MemoryExtractor
    decision_provider: MemoryDecisionProvider | None = None

    async def run(
        self,
        *,
        session: SessionRef,
        messages: list[dict[str, Any]],
        explicit_memory_ids: list[str],
    ) -> dict[str, Any]:
        candidates = await self.extractor.extract(
            session=session,
            messages=messages,
        )
        decider = self.decision_provider or CreateOnlyMemoryDecisionProvider()
        written_count = 0
        skipped_duplicates = 0
        written_ids: list[str] = []
        superseded_ids: list[str] = []
        candidate_decisions: list[dict[str, Any]] = []
        errors: list[str] = []

        for candidate in candidates:
            normalized = _normalize_candidate(candidate, messages=messages)
            if isinstance(normalized, str):
                candidate_decisions.append(
                    {
                        "action": "skip",
                        "reason": normalized,
                        "summary": str(candidate.get("summary") or "").strip(),
                    }
                )
                continue
            decision = await decider.decide(normalized)
            decision_payload = {
                "action": decision.action,
                "reason": decision.reason,
                "summary": normalized.summary,
                "memory_type": normalized.memory_type,
                "source_ref": normalized.source_ref,
                "target_ids": list(decision.target_ids),
            }
            candidate_decisions.append(decision_payload)
            if decision.action == "skip":
                skipped_duplicates += 1
                continue
            try:
                request = _write_request_from_candidate(normalized)
                if decision.action == "replace":
                    result = await self.memorizer.memorize(request)
                    result_item_id = result.item_id or ""
                    if result_item_id:
                        mutation = self.memorizer.supersede_many(
                            target_ids=decision.target_ids,
                            reason=decision.reason,
                            replacement_id=result_item_id,
                            replacement_source_ref=request.source_ref,
                        )
                        superseded_ids.extend(mutation.affected_ids)
                    else:
                        mutation = None
                    if mutation is not None and mutation.accepted:
                        result_status = "new"
                    else:
                        result_status = (
                            mutation.status if mutation is not None else result.status
                        )
                else:
                    result = await self.memorizer.memorize(request)
                    result_item_id = result.item_id or ""
                    result_status = result.status
            except Exception as error:
                errors.append(str(error))
                continue

            if result_item_id and result_item_id in explicit_memory_ids:
                skipped_duplicates += 1
                continue
            if result_status in {"new", "reinforced"} and result_item_id:
                written_count += 1
                written_ids.append(result_item_id)

        return {
            "written_count": written_count,
            "skipped_duplicates": skipped_duplicates,
            "written_ids": written_ids,
            "superseded_ids": _dedupe_ids(superseded_ids),
            "candidate_count": len(candidates),
            "candidate_decisions": candidate_decisions,
            "explicit_memory_ids": list(explicit_memory_ids),
            "errors": errors,
        }


def _write_request_from_candidate(candidate: MemoryCandidate) -> MemoryWriteRequest:
    return MemoryWriteRequest(
        summary=candidate.summary,
        memory_type=candidate.memory_type,
        source_ref=candidate.source_ref,
        happened_at=candidate.happened_at,
        scope=MemoryScope(),
        extra={
            **dict(candidate.extra),
            "candidate_confidence": candidate.confidence,
            "candidate_reason": candidate.reason,
            "source_message_ids": list(candidate.source_message_ids),
        },
    )


def _normalize_candidate(
    candidate: dict[str, Any],
    *,
    messages: list[dict[str, Any]],
) -> MemoryCandidate | str:
    summary = str(candidate.get("summary") or "").strip()
    memory_type = str(candidate.get("memory_type") or "event").strip() or "event"
    if not summary or memory_type not in ALLOWED_POST_RESPONSE_TYPES:
        return "summary_and_valid_memory_type_required"
    raw_extra = candidate.get("extra")
    extra = dict(raw_extra) if isinstance(raw_extra, dict) else {}
    source_message_ids = _string_list(candidate.get("source_message_ids"))
    source_ref = str(candidate.get("source_ref") or "").strip()
    if not source_message_ids and source_ref:
        source_message_ids = source_ref_message_ids(source_ref)
    if not source_message_ids:
        source_message_ids = [
            str(message.get("id") or "").strip()
            for message in messages
            if str(message.get("role") or "").lower() == "user"
            and str(message.get("id") or "").strip()
        ]
    if not _source_ids_resolve_to_user_messages(source_message_ids, messages):
        if source_ref and not _message_ids_index(messages):
            source_message_ids = source_message_ids or []
        else:
            return "source_ref_must_resolve_to_user_message"
    if not source_ref and source_message_ids:
        source_ref = build_message_source_ref(source_message_ids, summary)
    if not source_ref:
        return "source_ref_required"
    source_text = _source_text(source_message_ids, messages)
    if _is_short_term_noise(summary) or _is_short_term_noise(source_text):
        return "short_term_or_explicit_not_memory"
    confidence = candidate.get("confidence", 1.0)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 1.0
    return MemoryCandidate(
        summary=summary,
        memory_type=memory_type,
        source_ref=source_ref,
        source_message_ids=source_message_ids,
        happened_at=str(candidate.get("happened_at") or "").strip() or None,
        extra=extra,
        confidence=confidence_value,
        reason=str(candidate.get("reason") or "").strip(),
    )


def _format_message_for_prompt(message: dict[str, Any]) -> str:
    content = str(message.get("content") or "").strip()
    if not content:
        return ""
    message_id = str(message.get("id") or "").strip()
    role = str(message.get("role") or "").upper()
    return f"{role}[id={message_id}]: {content}"


def _source_ids_resolve_to_user_messages(
    source_message_ids: list[str],
    messages: list[dict[str, Any]],
) -> bool:
    if not source_message_ids:
        return False
    index = _message_ids_index(messages)
    if not index:
        return True
    for message_id in source_message_ids:
        message = index.get(message_id)
        if message is None:
            return False
        if str(message.get("role") or "").lower() != "user":
            return False
    return True


def _source_text(
    source_message_ids: list[str],
    messages: list[dict[str, Any]],
) -> str:
    index = _message_ids_index(messages)
    if not index:
        return "\n".join(
            str(message.get("content") or "")
            for message in messages
            if str(message.get("role") or "").lower() == "user"
        )
    return "\n".join(
        str(index[message_id].get("content") or "")
        for message_id in source_message_ids
        if message_id in index
    )


def _message_ids_index(messages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(message.get("id") or "").strip(): message
        for message in messages
        if str(message.get("id") or "").strip()
    }
def _is_short_term_noise(text: str) -> bool:
    return any(term in text for term in ("短期", "今晚", "这两天", "临时")) and any(
        term in text for term in ("别记", "不要记", "先别记", "长期")
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe_ids(ids: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        item_id = str(raw).strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            result.append(item_id)
    return result


_DECISION_PROMPT = """\
你是 Amadeus 的长期记忆去重与纠错决策器。根据候选新记忆和已有相似记忆，输出处理决策。

候选类型：{candidate_type}
候选新记忆：
{candidate_summary}

已有相似记忆：
{existing_memories}

目标：保持记忆一致、有用，同时避免破坏性编辑。

可选 decision：
- skip: 候选是重复/同义/信息量不足，不写入
- create: 候选是全新独立记忆，写入
- replace: 候选明确更新、纠正或取代某一条旧记忆；写入候选，并将 target_ids 中的旧条目标记为 superseded

约束：
- replace 最多选择 1 个 target_id
- 不确定时选择 create 或 skip，不要猜测 replace
- 只能引用“已有相似记忆”里的 id

仅返回 JSON，不加说明：
{{
  "decision": "skip|create|replace",
  "reason": "简短原因",
  "target_ids": ["<旧条目id>"]
}}"""
