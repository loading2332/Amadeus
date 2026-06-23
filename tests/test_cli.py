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
