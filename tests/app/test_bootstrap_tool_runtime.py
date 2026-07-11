from __future__ import annotations

import asyncio
from typing import Any

from amadeus.app.bootstrap import build_passive_app
from amadeus.session.identity import SessionRef
from amadeus.tools.base import ToolExecutionRequest, ToolResult

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


def test_build_passive_app_exposes_readonly_tool_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv("AMADEUS_MCP_MODE", raising=False)
    monkeypatch.setattr(
        "amadeus.app.bootstrap.PostgresDatabase.open",
        lambda _database: None,
    )
    monkeypatch.setattr(
        "amadeus.app.bootstrap.build_markdown_memory_runtime",
        lambda **_kwargs: object(),
    )
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
        "tool_search",
        "undo_memory_by_source",
        "write_file",
    ]
    assert app.config.mcp_mode == "disabled"
    assert app.mcp_server_registry is None
    assert app.runtime.tool_registry is app.tool_registry
    assert app.runtime.tool_executor is app.tool_executor
    asyncio.run(app.aclose())


def test_build_passive_app_enables_local_trusted_mcp_management_tools(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("AMADEUS_MCP_MODE", raising=False)
    monkeypatch.setattr(
        "amadeus.app.bootstrap.PostgresDatabase.open",
        lambda _database: None,
    )
    monkeypatch.setattr(
        "amadeus.app.bootstrap.build_markdown_memory_runtime",
        lambda **_kwargs: object(),
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
                "AMADEUS_MCP_MODE=local_trusted",
            ]
        ),
        encoding="utf-8",
    )

    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=env_path,
        client=FakeClient(),
    )

    assert app.config.mcp_mode == "local_trusted"
    assert app.mcp_server_registry is not None
    for name in ("mcp_add", "mcp_remove", "mcp_list"):
        metadata = app.tool_registry.get_metadata(name)
        assert metadata is not None
        assert metadata.always_on is True

    shutdown_calls = 0

    async def shutdown() -> None:
        nonlocal shutdown_calls
        shutdown_calls += 1

    monkeypatch.setattr(app.mcp_server_registry, "shutdown", shutdown)
    asyncio.run(app.aclose())

    assert shutdown_calls == 1


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

    read_execution = asyncio.run(
        app.tool_executor.execute(
            ToolExecutionRequest("read_file", {"path": str(source)})
        )
    )
    list_execution = asyncio.run(
        app.tool_executor.execute(
            ToolExecutionRequest("list_dir", {"path": str(outside)})
        )
    )
    write_execution = asyncio.run(
        app.tool_executor.execute(
            ToolExecutionRequest("write_file", {"path": str(target), "content": "before"})
        )
    )
    edit_execution = asyncio.run(
        app.tool_executor.execute(
            ToolExecutionRequest(
                "edit_file",
                {"path": str(target), "old_text": "before", "new_text": "after"},
            )
        )
    )

    # P2: ReadOnlyFilesystemHook 在 bootstrap 装配后生效——workspace 之外的
    # read/list/write/edit 都应被 deny（PRD A2 验收：hook 装配生效）。
    assert read_execution.status == "denied"
    assert "escapes allowed directory" in str(read_execution.output)
    assert list_execution.status == "denied"
    assert write_execution.status == "denied"
    assert edit_execution.status == "denied"
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


class _BusinessPurposeTool:
    name = "business_purpose"
    description = "Consume a business purpose."
    parameters = {
        "type": "object",
        "properties": {"purpose": {"type": "string"}},
        "required": ["purpose"],
    }

    def __init__(self) -> None:
        self.received: dict[str, Any] = {}

    def execute(self, **kwargs: Any) -> ToolResult:
        self.received = dict(kwargs)
        return ToolResult(tool_name=self.name, output=dict(kwargs))


def test_bootstrap_invoker_preserves_business_purpose_argument(
    tmp_path,
    monkeypatch,
):
    # 本测试只验证 bootstrap 的 invoker 边界。数据库连接属于独立启动契约，
    # 不应让一个纯装配回归测试依赖本机 PostgreSQL 是否可用。
    monkeypatch.setattr(
        "amadeus.app.bootstrap.PostgresDatabase.open",
        lambda _database: None,
    )
    monkeypatch.setattr(
        "amadeus.app.bootstrap.build_markdown_memory_runtime",
        lambda **_kwargs: object(),
    )
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
    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=env_path,
        client=FakeClient(),
    )
    tool = _BusinessPurposeTool()
    app.tool_registry.register(tool, always_on=True)

    execution = asyncio.run(
        app.tool_executor.execute(
            ToolExecutionRequest(
                tool_name=tool.name,
                arguments={"purpose": "business-purpose"},
            )
        )
    )

    assert execution.status == "success"
    assert tool.received == {"purpose": "business-purpose"}
