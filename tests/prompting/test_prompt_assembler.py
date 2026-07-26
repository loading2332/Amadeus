from amadeus.prompting.assembler import (
    SYSTEM_CONTEXT_FRAME_MARKER,
    PromptAssembler,
    PromptSectionRender,
    build_context_frame_content,
)


def section(name, content, priority=10):
    return PromptSectionRender(
        label=name,
        content=content,
        priority=priority,
        is_static=False,
    )


def test_prompt_assembler_routes_sections_by_name():
    result = PromptAssembler().assemble(
        [
            section("identity", "identity content", priority=10),
            section("recent_context", "recent content", priority=50),
            section("retrieved_memory", "retrieved content", priority=60),
            section("long_term_memory", "memory content", priority=40),
            section("runtime_metadata", "metadata content", priority=80),
        ]
    )

    assert result.system_prompt == "## identity\n\nidentity content"
    assert [item.label for item in result.system_sections] == ["identity"]
    assert [item.label for item in result.frame_sections] == [
        "long_term_memory",
        "recent_context",
        "retrieved_memory",
        "runtime_metadata",
    ]
    assert "recent content" in result.context_frame
    assert "memory content" in result.context_frame
    assert "retrieved content" in result.context_frame
    assert "metadata content" in result.context_frame


def test_context_frame_content_uses_system_reminder_marker():
    content = build_context_frame_content([section("recent_context", "recent content")])

    assert content.startswith(SYSTEM_CONTEXT_FRAME_MARKER)
    assert "以下内容由系统提供" in content
    assert "## recent_context\n\nrecent content" in content
    assert content.rstrip().endswith("</system-reminder>")


def test_context_frame_content_uses_label_as_single_visible_heading():
    content = build_context_frame_content(
        [section("recent_context", "recent content")]
    )

    assert "## recent_context\n\nrecent content" in content


def test_context_frame_content_is_empty_without_sections():
    assert build_context_frame_content([]) == ""


def test_prompt_assembler_skips_disabled_sections_and_injection():
    result = PromptAssembler().assemble(
        [
            section("identity", "identity content"),
            section("recent_context", "recent content"),
        ],
        disabled_sections={"recent_context", "tool_prefetch"},
        turn_injection_context={
            "tool_prefetch": "disabled tool context",
            "plugin_hints": "enabled hint",
        },
    )

    assert "identity content" in result.system_prompt
    assert "recent content" not in result.context_frame
    assert "disabled tool context" not in result.context_frame
    assert "enabled hint" in result.context_frame
    assert [item.label for item in result.frame_sections] == ["plugin_hints"]
