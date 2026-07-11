from __future__ import annotations

import re
from typing import Any, cast

from amadeus.mcp.client import McpClient, McpToolInfo
from amadeus.tools.base import ToolResult

_DEFAULT_CALL_TIMEOUT = 30.0
_PROVIDER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_PROVIDER_NAME_LENGTH = 64
_SAFE_RESOURCE_LINK_FIELDS = (
    "uri",
    "name",
    "description",
    "mimeType",
    "size",
)


def validate_server_name(server_name: str) -> None:
    if not server_name:
        raise ValueError("MCP server name 不能为空")
    if "__" in server_name:
        raise ValueError("MCP server name 不能包含双下划线")
    if _PROVIDER_NAME_PATTERN.fullmatch(server_name) is None:
        raise ValueError("MCP server name 只能包含字母、数字、下划线和连字符")


def _make_wrapper_name(server_name: str, tool_name: str) -> str:
    """生成不改写远端名称的可逆 wrapper name。"""
    validate_server_name(server_name)
    if not tool_name:
        raise ValueError("MCP tool name 不能为空")
    wrapper_name = f"mcp_{server_name}__{tool_name}"
    if (
        len(wrapper_name) > _MAX_PROVIDER_NAME_LENGTH
        or _PROVIDER_NAME_PATTERN.fullmatch(wrapper_name) is None
    ):
        raise ValueError(
            f"MCP tool {tool_name!r} 生成的工具名不符合 Provider function-name 约束"
        )
    return wrapper_name


def parse_wrapper_name(wrapper_name: str) -> tuple[str, str] | None:
    """从 `mcp_{server}__{tool}` 反解 `(server, tool)`。"""
    if not wrapper_name.startswith("mcp_"):
        return None
    rest = wrapper_name[len("mcp_") :]
    server, separator, tool = rest.partition("__")
    if not separator or not server or not tool:
        return None
    return server, tool


def _safe_scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return "[omitted]"


def _project_resource_link(block: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {"type": "resource_link"}
    for field in _SAFE_RESOURCE_LINK_FIELDS:
        if field in block:
            projected[field] = _safe_scalar(block[field])
    return projected


def _project_embedded_resource(block: dict[str, Any]) -> dict[str, Any]:
    projected_resource: dict[str, Any] = {}
    resource = block.get("resource")
    if not isinstance(resource, dict):
        return {"type": "resource", "omitted": True}
    for field in ("uri", "mimeType"):
        if field in resource:
            projected_resource[field] = _safe_scalar(resource[field])
    text = resource.get("text")
    if isinstance(text, str):
        projected_resource["text"] = text
    if "blob" in resource:
        projected_resource["blobOmitted"] = True
    return {"type": "resource", "resource": projected_resource}


def _project_mixed_content(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for block in content:
        block_type = block.get("type")
        if block_type == "text":
            projected.append(
                {
                    "type": "text",
                    "text": block.get("text") if isinstance(block.get("text"), str) else "",
                }
            )
        elif block_type == "resource_link":
            projected.append(_project_resource_link(block))
        elif block_type == "resource":
            projected.append(_project_embedded_resource(block))
        elif block_type in {"image", "audio"}:
            item: dict[str, Any] = {
                "type": cast("str", block_type),
                "omitted": True,
            }
            if "mimeType" in block:
                item["mimeType"] = _safe_scalar(block["mimeType"])
            projected.append(item)
        else:
            projected.append(
                {
                    "type": block_type if isinstance(block_type, str) else "unknown",
                    "omitted": True,
                }
            )
    return projected


def _project_output(
    *,
    structured_content: dict[str, Any] | None,
    content: list[dict[str, Any]],
) -> Any:
    if structured_content is not None:
        return structured_content
    if all(block.get("type") == "text" for block in content):
        return "\n".join(
            cast("str", block.get("text"))
            if isinstance(block.get("text"), str)
            else ""
            for block in content
        )
    return _project_mixed_content(content)


class McpToolWrapper:
    """把一个 MCP 工具适配成 Amadeus 的统一 `Tool`。"""

    def __init__(
        self,
        client: McpClient,
        info: McpToolInfo,
        server_name: str,
    ) -> None:
        if not isinstance(info.input_schema, dict):
            raise ValueError(f"MCP tool {info.name!r} input schema 必须是 object")
        self._client = client
        self._info = info
        self._server_name = server_name
        self.name = _make_wrapper_name(server_name, info.name)
        self.description = f"[MCP:{server_name}] {info.description}".strip()
        self.parameters = cast("dict[str, Any]", info.input_schema)

    async def execute(self, **kwargs: Any) -> ToolResult:
        result = await self._client.call(
            self._info.name,
            kwargs,
            timeout=_DEFAULT_CALL_TIMEOUT,
        )
        return ToolResult(
            tool_name=self.name,
            output=_project_output(
                structured_content=result.structured_content,
                content=result.content,
            ),
            is_error=result.is_error,
            metadata={
                "mcp_server": self._server_name,
                "mcp_tool": self._info.name,
            },
        )


__all__ = [
    "McpToolWrapper",
    "parse_wrapper_name",
    "validate_server_name",
]
