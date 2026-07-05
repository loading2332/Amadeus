from __future__ import annotations

EMBEDDING_DIM = 1024


def pad_embedding(values: list[float], dim: int = EMBEDDING_DIM) -> list[float]:
    """Pad a compact test vector to the pgvector schema dimension."""
    if len(values) >= dim:
        return [float(value) for value in values[:dim]]
    return [float(value) for value in values] + [0.0] * (dim - len(values))
