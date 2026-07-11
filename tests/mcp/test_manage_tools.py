from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

import pytest
from amadeus.mcp.config import McpServerConfig
from amadeus.mcp.manage_tools import McpAddTool, McpListTool, McpRemoveTool
from amadeus.mcp.registry import McpServerNotFoundError, McpServerStatus


class _FakeMcpRegistry:
    def __init__(self) -> None:
        self.added_configs: list[McpServerConfig] = []
        self.add_result: tuple[list[str], list[tuple[str, list[str]]]] = (
            ["mcp_local__echo"],
            [],
        )
        self.add_error: Exception | None = None
        self.remove_result = ["mcp_local__echo"]
        self.remove_error: Exception | None = None
        self.removed_names: list[str] = []
        self.statuses: list[McpServerStatus] = []

    async def add(
        self,
        config: McpServerConfig,
    ) -> tuple[list[str], list[tuple[str, list[str]]]]:
        self.added_configs.append(config)
        if self.add_error is not None:
            raise self.add_error
        return self.add_result

    async def remove(self, name: str) -> list[str]:
        self.removed_names.append(name)
        if self.remove_error is not None:
            raise self.remove_error
        return list(self.remove_result)

    def list_servers(self) -> list[McpServerStatus]:
        return list(self.statuses)


def _add_tool(registry: _FakeMcpRegistry) -> McpAddTool:
    return McpAddTool(mcp_registry=registry)  # type: ignore[arg-type]


def _remove_tool(registry: _FakeMcpRegistry) -> McpRemoveTool:
    return McpRemoveTool(mcp_registry=registry)  # type: ignore[arg-type]


def _list_tool(registry: _FakeMcpRegistry) -> McpListTool:
    return McpListTool(mcp_registry=registry)  # type: ignore[arg-type]


def test_mcp_add_schema_is_stdio_only_and_requires_name_and_command():
    tool = _add_tool(_FakeMcpRegistry())

    properties = tool.parameters["properties"]
    assert tool.parameters["type"] == "object"
    assert set(properties) == {"name", "command", "env", "cwd"}
    assert tool.parameters["required"] == ["name", "command"]
    assert properties["name"]["type"] == "string"
    assert properties["command"]["type"] == "array"
    assert properties["command"]["items"] == {"type": "string"}
    assert properties["env"]["type"] == "object"
    assert properties["env"]["additionalProperties"] == {"type": "string"}
    assert properties["cwd"]["type"] == "string"


def test_mcp_add_builds_stdio_config_and_returns_safe_structured_output():
    registry = _FakeMcpRegistry()
    registry.add_result = (
        ["mcp_local__echo"],
        [("bad", ["$ref is unsupported"])],
    )
    tool = _add_tool(registry)
    secret = "TOKEN_MUST_NOT_BE_RETURNED"
    private_command = "private-server-entrypoint.py"
    private_cwd = "C:/private/workspace"

    result = asyncio.run(
        tool.execute(
            name=" local ",
            command=["python", private_command],
            env={"ACCESS_TOKEN": secret},
            cwd=private_cwd,
        )
    )

    assert result.is_error is False
    assert result.output == {
        "server": "local",
        "status": "connected",
        "registered": ["mcp_local__echo"],
        "skipped": [{"tool": "bad", "errors": ["$ref is unsupported"]}],
    }
    assert len(registry.added_configs) == 1
    assert asdict(registry.added_configs[0]) == {
        "name": "local",
        "command": ["python", private_command],
        "env": {"ACCESS_TOKEN": secret},
        "cwd": private_cwd,
    }
    visible = json.dumps({"output": result.output, "metadata": result.metadata})
    assert secret not in visible
    assert private_command not in visible
    assert private_cwd not in visible


@pytest.mark.parametrize(
    ("kwargs", "expected_fragment"),
    [
        ({"name": "", "command": ["server"]}, "name"),
        ({"name": "local", "command": []}, "command"),
    ],
)
def test_mcp_add_rejects_invalid_model_arguments(
    kwargs: dict[str, object],
    expected_fragment: str,
):
    registry = _FakeMcpRegistry()
    result = asyncio.run(_add_tool(registry).execute(**kwargs))

    assert result.is_error is True
    assert expected_fragment in result.output["error"]
    assert registry.added_configs == []


def test_mcp_add_normalizes_registry_failure_as_tool_error():
    registry = _FakeMcpRegistry()
    registry.add_error = ValueError("同名 MCP server 已存在")

    result = asyncio.run(
        _add_tool(registry).execute(name="local", command=["server"])
    )

    assert result.is_error is True
    assert result.output == {
        "error": "添加 MCP server 失败",
        "code": "invalid_request",
    }


def test_mcp_add_failure_does_not_echo_exception_or_credentials():
    registry = _FakeMcpRegistry()
    secret = "TOKEN_MUST_NOT_ESCAPE"
    registry.add_error = RuntimeError(f"remote echoed {secret}")

    result = asyncio.run(
        _add_tool(registry).execute(
            name="local",
            command=["server"],
            env={"TOKEN": secret},
        )
    )

    assert result.is_error is True
    assert result.output["code"] == "internal_error"
    assert secret not in json.dumps(result.output)


def test_mcp_remove_returns_removed_tool_names():
    registry = _FakeMcpRegistry()
    registry.remove_result = ["mcp_local__add", "mcp_local__echo"]

    result = asyncio.run(_remove_tool(registry).execute(name=" local "))

    assert result.is_error is False
    assert registry.removed_names == ["local"]
    assert result.output == {
        "server": "local",
        "status": "removed",
        "removed_tools": ["mcp_local__add", "mcp_local__echo"],
    }


def test_mcp_remove_unknown_server_returns_tool_error():
    registry = _FakeMcpRegistry()
    registry.remove_error = McpServerNotFoundError("missing")

    result = asyncio.run(_remove_tool(registry).execute(name="missing"))

    assert result.is_error is True
    assert result.output == {
        "error": "移除 MCP server 失败",
        "code": "not_found",
    }


def test_mcp_remove_rejects_empty_name_without_calling_registry():
    registry = _FakeMcpRegistry()

    result = asyncio.run(_remove_tool(registry).execute(name="  "))

    assert result.is_error is True
    assert "name" in result.output["error"]
    assert registry.removed_names == []


def test_mcp_list_returns_only_safe_live_status_projection():
    registry = _FakeMcpRegistry()
    registry.statuses = [
        McpServerStatus(
            name="connected-server",
            status="connected",
            tools=("mcp_connected-server__echo",),
        ),
        McpServerStatus(
            name="dead-server",
            status="disconnected",
            tools=("mcp_dead-server__read", "mcp_dead-server__write"),
        ),
    ]

    result = asyncio.run(_list_tool(registry).execute())

    assert result.is_error is False
    assert result.output == {
        "servers": [
            {
                "name": "connected-server",
                "status": "connected",
                "tools": ["mcp_connected-server__echo"],
            },
            {
                "name": "dead-server",
                "status": "disconnected",
                "tools": [
                    "mcp_dead-server__read",
                    "mcp_dead-server__write",
                ],
            },
        ]
    }
    serialized = json.dumps(result.output)
    assert "command" not in serialized
    assert "env" not in serialized
    assert "cwd" not in serialized
    assert "transport_type" not in serialized
