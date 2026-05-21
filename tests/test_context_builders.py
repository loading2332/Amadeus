from dataclasses import dataclass

import pytest

from amadeus.context import (
    ContextBuilder,
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

    assert result.prompt == "earlier #1\n\n---\n\nlater #1"
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


def test_retrieval_is_structurally_after_identity_and_self_model(tmp_path):
    self_path = tmp_path / "memory" / "SELF.md"
    self_path.parent.mkdir()
    self_path.write_text("stable identity boundary", encoding="utf-8")

    result = ContextBuilder().render(
        make_context(tmp_path, retrieved_memory="dynamic retrieved material")
    )

    system_prompt = result.messages[0]["content"]
    assert system_prompt.index("## Identity") < system_prompt.index("## Amadeus Self Model")
    assert system_prompt.index("## Amadeus Self Model") < system_prompt.index(
        "## Retrieved Memory"
    )
    assert "dynamic retrieved material" in system_prompt
    assert [entry.label for entry in result.system_prompt.breakdown].index(
        "SelfModelPromptBlock"
    ) < [entry.label for entry in result.system_prompt.breakdown].index(
        "RetrievedMemoryPromptBlock"
    )


def test_message_envelope_places_system_history_and_current_user_message():
    history = [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]

    messages = MessageEnvelopeBuilder().build(
        system_prompt="system prompt",
        history=history,
        current_user_message="current question",
    )

    assert messages == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "current question"},
    ]


def test_message_envelope_rejects_system_messages_in_history():
    with pytest.raises(ValueError, match="history must not contain system messages"):
        MessageEnvelopeBuilder().build(
            system_prompt="system prompt",
            history=[{"role": "system", "content": "nested system"}],
            current_user_message="current question",
        )


def test_context_builder_default_blocks_include_self_model_in_system_prompt(tmp_path):
    self_path = tmp_path / "memory" / "SELF.md"
    self_path.parent.mkdir()
    self_path.write_text("Amadeus stays grounded.", encoding="utf-8")

    result = ContextBuilder().render(make_context(tmp_path))

    assert result.messages[0]["role"] == "system"
    assert "## Amadeus Self Model\n\nAmadeus stays grounded." in result.messages[0][
        "content"
    ]
    assert result.messages[-1] == {"role": "user", "content": "hello"}
    assert [entry.label for entry in result.system_prompt.breakdown] == [
        "IdentityPromptBlock",
        "BehaviorRulesPromptBlock",
        "SelfModelPromptBlock",
        "LongTermMemoryPromptBlock",
        "RecentContextPromptBlock",
        "RetrievedMemoryPromptBlock",
        "ActiveSkillsPromptBlock",
        "RuntimeMetadataPromptBlock",
    ]
