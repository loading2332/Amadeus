from __future__ import annotations

from amadeus.mcp.schema_validator import validate_openai_function_schema


def test_valid_object_schema_passes():
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    assert validate_openai_function_schema(schema) == []


def test_empty_type_tolerated():
    """参数为空时 type 可缺省。"""
    schema = {"properties": {}}
    assert validate_openai_function_schema(schema) == []


def test_non_object_type_flagged():
    schema = {"type": "array", "items": {}}
    errors = validate_openai_function_schema(schema)
    assert any("type 应为 object" in e for e in errors)


def test_ref_rejected():
    schema = {"type": "object", "$ref": "#/$defs/Foo"}
    errors = validate_openai_function_schema(schema)
    assert any("$ref" in e for e in errors)


def test_allof_anyof_onof_rejected():
    for kw in ("allOf", "anyOf", "oneOf"):
        schema = {"type": "object", kw: []}
        errors = validate_openai_function_schema(schema)
        assert any(kw in e for e in errors)


def test_non_dict_properties_flagged():
    schema = {"type": "object", "properties": ["not", "a", "dict"]}
    errors = validate_openai_function_schema(schema)
    assert any("properties 应为 object" in e for e in errors)


def test_non_dict_schema_flagged():
    errors = validate_openai_function_schema("not a dict")  # type: ignore[arg-type]
    assert any("应为 dict" in e for e in errors)