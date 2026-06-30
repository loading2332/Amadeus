from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from amadeus.events import EventBus, TurnCommitted
from amadeus.prompt_render import PromptRenderCtx, PromptRenderFrame
from amadeus.prompting import PromptSectionRender
from amadeus.provider import (
    ChatCompletionsClient,
    ChatNamespace,
    LLMProvider,
    LLMProviderConfig,
)
from amadeus.runtime.before_reasoning import BeforeReasoningFrame
from amadeus.runtime.before_turn import BeforeTurnFrame
from amadeus.runtime.lifecycle import (
    AfterTurnContext,
    BeforeTurnContext,
    PromptRenderContext,
)
from amadeus.runtime.passive import PassiveRuntime
from amadeus.runtime.step_phases import AfterStepFrame, BeforeStepFrame
from amadeus.session.store import SessionManager
from amadeus.tools.base import ToolResult
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.registry import ToolRegistry


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[Any] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.responses:
            return cast(SimpleNamespace, self.responses.pop(0))
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="assistant reply"))],
            usage={},
        )


class StageDirectionCompletions(FakeCompletions):
    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="（突然被夸，愣了一下）\n\n什么啊……谢了。"
                    )
                )
            ],
            usage={},
        )


class ContextLengthThenSuccessCompletions(FakeCompletions):
    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise Exception("maximum context length exceeded")
        return SimpleNamespace(
            id="resp_retry",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="retry ok"))],
            usage={},
        )


class AlwaysContextLengthCompletions(FakeCompletions):
    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        raise Exception("maximum context length exceeded")


@dataclass
class FakeChatNamespace:
    completions: ChatCompletionsClient


class FakeClient:
    def __init__(self, completions: FakeCompletions | None = None) -> None:
        self.completions: FakeCompletions = completions or FakeCompletions()
        self.chat: ChatNamespace = FakeChatNamespace(completions=self.completions)


class EchoTool:
    name = "echo_tool"
    description = "Echo text input back to the model."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(tool_name=self.name, output={"echo": kwargs["text"]})


class _RuntimeMarkerModule:
    slot = "plugin.runtime_marker"
    requires = ("before_turn.build_ctx", "session:ctx")
    produces = ("session:ctx",)

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        context = cast(BeforeTurnContext, frame.slots["session:ctx"])
        context.runtime_metadata["phase_plugin"] = "reached provider"
        return frame


class _PromptMarkerModule:
    slot = "plugin.prompt_marker"
    requires = ("prompt_render.emit", "prompt:ctx")
    produces = ("prompt:ctx",)

    async def run(self, frame: PromptRenderFrame) -> PromptRenderFrame:
        context = cast(PromptRenderCtx, frame.slots["prompt:ctx"])
        context.system_sections_bottom.append(
            PromptSectionRender(
                label="prompt_marker",
                content=f"prompt marker for {context.attempt_name}",
                priority=8_000,
                is_static=False,
            )
        )
        return frame


class _BeforeTurnAbortModule:
    slot = "plugin.before_turn_abort"
    requires = ("before_turn.emit", "session:ctx")
    produces = ("session:abort_reply",)

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        frame.slots["session:abort_reply"] = "blocked at before_turn"
        return frame


class _BeforeReasoningAbortModule:
    slot = "plugin.before_reasoning_abort"
    requires = ("before_reasoning.emit", "reasoning:ctx")
    produces = ("reasoning:abort_reply",)

    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        frame.slots["reasoning:abort_reply"] = "blocked at before_reasoning"
        return frame


class _LifecycleHintModule:
    slot = "plugin.lifecycle_hint"
    requires = ("before_turn.emit", "session:ctx")
    produces = ("session:extra_hint:test",)

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        frame.slots["session:extra_hint:test"] = "remember the lifecycle hint"
        return frame


class _ReasoningHintModule:
    slot = "plugin.reasoning_hint"
    requires = ("before_reasoning.emit", "reasoning:ctx")
    produces = ("reasoning:extra_hint:test",)

    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        frame.slots["reasoning:extra_hint:test"] = "remember the reasoning hint"
        return frame


class _BeforeStepStopModule:
    slot = "plugin.before_step_stop"
    requires = ("before_step.emit", "step:before_ctx")
    produces = ("step:early_stop_reply",)

    async def run(self, frame: BeforeStepFrame) -> BeforeStepFrame:
        frame.slots["step:early_stop_reply"] = "before step stopped"
        return frame


class _AfterStepStopModule:
    slot = "plugin.after_step_stop"
    requires = ("after_step.emit", "step:after_ctx")
    produces = ("step:early_stop_reply",)

    async def run(self, frame: AfterStepFrame) -> AfterStepFrame:
        frame.slots["step:early_stop_reply"] = "after step stopped"
        return frame


def test_passive_runtime_persists_turn_and_emits_committed_event(tmp_path):
    client = FakeClient()
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    bus = EventBus()
    events = []
    bus.on(TurnCommitted, lambda event: events.append(event))
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        event_bus=bus,
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="hello")
    )

    session = manager.get_or_create("chat:1")
    assert [message["role"] for message in session.messages] == ["user", "assistant"]
    assert result.user_message_id == "chat:1:0"
    assert result.assistant_message_id == "chat:1:1"
    assert result.assistant_response == "assistant reply"
    assert len(events) == 1
    assert events[0].assistant_response == "assistant reply"


def test_passive_runtime_applies_before_turn_and_prompt_render_gates(tmp_path):
    client = FakeClient()
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path),
    )
    order: list[str] = []

    def before_turn(context: BeforeTurnContext) -> None:
        order.append("before_turn")
        context.retrieved_memory = "memory injected by lifecycle"

    def prompt_render(context: PromptRenderContext) -> None:
        order.append(f"prompt_render:{context.attempt_name}")
        context.runtime_context.turn_injection_context["lifecycle"] = (
            "prompt marker injected by lifecycle"
        )

    runtime.lifecycle.on_before_turn(before_turn)
    runtime.lifecycle.on_prompt_render(prompt_render)

    asyncio.run(runtime.run_turn(session_key="lifecycle:1", user_message="hello"))

    rendered_messages = client.completions.calls[0]["messages"]
    rendered_text = "\n".join(str(message["content"]) for message in rendered_messages)
    assert order == ["before_turn", "prompt_render:full"]
    assert "memory injected by lifecycle" in rendered_text
    assert "prompt marker injected by lifecycle" in rendered_text


def test_passive_runtime_phase_module_changes_provider_prompt(tmp_path) -> None:
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=SessionManager(tmp_path),
    )
    runtime.set_before_turn_plugin_modules([_RuntimeMarkerModule()])

    asyncio.run(runtime.run_turn(session_key="phase:1", user_message="hello"))

    rendered_text = "\n".join(
        str(message["content"])
        for message in client.completions.calls[0]["messages"]
    )
    assert "phase_plugin: reached provider" in rendered_text


def test_passive_runtime_prompt_render_module_changes_provider_prompt(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=SessionManager(tmp_path),
    )
    runtime.set_prompt_render_plugin_modules([_PromptMarkerModule()])

    asyncio.run(runtime.run_turn(session_key="prompt-phase:1", user_message="hello"))

    rendered_text = "\n".join(
        str(message["content"])
        for message in client.completions.calls[0]["messages"]
    )
    assert "prompt marker for full" in rendered_text


def test_before_turn_abort_skips_provider_and_persists_control_reply(tmp_path) -> None:
    client = FakeClient()
    manager = SessionManager(tmp_path)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=manager,
    )
    runtime.set_before_turn_plugin_modules([_BeforeTurnAbortModule()])

    result = asyncio.run(
        runtime.run_turn(session_key="abort:before-turn", user_message="hello")
    )

    assert client.completions.calls == []
    assert result.assistant_response == "blocked at before_turn"
    assert result.context_retry["selected_plan"] == "before_turn_abort"
    session = manager.get_or_create("abort:before-turn")
    assert [message["role"] for message in session.messages] == ["user", "assistant"]


def test_before_reasoning_abort_skips_provider_and_persists_control_reply(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=SessionManager(tmp_path),
    )
    runtime.set_before_reasoning_plugin_modules([_BeforeReasoningAbortModule()])

    result = asyncio.run(
        runtime.run_turn(session_key="abort:before-reasoning", user_message="hello")
    )

    assert client.completions.calls == []
    assert result.assistant_response == "blocked at before_reasoning"
    assert result.context_retry["selected_plan"] == "before_reasoning_abort"


def test_before_turn_and_reasoning_hints_reach_prompt(tmp_path: Path) -> None:
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=SessionManager(tmp_path),
    )
    runtime.set_before_turn_plugin_modules([_LifecycleHintModule()])
    runtime.set_before_reasoning_plugin_modules([_ReasoningHintModule()])

    asyncio.run(runtime.run_turn(session_key="hint:1", user_message="hello"))

    rendered_text = "\n".join(
        str(message["content"]) for message in client.completions.calls[0]["messages"]
    )
    assert "remember the lifecycle hint" in rendered_text
    assert "remember the reasoning hint" in rendered_text


def test_before_step_early_stop_skips_tool_batch(tmp_path: Path) -> None:
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1",
            model="fake-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="echo_tool",
                                    arguments=json.dumps({"text": "should not run"}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage={},
        ),
    ]
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=SessionManager(tmp_path),
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry),
    )
    runtime.set_before_step_plugin_modules([_BeforeStepStopModule()])

    result = asyncio.run(
        runtime.run_turn(session_key="step:before", user_message="use tool")
    )

    assert result.assistant_response == "before step stopped"
    assert result.tool_chain == []
    assert len(client.completions.calls) == 1


def test_after_step_early_stop_skips_followup_llm_round(tmp_path: Path) -> None:
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1",
            model="fake-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="echo_tool",
                                    arguments=json.dumps({"text": "ran"}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage={},
        ),
    ]
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=SessionManager(tmp_path),
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry),
    )
    runtime.set_after_step_plugin_modules([_AfterStepStopModule()])

    result = asyncio.run(
        runtime.run_turn(session_key="step:after", user_message="use tool")
    )

    assert result.assistant_response == "after step stopped"
    assert result.tool_chain[0]["calls"][0]["name"] == "echo_tool"
    assert len(client.completions.calls) == 1


def test_failed_phase_rebuild_keeps_previous_runtime_phase(tmp_path) -> None:
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=SessionManager(tmp_path),
    )
    runtime.set_before_turn_plugin_modules([_RuntimeMarkerModule()])

    with pytest.raises(RuntimeError, match="模块 slot 重复"):
        runtime.set_before_turn_plugin_modules(
            [_RuntimeMarkerModule(), _RuntimeMarkerModule()]
        )

    asyncio.run(runtime.run_turn(session_key="phase:atomic", user_message="hello"))
    rendered_text = "\n".join(
        str(message["content"])
        for message in client.completions.calls[0]["messages"]
    )
    assert "phase_plugin: reached provider" in rendered_text


def test_failed_prompt_phase_rebuild_keeps_previous_runtime_phase(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=SessionManager(tmp_path),
    )
    runtime.set_prompt_render_plugin_modules([_PromptMarkerModule()])

    with pytest.raises(RuntimeError, match="模块 slot 重复"):
        runtime.set_prompt_render_plugin_modules(
            [_PromptMarkerModule(), _PromptMarkerModule()]
        )

    asyncio.run(runtime.run_turn(session_key="prompt-phase:atomic", user_message="hello"))
    rendered_text = "\n".join(
        str(message["content"])
        for message in client.completions.calls[0]["messages"]
    )
    assert "prompt marker for full" in rendered_text


def test_setting_empty_phase_snapshot_restores_builtin_runtime(tmp_path) -> None:
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=SessionManager(tmp_path),
    )
    runtime.set_before_turn_plugin_modules([_RuntimeMarkerModule()])
    runtime.set_before_turn_plugin_modules([])

    asyncio.run(runtime.run_turn(session_key="phase:reset", user_message="hello"))

    rendered_text = "\n".join(
        str(message["content"])
        for message in client.completions.calls[0]["messages"]
    )
    assert "phase_plugin" not in rendered_text


def test_setting_empty_prompt_phase_snapshot_restores_builtin_runtime(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        ),
        session_manager=SessionManager(tmp_path),
    )
    runtime.set_prompt_render_plugin_modules([_PromptMarkerModule()])
    runtime.set_prompt_render_plugin_modules([])

    asyncio.run(runtime.run_turn(session_key="prompt-phase:reset", user_message="hello"))

    rendered_text = "\n".join(
        str(message["content"])
        for message in client.completions.calls[0]["messages"]
    )
    assert "prompt marker" not in rendered_text


def test_prompt_render_gate_receives_fresh_context_for_each_retry(tmp_path):
    client = FakeClient(completions=ContextLengthThenSuccessCompletions())
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path),
    )
    attempts: list[tuple[int, int]] = []

    def mark_attempt(context: PromptRenderContext) -> None:
        attempts.append((context.attempt_index, id(context.runtime_context)))
        context.runtime_context.turn_injection_context["attempt"] = (
            f"attempt marker {context.attempt_index}"
        )

    runtime.lifecycle.on_prompt_render(mark_attempt)

    asyncio.run(runtime.run_turn(session_key="lifecycle:retry", user_message="hello"))

    assert [attempt_index for attempt_index, _ in attempts] == [0, 1]
    assert attempts[0][1] != attempts[1][1]
    first_text = str(client.completions.calls[0]["messages"])
    second_text = str(client.completions.calls[1]["messages"])
    assert "attempt marker 0" in first_text
    assert "attempt marker 1" not in first_text
    assert "attempt marker 1" in second_text
    assert "attempt marker 0" not in second_text


def test_prompt_render_phase_module_receives_fresh_context_for_each_retry(
    tmp_path: Path,
) -> None:
    client = FakeClient(completions=ContextLengthThenSuccessCompletions())
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path),
    )
    runtime.set_prompt_render_plugin_modules([_PromptMarkerModule()])

    asyncio.run(runtime.run_turn(session_key="phase:retry", user_message="hello"))

    first_text = str(client.completions.calls[0]["messages"])
    second_text = str(client.completions.calls[1]["messages"])
    assert "prompt marker for full" in first_text
    assert "prompt marker for trim_runtime_metadata" not in first_text
    assert "prompt marker for trim_runtime_metadata" in second_text
    assert "prompt marker for full" not in second_text


def test_after_turn_tap_observes_persisted_turn_and_isolates_failures(tmp_path, caplog):
    client = FakeClient()
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    bus = EventBus()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        event_bus=bus,
    )
    order: list[str] = []

    bus.on(TurnCommitted, lambda _event: order.append("committed"))

    def broken(_context: AfterTurnContext) -> None:
        raise RuntimeError("tap failed")

    def observe(context: AfterTurnContext) -> None:
        persisted = manager.store.fetch_by_ids(
            [context.user_message_id, context.assistant_message_id]
        )
        assert [message["role"] for message in persisted] == ["user", "assistant"]
        order.append("after_turn")

    runtime.lifecycle.on_after_turn(broken)
    runtime.lifecycle.on_after_turn(observe)

    result = asyncio.run(
        runtime.run_turn(session_key="lifecycle:after", user_message="hello")
    )

    assert result.assistant_response == "assistant reply"
    assert order == ["committed", "after_turn"]
    assert "tap failed" in caplog.text


def test_passive_runtime_strips_stage_directions_before_persisting(tmp_path):
    client = FakeClient(completions=StageDirectionCompletions())
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    bus = EventBus()
    events = []
    bus.on(TurnCommitted, lambda event: events.append(event))
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        event_bus=bus,
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="你真厉害。")
    )

    session = manager.get_or_create("chat:1")
    assert result.assistant_response == "什么啊……谢了。"
    assert session.messages[-1]["content"] == "什么啊……谢了。"
    assert events[0].assistant_response == "什么啊……谢了。"


def test_passive_runtime_executes_single_tool_call_before_persisting_final_reply(
    tmp_path,
):
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1",
            model="fake-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="echo_tool",
                                    arguments=json.dumps({"text": "hello from tool"}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage={},
        ),
        SimpleNamespace(
            id="resp_2",
            model="fake-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="assistant after tool")
                )
            ],
            usage={},
        ),
    ]
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry),
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="please use a tool")
    )

    session = manager.get_or_create("chat:1")
    assert result.assistant_response == "assistant after tool"
    assert [message["role"] for message in session.messages] == ["user", "assistant"]
    assert len(client.completions.calls) == 2
    assert client.completions.calls[0]["tools"] == registry.export_openai_tools()
    assert client.completions.calls[1]["tools"] == registry.export_openai_tools()
    assert [message["role"] for message in client.completions.calls[1]["messages"][-2:]] == [
        "assistant",
        "tool",
    ]
    assert (
        client.completions.calls[1]["messages"][-2]["tool_calls"][0]["function"]["name"]
        == "echo_tool"
    )
    assert (
        '"echo": "hello from tool"'
        in client.completions.calls[1]["messages"][-1]["content"]
    )
    # tool_chain records the tool call
    assert len(result.tool_chain) == 1
    assert result.tool_chain[0]["calls"][0]["name"] == "echo_tool"
    assert result.tool_chain[0]["calls"][0]["status"] == "success"


def test_passive_runtime_continues_when_followup_response_requests_another_tool(
    tmp_path,
):
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1",
            model="fake-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="echo_tool",
                                    arguments=json.dumps({"text": "first"}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage={},
        ),
        SimpleNamespace(
            id="resp_2",
            model="fake-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Need one more lookup.",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_2",
                                function=SimpleNamespace(
                                    name="echo_tool",
                                    arguments=json.dumps({"text": "second"}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage={},
        ),
        SimpleNamespace(
            id="resp_3",
            model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content="final answer"))],
            usage={},
        ),
    ]
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry),
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="use tools twice")
    )

    assert result.assistant_response == "final answer"
    assert len(client.completions.calls) == 3
    assert [
        message["role"]
        for message in client.completions.calls[2]["messages"][-4:]
    ] == ["assistant", "tool", "assistant", "tool"]
    assert (
        client.completions.calls[2]["messages"][-2]["tool_calls"][0]["function"]["name"]
        == "echo_tool"
    )
    assert '"echo": "second"' in client.completions.calls[2]["messages"][-1]["content"]
    # tool_chain records both tool call rounds
    assert len(result.tool_chain) == 2
    assert result.tool_chain[0]["calls"][0]["name"] == "echo_tool"
    assert result.tool_chain[0]["calls"][0]["status"] == "success"
    assert result.tool_chain[1]["calls"][0]["name"] == "echo_tool"
    assert result.tool_chain[1]["calls"][0]["status"] == "success"


def test_passive_runtime_returns_progress_summary_when_tool_loop_hits_iteration_limit(
    tmp_path,
):
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1",
            model="fake-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="I need a file.",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="echo_tool",
                                    arguments=json.dumps({"text": "first"}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage={},
        ),
    ]
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry),
        max_tool_iterations=1,
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="use too many tools")
    )

    assert len(client.completions.calls) == 1
    assert "工具执行已经达到本轮上限" in result.assistant_response
    assert "echo_tool" in result.assistant_response
    assert "first" in result.assistant_response
    assert manager.get_or_create("chat:1").messages[-1]["content"] == result.assistant_response
    # tool_chain has the calls up to the limit
    assert len(result.tool_chain) == 1
    assert result.tool_chain[0]["calls"][0]["name"] == "echo_tool"
    assert result.tool_chain[0]["calls"][0]["status"] == "success"


def test_tool_chain_is_persisted_in_assistant_message_extra(tmp_path):
    """tool_chain 持久化进 assistant message 的 extra 字段。"""
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1", model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(
                    id="call_1", function=SimpleNamespace(
                        name="echo_tool", arguments=json.dumps({"text": "hello"})))],
            ))],
            usage={},
        ),
        SimpleNamespace(
            id="resp_2", model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content="done"))],
            usage={},
        ),
    ]
    provider = LLMProvider(LLMProviderConfig(api_key="secret", model="fake-model"), client=client)
    manager = SessionManager(tmp_path)
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path, provider=provider, session_manager=manager,
        tool_registry=registry, tool_executor=ToolExecutor(registry=registry),
    )
    result = asyncio.run(
        runtime.run_turn(session_key="persist:1", user_message="use tool")
    )

    # 从 session 中重新读取 assistant message，验证 tool_chain 已持久化
    session = manager.get_or_create("persist:1")
    assistant_msg = session.messages[-1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == result.assistant_response
    assert "tool_chain" in assistant_msg
    assert len(assistant_msg["tool_chain"]) == 1
    assert assistant_msg["tool_chain"][0]["calls"][0]["name"] == "echo_tool"

    # 验证从数据库重新加载后 tool_chain 仍然存在
    manager._cache.clear()
    reloaded_session = manager.get_or_create("persist:1")
    reloaded_msg = reloaded_session.messages[-1]
    assert "tool_chain" in reloaded_msg
    assert reloaded_msg["tool_chain"][0]["calls"][0]["name"] == "echo_tool"


def test_tool_messages_are_not_in_session_history(tmp_path):
    """Assistant/tool 中间消息不直接持久化，但 get_history 会从 tool_chain 重建它们。"""
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1", model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(
                    id="call_1", function=SimpleNamespace(
                        name="echo_tool", arguments=json.dumps({"text": "hello"})))],
            ))],
            usage={},
        ),
        SimpleNamespace(
            id="resp_2", model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content="final"))],
            usage={},
        ),
    ]
    provider = LLMProvider(LLMProviderConfig(api_key="secret", model="fake-model"), client=client)
    manager = SessionManager(tmp_path)
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path, provider=provider, session_manager=manager,
        tool_registry=registry, tool_executor=ToolExecutor(registry=registry),
    )
    result = asyncio.run(
        runtime.run_turn(session_key="filter:1", user_message="use tool")
    )

    session = manager.get_or_create("filter:1")
    # session.messages 应只有 user + assistant，没有 tool 中间消息
    assert [m["role"] for m in session.messages] == ["user", "assistant"]
    assert len(session.messages) == 2

    # get_history 不直接复用 raw tool 消息，而是从 assistant.tool_chain 重建 assistant/tool 序列
    history = session.get_history(500)
    assert [m["role"] for m in history] == ["user", "assistant", "tool", "assistant"]
    assert history[1]["tool_calls"][0]["function"]["name"] == "echo_tool"
    assert history[2]["tool_call_id"] == "call_1"
    assert history[3]["content"] == result.assistant_response


def test_passive_runtime_retries_with_next_context_trim_attempt(tmp_path):
    client = FakeClient(completions=ContextLengthThenSuccessCompletions())
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
    )

    result = asyncio.run(
        runtime.run_turn(
            session_key="retry:1",
            user_message="hello",
            runtime_metadata={"trace": "large runtime metadata"},
        )
    )

    assert result.assistant_response == "retry ok"
    assert len(client.completions.calls) == 2
    first_messages = client.completions.calls[0]["messages"]
    retry_messages = client.completions.calls[1]["messages"]
    assert "large runtime metadata" in first_messages[-2]["content"]
    assert all("large runtime metadata" not in str(message.get("content", "")) for message in retry_messages)
    assert result.context_retry["selected_plan"] == "trim_runtime_metadata"
    assert result.context_retry["trimmed_sections"] == ["runtime_metadata"]
    assert [attempt["name"] for attempt in result.context_retry["attempts"][:2]] == [
        "full",
        "trim_runtime_metadata",
    ]


def test_passive_runtime_persists_fallback_when_all_context_trim_attempts_fail(tmp_path):
    client = FakeClient(completions=AlwaysContextLengthCompletions())
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
    )

    result = asyncio.run(
        runtime.run_turn(session_key="retry:all", user_message="too much context")
    )

    assert "上下文过长" in result.assistant_response
    assert len(client.completions.calls) == len(result.context_retry["attempts"])
    assert result.context_retry["selected_plan"] is None
    session = manager.get_or_create("retry:all")
    assert [message["role"] for message in session.messages] == ["user", "assistant"]
    assert session.messages[-1]["content"] == result.assistant_response
