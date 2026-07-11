from __future__ import annotations

from typing import Any

# OpenAI function calling 不支持的 JSON Schema keyword（MCP server 可能用）
_UNSUPPORTED_KEYWORDS = (
    "$ref",
    "$defs",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
)

# 只跟随“值仍然是 schema”的关键字，避免把 enum/default/examples 里的业务数据
# 误当成 schema。组合器和 $defs 已在上面直接拒绝，因此无需继续扫描其子树。
_SCHEMA_MAP_KEYWORDS = (
    "properties",
    "patternProperties",
    "dependentSchemas",
    "dependencies",
)
_SCHEMA_VALUE_KEYWORDS = (
    "additionalProperties",
    "contains",
    "contentSchema",
    "items",
    "propertyNames",
    "unevaluatedItems",
    "unevaluatedProperties",
)
_SCHEMA_ARRAY_KEYWORDS = ("prefixItems",)


def _format_path(path: tuple[str, ...]) -> str:
    return ".".join(path)


def validate_openai_function_schema(input_schema: object) -> list[str]:
    """轻校验 MCP 工具 input_schema 是否兼容 OpenAI function calling。

    校验只在 MCP 工具注册时执行。深层 keyword 检查使用显式栈做一次迭代式
    DFS：每个 schema 节点最多访问一次，时间复杂度 O(n)，不会受到 Python
    递归深度限制；同时只跟随 schema-bearing keyword，不扫描业务数据字段。

    返回错误字符串列表，空列表表示通过。
    """
    if not isinstance(input_schema, dict):
        return [f"input_schema 应为 dict，实际 {type(input_schema).__name__}"]

    errors: list[str] = []
    schema_type = input_schema.get("type")
    if schema_type is not None and schema_type != "object":
        # OpenAI function 顶层期望 object；空 type 也容忍（参数为空）。
        errors.append(f"type 应为 object，实际 {schema_type!r}")

    stack: list[tuple[tuple[str, ...], dict[str, Any]]] = [((), input_schema)]

    while stack:
        path, schema = stack.pop()

        for keyword in _UNSUPPORTED_KEYWORDS:
            if keyword in schema:
                unsupported_path = _format_path((*path, keyword))
                errors.append(
                    f"{unsupported_path}: OpenAI function calling 不支持 {keyword}，请内联展开"
                )

        for keyword in _SCHEMA_MAP_KEYWORDS:
            children = schema.get(keyword)
            if children is None:
                continue
            map_path = (*path, keyword)
            if not isinstance(children, dict):
                if keyword == "properties":
                    errors.append(f"{_format_path(map_path)} 应为 object")
                continue
            for child_name, child_schema in reversed(children.items()):
                if isinstance(child_schema, dict):
                    stack.append(((*map_path, str(child_name)), child_schema))

        for keyword in _SCHEMA_VALUE_KEYWORDS:
            child_schema = schema.get(keyword)
            if isinstance(child_schema, dict):
                stack.append(((*path, keyword), child_schema))
            elif keyword == "items" and isinstance(child_schema, list):
                # 兼容旧 draft 的 tuple validation，仅检查其中真正的 schema 节点。
                for index in range(len(child_schema) - 1, -1, -1):
                    item_schema = child_schema[index]
                    if isinstance(item_schema, dict):
                        stack.append(((*path, keyword, str(index)), item_schema))

        for keyword in _SCHEMA_ARRAY_KEYWORDS:
            child_schemas = schema.get(keyword)
            if not isinstance(child_schemas, list):
                continue
            for index in range(len(child_schemas) - 1, -1, -1):
                child_schema = child_schemas[index]
                if isinstance(child_schema, dict):
                    stack.append(((*path, keyword, str(index)), child_schema))

    return errors
