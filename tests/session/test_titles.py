from amadeus.session.titles import title_from_first_message


def test_title_from_first_message_normalizes_and_truncates_unicode() -> None:
    assert title_from_first_message("  第一行\n\t第二行  ") == "第一行 第二行"
    assert title_from_first_message("甲" * 31) == f"{'甲' * 30}…"
