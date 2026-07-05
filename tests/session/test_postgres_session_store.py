from __future__ import annotations

import pytest
from amadeus.session import PostgresSessionStore, SessionManager, fetch_messages
from amadeus.session.identity import SessionRef
from tests.db.postgres_helpers import clean_postgres


def test_postgres_session_store_user_isolation_and_message_round_trip() -> None:
    db = clean_postgres()
    try:
        store = PostgresSessionStore(db=db)
        first = store.create_session(user_id=1, title="u1")
        second = store.create_session(user_id=2, title="u2")

        manager = SessionManager(".", store=store)
        session = manager.get_or_create(first["session_key"])
        session.add_message("user", "hello")
        session.add_message(
            "assistant",
            "final",
            tool_chain=[
                {
                    "text": "call tool",
                    "calls": [
                        {
                            "call_id": "call_1",
                            "name": "lookup",
                            "arguments": {"q": "x"},
                            "result": {"ok": True},
                        }
                    ],
                }
            ],
        )
        manager.save(session)
        manager._cache.clear()

        assert [row["session_id"] for row in store.list_sessions(user_id=1)] == [
            first["session_id"]
        ]
        assert [row["session_id"] for row in store.list_sessions(user_id=2)] == [
            second["session_id"]
        ]
        assert store.list_messages(user_id=2, session_id=first["session_id"]) == []

        reloaded = manager.get_or_create(first["session_key"])
        history = reloaded.get_history()
        assert [message["role"] for message in history] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]

        rows = fetch_messages(store, source_ref="session:1:1:0")
        assert rows[0]["content"] == "hello"
    finally:
        db.close()


def test_postgres_session_store_rejects_noncanonical_session_keys() -> None:
    db = clean_postgres()
    try:
        store = PostgresSessionStore(db=db)
        manager = SessionManager(".", store=store)
        with pytest.raises(ValueError, match="user/session shape"):
            manager.get_or_create("session:1:1")
    finally:
        db.close()


def test_postgres_session_store_advances_sequence_after_explicit_session_id() -> None:
    db = clean_postgres()
    try:
        store = PostgresSessionStore(db=db)
        manager = SessionManager(".", store=store)

        manager.get_or_create(SessionRef(user_id=1, session_id=9))
        created = store.create_session(user_id=1, title="next")

        assert created["session_id"] > 9
    finally:
        db.close()

