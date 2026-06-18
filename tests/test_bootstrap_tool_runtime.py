from __future__ import annotations

from amadeus.bootstrap import build_passive_app


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
        "fetch_messages",
        "read_file",
        "recall_memory",
        "search_messages",
    ]
    assert app.runtime.tool_registry is app.tool_registry
    assert app.runtime.tool_executor is app.tool_executor
