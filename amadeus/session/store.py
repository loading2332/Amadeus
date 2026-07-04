from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from amadeus.context import Message
from amadeus.prompting import is_context_frame


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


@dataclass
class Session:
    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    last_consolidated: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

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


class SessionStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    key TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_consolidated INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    next_seq INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    extra TEXT NOT NULL DEFAULT '{}',
                    ts TEXT NOT NULL,
                    UNIQUE(session_key, seq)
                )
                """
            )
            self._conn.commit()

    def get_session_meta(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "key": str(row["key"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "last_consolidated": int(row["last_consolidated"] or 0),
            "metadata": json.loads(row["metadata"] or "{}"),
            "next_seq": int(row["next_seq"] or 0),
        }

    def upsert_session(self, session: Session) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (key, created_at, updated_at, last_consolidated, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    last_consolidated = excluded.last_consolidated,
                    metadata = excluded.metadata
                """,
                (
                    session.key,
                    session.created_at,
                    session.updated_at,
                    int(session.last_consolidated),
                    json.dumps(session.metadata, ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def next_seq(self, session_key: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq) + 1, 0) AS next_seq FROM messages WHERE session_key = ?",
                (session_key,),
            ).fetchone()
            meta = self._conn.execute(
                "SELECT next_seq FROM sessions WHERE key = ?",
                (session_key,),
            ).fetchone()
        from_messages = int((row["next_seq"] if row else 0) or 0)
        from_meta = int((meta["next_seq"] if meta else 0) or 0)
        return max(from_messages, from_meta)

    def insert_message(
        self,
        session_key: str,
        *,
        role: str,
        content: str,
        ts: str,
        seq: int,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = f"{session_key}:{seq}"
        payload = json.dumps(extra or {}, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO messages (id, session_key, seq, role, content, extra, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_key, int(seq), role, content, payload, ts),
            )
            self._conn.execute(
                """
                UPDATE sessions
                SET next_seq = CASE WHEN next_seq < ? THEN ? ELSE next_seq END
                WHERE key = ?
                """,
                (int(seq) + 1, int(seq) + 1, session_key),
            )
            self._conn.commit()
        return {
            "id": message_id,
            "session_key": session_key,
            "seq": int(seq),
            "role": role,
            "content": content,
            "timestamp": ts,
            **(extra or {}),
        }

    def fetch_session_messages(self, session_key: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, session_key, seq, role, content, extra, ts
                FROM messages
                WHERE session_key = ?
                ORDER BY seq ASC
                """,
                (session_key,),
            ).fetchall()
        return [_row_to_message(row) for row in rows]

    def update_last_consolidated(self, session_key: str, value: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET last_consolidated = ?, updated_at = ? WHERE key = ?",
                (int(value), _now_iso(), session_key),
            )
            self._conn.commit()

    def fetch_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT id, session_key, seq, role, content, extra, ts
                FROM messages
                WHERE id IN ({placeholders})
                ORDER BY session_key ASC, seq ASC
                """,
                tuple(ids),
            ).fetchall()
        found = {_row_to_message(row)["id"]: _row_to_message(row) for row in rows}
        return [found[item] for item in ids if item in found]

    def fetch_by_ids_with_context(
        self,
        ids: list[str],
        context: int,
    ) -> list[dict[str, Any]]:
        targets = self.fetch_by_ids(ids)
        if not targets:
            return []
        by_session: dict[str, list[int]] = {}
        for item in targets:
            by_session.setdefault(str(item["session_key"]), []).append(int(item["seq"]))

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        with self._lock:
            for session_key, seqs in by_session.items():
                for seq in seqs:
                    found = self._conn.execute(
                        """
                        SELECT id, session_key, seq, role, content, extra, ts
                        FROM messages
                        WHERE session_key = ? AND seq BETWEEN ? AND ?
                        ORDER BY seq ASC
                        """,
                        (session_key, max(0, seq - context), seq + context),
                    ).fetchall()
                    for row in found:
                        message = _row_to_message(row)
                        if message["id"] in seen:
                            continue
                        seen.add(str(message["id"]))
                        message["in_source_ref"] = message["id"] in ids
                        rows.append(message)
        return rows

    def search_messages(
        self,
        query: str,
        *,
        session_key: str | None = None,
        role: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses = ["content LIKE ?"]
        params: list[Any] = [f"%{query}%"]
        if session_key:
            clauses.append("session_key = ?")
            params.append(session_key)
        if role:
            clauses.append("role = ?")
            params.append(role)
        where = " AND ".join(clauses)
        with self._lock:
            total_row = self._conn.execute(
                f"SELECT COUNT(1) AS count FROM messages WHERE {where}",
                tuple(params),
            ).fetchone()
            rows = self._conn.execute(
                f"""
                SELECT id, session_key, seq, role, content, extra, ts
                FROM messages
                WHERE {where}
                ORDER BY ts DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                tuple([*params, int(limit), int(offset)]),
            ).fetchall()
        return [_row_to_message(row) for row in rows], int(total_row["count"] or 0)


class SessionManager:
    def __init__(self, workspace_root: str | Path, store: Any | None = None) -> None:
        self.workspace_root = Path(workspace_root)
        self.store = store or SessionStore(self.workspace_root / "sessions.db")
        self._cache: dict[str, Session] = {}

    def get_or_create(self, key: str) -> Session:
        if key in self._cache:
            return self._cache[key]
        meta = self.store.get_session_meta(key)
        if meta is None:
            session = Session(key=key)
            self.store.upsert_session(session)
        else:
            session = Session(
                key=key,
                created_at=meta["created_at"],
                updated_at=meta["updated_at"],
                last_consolidated=meta["last_consolidated"],
                metadata=meta["metadata"],
                messages=self.store.fetch_session_messages(key),
            )
        self._cache[key] = session
        return session

    def save(self, session: Session) -> None:
        self.store.upsert_session(session)
        next_seq = self.store.next_seq(session.key)
        for message in session.messages:
            if message.get("id"):
                continue
            ts = str(message.get("timestamp") or _now_iso())
            content = message.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            row = self.store.insert_message(
                session.key,
                role=str(message.get("role") or "assistant"),
                content=content,
                ts=ts,
                seq=next_seq,
                extra=_extra_fields(message),
            )
            message.update(row)
            next_seq += 1
        self.store.upsert_session(session)
        self._cache[session.key] = session

    def append_messages(self, session: Session, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            if message not in session.messages:
                session.messages.append(message)
        self.save(session)

    def update_last_consolidated(self, session: Session, value: int) -> None:
        session.last_consolidated = int(value)
        self.store.update_last_consolidated(session.key, int(value))
        self._cache[session.key] = session


def fetch_messages(
    store: SessionStore,
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
    store: SessionStore,
    query: str,
    *,
    session_key: str | None = None,
    role: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    rows, total = store.search_messages(
        query,
        session_key=session_key,
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


def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    extra = json.loads(row["extra"] or "{}")
    return {
        "id": str(row["id"]),
        "session_key": str(row["session_key"]),
        "seq": int(row["seq"]),
        "role": str(row["role"]),
        "content": str(row["content"]),
        "timestamp": str(row["ts"]),
        **extra,
    }


def _extra_fields(message: dict[str, Any]) -> dict[str, Any]:
    reserved = {"id", "session_key", "seq", "role", "content", "timestamp"}
    return {key: value for key, value in message.items() if key not in reserved}


def _render_history_tool_result(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _resolve_source_refs(values: list[str]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        raw = str(raw_value or "").strip()
        if not raw:
            continue
        prefix = raw.split("#", 1)[0]
        try:
            parsed = json.loads(prefix)
        except json.JSONDecodeError:
            candidates = [prefix]
        else:
            candidates = parsed if isinstance(parsed, list) else [parsed]
        for candidate in candidates:
            text = str(candidate).strip()
            if text and text not in seen:
                seen.add(text)
                resolved.append(text)
    return resolved


def _source_refs_from_evidence(evidence: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for item in evidence:
        source_ref = str(item.get("source_ref") or "").strip()
        if source_ref:
            values.append(source_ref)
        refs = item.get("refs")
        if isinstance(refs, list):
            values.extend(str(ref).strip() for ref in refs if str(ref).strip())
    return values


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
