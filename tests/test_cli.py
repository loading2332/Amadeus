from __future__ import annotations

import argparse
import asyncio
from types import SimpleNamespace

import pytest
from amadeus.cli import _run_chat


def test_run_chat_starts_before_turn_and_closes_on_runtime_error(monkeypatch):
    events: list[str] = []

    class Runtime:
        async def run_turn(self, **kwargs):
            events.append("turn")
            raise RuntimeError("turn failed")

    class App:
        config = SimpleNamespace(default_session_key="cli:default")
        runtime = Runtime()

        async def start(self):
            events.append("start")

        async def aclose(self):
            events.append("close")

    monkeypatch.setattr("amadeus.cli.build_passive_app", lambda **kwargs: App())
    args = argparse.Namespace(
        workspace_root=None,
        env=None,
        session_key=None,
        message="hello",
        retrieved_memory=None,
        skill=[],
        show_ids=False,
    )

    with pytest.raises(RuntimeError, match="turn failed"):
        asyncio.run(_run_chat(args))

    assert events == ["start", "turn", "close"]


def test_run_chat_preserves_runtime_error_when_close_also_fails(monkeypatch):
    class Runtime:
        async def run_turn(self, **kwargs):
            raise RuntimeError("turn failed")

    class App:
        config = SimpleNamespace(default_session_key="cli:default")
        runtime = Runtime()

        async def start(self):
            return None

        async def aclose(self):
            raise ValueError("sensitive cleanup detail")

    monkeypatch.setattr("amadeus.cli.build_passive_app", lambda **kwargs: App())
    args = argparse.Namespace(
        workspace_root=None,
        env=None,
        session_key=None,
        message="hello",
        retrieved_memory=None,
        skill=[],
        show_ids=False,
    )

    with pytest.raises(RuntimeError, match="turn failed") as exc_info:
        asyncio.run(_run_chat(args))

    notes = getattr(exc_info.value, "__notes__", [])
    assert notes == ["PassiveApp cleanup failed (ValueError)"]
    assert "sensitive cleanup detail" not in " ".join(notes)


def test_run_chat_preserves_start_error_when_close_also_fails(monkeypatch):
    class Runtime:
        async def run_turn(self, **kwargs):
            raise AssertionError("turn must not run")

    class App:
        config = SimpleNamespace(default_session_key="cli:default")
        runtime = Runtime()

        async def start(self):
            raise LookupError("start failed")

        async def aclose(self):
            raise OSError("sensitive cleanup detail")

    monkeypatch.setattr("amadeus.cli.build_passive_app", lambda **kwargs: App())
    args = argparse.Namespace(
        workspace_root=None,
        env=None,
        session_key=None,
        message="hello",
        retrieved_memory=None,
        skill=[],
        show_ids=False,
    )

    with pytest.raises(LookupError, match="start failed") as exc_info:
        asyncio.run(_run_chat(args))

    notes = getattr(exc_info.value, "__notes__", [])
    assert notes == ["PassiveApp cleanup failed (OSError)"]
    assert "sensitive cleanup detail" not in " ".join(notes)


def test_run_chat_propagates_close_error_when_operation_succeeds(monkeypatch):
    class Runtime:
        async def run_turn(self, **kwargs):
            return SimpleNamespace(
                assistant_response="reply",
                session_key="cli:default",
                user_message_id="user:1",
                assistant_message_id="assistant:1",
            )

    class App:
        config = SimpleNamespace(default_session_key="cli:default")
        runtime = Runtime()

        async def start(self):
            return None

        async def aclose(self):
            raise ValueError("close failed")

    monkeypatch.setattr("amadeus.cli.build_passive_app", lambda **kwargs: App())
    args = argparse.Namespace(
        workspace_root=None,
        env=None,
        session_key=None,
        message="hello",
        retrieved_memory=None,
        skill=[],
        show_ids=False,
    )

    with pytest.raises(ValueError, match="close failed"):
        asyncio.run(_run_chat(args))
