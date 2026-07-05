from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from amadeus.context import Message
from amadeus.memory.source_refs import collect_source_ref_ids, source_refs_from_evidence
from amadeus.prompting import is_context_frame
from amadeus.session.identity import (
    SessionRef,
    build_message_id,
)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


@dataclass
class Session:
    ref: SessionRef
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    last_consolidated: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> tuple[int, int]:
        return self.ref.identity

    def add_message(self, role: str, content: str, **extra: Any) -> dict[str, Any]:
        message = {
            "role": role,
            "content": content,
            "timestamp": _now_iso(),
            **extra,
        }
        self.messages.append(message)
        self.updated_at = _now_iso()
        return message

    def get_history(self, max_messages: int = 500) -> list[Message]:
        selected = self.messages[-max_messages:] if max_messages > 0 else []
        history: list[Message] = []
        for message in selected:
            role = str(message.get("role") or "")
            content = str(message.get("content") or "")
            if role not in {"user", "assistant", "tool"}:
                continue
            if role == "tool":
                continue
            if role == "assistant":
                tool_chain = message.get("tool_chain") or []
                if isinstance(tool_chain, list):
                    for group in tool_chain:
                        if not isinstance(group, dict):
                            continue
                        calls = group.get("calls") or []
                        if not isinstance(calls, list) or not calls:
                            continue
                        assistant_tool_message: Message = {
                            "role": "assistant",
                            "content": str(group.get("text") or ""),
                            "tool_calls": [],
                        }
                        for call in calls:
                            if not isinstance(call, dict):
                                continue
                            assistant_tool_message["tool_calls"].append(
                                {
                                    "id": str(call.get("call_id") or ""),
                                    "type": "function",
                                    "function": {
                                        "name": str(call.get("name") or ""),
                                        "arguments": json.dumps(
                                            call.get("arguments") or {},
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            )
                        reasoning_content = group.get("reasoning_content")
                        if isinstance(reasoning_content, str):
                            assistant_tool_message["reasoning_content"] = reasoning_content
                        history.append(assistant_tool_message)
                        for call in calls:
                            if not isinstance(call, dict):
                                continue
                            history.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": str(call.get("call_id") or ""),
                                    "content": _render_history_tool_result(call.get("result")),
                                }
                            )
                final_reasoning_content = message.get("reasoning_content")
                final_message: dict[str, Any] = {"role": role, "content": content}
                if isinstance(final_reasoning_content, str):
                    final_message["reasoning_content"] = final_reasoning_content
                history.append(final_message)  # type: ignore[arg-type]
                continue
            history.append({"role": role, "content": content})  # type: ignore[typeddict-item]
        return history


class SessionStoreProtocol(Protocol):
    def close(self) -> None: ...

    def get_session_meta(self, session: SessionRef) -> dict[str, Any] | None: ...

    def upsert_session(self, session: Session) -> None: ...

    def next_seq(self, session: SessionRef) -> int: ...

    def insert_message(
        self,
        session: SessionRef,
        *,
        role: str,
        content: str,
        ts: str,
        seq: int,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def fetch_session_messages(self, session: SessionRef) -> list[dict[str, Any]]: ...

    def update_last_consolidated(self, session: SessionRef, value: int) -> None: ...

    def fetch_by_ids(self, ids: list[str]) -> list[dict[str, Any]]: ...

    def fetch_by_ids_with_context(
        self,
        ids: list[str],
        context: int,
    ) -> list[dict[str, Any]]: ...

    def search_messages(
        self,
        query: str,
        *,
        user_id: int | None = None,
        session_id: int | None = None,
        role: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]: ...


class InMemorySessionStore:
    """Non-persistent session store for tests and isolated local flows."""

    def __init__(self) -> None:
        self._sessions: dict[tuple[int, int], dict[str, Any]] = {}
        self._messages: dict[tuple[int, int], list[dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def close(self) -> None:
        return None

    def get_session_meta(self, session: SessionRef) -> dict[str, Any] | None:
        with self._lock:
            meta = self._sessions.get(session.identity)
            if meta is None:
                return None
            return {
                "user_id": int(meta["user_id"]),
                "session_id": int(meta["session_id"]),
                "created_at": str(meta["created_at"]),
                "updated_at": str(meta["updated_at"]),
                "last_consolidated": int(meta["last_consolidated"] or 0),
                "metadata": dict(meta["metadata"]),
                "next_seq": int(meta["next_seq"] or 0),
            }

    def upsert_session(self, session: Session) -> None:
        with self._lock:
            identity = session.identity
            current = self._sessions.get(identity)
            next_seq = int((current or {}).get("next_seq") or 0)
            self._sessions[identity] = {
                "user_id": int(session.ref.user_id),
                "session_id": int(session.ref.session_id),
                "created_at": current["created_at"] if current is not None else session.created_at,
                "updated_at": session.updated_at,
                "last_consolidated": int(session.last_consolidated),
                "metadata": dict(session.metadata),
                "next_seq": next_seq,
            }
            self._messages.setdefault(identity, [])

    def next_seq(self, session: SessionRef) -> int:
        with self._lock:
            messages = self._messages.get(session.identity, [])
            from_messages = max((int(item["seq"]) for item in messages), default=-1) + 1
            from_meta = int(self._sessions.get(session.identity, {}).get("next_seq") or 0)
            return max(from_messages, from_meta)

    def insert_message(
        self,
        session: SessionRef,
        *,
        role: str,
        content: str,
        ts: str,
        seq: int,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = build_message_id(session.user_id, session.session_id, seq)
        row = {
            "id": message_id,
            "user_id": int(session.user_id),
            "session_id": int(session.session_id),
            "seq": int(seq),
            "role": role,
            "content": content,
            "timestamp": ts,
            **(extra or {}),
        }
        with self._lock:
            identity = session.identity
            self._messages.setdefault(identity, []).append(dict(row))
            meta = self._sessions.setdefault(
                identity,
                {
                    "user_id": int(session.user_id),
                    "session_id": int(session.session_id),
                    "created_at": ts,
                    "updated_at": ts,
                    "last_consolidated": 0,
                    "metadata": {},
                    "next_seq": 0,
                },
            )
            meta["updated_at"] = ts
            meta["next_seq"] = max(int(meta.get("next_seq") or 0), int(seq) + 1)
        return row

    def fetch_session_messages(self, session: SessionRef) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._messages.get(session.identity, [])
            return [dict(row) for row in sorted(rows, key=lambda item: int(item["seq"]))]

    def update_last_consolidated(self, session: SessionRef, value: int) -> None:
        with self._lock:
            meta = self._sessions.setdefault(
                session.identity,
                {
                    "user_id": int(session.user_id),
                    "session_id": int(session.session_id),
                    "created_at": _now_iso(),
                    "updated_at": _now_iso(),
                    "last_consolidated": 0,
                    "metadata": {},
                    "next_seq": 0,
                },
            )
            meta["last_consolidated"] = int(value)
            meta["updated_at"] = _now_iso()

    def fetch_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        with self._lock:
            found = {
                str(row["id"]): dict(row)
                for rows in self._messages.values()
                for row in rows
            }
        return [found[item] for item in ids if item in found]

    def fetch_by_ids_with_context(
        self,
        ids: list[str],
        context: int,
    ) -> list[dict[str, Any]]:
        targets = self.fetch_by_ids(ids)
        if not targets:
            return []
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        with self._lock:
            for item in targets:
                identity = (int(item["user_id"]), int(item["session_id"]))
                seq = int(item["seq"])
                for message in self._messages.get(identity, []):
                    message_seq = int(message["seq"])
                    if message_seq < max(0, seq - context) or message_seq > seq + context:
                        continue
                    message_id = str(message["id"])
                    if message_id in seen:
                        continue
                    seen.add(message_id)
                    row = dict(message)
                    row["in_source_ref"] = message_id in ids
                    rows.append(row)
        rows.sort(key=lambda item: (int(item["user_id"]), int(item["session_id"]), int(item["seq"])))
        return rows

    def search_messages(
        self,
        query: str,
        *,
        user_id: int | None = None,
        session_id: int | None = None,
        role: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        lowered = query.lower()
        with self._lock:
            rows = [dict(row) for items in self._messages.values() for row in items]
        if user_id is not None:
            rows = [row for row in rows if int(row["user_id"]) == int(user_id)]
        if session_id is not None:
            rows = [row for row in rows if int(row["session_id"]) == int(session_id)]
        if role is not None:
            rows = [row for row in rows if str(row["role"]) == role]
        rows = [row for row in rows if lowered in str(row["content"]).lower()]
        rows.sort(key=lambda item: (str(item["timestamp"]), str(item["id"])), reverse=True)
        total = len(rows)
        sliced = rows[offset : offset + limit]
        return sliced, total


class SessionManager:
    def __init__(
        self,
        workspace_root: str | Path,
        store: SessionStoreProtocol,
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self.store: SessionStoreProtocol = store
        self._cache: dict[tuple[int, int], Session] = {}

    def get_or_create(self, session_ref: SessionRef) -> Session:
        identity = session_ref.identity
        if identity in self._cache:
            return self._cache[identity]
        meta = self.store.get_session_meta(session_ref)
        if meta is None:
            session = Session(ref=session_ref)
            self.store.upsert_session(session)
        else:
            session = Session(
                ref=SessionRef(int(meta["user_id"]), int(meta["session_id"])),
                created_at=meta["created_at"],
                updated_at=meta["updated_at"],
                last_consolidated=meta["last_consolidated"],
                metadata=meta["metadata"],
                messages=self.store.fetch_session_messages(session_ref),
            )
        self._cache[identity] = session
        return session

    def save(self, session: Session) -> None:
        self.store.upsert_session(session)
        next_seq = self.store.next_seq(session.ref)
        for message in session.messages:
            if message.get("id"):
                continue
            ts = str(message.get("timestamp") or _now_iso())
            content = message.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            row = self.store.insert_message(
                session.ref,
                role=str(message.get("role") or "assistant"),
                content=content,
                ts=ts,
                seq=next_seq,
                extra=_extra_fields(message),
            )
            message.update(row)
            next_seq += 1
        self.store.upsert_session(session)
        self._cache[session.identity] = session

    def append_messages(self, session: Session, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            if message not in session.messages:
                session.messages.append(message)
        self.save(session)

    def update_last_consolidated(self, session: Session, value: int) -> None:
        session.last_consolidated = int(value)
        self.store.update_last_consolidated(session.ref, int(value))
        self._cache[session.identity] = session


def fetch_messages(
    store: SessionStoreProtocol,
    *,
    ids: list[str] | None = None,
    source_ref: str | None = None,
    source_refs: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    context: int = 0,
) -> list[dict[str, Any]]:
    resolved = _resolve_source_refs(
        [
            *(ids or []),
            *([source_ref] if source_ref else []),
            *(source_refs or []),
            *_source_refs_from_evidence(evidence or []),
        ]
    )
    if context <= 0:
        return store.fetch_by_ids(resolved)
    return store.fetch_by_ids_with_context(resolved, context)


def search_messages(
    store: SessionStoreProtocol,
    query: str,
    *,
    user_id: int | None = None,
    session_id: int | None = None,
    role: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    rows, total = store.search_messages(
        query,
        user_id=user_id,
        session_id=session_id,
        role=role,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + len(rows)
    messages = [_build_search_preview(row, query) for row in rows]
    return {
        "count": len(rows),
        "matched_count": total,
        "has_more": next_offset < total,
        "next_offset": next_offset if next_offset < total else None,
        "messages": messages,
    }


def _extra_fields(message: dict[str, Any]) -> dict[str, Any]:
    reserved = {"id", "user_id", "session_id", "seq", "role", "content", "timestamp"}
    return {key: value for key, value in message.items() if key not in reserved}


def _render_history_tool_result(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _resolve_source_refs(values: list[str]) -> list[str]:
    return collect_source_ref_ids(values)


def _source_refs_from_evidence(evidence: list[dict[str, Any]]) -> list[str]:
    return source_refs_from_evidence(evidence)


def _build_search_preview(message: dict[str, Any], query: str) -> dict[str, Any]:
    content = str(message.get("content") or "")
    preview, total_line_count, truncated = _preview_lines(content)
    terms = [term for term in query.split() if term]
    return {
        **message,
        "source_ref": str(message.get("id") or ""),
        "preview": preview,
        "preview_line_count": len(preview.splitlines()) if preview else 0,
        "total_line_count": total_line_count,
        "truncated": truncated,
        "matched_terms": [term for term in terms if term.lower() in content.lower()],
    }


def _preview_lines(content: str, *, max_lines: int = 50) -> tuple[str, int, bool]:
    lines = content.splitlines() or [content]
    total = len(lines)
    truncated = total > max_lines
    preview_lines = lines[:max_lines]
    if truncated:
        preview_lines.append(f"... truncated {total - max_lines} lines; call fetch_messages(source_ref) for full text")
    return "\n".join(preview_lines), total, truncated


def is_real_memory_message(message: dict[str, Any]) -> bool:
    if message.get("role") == "tool":
        return False
    if message.get("role") not in {"user", "assistant"}:
        return False
    if message.get("role") == "assistant" and message.get("proactive"):
        return False
    return not is_context_frame(str(message.get("content") or ""))
