from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from amadeus.mcp.client import McpCallResult, McpToolInfo
from amadeus.mcp.tool import McpToolWrapper, _make_wrapper_name, parse_wrapper_name


class _FakeClient:
    def __init__(
        self,
        result: McpCallResult | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, Any], float | None]] = []

    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> McpCallResult:
        self.calls.append((tool_name, arguments, timeout))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _wrapper(client: _FakeClient) -> McpToolWrapper:
    info = McpToolInfo(
        name="read_file",
        description="Read a file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    return McpToolWrapper(client, info, server_name="filesystem")  # type: ignore[arg-type]


def test_wrapper_exposes_local_tool_contract_and_calls_remote_tool():
    client = _FakeClient(
        McpCallResult(
            content=[{"type": "text", "text": "done"}],
            structured_content=None,
            is_error=False,
        )
    )
    wrapper = _wrapper(client)

    result = asyncio.run(wrapper.execute(path="notes.txt"))

    assert wrapper.name == "mcp_filesystem__read_file"
    assert wrapper.description == "[MCP:filesystem] Read a file"
    assert wrapper.parameters == {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    assert client.calls == [("read_file", {"path": "notes.txt"}, 30.0)]
    assert result.tool_name == wrapper.name
    assert result.output == "done"
    assert result.is_error is False
    assert result.metadata == {
        "mcp_server": "filesystem",
        "mcp_tool": "read_file",
    }


def test_wrapper_prefers_structured_content_over_text_blocks():
    client = _FakeClient(
        McpCallResult(
            content=[{"type": "text", "text": "fallback"}],
            structured_content={"count": 2, "items": ["a", "b"]},
            is_error=False,
        )
    )

    result = asyncio.run(_wrapper(client).execute(path="x"))

    assert result.output == {"count": 2, "items": ["a", "b"]}


def test_wrapper_joins_all_text_blocks_in_protocol_order():
    client = _FakeClient(
        McpCallResult(
            content=[
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ],
            structured_content=None,
            is_error=False,
        )
    )

    result = asyncio.run(_wrapper(client).execute(path="x"))

    assert result.output == "first\nsecond"


def test_wrapper_redacts_image_and_audio_payloads_in_mixed_content():
    image_secret = "IMAGE_BASE64_MUST_NOT_REACH_MODEL"
    audio_secret = "AUDIO_BASE64_MUST_NOT_REACH_MODEL"
    client = _FakeClient(
        McpCallResult(
            content=[
                {"type": "text", "text": "caption"},
                {
                    "type": "resource_link",
                    "uri": "file:///report.txt",
                    "name": "report",
                    "mimeType": "text/plain",
                },
                {
                    "type": "resource",
                    "resource": {
                        "uri": "file:///body.txt",
                        "mimeType": "text/plain",
                        "text": "body",
                    },
                },
                {
                    "type": "image",
                    "mimeType": "image/png",
                    "data": image_secret,
                },
                {
                    "type": "audio",
                    "mimeType": "audio/wav",
                    "data": audio_secret,
                },
            ],
            structured_content=None,
            is_error=False,
        )
    )

    result = asyncio.run(_wrapper(client).execute(path="x"))

    assert isinstance(result.output, list)
    assert result.output[:3] == [
        {"type": "text", "text": "caption"},
        {
            "type": "resource_link",
            "uri": "file:///report.txt",
            "name": "report",
            "mimeType": "text/plain",
        },
        {
            "type": "resource",
            "resource": {
                "uri": "file:///body.txt",
                "mimeType": "text/plain",
                "text": "body",
            },
        },
    ]
    assert result.output[3] == {
        "type": "image",
        "mimeType": "image/png",
        "omitted": True,
    }
    assert result.output[4] == {
        "type": "audio",
        "mimeType": "audio/wav",
        "omitted": True,
    }
    model_visible_output = json.dumps(result.output)
    assert image_secret not in model_visible_output
    assert audio_secret not in model_visible_output


def test_wrapper_maps_mcp_tool_error_without_guessing_from_text():
    client = _FakeClient(
        McpCallResult(
            content=[{"type": "text", "text": "ordinary-looking response"}],
            structured_content=None,
            is_error=True,
        )
    )

    result = asyncio.run(_wrapper(client).execute(path="x"))

    assert result.output == "ordinary-looking response"
    assert result.is_error is True


def test_wrapper_does_not_infer_error_from_output_prefix():
    client = _FakeClient(
        McpCallResult(
            content=[{"type": "text", "text": "MCP error is documentation text"}],
            structured_content=None,
            is_error=False,
        )
    )

    result = asyncio.run(_wrapper(client).execute(path="x"))

    assert result.is_error is False


def test_wrapper_propagates_json_rpc_or_connection_exception():
    client = _FakeClient(error=ConnectionError("server exited"))

    with pytest.raises(ConnectionError, match="server exited"):
        asyncio.run(_wrapper(client).execute(path="x"))


def test_make_wrapper_name_and_parse_round_trip():
    name = _make_wrapper_name("my_server-1", "read_file")

    assert name == "mcp_my_server-1__read_file"
    assert parse_wrapper_name(name) == ("my_server-1", "read_file")


@pytest.mark.parametrize("server_name", ["", "bad__server", "bad server", "bad/server"])
def test_make_wrapper_name_rejects_invalid_server_alias(server_name: str):
    with pytest.raises(ValueError):
        _make_wrapper_name(server_name, "read_file")


@pytest.mark.parametrize("tool_name", ["", "bad tool", "bad.tool", "bad/tool"])
def test_make_wrapper_name_rejects_provider_incompatible_remote_name(tool_name: str):
    with pytest.raises(ValueError):
        _make_wrapper_name("server", tool_name)


def test_make_wrapper_name_rejects_generated_name_over_provider_limit():
    with pytest.raises(ValueError):
        _make_wrapper_name("server", "x" * 64)


@pytest.mark.parametrize(
    "name",
    ["read_file", "echo_tool", "mcp_github", "mcp___tool", "mcp_server__"],
)
def test_parse_wrapper_name_rejects_non_wrapper_names(name: str):
    assert parse_wrapper_name(name) is None
