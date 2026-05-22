from dev_utils.run_context_llm import (
    build_runtime_context,
    parse_key_value_items,
    render_context_messages,
)


def test_parse_key_value_items_parses_named_context_values():
    assert parse_key_value_items(["source=unit-test", "detail=a=b"]) == {
        "source": "unit-test",
        "detail": "a=b",
    }


def test_parse_key_value_items_rejects_missing_separator():
    try:
        parse_key_value_items(["broken"])
    except ValueError as error:
        assert "expected KEY=VALUE" in str(error)
    else:
        raise AssertionError("parse_key_value_items should reject malformed items")


def test_render_context_messages_uses_project_context_builder(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "SELF.md").write_text("debug self model", encoding="utf-8")

    context = build_runtime_context(
        workspace_root=tmp_path,
        user_message="what changed?",
        retrieved_memory="retrieved debug fact",
        active_skills=["provider-debug"],
        runtime_metadata={"source": "test"},
    )

    result = render_context_messages(context)

    assert result.messages[0]["role"] == "system"
    assert "debug self model" in result.system_prompt.prompt
    assert result.messages[-2]["role"] == "user"
    assert "retrieved debug fact" in result.messages[-2]["content"]
    assert "provider-debug" in result.messages[-2]["content"]
    assert "- source: test" in result.messages[-2]["content"]
    assert result.messages[-1] == {"role": "user", "content": "what changed?"}
