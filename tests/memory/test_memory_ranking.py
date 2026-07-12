from __future__ import annotations

from datetime import UTC, datetime

import pytest
from amadeus.memory.ranking import (
    MemoryCandidateLanes,
    build_query_plan,
    extract_terms,
    hotness_signal_for_row,
    rank_candidate_lanes,
    rank_multi_query_rows,
    rank_rows,
    rrf_merge,
)


def _candidate_row(
    item_id: str,
    *,
    summary: str | None = None,
    vector_distance: float | None = None,
    lexical_score: float | None = None,
    reinforcement: int = 1,
    updated_at: str = "2025-01-01T00:00:00+00:00",
) -> dict[str, object]:
    row: dict[str, object] = {
        "id": item_id,
        "kind": "event",
        "summary": summary or f"summary for {item_id}",
        "embedding": [1.0, 0.0],
        "source_ref": "",
        "extra": {},
        "reinforcement": reinforcement,
        "emotional_weight": 0,
        "updated_at": updated_at,
    }
    if vector_distance is not None:
        row["vector_distance"] = vector_distance
    if lexical_score is not None:
        row["lexical_score"] = lexical_score
    return row


def test_rrf_single_lane_only():
    result = rrf_merge([("a", 0.9), ("b", 0.8)], [], top_n=3)
    assert len(result) == 2
    assert result[0][:2] == ("a", 1.0 / 61)
    assert result[1][:2] == ("b", 1.0 / 62)
    assert result[0][2] == 0.0
    assert result[1][2] == 0.0


def test_rrf_empty_input_returns_empty():
    assert rrf_merge([], [], top_n=5) == []
    assert rrf_merge([("a", 0.9)], [], top_n=0) == []


def test_rrf_double_lane_outranks_single_only():
    result = rrf_merge([("a", 0.9), ("c", 0.6)], [("b", 0.8), ("c", 0.5)], top_n=3)
    assert len(result) == 3
    assert result[0][0] == "c"
    assert result[0][1] > 0.024
    assert result[1][0] == "a"
    assert result[2][0] == "b"


def test_rrf_k_is_explicitly_injectable() -> None:
    result = rrf_merge([("a", 0.9)], [], top_n=1, rrf_k=10)

    assert result[0][1] == pytest.approx(1.0 / 11)


def test_hotness_frequency_strength_and_emotional_scale_are_independent() -> None:
    row = _candidate_row(
        "hotness",
        reinforcement=100,
        updated_at="2026-07-02T00:00:00+00:00",
    )
    row["emotional_weight"] = 10
    no_frequency = hotness_signal_for_row(
        row,
        now=datetime(2026, 7, 12, tzinfo=UTC),
        half_life_days=14.0,
        reinforcement_strength=0.0,
        emotional_half_life_scale=1.0,
    )
    baseline = hotness_signal_for_row(
        row,
        now=datetime(2026, 7, 12, tzinfo=UTC),
        half_life_days=14.0,
        reinforcement_strength=1.0,
        emotional_half_life_scale=0.5,
    )

    assert no_frequency["frequency"] == 0.5
    assert no_frequency["effective_half_life_days"] == 28.0
    assert float(baseline["frequency"]) > float(no_frequency["frequency"])
    assert baseline["effective_half_life_days"] == 21.0


def test_rank_rows_rrf_double_lane_wins():
    rows = [
        {
            "id": "1",
            "kind": "event",
            "summary": "用户喜欢讨论各种游戏机制",
            "embedding": [0.9, 0.0, 0.0],
            "source_ref": "",
            "happened_at": None,
            "extra": {},
            "reinforcement": 1,
        },
        {
            "id": "2",
            "kind": "event",
            "summary": "仁王是一款硬核动作游戏",
            "embedding": [0.0, 0.9, 0.0],
            "source_ref": "",
            "happened_at": None,
            "extra": {},
            "reinforcement": 1,
        },
        {
            "id": "3",
            "kind": "preference",
            "summary": "仁王游戏的难度设计和boss机制",
            "embedding": [0.6, 0.5, 0.0],
            "source_ref": "",
            "happened_at": None,
            "extra": {},
            "reinforcement": 1,
        },
    ]
    result = rank_rows(rows, [1.0, 0.0, 0.0], "仁王 hardcore", limit=3, threshold=0.3)
    assert len(result) == 3
    assert result[0].id == "3"
    assert result[1].id == "1"
    assert result[2].id == "2"
    assert result[0].signals["lanes"] == ["vector", "lexical"]


def test_multi_query_vector_hits_keep_best_id_instead_of_accumulating():
    rows = [
        {
            "id": "single",
            "kind": "event",
            "summary": "single high vector match",
            "embedding": [1.0, 0.0, 0.0],
            "source_ref": "",
            "happened_at": None,
            "extra": {},
            "reinforcement": 1,
        },
        {
            "id": "repeated",
            "kind": "event",
            "summary": "repeated vector match",
            "embedding": [0.8, 0.6, 0.0],
            "source_ref": "",
            "happened_at": None,
            "extra": {},
            "reinforcement": 1,
        },
    ]

    result, lane_counts = rank_multi_query_rows(
        rows,
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        ["raw", "hypothesis"],
        limit=2,
        threshold=0.5,
    )

    assert [record.id for record in result] == ["single", "repeated"]
    assert result[1].signals["matched_query_indexes"] == ["0", "1"]
    assert result[1].signals["final_vector_score"] > 0
    assert result[1].signals["rrf_score"] == 1.0 / 62
    assert lane_counts == {
        "raw": {"vector": 2, "lexical": 0},
        "hypothesis": {"vector": 1, "lexical": 0},
    }


def test_rank_rows_reinforcement_does_not_outrank_stronger_dual_lane_match():
    rows = [
        {
            "id": "single",
            "kind": "event",
            "summary": "用户喜欢讨论各种游戏机制",
            "embedding": [0.9, 0.0, 0.0],
            "source_ref": "",
            "happened_at": None,
            "extra": {},
            "reinforcement": 1_000_000_000,
        },
        {
            "id": "keyword",
            "kind": "event",
            "summary": "仁王是一款硬核动作游戏",
            "embedding": [0.0, 0.9, 0.0],
            "source_ref": "",
            "happened_at": None,
            "extra": {},
            "reinforcement": 1,
        },
        {
            "id": "dual",
            "kind": "preference",
            "summary": "仁王游戏的难度设计和boss机制",
            "embedding": [0.6, 0.5, 0.0],
            "source_ref": "",
            "happened_at": None,
            "extra": {},
            "reinforcement": 1,
        },
    ]

    result = rank_rows(rows, [1.0, 0.0, 0.0], "仁王 hardcore", limit=3, threshold=0.3)

    assert result[0].id == "dual"
    assert result[0].signals["rrf_score"] > result[1].signals["rrf_score"]
    assert result[1].id == "single"
    assert result[1].signals["reinforcement"] == 1_000_000_000


def test_rank_rows_hotness_fusion_prefers_recent_reinforced_memory():
    rows = [
        {
            "id": "stale",
            "kind": "event",
            "summary": "用户讨论过发布流程",
            "embedding": [0.8, 0.0, 0.0],
            "source_ref": "",
            "happened_at": None,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00",
            "extra": {},
            "reinforcement": 1,
            "emotional_weight": 0,
        },
        {
            "id": "recent",
            "kind": "event",
            "summary": "用户讨论过发布流程",
            "embedding": [0.8, 0.0, 0.0],
            "source_ref": "",
            "happened_at": None,
            "created_at": "2999-01-01T00:00:00+00:00",
            "updated_at": "2999-01-01T00:00:00+00:00",
            "extra": {},
            "reinforcement": 10,
            "emotional_weight": 0,
        },
    ]

    result = rank_rows(rows, [1.0, 0.0, 0.0], "release", limit=2, threshold=0.3)

    assert result[0].id == "recent"
    assert (
        result[0].signals["final_vector_score"]
        > result[1].signals["final_vector_score"]
    )
    assert result[0].signals["hotness_score"] > result[1].signals["hotness_score"]


def test_rank_rows_emotional_weight_slows_hotness_decay():
    rows = [
        {
            "id": "neutral",
            "kind": "event",
            "summary": "用户讨论过长期计划",
            "embedding": [0.8, 0.0, 0.0],
            "source_ref": "",
            "happened_at": None,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "extra": {},
            "reinforcement": 3,
            "emotional_weight": 0,
        },
        {
            "id": "weighted",
            "kind": "event",
            "summary": "用户讨论过长期计划",
            "embedding": [0.8, 0.0, 0.0],
            "source_ref": "",
            "happened_at": None,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "extra": {},
            "reinforcement": 3,
            "emotional_weight": 10,
        },
    ]

    result = rank_rows(rows, [1.0, 0.0, 0.0], "plan", limit=2, threshold=0.3)

    assert result[0].id == "weighted"
    assert (
        result[0].signals["hotness_effective_half_life_days"]
        > result[1].signals["hotness_effective_half_life_days"]
    )
    assert result[0].signals["hotness_score"] > result[1].signals["hotness_score"]


def test_rank_rows_hot_unrelated_memory_does_not_cross_semantic_threshold():
    rows = [
        {
            "id": "relevant",
            "kind": "event",
            "summary": "相关候选",
            "embedding": [0.7, 0.0, 0.0],
            "source_ref": "",
            "happened_at": None,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00",
            "extra": {},
            "reinforcement": 1,
            "emotional_weight": 0,
        },
        {
            "id": "hot-unrelated",
            "kind": "event",
            "summary": "无关候选",
            "embedding": [0.0, 1.0, 0.0],
            "source_ref": "",
            "happened_at": None,
            "created_at": "2999-01-01T00:00:00+00:00",
            "updated_at": "2999-01-01T00:00:00+00:00",
            "extra": {},
            "reinforcement": 1_000_000,
            "emotional_weight": 10,
        },
    ]

    result = rank_rows(rows, [1.0, 0.0, 0.0], "nomatch", limit=2, threshold=0.3)

    assert [record.id for record in result] == ["relevant"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("支付", ["支付"]),
        ("支付宝", ["支付宝"]),
        ("长期记忆", ["长期记忆"]),
        ("支付宝支付", ["支付", "付宝", "宝支"]),
        ("かな", ["かな"]),
        ("カタカナ", ["カタカナ"]),
        ("こんにちは", ["こん", "んに", "にち", "ちは"]),
        ("ZXQ-4917 v1.2 foo_bar x", ["ZXQ-4917", "v1.2", "foo_bar"]),
    ],
)
def test_extract_terms_matches_akashic_ascii_and_cjk_rules(
    query: str,
    expected: list[str],
):
    assert extract_terms(query) == expected


def test_extract_terms_applies_akashic_stopwords_and_stable_dedupe():
    assert extract_terms("用户 当前 支付宝 支付宝 alpha alpha") == [
        "alpha",
        "支付宝",
    ]


def test_extract_terms_keeps_only_the_first_twenty_terms():
    query = " ".join(f"term{index:02d}" for index in range(21))

    assert extract_terms(query) == [f"term{index:02d}" for index in range(20)]


def test_legacy_rank_rows_matches_ascii_terms_case_insensitively():
    row = _candidate_row(
        "lexical",
        summary="memory contains zxq-4917",
    )
    row["embedding"] = [0.0, 1.0]

    records = rank_rows(
        [row],
        [1.0, 0.0],
        "ZXQ-4917",
        limit=1,
        threshold=0.3,
    )

    assert [record.id for record in records] == ["lexical"]
    assert records[0].signals["lanes"] == ["lexical"]


def test_rank_candidate_lanes_preserves_real_lane_provenance_and_contributions():
    vector_only = _candidate_row(
        "vector-only",
        summary="rare-token also appears here",
        vector_distance=0.1,
    )
    lexical_only = _candidate_row(
        "lexical-only",
        lexical_score=0.9,
    )
    both_vector = _candidate_row("both", vector_distance=0.2)
    both_lexical = _candidate_row("both", lexical_score=0.8)
    candidates = MemoryCandidateLanes(
        vector_groups=((vector_only, both_vector),),
        lexical=(lexical_only, both_lexical),
        lexical_terms=("rare-token",),
    )

    records, trace = rank_candidate_lanes(
        candidates,
        [[1.0, 0.0]],
        ["rare-token"],
        limit=3,
        threshold=0.3,
    )

    assert [record.id for record in records] == [
        "both",
        "lexical-only",
        "vector-only",
    ]
    by_id = {record.id: record for record in records}
    assert by_id["vector-only"].signals["lanes"] == ["vector"]
    assert by_id["vector-only"].signals["lexical_rank"] is None
    assert by_id["lexical-only"].signals["lanes"] == ["lexical"]
    assert by_id["lexical-only"].signals["vector_rank"] is None
    assert by_id["both"].signals["lanes"] == ["vector", "lexical"]
    assert by_id["both"].signals["vector_rank"] == 2
    assert by_id["both"].signals["lexical_rank"] == 2
    assert by_id["both"].signals["vector_rrf_contribution"] == pytest.approx(1.0 / 62)
    assert by_id["both"].signals["lexical_rrf_contribution"] == pytest.approx(1.0 / 62)
    assert by_id["both"].signals["rrf_score"] == pytest.approx(2.0 / 62)
    assert trace.candidate_counts == {
        "vector": 2,
        "lexical": 2,
        "union": 3,
        "final": 3,
    }
    assert trace.lane_counts == {"rare-token": {"vector": 2, "lexical": 2}}


def test_rank_candidate_lanes_keeps_best_multi_query_vector_hit_once():
    candidates = MemoryCandidateLanes(
        vector_groups=(
            (
                _candidate_row("single", vector_distance=0.1),
                _candidate_row("repeated", vector_distance=0.2),
            ),
            (_candidate_row("repeated", vector_distance=0.05),),
        ),
        lexical=(),
    )

    records, trace = rank_candidate_lanes(
        candidates,
        [[1.0, 0.0], [0.0, 1.0]],
        ["raw", "hypothesis"],
        limit=2,
        threshold=0.5,
    )

    assert [record.id for record in records] == ["repeated", "single"]
    assert records[0].signals["matched_query_indexes"] == ["0", "1"]
    assert records[0].signals["vector_score"] == pytest.approx(0.95)
    assert records[0].signals["vector_rank"] == 1
    assert records[0].signals["vector_rrf_contribution"] == pytest.approx(1.0 / 61)
    assert records[0].signals["rrf_score"] == pytest.approx(1.0 / 61)
    assert trace.lane_counts == {
        "raw": {"vector": 2, "lexical": 0},
        "hypothesis": {"vector": 1, "lexical": 0},
    }


def test_rank_candidate_lanes_uses_stable_id_for_equal_vector_scores():
    candidates = MemoryCandidateLanes(
        vector_groups=(
            (
                _candidate_row("z-last", vector_distance=0.1),
                _candidate_row("a-first", vector_distance=0.1),
            ),
        ),
        lexical=(),
    )

    records, _ = rank_candidate_lanes(
        candidates,
        [[1.0, 0.0]],
        ["raw"],
        limit=2,
        threshold=0.3,
    )

    assert [record.id for record in records] == ["a-first", "z-last"]


def test_rank_candidate_lanes_uses_one_time_snapshot_for_hotness_ties():
    updated_at = datetime.now(UTC).isoformat()
    rows = tuple(
        _candidate_row(
            f"candidate-{index:02d}",
            vector_distance=0.1,
            updated_at=updated_at,
        )
        for index in reversed(range(32))
    )

    records, _ = rank_candidate_lanes(
        MemoryCandidateLanes(vector_groups=(rows,), lexical=()),
        [[1.0, 0.0]],
        ["raw"],
        limit=32,
        threshold=0.3,
    )

    assert [record.id for record in records] == [
        f"candidate-{index:02d}" for index in range(32)
    ]


def test_rank_candidate_lanes_applies_vector_threshold_before_hotness():
    candidates = MemoryCandidateLanes(
        vector_groups=(
            (
                _candidate_row(
                    "relevant",
                    vector_distance=0.4,
                    updated_at="2020-01-01T00:00:00+00:00",
                ),
                _candidate_row(
                    "hot-unrelated",
                    vector_distance=0.8,
                    reinforcement=1_000_000,
                    updated_at="2999-01-01T00:00:00+00:00",
                ),
            ),
        ),
        lexical=(),
    )

    records, trace = rank_candidate_lanes(
        candidates,
        [[1.0, 0.0]],
        ["raw"],
        limit=2,
        threshold=0.5,
    )

    assert [record.id for record in records] == ["relevant"]
    assert trace.candidate_counts["vector"] == 2
    assert trace.lane_counts["raw"]["vector"] == 1


def test_rank_candidate_lanes_default_weight_makes_lexical_rank_one_visible():
    vector_rows = tuple(
        _candidate_row(f"vector-{index}", vector_distance=index / 100)
        for index in range(1, 10)
    )
    lexical_target = _candidate_row("lexical-target", lexical_score=1.0)
    candidates = MemoryCandidateLanes(
        vector_groups=(vector_rows,),
        lexical=(lexical_target,),
    )

    default_records, _ = rank_candidate_lanes(
        candidates,
        [[1.0, 0.0]],
        ["raw"],
        limit=8,
        threshold=0.3,
    )
    akashic_weight_records, _ = rank_candidate_lanes(
        candidates,
        [[1.0, 0.0]],
        ["raw"],
        limit=8,
        threshold=0.3,
        lexical_weight=0.5,
    )

    assert "lexical-target" in [record.id for record in default_records]
    assert "lexical-target" not in [record.id for record in akashic_weight_records]


def test_rank_candidate_lanes_zero_weight_excludes_lexical_only_results():
    vector_row = _candidate_row("vector", vector_distance=0.1)
    lexical_row = _candidate_row("lexical", lexical_score=1.0)

    records, trace = rank_candidate_lanes(
        MemoryCandidateLanes(
            vector_groups=((vector_row,),),
            lexical=(lexical_row,),
        ),
        [[1.0, 0.0]],
        ["raw"],
        limit=8,
        threshold=0.3,
        lexical_weight=0.0,
    )

    assert [record.id for record in records] == ["vector"]
    assert trace.candidate_counts == {
        "vector": 1,
        "lexical": 1,
        "union": 2,
        "final": 1,
    }


def test_rank_candidate_lanes_requires_query_aligned_vector_groups():
    candidates = MemoryCandidateLanes(vector_groups=((),), lexical=())

    with pytest.raises(ValueError, match="vector_groups"):
        rank_candidate_lanes(
            candidates,
            [[1.0, 0.0]],
            ["raw", "hypothesis"],
            limit=8,
            threshold=0.3,
        )


def test_context_query_plan_keeps_raw_query_before_explicit_queries():
    plan = build_query_plan(
        text="原问题",
        intent="context",
        memory_types=(),
        context={"queries": ["历史问题", "偏好问题", "历史问题"]},
    )

    assert plan.queries == ("原问题", "历史问题", "偏好问题")


def test_procedure_query_plan_limits_memory_types():
    plan = build_query_plan(
        text="如何发布版本",
        intent="procedure",
        memory_types=(),
        context={},
    )

    assert plan.memory_types == ("procedure", "preference")
    assert plan.queries == ("如何发布版本", "执行发布版本的步骤", "发布版本流程")
