from __future__ import annotations

import argparse
import asyncio
from types import SimpleNamespace

import pytest
from amadeus.app.cli import _run_chat
from amadeus.session.identity import SessionRef

_DEFAULT_SESSION_KEY = "user:1:session:1"
_DEFAULT_SESSION = SessionRef(user_id=1, session_id=1)


def test_run_chat_starts_before_turn_and_closes_on_runtime_error(monkeypatch):
    events: list[str] = []

    class Runtime:
        async def run_turn(self, **kwargs):
            events.append("turn")
            raise RuntimeError("turn failed")

    class App:
        config = SimpleNamespace(
            default_session=_DEFAULT_SESSION,
            default_session_key=_DEFAULT_SESSION_KEY,
        )
        runtime = Runtime()

        async def start(self):
            events.append("start")

        async def aclose(self):
            events.append("close")

    monkeypatch.setattr("amadeus.app.cli.build_passive_app", lambda **kwargs: App())
    args = argparse.Namespace(
        workspace_root=None,
        env=None,
        session_key=None,
        message="hello",
        retrieved_memory=None,
        skill=[],
        show_ids=False,
        trace=False,
    )

    with pytest.raises(RuntimeError, match="turn failed"):
        asyncio.run(_run_chat(args))

    assert events == ["start", "turn", "close"]


def test_run_chat_preserves_runtime_error_when_close_also_fails(monkeypatch):
    class Runtime:
        async def run_turn(self, **kwargs):
            raise RuntimeError("turn failed")

    class App:
        config = SimpleNamespace(
            default_session=_DEFAULT_SESSION,
            default_session_key=_DEFAULT_SESSION_KEY,
        )
        runtime = Runtime()

        async def start(self):
            return None

        async def aclose(self):
            raise ValueError("sensitive cleanup detail")

    monkeypatch.setattr("amadeus.app.cli.build_passive_app", lambda **kwargs: App())
    args = argparse.Namespace(
        workspace_root=None,
        env=None,
        session_key=None,
        message="hello",
        retrieved_memory=None,
        skill=[],
        show_ids=False,
        trace=False,
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
        config = SimpleNamespace(
            default_session=_DEFAULT_SESSION,
            default_session_key=_DEFAULT_SESSION_KEY,
        )
        runtime = Runtime()

        async def start(self):
            raise LookupError("start failed")

        async def aclose(self):
            raise OSError("sensitive cleanup detail")

    monkeypatch.setattr("amadeus.app.cli.build_passive_app", lambda **kwargs: App())
    args = argparse.Namespace(
        workspace_root=None,
        env=None,
        session_key=None,
        message="hello",
        retrieved_memory=None,
        skill=[],
        show_ids=False,
        trace=False,
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
                session_key=_DEFAULT_SESSION_KEY,
                user_message_id="user:1",
                assistant_message_id="assistant:1",
                tool_chain=[],
                context_retry={},
                provider_raw=None,
            )

    class App:
        config = SimpleNamespace(
            default_session=_DEFAULT_SESSION,
            default_session_key=_DEFAULT_SESSION_KEY,
        )
        runtime = Runtime()

        async def start(self):
            return None

        async def aclose(self):
            raise ValueError("close failed")

    monkeypatch.setattr("amadeus.app.cli.build_passive_app", lambda **kwargs: App())
    args = argparse.Namespace(
        workspace_root=None,
        env=None,
        session_key=None,
        message="hello",
        retrieved_memory=None,
        skill=[],
        show_ids=False,
        trace=False,
    )

    with pytest.raises(ValueError, match="close failed"):
        asyncio.run(_run_chat(args))


def test_format_trace_includes_session_and_tool_chain():
    """_format_trace produces deterministic trace output."""
    import amadeus.context as context
    from amadeus.app.cli import _format_trace
    from amadeus.prompting.assembler import PromptAssemblyResult
    from amadeus.runtime.passive import PassiveTurnResult

    result = PassiveTurnResult(
        session=SessionRef(user_id=1, session_id=1),
        user_message_id="trace:1:0",
        assistant_message_id="trace:1:1",
        assistant_response="final answer",
        context=context.ContextRenderResult(
            messages=[],
            system_prompt=context.SystemPromptResult(prompt="", breakdown=[], sections=[]),
            context_frame=context.ContextFrameResult(prompt="", breakdown=[], sections=[]),
            assembly=PromptAssemblyResult(),
        ),
        tool_chain=[
            {
                "text": "",
                "calls": [
                    {"name": "read_file", "status": "success",
                     "arguments": {"path": "/tmp/a"}, "call_id": "c1", "result": "ok"},
                ],
            },
        ],
        context_retry={
            "selected_plan": "full",
            "attempts": [
                {"name": "full", "history_window": 500, "disabled_sections": []},
            ],
            "trimmed_sections": [],
        },
        provider_raw=SimpleNamespace(model="gpt-4", usage={"prompt_tokens": 100}),
    )

    output = _format_trace(result, None)

    assert "Session key:        user:1:session:1" in output
    assert "User message ID:    trace:1:0" in output
    assert "Assistant message ID: trace:1:1" in output
    assert "Tool chain steps:   1" in output
    assert "read_file" in output
    assert "status=success" in output
    assert "Retry plan:         full" in output
    assert "Provider model:     gpt-4" in output
    assert "Usage:" in output


def test_format_trace_includes_memory_retrieval_section():
    import amadeus.context as context
    from amadeus.app.cli import _format_trace
    from amadeus.prompting.assembler import PromptAssemblyResult
    from amadeus.runtime.passive import PassiveTurnResult

    output = _format_trace(
        PassiveTurnResult(
            session=SessionRef(user_id=1, session_id=1),
            user_message_id="trace:1:0",
            assistant_message_id="trace:1:1",
            assistant_response="done",
            context=context.ContextRenderResult(
                messages=[],
                system_prompt=context.SystemPromptResult(prompt="", breakdown=[], sections=[]),
                context_frame=context.ContextFrameResult(prompt="", breakdown=[], sections=[]),
                assembly=PromptAssemblyResult(),
            ),
            tool_chain=[],
            context_retry={},
            memory_trace={
                "intent": "context",
                "candidate_count": 4,
                "record_count": 2,
                "fallbacks": ["lexical_only"],
                "injected_ids": ["mem_a"],
                "omitted_ids": ["mem_b"],
            },
        ),
        None,
    )

    assert "Memory intent:      context" in output
    assert "Memory candidates:  4" in output
    assert "Memory records:     2" in output
    assert "Memory injected:    mem_a" in output
    assert "Memory omitted:     mem_b" in output
    assert "Memory fallbacks:   lexical_only" in output


def test_run_eval_memory_recall_prints_summary(monkeypatch, capsys, tmp_path):
    from amadeus.app.cli import _run_eval_memory_recall

    captured: dict[str, object] = {}

    def fake_run_memory_recall_evaluation(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            total_cases=3,
            passed_cases=2,
            failed_case_ids=["case-b"],
            experiment_name="amadeus-memory-recall-001",
            experiment_url="https://smith.example.test/e/1",
            summary_path=tmp_path / "summary.md",
            results_path=tmp_path / "results.json",
        )

    monkeypatch.setattr(
        "amadeus.app.cli.run_memory_recall_evaluation",
        fake_run_memory_recall_evaluation,
    )
    args = argparse.Namespace(
        env=tmp_path / ".env",
        case_file=tmp_path / "cases.yaml",
        dataset_name="amadeus-memory-recall-v1",
        experiment_prefix="amadeus-memory-recall",
        judge_model=None,
        artifacts_dir=tmp_path / "runtime-artifacts" / "evaluation",
    )

    _run_eval_memory_recall(args)

    output = capsys.readouterr().out
    assert captured["dataset_name"] == "amadeus-memory-recall-v1"
    assert "Total cases: 3" in output
    assert "Passed cases: 2" in output
    assert "Failed cases: case-b" in output
    assert "LangSmith experiment: amadeus-memory-recall-001" in output


def test_run_eval_memory_quality_prints_summary(monkeypatch, capsys, tmp_path):
    from amadeus.app.cli import _run_eval_memory_quality

    captured: dict[str, object] = {}

    def fake_run_memory_quality_evaluation(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            total_cases=5,
            passed_cases=3,
            failed_case_ids=["quality-b", "quality-c"],
            experiment_name="amadeus-memory-quality-001",
            experiment_url="https://smith.example.test/e/quality-1",
            summary_path=tmp_path / "quality-summary.md",
            results_path=tmp_path / "quality-results.json",
        )

    monkeypatch.setattr(
        "amadeus.app.cli.run_memory_quality_evaluation",
        fake_run_memory_quality_evaluation,
    )
    args = argparse.Namespace(
        env=tmp_path / ".env",
        case_file=tmp_path / "quality-cases.yaml",
        dataset_name="amadeus-memory-quality-v1",
        experiment_prefix="amadeus-memory-quality",
        judge_model=None,
        artifacts_dir=tmp_path / "runtime-artifacts" / "evaluation",
    )

    _run_eval_memory_quality(args)

    output = capsys.readouterr().out
    assert captured["dataset_name"] == "amadeus-memory-quality-v1"
    assert "Total cases: 5" in output
    assert "Passed cases: 3" in output
    assert "Failed cases: quality-b, quality-c" in output
    assert "LangSmith experiment: amadeus-memory-quality-001" in output
