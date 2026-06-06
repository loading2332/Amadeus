from amadeus.response_parser import parse_response


def test_parse_response_preserves_raw_text_metadata():
    result = parse_response("什么啊……不过，谢了。", tool_chain=[])

    assert result.clean_text == "什么啊……不过，谢了。"
    assert result.metadata.raw_text == "什么啊……不过，谢了。"


def test_parse_response_removes_standalone_parenthetical_stage_lines():
    text = "（突然被夸，愣了一下）\n\n什么啊……\n\n不过，谢了。"

    assert parse_response(text, tool_chain=[]).clean_text == "什么啊……\n\n不过，谢了。"


def test_parse_response_keeps_normal_parentheses():
    text = "函数 f(x) 的输入不是问题。\n\n先看变量。"

    assert parse_response(text, tool_chain=[]).clean_text == text


def test_parse_response_removes_multiple_stage_lines():
    text = "（小声）\n（移开视线）\n等、等一下……"

    assert parse_response(text, tool_chain=[]).clean_text == "等、等一下……"


def test_parse_response_removes_leading_inline_stage_direction():
    text = "（愣了一下）突然夸我干什么……不过，谢了。"

    assert parse_response(text, tool_chain=[]).clean_text == "突然夸我干什么……不过，谢了。"


def test_parse_response_removes_inline_stage_direction_after_speech():
    text = "突然夸我干什么……（移开视线）不过，谢了。"

    assert parse_response(text, tool_chain=[]).clean_text == "突然夸我干什么……不过，谢了。"
