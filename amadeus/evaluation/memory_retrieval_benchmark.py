from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml

ReviewStatus = Literal["draft", "approved"]
BenchmarkSplit = Literal["development", "holdout"]
ProductScenario = Literal["personal_assistant", "project_assistant", "stress"]
MemoryCapability = Literal[
    "information_extraction",
    "cross_session",
    "knowledge_update",
    "temporal_reasoning",
    "abstention",
]
BenchmarkLanguage = Literal["zh", "en", "mixed"]
ExpectedLane = Literal["vector", "lexical"]
MemoryStatus = Literal["active", "superseded"]
MemoryOwner = Literal["experiment", "other_user"]
EmbeddingMode = Literal["generated", "null"]

_REVIEW_STATUSES: set[ReviewStatus] = {"draft", "approved"}
_SPLITS: set[BenchmarkSplit] = {"development", "holdout"}
_PRODUCT_SCENARIOS: set[ProductScenario] = {
    "personal_assistant",
    "project_assistant",
    "stress",
}
_MEMORY_CAPABILITIES: set[MemoryCapability] = {
    "information_extraction",
    "cross_session",
    "knowledge_update",
    "temporal_reasoning",
    "abstention",
}
_LANGUAGES: set[BenchmarkLanguage] = {"zh", "en", "mixed"}
_EXPECTED_LANES: set[ExpectedLane] = {"vector", "lexical"}
_MEMORY_STATUSES: set[MemoryStatus] = {"active", "superseded"}
_MEMORY_OWNERS: set[MemoryOwner] = {"experiment", "other_user"}
_EMBEDDING_MODES: set[EmbeddingMode] = {"generated", "null"}
_LiteralValue = TypeVar("_LiteralValue", bound=str)


@dataclass(frozen=True)
class RetrievalBenchmarkMemory:
    key: str
    summary: str
    memory_type: str
    updated_at: str
    happened_at: str | None = None
    reinforcement: int = 1
    emotional_weight: float = 0.0
    embedding_mode: EmbeddingMode = "generated"
    status: MemoryStatus = "active"
    owner: MemoryOwner = "experiment"
    scope_channel: str | None = None
    scope_chat_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "summary": self.summary,
            "memory_type": self.memory_type,
            "updated_at": self.updated_at,
            "happened_at": self.happened_at,
            "reinforcement": self.reinforcement,
            "emotional_weight": self.emotional_weight,
            "embedding_mode": self.embedding_mode,
            "status": self.status,
            "owner": self.owner,
            "scope_channel": self.scope_channel,
            "scope_chat_id": self.scope_chat_id,
            "extra": dict(self.extra),
        }


@dataclass(frozen=True)
class RetrievalBenchmarkCorpus:
    id: str
    memories: tuple[RetrievalBenchmarkMemory, ...]

    @property
    def memory_keys(self) -> set[str]:
        return {memory.key for memory in self.memories}

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "memories": [memory.to_record() for memory in self.memories],
        }


@dataclass(frozen=True)
class RetrievalJudgment:
    memory_key: str
    relevance: int
    dangerous: bool
    rationale: str
    danger_reasons: tuple[str, ...] = ()
    expected_lanes: tuple[ExpectedLane, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return {
            "memory_key": self.memory_key,
            "relevance": self.relevance,
            "dangerous": self.dangerous,
            "danger_reasons": list(self.danger_reasons),
            "expected_lanes": list(self.expected_lanes),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class RetrievalHotnessPair:
    preferred_memory_key: str
    other_memory_key: str
    rationale: str

    def to_record(self) -> dict[str, str]:
        return {
            "preferred_memory_key": self.preferred_memory_key,
            "other_memory_key": self.other_memory_key,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class FixedRetrievalHypotheses:
    event: str = ""
    general: str = ""

    def to_record(self) -> dict[str, str]:
        return {"event": self.event, "general": self.general}


@dataclass(frozen=True)
class RetrievalBenchmarkQuery:
    id: str
    family_id: str
    corpus_id: str
    split: BenchmarkSplit
    review_status: ReviewStatus
    review_batch: int
    product_scenario: ProductScenario
    memory_capability: MemoryCapability
    language: BenchmarkLanguage
    raw_query: str
    fixed_hypotheses: FixedRetrievalHypotheses
    strata: tuple[str, ...]
    judgments: tuple[RetrievalJudgment, ...]
    required_memory_keys: tuple[str, ...] = ()
    expected_abstention: bool = False
    hotness_pairs: tuple[RetrievalHotnessPair, ...] = ()
    memory_types: tuple[str, ...] = ()
    scope_channel: str | None = None
    scope_chat_id: str | None = None
    time_start: str | None = None
    time_end: str | None = None
    rationale: str = ""

    @property
    def judgment_by_key(self) -> dict[str, RetrievalJudgment]:
        return {judgment.memory_key: judgment for judgment in self.judgments}

    @property
    def relevant_memory_keys(self) -> set[str]:
        return {
            judgment.memory_key
            for judgment in self.judgments
            if judgment.relevance >= 2 and not judgment.dangerous
        }

    @property
    def dangerous_memory_keys(self) -> set[str]:
        return {
            judgment.memory_key for judgment in self.judgments if judgment.dangerous
        }

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family_id": self.family_id,
            "corpus_id": self.corpus_id,
            "split": self.split,
            "review_status": self.review_status,
            "review_batch": self.review_batch,
            "product_scenario": self.product_scenario,
            "memory_capability": self.memory_capability,
            "language": self.language,
            "raw_query": self.raw_query,
            "fixed_hypotheses": self.fixed_hypotheses.to_record(),
            "strata": list(self.strata),
            "expected_abstention": self.expected_abstention,
            "required_memory_keys": list(self.required_memory_keys),
            "judgments": [judgment.to_record() for judgment in self.judgments],
            "hotness_pairs": [pair.to_record() for pair in self.hotness_pairs],
            "memory_types": list(self.memory_types),
            "scope_channel": self.scope_channel,
            "scope_chat_id": self.scope_chat_id,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class MemoryRetrievalBenchmark:
    version: str
    review_status: ReviewStatus
    corpora: tuple[RetrievalBenchmarkCorpus, ...]
    queries: tuple[RetrievalBenchmarkQuery, ...]

    @property
    def corpus_by_id(self) -> dict[str, RetrievalBenchmarkCorpus]:
        return {corpus.id: corpus for corpus in self.corpora}

    @property
    def family_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(query.family_id for query in self.queries))

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(
            self.to_record(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_record(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "review_status": self.review_status,
            "corpora": [corpus.to_record() for corpus in self.corpora],
            "queries": [query.to_record() for query in self.queries],
        }

    def require_approved(self) -> None:
        if self.review_status != "approved":
            raise ValueError("formal retrieval experiments require an approved dataset")
        draft_families = sorted(
            {
                query.family_id
                for query in self.queries
                if query.review_status != "approved"
            }
        )
        if draft_families:
            raise ValueError(
                "formal retrieval experiments require approved families: "
                + ", ".join(draft_families)
            )

    def review_batches(self) -> dict[int, tuple[str, ...]]:
        batches: dict[int, list[str]] = defaultdict(list)
        seen: set[tuple[int, str]] = set()
        for query in self.queries:
            marker = (query.review_batch, query.family_id)
            if marker in seen:
                continue
            seen.add(marker)
            batches[query.review_batch].append(query.family_id)
        return {batch: tuple(families) for batch, families in sorted(batches.items())}


def load_memory_retrieval_benchmark(
    case_file: str | Path,
    *,
    enforce_v1_distribution: bool = True,
) -> MemoryRetrievalBenchmark:
    path = Path(case_file)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    benchmark = _parse_benchmark(payload)
    if enforce_v1_distribution:
        validate_v1_distribution(benchmark)
    return benchmark


def validate_v1_distribution(benchmark: MemoryRetrievalBenchmark) -> None:
    family_metadata: dict[
        str,
        tuple[BenchmarkSplit, ProductScenario, MemoryCapability, int],
    ] = {}
    for query in benchmark.queries:
        metadata = (
            query.split,
            query.product_scenario,
            query.memory_capability,
            query.review_batch,
        )
        previous = family_metadata.setdefault(query.family_id, metadata)
        if previous != metadata:
            raise ValueError(
                f"family {query.family_id!r} has inconsistent split or metadata"
            )

    if len(family_metadata) != 60:
        raise ValueError("memory retrieval benchmark v1 must contain 60 families")

    split_counts = Counter(metadata[0] for metadata in family_metadata.values())
    if split_counts != Counter({"development": 42, "holdout": 18}):
        raise ValueError("benchmark split must contain 42 development and 18 holdout")

    expected_scenarios = Counter(
        {"personal_assistant": 30, "project_assistant": 21, "stress": 9}
    )
    scenario_counts = Counter(metadata[1] for metadata in family_metadata.values())
    if scenario_counts != expected_scenarios:
        raise ValueError("benchmark scenarios must use the 30/21/9 distribution")

    expected_by_split = {
        "development": Counter(
            {"personal_assistant": 21, "project_assistant": 15, "stress": 6}
        ),
        "holdout": Counter(
            {"personal_assistant": 9, "project_assistant": 6, "stress": 3}
        ),
    }
    for split, expected in expected_by_split.items():
        actual = Counter(
            metadata[1]
            for metadata in family_metadata.values()
            if metadata[0] == split
        )
        if actual != expected:
            raise ValueError(f"{split} scenarios do not match the required distribution")

    batches = benchmark.review_batches()
    if set(batches) != set(range(1, 7)) or any(
        len(families) != 10 for families in batches.values()
    ):
        raise ValueError("benchmark must contain six review batches of 10 families")
    query_by_family = {query.family_id: query for query in benchmark.queries}
    if any(query_by_family[family_id].split != "development" for family_id in batches[1]):
        raise ValueError("review batch 1 must contain development families only")

    for split in ("development", "holdout"):
        capability_counts = Counter(
            metadata[2]
            for metadata in family_metadata.values()
            if metadata[0] == split
        )
        missing = sorted(_MEMORY_CAPABILITIES - set(capability_counts))
        if missing:
            raise ValueError(f"{split} is missing capabilities: {', '.join(missing)}")
        if any(count < 2 for count in capability_counts.values()):
            raise ValueError(f"{split} must contain multiple families per capability")

    development_corpus_ids = {
        query.corpus_id for query in benchmark.queries if query.split == "development"
    }
    eligible_development_memories = sum(
        memory.owner == "experiment" and memory.status == "active"
        for corpus in benchmark.corpora
        if corpus.id in development_corpus_ids
        for memory in corpus.memories
    )
    if eligible_development_memories <= 64:
        raise ValueError(
            "development search pool must contain more than 64 eligible memories"
        )


def _parse_benchmark(payload: dict[str, Any]) -> MemoryRetrievalBenchmark:
    version = _required_string(payload, "version", prefix="benchmark")
    review_status = _literal(
        payload.get("review_status"),
        allowed=_REVIEW_STATUSES,
        field="review_status",
        prefix=version,
    )
    raw_corpora = _required_list(payload, "corpora", prefix=version)
    corpora = tuple(
        _parse_corpus(item, index=index, version=version)
        for index, item in enumerate(raw_corpora)
    )
    _reject_duplicates((corpus.id for corpus in corpora), label="corpus id")
    corpus_by_id = {corpus.id: corpus for corpus in corpora}
    _reject_duplicates(
        (memory.key for corpus in corpora for memory in corpus.memories),
        label="benchmark memory key",
    )

    raw_queries = _required_list(payload, "queries", prefix=version)
    queries = tuple(
        _parse_query(item, index=index, version=version)
        for index, item in enumerate(raw_queries)
    )
    _reject_duplicates((query.id for query in queries), label="query id")
    for query in queries:
        if query.corpus_id not in corpus_by_id:
            raise ValueError(f"{query.id}: unknown corpus {query.corpus_id!r}")

    family_splits: dict[str, BenchmarkSplit] = {}
    corpus_splits: dict[str, BenchmarkSplit] = {}
    for query in queries:
        previous = family_splits.setdefault(query.family_id, query.split)
        if previous != query.split:
            raise ValueError(f"family {query.family_id!r} crosses benchmark splits")
        previous_corpus_split = corpus_splits.setdefault(query.corpus_id, query.split)
        if previous_corpus_split != query.split:
            raise ValueError(f"corpus {query.corpus_id!r} crosses benchmark splits")

    memory_keys_by_split = {
        split: {
            memory.key
            for corpus_id, corpus_split in corpus_splits.items()
            if corpus_split == split
            for memory in corpus_by_id[corpus_id].memories
        }
        for split in _SPLITS
    }
    for query in queries:
        _validate_query_against_search_pool(
            query,
            memory_keys=memory_keys_by_split[query.split],
        )

    return MemoryRetrievalBenchmark(
        version=version,
        review_status=review_status,
        corpora=corpora,
        queries=queries,
    )


def _parse_corpus(payload: Any, *, index: int, version: str) -> RetrievalBenchmarkCorpus:
    prefix = f"{version}.corpora[{index}]"
    item = _object(payload, prefix=prefix)
    corpus_id = _required_string(item, "id", prefix=prefix)
    raw_memories = _required_list(item, "memories", prefix=corpus_id)
    memories = tuple(
        _parse_memory(memory, index=memory_index, corpus_id=corpus_id)
        for memory_index, memory in enumerate(raw_memories)
    )
    if not memories:
        raise ValueError(f"{corpus_id}: memories must not be empty")
    _reject_duplicates((memory.key for memory in memories), label=f"{corpus_id} memory key")
    _reject_duplicates(
        (
            f"{memory.owner}:{memory.memory_type}:"
            + " ".join(memory.summary.lower().split())
            for memory in memories
        ),
        label=f"{corpus_id} owner/type/summary",
    )
    return RetrievalBenchmarkCorpus(id=corpus_id, memories=memories)


def _parse_memory(
    payload: Any,
    *,
    index: int,
    corpus_id: str,
) -> RetrievalBenchmarkMemory:
    prefix = f"{corpus_id}.memories[{index}]"
    item = _object(payload, prefix=prefix)
    reinforcement = _integer(item.get("reinforcement", 1), field="reinforcement", prefix=prefix)
    if reinforcement < 0:
        raise ValueError(f"{prefix}: reinforcement must be non-negative")
    emotional_weight = _number(
        item.get("emotional_weight", 0.0),
        field="emotional_weight",
        prefix=prefix,
    )
    if emotional_weight < 0.0 or emotional_weight > 10.0:
        raise ValueError(f"{prefix}: emotional_weight must be between 0 and 10")
    raw_extra = item.get("extra", {})
    if not isinstance(raw_extra, dict):
        raise ValueError(f"{prefix}: extra must be an object")
    raw_embedding_mode = item.get("embedding_mode", "generated")
    if "embedding_mode" in item and raw_embedding_mode is None:
        raw_embedding_mode = "null"
    return RetrievalBenchmarkMemory(
        key=_required_string(item, "key", prefix=prefix),
        summary=_required_string(item, "summary", prefix=prefix),
        memory_type=_required_string(item, "memory_type", prefix=prefix),
        updated_at=_required_string(item, "updated_at", prefix=prefix),
        happened_at=_optional_string(item.get("happened_at"), field="happened_at", prefix=prefix),
        reinforcement=reinforcement,
        emotional_weight=emotional_weight,
        embedding_mode=_literal(
            raw_embedding_mode,
            allowed=_EMBEDDING_MODES,
            field="embedding_mode",
            prefix=prefix,
        ),
        status=_literal(
            item.get("status", "active"),
            allowed=_MEMORY_STATUSES,
            field="status",
            prefix=prefix,
        ),
        owner=_literal(
            item.get("owner", "experiment"),
            allowed=_MEMORY_OWNERS,
            field="owner",
            prefix=prefix,
        ),
        scope_channel=_optional_string(item.get("scope_channel"), field="scope_channel", prefix=prefix),
        scope_chat_id=_optional_string(item.get("scope_chat_id"), field="scope_chat_id", prefix=prefix),
        extra=dict(raw_extra),
    )


def _parse_query(payload: Any, *, index: int, version: str) -> RetrievalBenchmarkQuery:
    prefix = f"{version}.queries[{index}]"
    item = _object(payload, prefix=prefix)
    query_id = _required_string(item, "id", prefix=prefix)
    raw_hypotheses = item.get("fixed_hypotheses", {})
    hypotheses = _object(raw_hypotheses, prefix=f"{query_id}.fixed_hypotheses")
    raw_judgments = _required_list(item, "judgments", prefix=query_id)
    judgments = tuple(
        _parse_judgment(judgment, index=judgment_index, query_id=query_id)
        for judgment_index, judgment in enumerate(raw_judgments)
    )
    _reject_duplicates(
        (judgment.memory_key for judgment in judgments),
        label=f"{query_id} judgment memory key",
    )
    hotness_pairs = tuple(
        _parse_hotness_pair(pair, index=pair_index, query_id=query_id)
        for pair_index, pair in enumerate(
            _optional_list(item.get("hotness_pairs"), field="hotness_pairs", prefix=query_id)
        )
    )
    strata = _string_tuple(item.get("strata"), field="strata", prefix=query_id)
    if not strata:
        raise ValueError(f"{query_id}: strata must not be empty")
    review_batch = _integer(item.get("review_batch"), field="review_batch", prefix=query_id)
    if review_batch < 1 or review_batch > 6:
        raise ValueError(f"{query_id}: review_batch must be between 1 and 6")
    rationale = _required_string(item, "rationale", prefix=query_id)
    return RetrievalBenchmarkQuery(
        id=query_id,
        family_id=_required_string(item, "family_id", prefix=query_id),
        corpus_id=_required_string(item, "corpus_id", prefix=query_id),
        split=_literal(item.get("split"), allowed=_SPLITS, field="split", prefix=query_id),
        review_status=_literal(
            item.get("review_status"),
            allowed=_REVIEW_STATUSES,
            field="review_status",
            prefix=query_id,
        ),
        review_batch=review_batch,
        product_scenario=_literal(
            item.get("product_scenario"),
            allowed=_PRODUCT_SCENARIOS,
            field="product_scenario",
            prefix=query_id,
        ),
        memory_capability=_literal(
            item.get("memory_capability"),
            allowed=_MEMORY_CAPABILITIES,
            field="memory_capability",
            prefix=query_id,
        ),
        language=_literal(
            item.get("language"),
            allowed=_LANGUAGES,
            field="language",
            prefix=query_id,
        ),
        raw_query=_required_string(item, "raw_query", prefix=query_id),
        fixed_hypotheses=FixedRetrievalHypotheses(
            event=_optional_string(hypotheses.get("event"), field="event", prefix=query_id) or "",
            general=_optional_string(hypotheses.get("general"), field="general", prefix=query_id) or "",
        ),
        strata=strata,
        judgments=judgments,
        required_memory_keys=_string_tuple(
            item.get("required_memory_keys"),
            field="required_memory_keys",
            prefix=query_id,
        ),
        expected_abstention=_boolean(
            item.get("expected_abstention", False),
            field="expected_abstention",
            prefix=query_id,
        ),
        hotness_pairs=hotness_pairs,
        memory_types=_string_tuple(item.get("memory_types"), field="memory_types", prefix=query_id),
        scope_channel=_optional_string(item.get("scope_channel"), field="scope_channel", prefix=query_id),
        scope_chat_id=_optional_string(item.get("scope_chat_id"), field="scope_chat_id", prefix=query_id),
        time_start=_optional_string(item.get("time_start"), field="time_start", prefix=query_id),
        time_end=_optional_string(item.get("time_end"), field="time_end", prefix=query_id),
        rationale=rationale,
    )


def _parse_judgment(payload: Any, *, index: int, query_id: str) -> RetrievalJudgment:
    prefix = f"{query_id}.judgments[{index}]"
    item = _object(payload, prefix=prefix)
    relevance = _integer(item.get("relevance"), field="relevance", prefix=prefix)
    if relevance < 0 or relevance > 3:
        raise ValueError(f"{prefix}: relevance must be between 0 and 3")
    dangerous = _boolean(item.get("dangerous", False), field="dangerous", prefix=prefix)
    danger_reasons = _string_tuple(item.get("danger_reasons"), field="danger_reasons", prefix=prefix)
    if dangerous and not danger_reasons:
        raise ValueError(f"{prefix}: dangerous judgments require danger_reasons")
    expected_lanes_raw = _string_tuple(
        item.get("expected_lanes"),
        field="expected_lanes",
        prefix=prefix,
    )
    expected_lanes = tuple(
        _literal(
            lane,
            allowed=_EXPECTED_LANES,
            field="expected_lanes",
            prefix=prefix,
        )
        for lane in expected_lanes_raw
    )
    return RetrievalJudgment(
        memory_key=_required_string(item, "memory_key", prefix=prefix),
        relevance=relevance,
        dangerous=dangerous,
        danger_reasons=danger_reasons,
        expected_lanes=expected_lanes,
        rationale=_required_string(item, "rationale", prefix=prefix),
    )


def _parse_hotness_pair(
    payload: Any,
    *,
    index: int,
    query_id: str,
) -> RetrievalHotnessPair:
    prefix = f"{query_id}.hotness_pairs[{index}]"
    item = _object(payload, prefix=prefix)
    return RetrievalHotnessPair(
        preferred_memory_key=_required_string(item, "preferred_memory_key", prefix=prefix),
        other_memory_key=_required_string(item, "other_memory_key", prefix=prefix),
        rationale=_required_string(item, "rationale", prefix=prefix),
    )


def _validate_query_against_search_pool(
    query: RetrievalBenchmarkQuery,
    *,
    memory_keys: set[str],
) -> None:
    judgment_by_key = query.judgment_by_key
    unknown_judgments = sorted(set(judgment_by_key) - memory_keys)
    if unknown_judgments:
        raise ValueError(f"{query.id}: judgments reference unknown memories {unknown_judgments}")
    unknown_required = sorted(set(query.required_memory_keys) - memory_keys)
    if unknown_required:
        raise ValueError(f"{query.id}: required keys are unknown {unknown_required}")
    invalid_required = sorted(
        key
        for key in query.required_memory_keys
        if key not in query.relevant_memory_keys
    )
    if invalid_required:
        raise ValueError(
            f"{query.id}: required keys must have safe relevance >= 2: {invalid_required}"
        )
    if query.expected_abstention and query.relevant_memory_keys:
        raise ValueError(f"{query.id}: abstention queries cannot declare relevant memories")
    if query.expected_abstention and query.required_memory_keys:
        raise ValueError(f"{query.id}: abstention queries cannot require memories")
    if not query.expected_abstention and not query.relevant_memory_keys:
        raise ValueError(
            f"{query.id}: non-abstention queries require safe relevance >= 2"
        )
    for pair in query.hotness_pairs:
        pair_keys = {pair.preferred_memory_key, pair.other_memory_key}
        if len(pair_keys) != 2 or not pair_keys <= memory_keys:
            raise ValueError(
                f"{query.id}: hotness pair must reference two search-pool memories"
            )


def _object(value: Any, *, prefix: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{prefix} must be an object")
    return value


def _required_list(payload: dict[str, Any], field: str, *, prefix: str) -> list[Any]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{prefix}: {field} must be a list")
    return value


def _optional_list(value: Any, *, field: str, prefix: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{prefix}: {field} must be a list")
    return value


def _required_string(payload: dict[str, Any], field: str, *, prefix: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{prefix}: {field} is required")
    return value.strip()


def _optional_string(value: Any, *, field: str, prefix: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{prefix}: {field} must be a string")
    return value.strip() or None


def _string_tuple(value: Any, *, field: str, prefix: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{prefix}: {field} must be a list of non-empty strings")
    normalized = tuple(item.strip() for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{prefix}: {field} must not contain duplicates")
    return normalized


def _integer(value: Any, *, field: str, prefix: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{prefix}: {field} must be an integer")
    return value


def _number(value: Any, *, field: str, prefix: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{prefix}: {field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{prefix}: {field} must be finite")
    return number


def _boolean(value: Any, *, field: str, prefix: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{prefix}: {field} must be a boolean")
    return value


def _literal(
    value: Any,
    *,
    allowed: set[_LiteralValue],
    field: str,
    prefix: str,
) -> _LiteralValue:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{prefix}: {field} must be one of {sorted(allowed)}")
    return value


def _reject_duplicates(values: Any, *, label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"duplicate {label}: {', '.join(sorted(duplicates))}")
