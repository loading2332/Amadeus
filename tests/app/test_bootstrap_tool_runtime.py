from __future__ import annotations

import asyncio

from amadeus.app.bootstrap import build_passive_app


class FakeCompletions:
    async def create(self, **kwargs):
        raise AssertionError("chat should not run in this bootstrap test")


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = type("Chat", (), {"completions": self.completions})()


def test_build_passive_app_exposes_readonly_tool_runtime(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
            ]
        ),
        encoding="utf-8",
    )

    app = build_passive_app(workspace_root=tmp_path, env_path=env_path, client=FakeClient())

    assert app.tool_registry is not None
    assert sorted(app.tool_registry.names()) == [
        "edit_file",
        "fetch_messages",
        "forget_memory",
        "list_dir",
        "memorize",
        "read_file",
        "recall_memory",
        "search_messages",
        "undo_memory_by_source",
        "write_file",
    ]
    assert app.runtime.tool_registry is app.tool_registry
    assert app.runtime.tool_executor is app.tool_executor


def test_build_passive_app_uses_akashic_style_unscoped_file_tools(tmp_path):
    env_path = tmp_path / "workspace" / ".env"
    env_path.parent.mkdir()
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
            ]
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "source.txt"
    source.write_text("outside read", encoding="utf-8")
    target = outside / "target.txt"

    app = build_passive_app(
        workspace_root=workspace,
        env_path=env_path,
        client=FakeClient(),
    )

    read_result, read_trace = app.tool_executor.execute(
        "read_file",
        {"path": str(source)},
    )
    list_result, list_trace = app.tool_executor.execute(
        "list_dir",
        {"path": str(outside)},
    )
    write_result, write_trace = asyncio.run(
        app.tool_executor.execute_async(
            "write_file",
            {"path": str(target), "content": "before"},
        )
    )
    edit_result, edit_trace = asyncio.run(
        app.tool_executor.execute_async(
            "edit_file",
            {"path": str(target), "old_text": "before", "new_text": "after"},
        )
    )

    assert read_trace.status == "success"
    assert read_result.output["content"] == "outside read"
    assert list_trace.status == "success"
    assert any(entry["name"] == "source.txt" for entry in list_result.output["entries"])
    assert write_trace.status == "success"
    assert write_result.output["path"] == str(target.resolve())
    assert edit_trace.status == "success"
    assert target.read_text(encoding="utf-8") == "after"
