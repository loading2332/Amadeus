from __future__ import annotations

from dataclasses import replace

import pytest
from amadeus.memory.retrieval_parameters import MemoryRetrievalParameters


def test_default_retrieval_parameters_reproduce_amadeus_baseline() -> None:
    parameters = MemoryRetrievalParameters()

    assert parameters.vector_candidate_limit(8) == 32
    assert parameters.lexical_candidate_limit(8) == 30
    assert parameters.as_dict() == {
        "vector_candidate_floor": 32,
        "vector_candidate_multiplier": 4,
        "lexical_candidate_floor": 30,
        "lexical_candidate_multiplier": 2,
        "lexical_rrf_weight": 1.0,
        "rrf_k": 60,
        "semantic_threshold": 0.35,
        "hotness_alpha": 0.2,
        "hotness_half_life_days": 14.0,
        "reinforcement_strength": 1.0,
        "emotional_half_life_scale": 0.5,
    }
    assert len(parameters.fingerprint) == 16


def test_candidate_limits_can_reproduce_akashic_vector_window() -> None:
    parameters = replace(
        MemoryRetrievalParameters(),
        vector_candidate_floor=15,
        vector_candidate_multiplier=1,
    )

    assert parameters.vector_candidate_limit(8) == 15
    assert parameters.vector_candidate_limit(20) == 20


def test_parameter_fingerprint_is_stable_and_changes_with_profile() -> None:
    baseline = MemoryRetrievalParameters()
    same = MemoryRetrievalParameters()
    candidate = replace(baseline, lexical_rrf_weight=0.75)

    assert baseline.fingerprint == same.fingerprint
    assert baseline.fingerprint != candidate.fingerprint


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("vector_candidate_floor", 0),
        ("vector_candidate_multiplier", 0),
        ("lexical_candidate_floor", 0),
        ("lexical_candidate_multiplier", 0),
        ("lexical_rrf_weight", -0.1),
        ("rrf_k", 0),
        ("semantic_threshold", 1.1),
        ("hotness_alpha", -0.1),
        ("hotness_half_life_days", 0.0),
        ("reinforcement_strength", -1.0),
        ("emotional_half_life_scale", float("nan")),
    ],
)
def test_retrieval_parameters_reject_invalid_values(
    field_name: str,
    value: int | float,
) -> None:
    with pytest.raises(ValueError):
        replace(MemoryRetrievalParameters(), **{field_name: value})
