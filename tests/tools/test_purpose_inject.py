from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from amadeus.tools.base import ToolResult
from amadeus.tools.registry import ToolRegistry


@dataclass
class SimpleTool:
    name: str
    description: str = "Simple."
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        # 记录实际收到的 kwargs，断言 purpose 不应出现
        return ToolResult(tool_name=self.name, output={"got": list(kwargs.keys())})


@dataclass
class RecallMemoryLikeTool:
    """模拟 recall_memory：自带 intent 字段，不应被注入逻辑碰。"""

    name: str = "recall_memory"
    description: str = "Recall."
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "intent": {
                    "type": "string",
                    "enum": ["answer", "timeline", "context"],
                },
            },
            "required": ["query", "intent"],
        }
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(tool_name=self.name, output=kwargs.get("intent"))


def test_all_tools_get_purpose_in_properties_and_required():
    registry = ToolRegistry()
    registry.register(SimpleTool(name="alpha"))

    schemas = registry.get_schemas()

    props = schemas[0]["function"]["parameters"]["properties"]
    required = schemas[0]["function"]["parameters"]["required"]
    assert "purpose" in props
    assert "purpose" in required


def test_purpose_schema_has_no_minlength_maxlength():
    registry = ToolRegistry()
    registry.register(SimpleTool(name="alpha"))

    schema = registry.get_schemas()[0]
    purpose_field = schema["function"]["parameters"]["properties"]["purpose"]

    assert "minLength" not in purpose_field
    assert "maxLength" not in purpose_field
    assert purpose_field["type"] == "string"


def test_inject_does_not_mutate_tool_own_parameters():
    """deepcopy 保护：注入不应改 Tool 实例自带的 parameters。"""
    registry = ToolRegistry()
    tool = SimpleTool(name="alpha")
    registry.register(tool)

    registry.get_schemas()  # 调一次导出
    # Tool 自带 parameters 不应有 purpose
    assert "purpose" not in tool.parameters.get("properties", {})


def test_recall_memory_intent_field_not_overwritten_by_purpose_injection():
    """注入 purpose 不应覆盖 recall_memory 已声明的 intent 字段。"""
    registry = ToolRegistry()
    registry.register(RecallMemoryLikeTool())

    schema = registry.get_schemas()[0]
    props = schema["function"]["parameters"]["properties"]

    # intent 字段保留（语义不被破坏）
    assert "intent" in props
    assert "enum" in props["intent"]
    # purpose 也注入了（两者并存）
    assert "purpose" in props


def test_invoker_pops_purpose_before_tool_execute():
    """invoker 装配层 pop purpose：工具 execute(**kwargs) 不应收到 purpose。"""
    registry = ToolRegistry()
    registry.register(SimpleTool(name="alpha"))

    captured: dict[str, Any] = {}

    async def invoker(name: str, arguments: dict[str, Any]) -> Any:
        arguments.pop("purpose", None)  # 模拟 bootstrap _tool_invoker 的 pop
        result = await registry.execute(name, arguments)
        captured["got_keys"] = result.output["got"]
        return result

    asyncio.run(invoker("alpha", {"purpose": "读个文件"}))

    # 工具没收到 purpose
    assert captured["got_keys"] == []


def test_get_schemas_subset_also_injects_purpose():
    registry = ToolRegistry()
    registry.register(SimpleTool(name="alpha"))
    registry.register(SimpleTool(name="beta"))

    schemas = registry.get_schemas(names={"alpha"})
    assert len(schemas) == 1
    assert "purpose" in schemas[0]["function"]["parameters"]["properties"]