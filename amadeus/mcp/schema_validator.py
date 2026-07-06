from __future__ import annotations

from typing import Any

# OpenAI function calling 不支持的 JSON Schema keyword（MCP server 可能用）
_UNSUPPORTED_KEYWORDS = ("$ref", "$defs", "allOf", "anyOf", "oneOf", "not", "if", "then", "else")


def validate_openai_function_schema(input_schema: dict[str, Any]) -> list[str]:
    """轻校验 MCP 工具的 input_schema 是否兼容 OpenAI function calling。

    不做完整 JSON Schema 校验，只挡明显不合法的情况：
    - type 应为 object（或空，参数为空时容忍）
    - 不使用 OpenAI 不支持的 keyword（$ref / $defs / allOf 等）
    - properties 若存在应为 dict

    返回错误字符串列表，空列表表示通过。
    """
    errors: list[str] = []
    if not isinstance(input_schema, dict):
        return [f"input_schema 应为 dict，实际 {type(input_schema).__name__}"]

    schema_type = input_schema.get("type")
    if schema_type is not None and schema_type != "object":
        # OpenAI function 期望 object；空 type 也容忍（参数为空）
        errors.append(f"type 应为 object，实际 {schema_type!r}")

    for kw in _UNSUPPORTED_KEYWORDS:
        if kw in input_schema:
            errors.append(f"OpenAI function calling 不支持 {kw}，请内联展开")

    properties = input_schema.get("properties")
    if properties is not None and not isinstance(properties, dict):
        errors.append("properties 应为 object")

    return errors