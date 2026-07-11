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
    errors = validate_openai_function_schema("not a dict")
    assert any("应为 dict" in e for e in errors)


def test_nested_ref_in_properties_is_rejected_with_path():
    schema = {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "properties": {"item": {"$ref": "#/$defs/Item"}},
            }
        },
    }

    errors = validate_openai_function_schema(schema)

    assert any("properties.payload.properties.item.$ref" in error for error in errors)


def test_nested_ref_in_items_and_additional_properties_is_rejected():
    schema = {
        "type": "object",
        "properties": {
            "rows": {"type": "array", "items": {"$ref": "#/Row"}},
            "labels": {
                "type": "object",
                "additionalProperties": {"$ref": "#/Label"},
            },
        },
    }

    errors = validate_openai_function_schema(schema)

    assert any("properties.rows.items.$ref" in error for error in errors)
    assert any(
        "properties.labels.additionalProperties.$ref" in error for error in errors
    )


def test_schema_like_business_data_is_not_traversed():
    schema = {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "enum": [{"$ref": "business-data", "allOf": ["not-a-schema"]}],
                "default": {"$ref": "also-business-data"},
            }
        },
    }

    assert validate_openai_function_schema(schema) == []


def test_deep_schema_uses_iterative_walk():
    schema: dict = {"type": "object", "properties": {"payload": {}}}
    cursor = schema["properties"]["payload"]
    for _ in range(1500):
        cursor["items"] = {}
        cursor = cursor["items"]
    cursor["$ref"] = "#/Deep"

    errors = validate_openai_function_schema(schema)

    assert any("$ref" in error for error in errors)
