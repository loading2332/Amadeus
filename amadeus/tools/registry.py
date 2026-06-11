from __future__ import annotations

from collections import OrderedDict
from typing import Any

from amadeus.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: OrderedDict[str, Tool] = OrderedDict()

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self):
        return self._tools.keys()

    def export_openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]
