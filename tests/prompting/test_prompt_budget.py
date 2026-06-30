from amadeus.prompting.budget import (
    CORE_SECTIONS,
    DEFAULT_CONTEXT_TRIM_PLANS,
    build_context_trim_attempts,
)


def test_default_trim_plans_never_drop_core_sections():
    for plan in DEFAULT_CONTEXT_TRIM_PLANS:
        assert CORE_SECTIONS.isdisjoint(plan.drop_sections)


def test_build_context_trim_attempts_generates_disabled_sections_and_history_windows():
    attempts = build_context_trim_attempts(total_history=10)

    assert attempts[0].name == "full"
    assert attempts[0].disabled_sections == set()
    assert attempts[0].history_window == 10
    assert any("long_term_memory" in item.disabled_sections for item in attempts)
    assert any("retrieved_memory" in item.disabled_sections for item in attempts)
    assert attempts[-1].history_window < attempts[0].history_window


def test_build_context_trim_attempts_deduplicates_attempts():
    attempts = build_context_trim_attempts(total_history=1)
    keys = [
        (tuple(sorted(item.disabled_sections)), item.history_window)
        for item in attempts
    ]

    assert len(keys) == len(set(keys))
