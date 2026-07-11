from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from amadeus.tools.base import ToolResult
from amadeus.tools.registry import ToolNotFoundError, ToolRegistry


@dataclass
class FakeTool:
    name: str
    description: str
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(tool_name=self.name, output={})


def _make(name: str, description: str = "desc") -> FakeTool:
    return FakeTool(name=name, description=description)


def test_register_populates_three_tables_in_sync():
    registry = ToolRegistry()
    tool = _make("alpha")

    registry.register(tool, risk="write", always_on=True, search_hint="hint")

    assert registry.get("alpha") is tool
    meta = registry.get_metadata("alpha")
    assert meta is not None
    assert meta.risk == "write"
    assert meta.always_on is True
    assert meta.search_hint == "hint"
    assert meta.source_type == "builtin"
    assert meta.source_name == ""

    doc = registry.get_document("alpha")
    assert doc is not None
    assert doc.name == "alpha"
    assert doc.description == "desc"
    assert doc.risk == "write"
    assert doc.always_on is True
    assert doc.search_hint == "hint"


def test_unregister_clears_three_tables():
    registry = ToolRegistry()
    registry.register(_make("alpha"))

    registry.unregister("alpha")

    assert registry.get("alpha") is None
    assert registry.get_metadata("alpha") is None
    assert registry.get_document("alpha") is None
    assert "alpha" not in registry.get_registered_names()


def test_get_schemas_with_names_subset():
    registry = ToolRegistry()
    registry.register(_make("alpha"))
    registry.register(_make("beta"))
    registry.register(_make("gamma"))

    schemas = registry.get_schemas(names={"alpha", "gamma"})

    names_returned = {s["function"]["name"] for s in schemas}
    assert names_returned == {"alpha", "gamma"}


def test_get_schemas_none_returns_all():
    registry = ToolRegistry()
    registry.register(_make("alpha"))
    registry.register(_make("beta"))

    schemas = registry.get_schemas(names=None)

    assert {s["function"]["name"] for s in schemas} == {"alpha", "beta"}


def test_get_schemas_without_names_returns_all_registered_tools():
    registry = ToolRegistry()
    registry.register(_make("alpha"))

    assert [schema["function"]["name"] for schema in registry.get_schemas()] == ["alpha"]


def test_get_always_on_names():
    registry = ToolRegistry()
    registry.register(_make("alpha"), always_on=True)
    registry.register(_make("beta"), always_on=False)
    registry.register(_make("gamma"), always_on=True)

    assert registry.get_always_on_names() == {"alpha", "gamma"}


def test_get_names_by_source():
    registry = ToolRegistry()
    registry.register(_make("a1"), source_type="mcp", source_name="github")
    registry.register(_make("a2"), source_type="mcp", source_name="github")
    registry.register(_make("b1"), source_type="mcp", source_name="filesystem")

    assert registry.get_names_by_source("github") == {"a1", "a2"}
    assert registry.get_names_by_source("filesystem") == {"b1"}
    assert registry.get_names_by_source("nonexistent") == set()


def test_get_documents_returns_all():
    registry = ToolRegistry()
    registry.register(_make("alpha"))
    registry.register(_make("beta"))

    docs = registry.get_documents()
    assert {d.name for d in docs} == {"alpha", "beta"}


def test_execute_missing_tool_raises_typed_error():
    registry = ToolRegistry()

    with pytest.raises(ToolNotFoundError, match="missing") as exc_info:
        asyncio.run(registry.execute("missing", {}))

    assert exc_info.value.tool_name == "missing"
