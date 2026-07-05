from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from amadeus.tools.base import ToolExecutionRequest, ToolResult
from amadeus.tools.registry import ToolRegistry


def test_tool_result_exposes_structured_output():
    result = ToolResult(
        tool_name="fetch_messages",
        output={"messages": [{"id": "session:1:1:0"}]},
        is_error=False,
        metadata={"source": "session"},
    )
    request = ToolExecutionRequest(
        tool_name="fetch_messages",
        arguments={"source_ref": '["session:1:1:0"]'},
    )

    assert result.tool_name == "fetch_messages"
    assert result.output["messages"][0]["id"] == "session:1:1:0"
    assert request.arguments["source_ref"] == '["session:1:1:0"]'


@dataclass
class EchoTool:
    name: str = "echo"
    description: str = "Echo the provided text."
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
        }
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(tool_name=self.name, output={"echo": kwargs["text"]})


def test_registry_registers_and_fetches_tools():
    registry = ToolRegistry()
    tool = EchoTool()

    registry.register(tool)

    assert registry.get("echo") is tool
    assert list(registry.names()) == ["echo"]


def test_registry_exports_openai_tool_schema():
    registry = ToolRegistry()
    registry.register(EchoTool())

    schema = registry.export_openai_tools()

    assert schema == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo the provided text.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }
    ]

