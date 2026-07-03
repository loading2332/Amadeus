from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class MemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def list_table_names(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                ORDER BY name
                """
            ).fetchall()
        return [str(row["name"]) for row in rows]

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    happened_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    reinforcement INTEGER NOT NULL DEFAULT 1,
                    emotional_weight REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    extra_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS ix_memory_items_status
                    ON memory_items(status);
                CREATE INDEX IF NOT EXISTS ix_memory_items_type
                    ON memory_items(memory_type);
                CREATE INDEX IF NOT EXISTS ix_memory_items_source_ref
                    ON memory_items(source_ref);

                CREATE TABLE IF NOT EXISTS memory_replacements (
                    old_item_id TEXT NOT NULL,
                    new_item_id TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_memory_replacements_old_item
                    ON memory_replacements(old_item_id);
                CREATE INDEX IF NOT EXISTS ix_memory_replacements_source_ref
                    ON memory_replacements(source_ref);
                """
            )
            self._conn.commit()

    def insert_item(
        self,
        *,
        item_id: str,
        memory_type: str,
        summary: str,
        content_hash: str,
        embedding: list[float],
        source_ref: str,
        happened_at: str | None,
        scope_channel: str | None,
        scope_chat_id: str | None,
        emotional_weight: float,
        extra: dict[str, Any],
    ) -> None:
        now = datetime.now().astimezone().isoformat()
        extra_payload = dict(extra)
        extra_payload["scope_channel"] = scope_channel
        extra_payload["scope_chat_id"] = scope_chat_id
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memory_items (
                    id,
                    memory_type,
                    summary,
                    content_hash,
                    embedding,
                    source_ref,
                    happened_at,
                    status,
                    reinforcement,
                    emotional_weight,
                    created_at,
                    updated_at,
                    extra_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    memory_type,
                    summary,
                    content_hash,
                    json.dumps([float(value) for value in embedding]),
                    source_ref,
                    happened_at,
                    float(emotional_weight),
                    now,
                    now,
                    json.dumps(extra_payload, ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def upsert_item(
        self,
        *,
        memory_type: str,
        summary: str,
        embedding: list[float],
        source_ref: str,
        happened_at: str | None = None,
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        emotional_weight: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        normalized_type = memory_type.strip() or "event"
        text = summary.strip()
        src = source_ref.strip()
        if not text or not src:
            return "", "invalid"
        digest = _content_hash(text, normalized_type)
        item_id = f"mem_{digest}"
        now = datetime.now().astimezone().isoformat()
        extra_payload = dict(extra or {})
        extra_payload["scope_channel"] = scope_channel
        extra_payload["scope_chat_id"] = scope_chat_id
        with self._lock:
            existing_source = self._conn.execute(
                """
                SELECT id
                FROM memory_items
                WHERE source_ref = ? AND memory_type = ?
                """,
                (src, normalized_type),
            ).fetchone()
            if existing_source is not None:
                return str(existing_source["id"]), "skipped"

            existing_hash = self._conn.execute(
                """
                SELECT id
                FROM memory_items
                WHERE content_hash = ? AND memory_type = ?
                """,
                (digest, normalized_type),
            ).fetchone()
            if existing_hash is not None:
                reinforced_id = str(existing_hash["id"])
                self._conn.execute(
                    """
                    UPDATE memory_items
                    SET reinforcement = reinforcement + 1,
                        updated_at = ?,
                        happened_at = COALESCE(NULLIF(happened_at, ''), ?),
                        emotional_weight = MAX(emotional_weight, ?)
                    WHERE id = ?
                    """,
                    (now, happened_at, float(emotional_weight), reinforced_id),
                )
                self._conn.commit()
                return reinforced_id, "reinforced"

            self._conn.execute(
                """
                INSERT INTO memory_items (
                    id,
                    memory_type,
                    summary,
                    content_hash,
                    embedding,
                    source_ref,
                    happened_at,
                    status,
                    reinforcement,
                    emotional_weight,
                    created_at,
                    updated_at,
                    extra_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    normalized_type,
                    text,
                    digest,
                    json.dumps([float(value) for value in embedding]),
                    src,
                    happened_at,
                    float(emotional_weight),
                    now,
                    now,
                    json.dumps(extra_payload, ensure_ascii=False),
                ),
            )
            self._conn.commit()
        return item_id, "new"

    def record_replacement(
        self,
        old_item_id: str,
        new_item_id: str,
        source_ref: str,
    ) -> None:
        now = datetime.now().astimezone().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memory_replacements (
                    old_item_id,
                    new_item_id,
                    source_ref,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (old_item_id, new_item_id, source_ref, now),
            )
            self._conn.commit()

    def list_replacements_for(self, old_item_id: str) -> list[dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT old_item_id, new_item_id
                FROM memory_replacements
                WHERE old_item_id = ?
                ORDER BY created_at ASC
                """,
                (old_item_id,),
            ).fetchall()
        return [
            {
                "old_item_id": str(row["old_item_id"]),
                "new_item_id": str(row["new_item_id"]),
            }
            for row in rows
        ]

    def find_replacements_by_source_ref(self, source_ref: str) -> list[dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT old_item_id, new_item_id, source_ref
                FROM memory_replacements
                WHERE source_ref = ?
                ORDER BY created_at ASC
                """,
                (source_ref,),
            ).fetchall()
        return [
            {
                "old_item_id": str(row["old_item_id"]),
                "new_item_id": str(row["new_item_id"]),
                "source_ref": str(row["source_ref"]),
            }
            for row in rows
        ]

    def list_active_items(
        self,
        *,
        memory_types: tuple[str, ...] = (),
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["status = 'active'"]
        params: list[Any] = []
        clean_types = tuple(value.strip() for value in memory_types if value.strip())
        if clean_types:
            clauses.append(f"memory_type IN ({','.join('?' for _ in clean_types)})")
            params.extend(clean_types)
        if scope_channel is not None:
            clauses.append("json_extract(extra_json, '$.scope_channel') = ?")
            params.append(scope_channel)
        if scope_chat_id is not None:
            clauses.append("json_extract(extra_json, '$.scope_chat_id') = ?")
            params.append(scope_chat_id)
        if time_start is not None:
            clauses.append("happened_at IS NOT NULL")
            clauses.append("datetime(happened_at) >= datetime(?)")
            params.append(_normalize_datetime(time_start))
        if time_end is not None:
            clauses.append("happened_at IS NOT NULL")
            clauses.append("datetime(happened_at) <= datetime(?)")
            params.append(_normalize_datetime(time_end))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM memory_items
                WHERE {" AND ".join(clauses)}
                ORDER BY updated_at DESC
                """,
                tuple(params),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def find_items_by_source_ref(self, source_ref: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT *
                FROM memory_items
                WHERE source_ref = ?
                ORDER BY updated_at DESC
                """,
                (source_ref,),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def get_items_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM memory_items
                WHERE id IN ({placeholders})
                ORDER BY updated_at DESC
                """,
                tuple(ids),
            ).fetchall()
        found = {item["id"]: item for item in (self._row_to_item(row) for row in rows)}
        return [found[item_id] for item_id in ids if item_id in found]

    def get_item_by_id(self, item_id: str) -> dict[str, Any] | None:
        items = self.get_items_by_ids([item_id])
        return items[0] if items else None

    def mark_items_status(
        self,
        ids: list[str],
        *,
        status: str,
        extra_patch: dict[str, Any],
    ) -> None:
        now = datetime.now().astimezone().isoformat()
        with self._lock:
            for item in self.get_items_by_ids(ids):
                extra = dict(item["extra"])
                extra.update(extra_patch)
                self._conn.execute(
                    """
                    UPDATE memory_items
                    SET status = ?, updated_at = ?, extra_json = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        now,
                        json.dumps(extra, ensure_ascii=False),
                        item["id"],
                    ),
                )
            self._conn.commit()

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "memory_type": str(row["memory_type"]),
            "summary": str(row["summary"]),
            "content_hash": str(row["content_hash"]),
            "embedding": json.loads(row["embedding"]),
            "source_ref": str(row["source_ref"]),
            "happened_at": row["happened_at"],
            "status": str(row["status"]),
            "reinforcement": int(row["reinforcement"] or 1),
            "emotional_weight": float(row["emotional_weight"] or 0.0),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "extra": json.loads(row["extra_json"] or "{}"),
        }


def _normalize_datetime(value: datetime) -> str:
    normalized = (
        value.astimezone(UTC).replace(tzinfo=None)
        if value.tzinfo
        else value.replace(tzinfo=None)
    )
    return normalized.replace(microsecond=0).isoformat()


def _content_hash(summary: str, memory_type: str) -> str:
    normalized = " ".join(summary.lower().split())
    return hashlib.sha256(f"{memory_type}:{normalized}".encode()).hexdigest()[:16]
