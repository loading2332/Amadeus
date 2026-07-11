from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from amadeus.tools.base import ToolResult
from amadeus.tools.registry import ToolRegistry


@dataclass
class BusinessPurposeTool:
    """业务本身就声明 purpose 参数的远端工具替身。"""

    name: str = "business_purpose"
    description: str = "Consume a business purpose."
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "purpose": {
                    "type": "string",
                    "description": "远端工具真正消费的业务用途。",
                }
            },
            "required": ["purpose"],
        }
    )
    received: dict[str, Any] = field(default_factory=dict)

    def execute(self, **kwargs: Any) -> ToolResult:
        self.received = dict(kwargs)
        return ToolResult(tool_name=self.name, output=dict(kwargs))


def test_registry_exports_only_the_real_business_schema() -> None:
    registry = ToolRegistry()
    tool = BusinessPurposeTool()
    registry.register(tool)

    schema = registry.get_schemas()[0]
    parameters = schema["function"]["parameters"]

    assert parameters == tool.parameters
    assert parameters["properties"]["purpose"]["description"] == (
        "远端工具真正消费的业务用途。"
    )
    assert parameters["required"] == ["purpose"]


def test_registry_schema_export_is_detached_from_tool_parameters() -> None:
    registry = ToolRegistry()
    tool = BusinessPurposeTool()
    registry.register(tool)

    exported = registry.get_schemas()[0]["function"]["parameters"]
    exported["properties"]["purpose"]["description"] = "mutated"

    assert tool.parameters["properties"]["purpose"]["description"] == (
        "远端工具真正消费的业务用途。"
    )


def test_registry_subset_export_does_not_inject_host_fields() -> None:
    registry = ToolRegistry()
    registry.register(BusinessPurposeTool(name="alpha"))
    registry.register(BusinessPurposeTool(name="beta"))

    schemas = registry.get_schemas(names={"alpha"})

    assert [schema["function"]["name"] for schema in schemas] == ["alpha"]
    assert set(schemas[0]["function"]["parameters"]["properties"]) == {"purpose"}


def test_registry_execute_preserves_a_business_purpose_argument() -> None:
    registry = ToolRegistry()
    tool = BusinessPurposeTool()
    registry.register(tool)

    result = asyncio.run(
        registry.execute(tool.name, {"purpose": "business-purpose"})
    )

    assert result.output == {"purpose": "business-purpose"}
    assert tool.received == {"purpose": "business-purpose"}
