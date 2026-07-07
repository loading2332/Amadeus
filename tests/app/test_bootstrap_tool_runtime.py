from __future__ import annotations

import asyncio

from amadeus.app.bootstrap import build_passive_app
from amadeus.session.identity import SessionRef

from tests.db.postgres_helpers import clean_postgres

EMBEDDING_DIM = 1024


def _embedding(values: list[float]) -> list[float]:
    return [float(v) for v in values] + [0.0] * (EMBEDDING_DIM - len(values))


class FakeCompletions:
    async def create(self, **kwargs):
        raise AssertionError("chat should not run in this bootstrap test")


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = type("Chat", (), {"completions": self.completions})()


def _memory_env_path(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
                "AMADEUS_LONG_TERM_MEMORY_ENABLED=1",
                "OPENAI_EMBEDDING_MODEL=fake-embedding",
            ]
        ),
        encoding="utf-8",
    )
    return env_path


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
        "mcp_add",
        "mcp_list",
        "mcp_remove",
        "memorize",
        "read_file",
        "recall_memory",
        "search_messages",
        "tool_search",
        "undo_memory_by_source",
        "write_file",
    ]
    assert app.runtime.tool_registry is app.tool_registry
    assert app.runtime.tool_executor is app.tool_executor


def test_build_passive_app_uses_unscoped_file_tools(tmp_path):
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

    read_result, read_trace = asyncio.run(
        app.tool_executor.execute_async(
            "read_file",
            {"path": str(source)},
        )
    )
    list_result, list_trace = asyncio.run(
        app.tool_executor.execute_async(
            "list_dir",
            {"path": str(outside)},
        )
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

    # P2: ReadOnlyFilesystemHook 在 bootstrap 装配后生效——workspace 之外的
    # read/list/write/edit 都应被 deny（PRD A2 验收：hook 装配生效）。
    assert read_trace.status == "denied"
    assert "escapes allowed directory" in str(read_result.output)
    assert list_trace.status == "denied"
    assert write_trace.status == "denied"
    assert edit_trace.status == "denied"
    # 越界写未实际落盘
    assert not target.exists()


def test_build_passive_app_composes_store_retriever_memorizer_and_worker(
    tmp_path,
    monkeypatch,
):
    clean_postgres().close()

    class StableEmbeddingProvider:
        async def embed(self, text: str) -> list[float]:
            return _embedding([1.0, 0.0, 0.0])

    class FakeExtractor:
        def __init__(self, *, provider, model: str) -> None:
            self.provider = provider
            self.model = model

        async def extract(
            self,
            *,
            session: SessionRef,
            messages: list[dict[str, object]],
        ):
            del session, messages
            return []

    monkeypatch.setattr(
        "amadeus.app.bootstrap.OpenAIEmbeddingProvider",
        lambda _config: StableEmbeddingProvider(),
    )
    monkeypatch.setattr(
        "amadeus.app.bootstrap.LLMMemoryExtractor",
        FakeExtractor,
    )

    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=_memory_env_path(tmp_path),
        client=FakeClient(),
    )

    engine = app.runtime.memory_engine
    assert engine is not None
    assert engine.__class__.__name__ == "LongTermMemoryEngine"
    assert engine.store.__class__.__name__ == "PostgresMemoryStore"
    assert engine.retriever.__class__.__name__ == "MemoryRetriever"
    assert engine.memorizer.__class__.__name__ == "MemoryMemorizer"
    assert engine.worker.__class__.__name__ == "PostResponseMemoryWorker"
