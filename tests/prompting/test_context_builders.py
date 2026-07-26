from dataclasses import dataclass

import pytest
from amadeus.context import (
    ContextBuilder,
    Message,
    MessageEnvelopeBuilder,
    RuntimeContext,
    SystemPromptBuilder,
)
from amadeus.prompt_block import PromptBlockRenderResult


def make_context(tmp_path, **overrides):
    values = {
        "workspace_root": tmp_path,
        "history": [],
        "current_user_message": "hello",
    }
    values.update(overrides)
    return RuntimeContext(**values)


@dataclass
class CountingBlock:
    label: str
    priority: int
    content: str
    is_static: bool = False
    empty_reason: str = "empty"
    calls: int = 0

    def render(self, context):
        self.calls += 1
        if not self.content:
            return PromptBlockRenderResult("", self.empty_reason)
        return PromptBlockRenderResult(f"{self.content} #{self.calls}")


def test_system_prompt_builder_sorts_blocks_by_priority(tmp_path):
    low_priority = CountingBlock("later", 20, "later")
    high_priority = CountingBlock("earlier", 10, "earlier")

    result = SystemPromptBuilder([low_priority, high_priority]).build(make_context(tmp_path))

    assert [section.content for section in result.sections] == [
        "earlier #1",
        "later #1",
    ]
    assert [entry.label for entry in result.breakdown] == ["earlier", "later"]


def test_system_prompt_builder_tracks_empty_blocks_without_rendering_them(tmp_path):
    empty = CountingBlock("empty", 10, "", empty_reason="nothing to render")
    full = CountingBlock("full", 20, "content")

    result = SystemPromptBuilder([empty, full]).build(make_context(tmp_path))

    assert result.prompt == "content #1"
    assert result.breakdown[0].label == "empty"
    assert result.breakdown[0].rendered is False
    assert result.breakdown[0].char_count == 0
    assert result.breakdown[0].estimated_tokens == 0
    assert result.breakdown[0].empty_reason == "nothing to render"


def test_system_prompt_builder_caches_static_blocks(tmp_path):
    static = CountingBlock("static", 10, "static", is_static=True)
    builder = SystemPromptBuilder([static])

    first = builder.build(make_context(tmp_path))
    second = builder.build(make_context(tmp_path))

    assert static.calls == 1
    assert first.prompt == "static #1"
    assert second.prompt == "static #1"


def test_system_prompt_builder_rerenders_dynamic_blocks(tmp_path):
    dynamic = CountingBlock("dynamic", 10, "dynamic", is_static=False)
    builder = SystemPromptBuilder([dynamic])

    first = builder.build(make_context(tmp_path))
    second = builder.build(make_context(tmp_path))

    assert dynamic.calls == 2
    assert first.prompt == "dynamic #1"
    assert second.prompt == "dynamic #2"


def test_debug_entry_counts_characters_and_estimated_tokens(tmp_path):
    block = CountingBlock("block", 10, "abcd")

    result = SystemPromptBuilder([block]).build(make_context(tmp_path))

    entry = result.breakdown[0]
    assert entry.label == "block"
    assert entry.priority == 10
    assert entry.rendered is True
    assert entry.char_count == len("abcd #1")
    assert entry.estimated_tokens == 2
    assert entry.empty_reason is None


def test_dynamic_memory_is_structurally_in_context_frame_not_system_prompt(tmp_path):
    self_path = tmp_path / "memory" / "SELF.md"
    self_path.parent.mkdir()
    self_path.write_text("stable identity boundary", encoding="utf-8")

    result = ContextBuilder().render(
        make_context(tmp_path, retrieved_memory="dynamic retrieved material")
    )

    system_prompt = result.system_prompt.prompt
    assert "## self_model" not in system_prompt
    assert "stable identity boundary" not in system_prompt
    assert "stable identity boundary" in result.context_frame.prompt
    assert "dynamic retrieved material" not in system_prompt
    assert "dynamic retrieved material" in result.context_frame.prompt
    assert [entry.label for entry in result.system_prompt.breakdown] == [
        "identity",
        "behavior_rules",
    ]
    assert [entry.label for entry in result.context_frame.breakdown] == [
        "self_model",
        "long_term_memory",
        "recent_context",
        "retrieved_memory",
        "active_skills",
        "runtime_metadata",
    ]


def test_message_envelope_places_system_history_and_current_user_message():
    history: list[Message] = [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]

    messages = MessageEnvelopeBuilder().build(
        system_prompt="system prompt",
        history=history,
        context_frame="context frame",
        current_user_message="current question",
    )

    assert messages == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "context frame"},
        {"role": "user", "content": "current question"},
    ]


def test_message_envelope_omits_empty_context_frame():
    messages = MessageEnvelopeBuilder().build(
        system_prompt="system prompt",
        history=[],
        context_frame="  ",
        current_user_message="current question",
    )

    assert messages == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "current question"},
    ]


def test_message_envelope_rejects_system_messages_in_history():
    with pytest.raises(ValueError, match="history must not contain system messages"):
        MessageEnvelopeBuilder().build(
            system_prompt="system prompt",
            history=[{"role": "system", "content": "nested system"}],
            current_user_message="current question",
        )


def test_context_builder_default_blocks_route_self_model_to_context_frame(tmp_path):
    self_path = tmp_path / "memory" / "SELF.md"
    self_path.parent.mkdir()
    self_path.write_text("Amadeus stays grounded.", encoding="utf-8")

    result = ContextBuilder().render(make_context(tmp_path))

    assert result.messages[0]["role"] == "system"
    assert "Amadeus stays grounded." not in result.messages[0]["content"]
    assert "## self_model\n\nAmadeus stays grounded." in result.context_frame.prompt
    assert result.messages[-1] == {"role": "user", "content": "hello"}
    assert [entry.label for entry in result.system_prompt.breakdown] == [
        "identity",
        "behavior_rules",
    ]


def test_context_builder_routes_dynamic_context_to_context_frame(tmp_path):
    recent_path = tmp_path / "memory" / "RECENT_CONTEXT.md"
    recent_path.parent.mkdir()
    recent_path.write_text("recent summary", encoding="utf-8")

    result = ContextBuilder().render(
        make_context(
            tmp_path,
            retrieved_memory="retrieved fact",
            active_skills=["python"],
            runtime_metadata={"channel": "chat"},
        )
    )

    assert "recent summary" not in result.system_prompt.prompt
    assert "retrieved fact" not in result.system_prompt.prompt
    assert "## recent_context" in result.context_frame.prompt
    assert "## Recent Context" not in result.context_frame.prompt
    assert "recent summary" in result.context_frame.prompt
    assert "retrieved fact" in result.context_frame.prompt
    assert "- python" in result.context_frame.prompt
    assert "- channel: chat" in result.context_frame.prompt
    assert result.messages[-2] == {
        "role": "user",
        "content": result.context_frame.prompt,
    }


def test_context_builder_slices_history_with_runtime_history_window(tmp_path):
    history: list[Message] = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "recent question"},
    ]

    result = ContextBuilder().render(
        make_context(tmp_path, history=history, history_window=2)
    )

    assert result.messages == [
        {"role": "system", "content": result.system_prompt.prompt},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "recent question"},
        {"role": "user", "content": "hello"},
    ]


def test_context_builder_applies_disabled_sections_and_turn_injection(tmp_path):
    result = ContextBuilder().render(
        make_context(
            tmp_path,
            retrieved_memory="retrieved fact",
            disabled_sections={"retrieved_memory"},
            turn_injection_context={"tool_prefetch": "prefetched data"},
        )
    )

    assert "retrieved fact" not in result.context_frame.prompt
    assert "prefetched data" in result.context_frame.prompt
    assert "retrieved_memory" not in [
        entry.label for entry in result.context_frame.breakdown
    ]
    assert result.context_frame.breakdown[-1].label == "tool_prefetch"
