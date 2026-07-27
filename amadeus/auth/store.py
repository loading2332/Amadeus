from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from amadeus.db import PostgresDatabase


@dataclass(frozen=True)
class RefreshResult:
    user_id: int


class AuthStore:
    def __init__(self, db: PostgresDatabase) -> None:
        self.db = db

    def get_or_create_identity(self, provider: str, subject: str) -> int:
        with self.db.connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id FROM user_identities WHERE provider = %s AND provider_subject = %s",
                (provider, subject),
            )
            row = cursor.fetchone()
            if row is not None:
                return int(row["user_id"])
            cursor.execute("INSERT INTO users (metadata) VALUES ('{}'::jsonb) RETURNING id")
            user_id = int(cursor.fetchone()["id"])
            cursor.execute(
                """
                INSERT INTO user_identities (user_id, provider, provider_subject)
                VALUES (%s, %s, %s)
                ON CONFLICT (provider, provider_subject) DO NOTHING
                RETURNING user_id
                """,
                (user_id, provider, subject),
            )
            inserted = cursor.fetchone()
            if inserted is None:
                # Another callback won the identity race. Remove the unused
                # local user created by this transaction and reuse the winner.
                cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
                cursor.execute(
                    """
                    SELECT user_id FROM user_identities
                    WHERE provider = %s AND provider_subject = %s
                    """,
                    (provider, subject),
                )
                user_id = int(cursor.fetchone()["user_id"])
            conn.commit()
            return user_id

    def create_refresh_token(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        with self.db.connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO auth_refresh_tokens (id, user_id, token_hash, expires_at) VALUES (%s, %s, %s, %s)",
                (str(uuid4()), user_id, token_hash, expires_at),
            )
            conn.commit()

    def rotate_refresh_token(self, token_hash: str, replacement_hash: str, expires_at: datetime) -> RefreshResult | None:
        replacement_id = str(uuid4())
        with self.db.connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, revoked_at, expires_at FROM auth_refresh_tokens
                WHERE token_hash = %s FOR UPDATE
                """,
                (token_hash,),
            )
            row = cursor.fetchone()
            if row is None or row["expires_at"] <= datetime.now(row["expires_at"].tzinfo):
                conn.rollback()
                return None
            if row["revoked_at"] is not None:
                # A rotated token being presented again is evidence of token
                # replay. Revoke only its replacement chain (this login
                # session), leaving independent devices signed in.
                cursor.execute(
                    """
                    WITH RECURSIVE token_chain(id) AS (
                        SELECT %s::uuid
                        UNION ALL
                        SELECT token.replaced_by_id
                        FROM auth_refresh_tokens AS token
                        JOIN token_chain AS chain ON token.id = chain.id
                        WHERE token.replaced_by_id IS NOT NULL
                    )
                    UPDATE auth_refresh_tokens
                    SET revoked_at = now()
                    WHERE id IN (SELECT id FROM token_chain)
                      AND revoked_at IS NULL
                    """,
                    (row["id"],),
                )
                conn.commit()
                return None
            cursor.execute(
                "INSERT INTO auth_refresh_tokens (id, user_id, token_hash, expires_at) VALUES (%s, %s, %s, %s)",
                (replacement_id, row["user_id"], replacement_hash, expires_at),
            )
            cursor.execute(
                "UPDATE auth_refresh_tokens SET revoked_at = now(), replaced_by_id = %s WHERE id = %s",
                (replacement_id, row["id"]),
            )
            conn.commit()
            return RefreshResult(user_id=int(row["user_id"]))

    def revoke_refresh_token(self, token_hash: str) -> None:
        with self.db.connection() as conn, conn.cursor() as cursor:
            cursor.execute("UPDATE auth_refresh_tokens SET revoked_at = now() WHERE token_hash = %s AND revoked_at IS NULL", (token_hash,))
            conn.commit()
