from amadeus.context import RuntimeContext
from amadeus.prompt_block import (
    ActiveSkillsPromptBlock,
    LongTermMemoryPromptBlock,
    RecentContextPromptBlock,
    RetrievedMemoryPromptBlock,
    RuntimeMetadataPromptBlock,
    SelfModelPromptBlock,
)


def make_context(tmp_path, **overrides):
    values = {
        "workspace_root": tmp_path,
        "history": [],
        "current_user_message": "hello",
    }
    values.update(overrides)
    return RuntimeContext(**values)


def test_self_model_block_skips_missing_self_md(tmp_path):
    result = SelfModelPromptBlock().render(make_context(tmp_path))

    assert not result.rendered
    assert result.content == ""
    assert result.empty_reason == "missing SELF.md"


def test_self_model_block_skips_empty_self_md(tmp_path):
    self_path = tmp_path / "memory" / "SELF.md"
    self_path.parent.mkdir()
    self_path.write_text(" \n\t", encoding="utf-8")

    result = SelfModelPromptBlock().render(make_context(tmp_path))

    assert not result.rendered
    assert result.empty_reason == "empty SELF.md"


def test_self_model_block_reads_self_md(tmp_path):
    self_path = tmp_path / "memory" / "SELF.md"
    self_path.parent.mkdir()
    self_path.write_text("Stable self model.", encoding="utf-8")

    result = SelfModelPromptBlock().render(make_context(tmp_path))

    assert result.rendered
    assert result.content == "## Amadeus Self Model\n\nStable self model."
    assert result.empty_reason is None


def test_long_term_memory_block_reads_memory_md(tmp_path):
    memory_path = tmp_path / "memory" / "MEMORY.md"
    memory_path.parent.mkdir()
    memory_path.write_text("User prefers concise answers.", encoding="utf-8")

    result = LongTermMemoryPromptBlock().render(make_context(tmp_path))

    assert result.rendered
    assert result.content == "## User Long-Term Memory\n\nUser prefers concise answers."


def test_recent_context_block_reads_recent_context_md(tmp_path):
    recent_path = tmp_path / "memory" / "RECENT_CONTEXT.md"
    recent_path.parent.mkdir()
    recent_path.write_text("We are designing phase one.", encoding="utf-8")

    result = RecentContextPromptBlock().render(make_context(tmp_path))

    assert result.rendered
    assert result.content == "## Recent Context\n\nWe are designing phase one."


def test_recent_context_override_takes_precedence_over_file(tmp_path):
    recent_path = tmp_path / "memory" / "RECENT_CONTEXT.md"
    recent_path.parent.mkdir()
    recent_path.write_text("file context", encoding="utf-8")

    result = RecentContextPromptBlock().render(
        make_context(tmp_path, recent_context_override="runtime context")
    )

    assert result.rendered
    assert result.content == "## Recent Context\n\nruntime context"


def test_retrieved_memory_block_renders_runtime_retrieval(tmp_path):
    result = RetrievedMemoryPromptBlock().render(
        make_context(tmp_path, retrieved_memory="retrieved fact")
    )

    assert result.rendered
    assert result.content == "## Retrieved Memory\n\nretrieved fact"


def test_active_skills_block_renders_skill_names(tmp_path):
    result = ActiveSkillsPromptBlock().render(
        make_context(tmp_path, active_skills=["python", "pytest"])
    )

    assert result.rendered
    assert result.content == "## Active Skills\n\n- python\n- pytest"


def test_runtime_metadata_block_renders_sorted_metadata(tmp_path):
    result = RuntimeMetadataPromptBlock().render(
        make_context(
            tmp_path,
            runtime_metadata={"request_time": "2026-05-21", "channel": "chat"},
        )
    )

    assert result.rendered
    assert result.content == (
        "## Runtime Metadata\n\n"
        "- channel: chat\n"
        "- request_time: 2026-05-21"
    )
