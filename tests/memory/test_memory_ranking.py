from __future__ import annotations

from amadeus.memory.ranking import (
    build_query_plan,
    extract_terms,
    rank_rows,
    rrf_merge,
)


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


def test_extract_terms_adds_cjk_bigrams_and_removes_stop_words():
    terms = extract_terms("我 之前 讨论仁王机制")

    assert "仁王" in terms
    assert "机制" in terms
    assert "之前" not in terms


def test_context_query_plan_uses_explicit_queries():
    plan = build_query_plan(
        text="原问题",
        intent="context",
        memory_types=(),
        context={"queries": ["历史问题", "偏好问题", "历史问题"]},
    )

    assert plan.queries == ("历史问题", "偏好问题")


def test_procedure_query_plan_limits_memory_types():
    plan = build_query_plan(
        text="如何发布版本",
        intent="procedure",
        memory_types=(),
        context={},
    )

    assert plan.memory_types == ("procedure", "preference")
    assert plan.queries == ("如何发布版本", "执行发布版本的步骤", "发布版本流程")
