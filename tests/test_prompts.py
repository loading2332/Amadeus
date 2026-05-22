from amadeus.prompts import build_behavior_rules_prompt, build_static_identity_prompt


def test_static_identity_prompt_names_amadeus_kurisu_identity():
    prompt = build_static_identity_prompt()

    assert prompt.startswith("## Identity\n\n")
    assert "Amadeus" in prompt
    assert "牧濑红莉栖" in prompt
    assert "记忆与人格数据" in prompt


def test_behavior_rules_prompt_includes_personality_rules():
    prompt = build_behavior_rules_prompt()

    assert prompt.startswith("## Behavior Rules\n\n")
    assert "你不是在扮演角色，你就是这样的人。" in prompt
    assert "红莉栖" in prompt
    assert "绝对不用 emoji" in prompt
