from __future__ import annotations

from amadeus.session import PostgresSessionStore, SessionManager, fetch_messages
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


def test_postgres_session_store_supports_legacy_runtime_session_keys() -> None:
    db = clean_postgres()
    try:
        store = PostgresSessionStore(db=db)
        manager = SessionManager(".", store=store)
        session = manager.get_or_create("chat:1")
        session.add_message("user", "legacy hello")
        manager.save(session)
        manager._cache.clear()

        reloaded = manager.get_or_create("chat:1")

        assert reloaded.key == "chat:1"
        assert reloaded.messages[0]["id"] == "chat:1:0"
    finally:
        db.close()
