from dataclasses import dataclass

CORE_SECTIONS = frozenset({"identity", "behavior_rules", "self_model"})
_SAFETY_RETRY_RATIOS = (1.0, 0.5, 0.25, 0.0)


@dataclass(frozen=True)
class ContextTrimPlan:
    name: str
    drop_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextTrimAttempt:
    name: str
    disabled_sections: set[str]
    history_window: int


DEFAULT_CONTEXT_TRIM_PLANS: tuple[ContextTrimPlan, ...] = (
    ContextTrimPlan(name="full"),
    ContextTrimPlan(name="trim_runtime_metadata", drop_sections=("runtime_metadata",)),
    ContextTrimPlan(
        name="trim_active_skills",
        drop_sections=("runtime_metadata", "active_skills"),
    ),
    ContextTrimPlan(
        name="trim_long_term_memory",
        drop_sections=("runtime_metadata", "active_skills", "long_term_memory"),
    ),
    ContextTrimPlan(
        name="trim_retrieved_memory",
        drop_sections=(
            "runtime_metadata",
            "active_skills",
            "long_term_memory",
            "retrieved_memory",
        ),
    ),
)


def build_context_trim_attempts(
    total_history: int,
    trim_plans: tuple[ContextTrimPlan, ...] = DEFAULT_CONTEXT_TRIM_PLANS,
    retry_ratios: tuple[float, ...] = _SAFETY_RETRY_RATIOS,
) -> list[ContextTrimAttempt]:
    history_size = max(0, total_history)
    full_window = int(history_size * retry_ratios[0]) if retry_ratios else history_size
    attempts: list[ContextTrimAttempt] = []
    seen: set[tuple[tuple[str, ...], int]] = set()

    for trim_plan in trim_plans:
        disabled = set(trim_plan.drop_sections)
        key = (tuple(sorted(disabled)), full_window)
        if key in seen:
            continue
        seen.add(key)
        attempts.append(
            ContextTrimAttempt(
                name=trim_plan.name,
                disabled_sections=disabled,
                history_window=full_window,
            )
        )

    if not trim_plans:
        return attempts

    last_trim = set(trim_plans[-1].drop_sections)
    for ratio in retry_ratios[1:]:
        window = int(history_size * ratio)
        key = (tuple(sorted(last_trim)), window)
        if key in seen:
            continue
        seen.add(key)
        attempts.append(
            ContextTrimAttempt(
                name=f"{trim_plans[-1].name}_history",
                disabled_sections=set(last_trim),
                history_window=window,
            )
        )

    return attempts
