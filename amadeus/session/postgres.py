from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from psycopg.types.json import Jsonb

from amadeus.db import PostgresConfig, PostgresDatabase, normalize_psycopg_dsn
from amadeus.session.identity import SessionRef, build_message_id
from amadeus.session.store import Session, _now_iso


class PostgresSessionStore:
    """PostgreSQL session/message store used by the product runtime."""

    def __init__(self, dsn: str | None = None, *, db: PostgresDatabase | None = None) -> None:
        if db is None:
            if dsn is None:
                raise ValueError("Missing Amadeus runtime config: AMADEUS_POSTGRES_DSN")
            db = PostgresDatabase(PostgresConfig(dsn=normalize_psycopg_dsn(dsn)))
            db.open()
            self._owns_db = True
        else:
            self._owns_db = False
        self.db = db

    def close(self) -> None:
        if self._owns_db:
            self.db.close()

    def ensure_user(self, user_id: int, *, external_key: str | None = None) -> int:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (id, external_key, metadata, updated_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (id) DO UPDATE SET
                        external_key = COALESCE(users.external_key, excluded.external_key),
                        updated_at = now()
                    RETURNING id
                    """,
                    (int(user_id), external_key, Jsonb({})),
                )
                row = cursor.fetchone()
            conn.commit()
        return int(row["id"])

    def create_session(
        self,
        *,
        user_id: int,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_user(user_id)
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversation_sessions (
                        user_id, title, metadata, updated_at
                    )
                    VALUES (%s, %s, %s, now())
                    RETURNING id, user_id, title, metadata, last_consolidated,
                              created_at, updated_at
                    """,
                    (int(user_id), title, Jsonb(metadata or {})),
                )
                row = cursor.fetchone()
            conn.commit()
        return _session_row(row)

    def list_sessions(self, *, user_id: int) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, title, metadata, last_consolidated,
                           created_at, updated_at
                    FROM conversation_sessions
                    WHERE user_id = %s
                    ORDER BY updated_at DESC, id DESC
                    """,
                    (int(user_id),),
                )
                rows = cursor.fetchall()
        return [_session_row(row) for row in rows]

    def delete_session(self, *, user_id: int, session_id: int) -> bool:
        # messages / turns / markdown state 由 DB 外键 ON DELETE CASCADE 清理。
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM conversation_sessions
                    WHERE id = %s AND user_id = %s
                    """,
                    (int(session_id), int(user_id)),
                )
                deleted = bool(cursor.rowcount > 0)
            conn.commit()
        return deleted

    def get_session_meta(self, session: SessionRef) -> dict[str, Any] | None:
        user_id, session_id = session.identity
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, title, metadata, last_consolidated,
                           created_at, updated_at
                    FROM conversation_sessions
                    WHERE id = %s AND user_id = %s
                    """,
                    (session_id, user_id),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return _session_meta_from_row(row)

    def upsert_session(self, session: Session) -> None:
        user_id, session_id = session.identity
        self.ensure_user(user_id)
        metadata = dict(session.metadata)
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversation_sessions (
                        id, user_id, title, metadata, last_consolidated, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, now())
                    ON CONFLICT (id) DO UPDATE SET
                        metadata = excluded.metadata,
                        last_consolidated = excluded.last_consolidated,
                        updated_at = now()
                    """,
                    (
                        session_id,
                        user_id,
                        metadata.get("title"),
                        Jsonb(metadata),
                        int(session.last_consolidated),
                    ),
                )
                cursor.execute(
                    """
                    SELECT setval(
                        pg_get_serial_sequence('conversation_sessions', 'id'),
                        GREATEST(
                            (SELECT COALESCE(MAX(id), 1) FROM conversation_sessions),
                            %s
                        ),
                        true
                    )
                    """,
                    (session_id,),
                )
            conn.commit()

    def next_seq(self, session: SessionRef) -> int:
        user_id, session_id = session.identity
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(seq) + 1, 0) AS next_seq
                    FROM conversation_messages
                    WHERE user_id = %s AND session_id = %s
                    """,
                    (user_id, session_id),
                )
                row = cursor.fetchone()
        return int((row["next_seq"] if row else 0) or 0)

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
        user_id, session_id = session.identity
        message_id = build_message_id(user_id, session_id, seq)
        payload = dict(extra or {})
        turn_id = payload.get("turn_id")
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s, %s)",
                    (user_id, session_id),
                )
                cursor.execute(
                    """
                    INSERT INTO conversation_messages (
                        id, user_id, session_id, seq, role, content,
                        extra_json, ts, turn_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message_id,
                        user_id,
                        session_id,
                        int(seq),
                        role,
                        content,
                        Jsonb(payload),
                        ts,
                        turn_id,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE conversation_sessions
                    SET updated_at = now()
                    WHERE id = %s AND user_id = %s
                    """,
                    (session_id, user_id),
                )
            conn.commit()
        return {
            "id": message_id,
            "user_id": user_id,
            "session_id": session_id,
            "seq": int(seq),
            "role": role,
            "content": content,
            "timestamp": ts,
            **payload,
        }

    def fetch_session_messages(self, session: SessionRef) -> list[dict[str, Any]]:
        user_id, session_id = session.identity
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, session_id, seq, role, content,
                           extra_json, ts, turn_id
                    FROM conversation_messages
                    WHERE user_id = %s AND session_id = %s
                    ORDER BY seq ASC
                    """,
                    (user_id, session_id),
                )
                rows = cursor.fetchall()
        return [_message_row(row) for row in rows]

    def list_messages(self, *, user_id: int, session_id: int) -> list[dict[str, Any]]:
        return self.fetch_session_messages(SessionRef(user_id, session_id))

    def find_message_by_turn(
        self,
        turn_id: str,
        *,
        role: str,
    ) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, session_id, seq, role, content,
                           extra_json, ts, turn_id
                    FROM conversation_messages
                    WHERE turn_id = %s AND role = %s
                    """,
                    (turn_id, role),
                )
                row = cursor.fetchone()
        return _message_row(row) if row is not None else None

    def update_last_consolidated(self, session: SessionRef, value: int) -> None:
        user_id, session_id = session.identity
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE conversation_sessions
                    SET last_consolidated = %s, updated_at = now()
                    WHERE id = %s AND user_id = %s
                    """,
                    (int(value), session_id, user_id),
                )
            conn.commit()

    def fetch_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, session_id, seq, role, content,
                           extra_json, ts, turn_id
                    FROM conversation_messages
                    WHERE id = ANY(%s)
                    ORDER BY user_id ASC, session_id ASC, seq ASC
                    """,
                    (ids,),
                )
                rows = cursor.fetchall()
        found = {_message_row(row)["id"]: _message_row(row) for row in rows}
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
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                for item in targets:
                    user_id = int(item["user_id"])
                    session_id = int(item["session_id"])
                    seq = int(item["seq"])
                    cursor.execute(
                        """
                        SELECT id, user_id, session_id, seq, role, content,
                               extra_json, ts, turn_id
                        FROM conversation_messages
                        WHERE user_id = %s AND session_id = %s AND seq BETWEEN %s AND %s
                        ORDER BY seq ASC
                        """,
                        (user_id, session_id, max(0, seq - context), seq + context),
                    )
                    for row in cursor.fetchall():
                        message = _message_row(row)
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
        user_id: int | None = None,
        session_id: int | None = None,
        role: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses = ["content ILIKE %s"]
        params: list[Any] = [f"%{query}%"]
        if user_id is not None:
            clauses.append("user_id = %s")
            params.append(int(user_id))
        if session_id is not None:
            clauses.append("session_id = %s")
            params.append(int(session_id))
        if role:
            clauses.append("role = %s")
            params.append(role)
        where = " AND ".join(clauses)
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(1) AS count FROM conversation_messages WHERE {where}",
                    params,
                )
                total_row = cursor.fetchone()
                cursor.execute(
                    f"""
                    SELECT id, user_id, session_id, seq, role, content,
                           extra_json, ts, turn_id
                    FROM conversation_messages
                    WHERE {where}
                    ORDER BY ts DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    [*params, int(limit), int(offset)],
                )
                rows = cursor.fetchall()
        return [_message_row(row) for row in rows], int(total_row["count"] or 0)


def _session_meta_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    user_id = int(row["user_id"])
    session_id = int(row["id"])
    return {
        "user_id": user_id,
        "session_id": session_id,
        "created_at": _ts(row["created_at"]) or _now_iso(),
        "updated_at": _ts(row["updated_at"]) or _now_iso(),
        "last_consolidated": int(row["last_consolidated"] or 0),
        "metadata": dict(row["metadata"] or {}),
        "next_seq": 0,
    }


def _session_row(row: Mapping[str, Any]) -> dict[str, Any]:
    session_id = int(row["id"])
    user_id = int(row["user_id"])
    return {
        "session_id": session_id,
        "user_id": user_id,
        "title": row["title"],
        "metadata": dict(row["metadata"] or {}),
        "last_consolidated": int(row["last_consolidated"] or 0),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
    }


def _message_row(row: Mapping[str, Any]) -> dict[str, Any]:
    user_id = int(row["user_id"])
    session_id = int(row["session_id"])
    extra = dict(row["extra_json"] or {})
    turn_id = row.get("turn_id")
    return {
        "id": str(row["id"]),
        "user_id": user_id,
        "session_id": session_id,
        "seq": int(row["seq"]),
        "role": str(row["role"]),
        "content": str(row["content"]),
        "timestamp": _ts(row["ts"]) or _now_iso(),
        **({"turn_id": str(turn_id)} if turn_id is not None else {}),
        **extra,
    }


def _ts(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)
