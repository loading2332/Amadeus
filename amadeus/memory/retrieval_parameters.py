from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryRetrievalParameters:
    """Immutable parameters that control candidate retrieval and ranking."""

    vector_candidate_floor: int = 32
    vector_candidate_multiplier: int = 4
    lexical_candidate_floor: int = 30
    lexical_candidate_multiplier: int = 2
    lexical_rrf_weight: float = 1.0
    rrf_k: int = 60
    semantic_threshold: float = 0.35
    hotness_alpha: float = 0.20
    hotness_half_life_days: float = 14.0
    reinforcement_strength: float = 1.0
    emotional_half_life_scale: float = 0.5

    def __post_init__(self) -> None:
        _require_positive_int(
            self.vector_candidate_floor,
            name="vector_candidate_floor",
        )
        _require_positive_int(
            self.vector_candidate_multiplier,
            name="vector_candidate_multiplier",
        )
        _require_positive_int(
            self.lexical_candidate_floor,
            name="lexical_candidate_floor",
        )
        _require_positive_int(
            self.lexical_candidate_multiplier,
            name="lexical_candidate_multiplier",
        )
        _require_non_negative_float(
            self.lexical_rrf_weight,
            name="lexical_rrf_weight",
        )
        _require_positive_int(self.rrf_k, name="rrf_k")
        _require_unit_interval(
            self.semantic_threshold,
            name="semantic_threshold",
        )
        _require_unit_interval(self.hotness_alpha, name="hotness_alpha")
        _require_positive_float(
            self.hotness_half_life_days,
            name="hotness_half_life_days",
        )
        _require_non_negative_float(
            self.reinforcement_strength,
            name="reinforcement_strength",
        )
        _require_non_negative_float(
            self.emotional_half_life_scale,
            name="emotional_half_life_scale",
        )

    def vector_candidate_limit(self, request_limit: int) -> int:
        return max(
            self.vector_candidate_floor,
            _positive_request_limit(request_limit)
            * self.vector_candidate_multiplier,
        )

    def lexical_candidate_limit(self, request_limit: int) -> int:
        return max(
            self.lexical_candidate_floor,
            _positive_request_limit(request_limit)
            * self.lexical_candidate_multiplier,
        )

    def as_dict(self) -> dict[str, int | float]:
        return {
            "vector_candidate_floor": self.vector_candidate_floor,
            "vector_candidate_multiplier": self.vector_candidate_multiplier,
            "lexical_candidate_floor": self.lexical_candidate_floor,
            "lexical_candidate_multiplier": self.lexical_candidate_multiplier,
            "lexical_rrf_weight": float(self.lexical_rrf_weight),
            "rrf_k": self.rrf_k,
            "semantic_threshold": float(self.semantic_threshold),
            "hotness_alpha": float(self.hotness_alpha),
            "hotness_half_life_days": float(self.hotness_half_life_days),
            "reinforcement_strength": float(self.reinforcement_strength),
            "emotional_half_life_scale": float(self.emotional_half_life_scale),
        }

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.as_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("ascii")).hexdigest()[:16]


def _positive_request_limit(value: int) -> int:
    _require_positive_int(value, name="request_limit")
    return value


def _require_positive_int(value: Any, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _require_unit_interval(value: Any, *, name: str) -> None:
    number = _finite_float(value, name=name)
    if number < 0.0 or number > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


def _require_positive_float(value: Any, *, name: str) -> None:
    if _finite_float(value, name=name) <= 0.0:
        raise ValueError(f"{name} must be greater than 0")


def _require_non_negative_float(value: Any, *, name: str) -> None:
    if _finite_float(value, name=name) < 0.0:
        raise ValueError(f"{name} must be non-negative")


def _finite_float(value: Any, *, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number
