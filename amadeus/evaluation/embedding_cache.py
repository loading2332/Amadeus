from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from amadeus.evaluation.memory_retrieval_benchmark import MemoryRetrievalBenchmark
from amadeus.memory.providers import EmbeddingProvider

_CACHE_VERSION = 1


class FileEmbeddingCacheProvider:
    """Embedding provider backed by a versioned, text-hash keyed JSON cache."""

    def __init__(
        self,
        path: str | Path,
        *,
        identity: str,
        dimensions: int,
        input_hash: str,
        underlying: EmbeddingProvider | None = None,
        allow_misses: bool = False,
    ) -> None:
        self.path = Path(path)
        self.identity = identity.strip()
        self.dimensions = dimensions
        self.input_hash = input_hash.strip()
        self.underlying = underlying
        self.allow_misses = allow_misses
        self._vectors: dict[str, list[float]] = {}
        self._dirty = False
        self._validate_config()
        if self.path.exists():
            self._load()
        elif not allow_misses:
            raise ValueError(f"frozen embedding cache does not exist: {self.path}")

    @property
    def entry_count(self) -> int:
        return len(self._vectors)

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self._payload(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("ascii")).hexdigest()

    async def embed(self, text: str) -> list[float]:
        key = _text_key(text)
        cached = self._vectors.get(key)
        if cached is not None:
            return list(cached)
        if not self.allow_misses:
            raise ValueError(f"frozen embedding cache miss: {key}")
        if self.underlying is None:
            raise ValueError("embedding cache misses require an underlying provider")
        vector = list(await self.underlying.embed(text))
        _validate_vector(vector, dimensions=self.dimensions, field=f"embedding:{key}")
        self._vectors[key] = vector
        self._dirty = True
        return list(vector)

    def flush(self) -> None:
        if not self._dirty and self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(self._payload(), ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        self._dirty = False

    def _validate_config(self) -> None:
        if not self.identity:
            raise ValueError("embedding cache identity is required")
        if isinstance(self.dimensions, bool) or self.dimensions <= 0:
            raise ValueError("embedding cache dimensions must be positive")
        if not self.input_hash:
            raise ValueError("embedding cache input_hash is required")

    def _load(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("embedding cache must contain an object")
        expected = {
            "version": _CACHE_VERSION,
            "identity": self.identity,
            "dimensions": self.dimensions,
            "input_hash": self.input_hash,
        }
        for field, value in expected.items():
            if payload.get(field) != value:
                raise ValueError(
                    f"embedding cache {field} mismatch: expected {value!r}"
                )
        raw_vectors = payload.get("vectors")
        if not isinstance(raw_vectors, dict):
            raise ValueError("embedding cache vectors must be an object")
        vectors: dict[str, list[float]] = {}
        for key, raw_vector in raw_vectors.items():
            if not isinstance(key, str) or not isinstance(raw_vector, list):
                raise ValueError("embedding cache contains an invalid vector entry")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in raw_vector
            ):
                raise ValueError(f"vectors.{key} must contain only numbers")
            vector = [float(value) for value in raw_vector]
            _validate_vector(vector, dimensions=self.dimensions, field=f"vectors.{key}")
            vectors[key] = vector
        self._vectors = vectors

    def _payload(self) -> dict[str, Any]:
        return {
            "version": _CACHE_VERSION,
            "identity": self.identity,
            "dimensions": self.dimensions,
            "input_hash": self.input_hash,
            "vectors": self._vectors,
        }


def benchmark_embedding_texts(
    benchmark: MemoryRetrievalBenchmark,
) -> tuple[str, ...]:
    values: list[str] = []
    for corpus in benchmark.corpora:
        values.extend(memory.summary for memory in corpus.memories)
    for query in benchmark.queries:
        values.append(query.raw_query)
        values.extend(
            text
            for text in (
                query.fixed_hypotheses.event,
                query.fixed_hypotheses.general,
            )
            if text
        )
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def benchmark_embedding_input_hash(benchmark: MemoryRetrievalBenchmark) -> str:
    canonical = json.dumps(
        benchmark_embedding_texts(benchmark),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prepare_benchmark_embedding_cache(
    benchmark: MemoryRetrievalBenchmark,
    cache: FileEmbeddingCacheProvider,
) -> str:
    return asyncio.run(populate_benchmark_embedding_cache(benchmark, cache))


async def populate_benchmark_embedding_cache(
    benchmark: MemoryRetrievalBenchmark,
    cache: FileEmbeddingCacheProvider,
) -> str:
    if not cache.allow_misses:
        raise ValueError("cache preparation requires allow_misses=True")
    await _populate_cache(benchmark_embedding_texts(benchmark), cache)
    cache.flush()
    return cache.fingerprint


async def _populate_cache(
    texts: tuple[str, ...],
    cache: FileEmbeddingCacheProvider,
) -> None:
    for text in texts:
        await cache.embed(text)


def _text_key(text: str) -> str:
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _validate_vector(vector: list[float], *, dimensions: int, field: str) -> None:
    if len(vector) != dimensions:
        raise ValueError(
            f"{field} must have {dimensions} dimensions, got {len(vector)}"
        )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in vector
    ):
        raise ValueError(f"{field} must contain only finite values")
