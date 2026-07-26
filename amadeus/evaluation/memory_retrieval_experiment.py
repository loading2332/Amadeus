from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import secrets
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from psycopg.types.json import Jsonb

from amadeus.db import PostgresDatabase
from amadeus.evaluation.memory_retrieval_benchmark import (
    MemoryRetrievalBenchmark,
    RetrievalBenchmarkCorpus,
    RetrievalBenchmarkMemory,
    RetrievalBenchmarkQuery,
    validate_v1_distribution,
)
from amadeus.evaluation.memory_retrieval_metrics import (
    QueryRetrievalMetrics,
    RetrievalAggregateReport,
    RetrievalObservation,
    aggregate_retrieval_metrics,
    evaluate_retrieval_observation,
    metrics_to_record,
)
from amadeus.memory.engine import MemoryRecallRequest, MemoryScope
from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.post_response_worker import PostResponseMemoryWorker
from amadeus.memory.postgres import PostgresMemoryStore
from amadeus.memory.providers import EmbeddingProvider
from amadeus.memory.retrieval_parameters import MemoryRetrievalParameters
from amadeus.memory.retriever import (
    MemoryRetriever,
    RetrievalCandidateSnapshot,
)
from amadeus.memory.runtime import LongTermMemoryEngine
from amadeus.memory.store import _content_hash
from amadeus.session.identity import SessionRef

ExperimentSplit = Literal["development", "holdout"]


@dataclass(frozen=True)
class MemoryRetrievalExperimentProfile:
    name: str
    parameters: MemoryRetrievalParameters
    changed_fields: tuple[str, ...] = ()
    hypothesis_enabled: bool = True
    lexical_enabled: bool = True

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameters": self.parameters.as_dict(),
            "fingerprint": self.parameters.fingerprint,
            "changed_fields": list(self.changed_fields),
            "hypothesis_enabled": self.hypothesis_enabled,
            "lexical_enabled": self.lexical_enabled,
        }


@dataclass(frozen=True)
class MemoryRetrievalExperimentReport:
    experiment_id: str
    stage: int | None
    split: ExperimentSplit
    formal: bool
    dataset_hash: str
    profile_count: int
    query_count: int
    results_path: Path
    csv_path: Path
    summary_path: Path
    profile_results: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class MemoryRetrievalJudgingPoolReport:
    experiment_id: str
    split: ExperimentSplit
    dataset_hash: str
    unknown_pair_count: int
    json_path: Path
    review_path: Path


def freeze_profile_shortlist(
    results_path: str | Path,
    *,
    profile_names: Sequence[str],
    source_stage: int,
    output_path: str | Path,
) -> Path:
    if source_stage < 1 or source_stage > 5:
        raise ValueError("source_stage must be between 1 and 5")
    selected_names = tuple(profile_names)
    max_profiles = 3 if source_stage == 5 else 2
    if not selected_names or len(selected_names) > max_profiles:
        raise ValueError(f"Stage {source_stage} shortlist allows at most {max_profiles} profiles")
    if len(selected_names) != len(set(selected_names)):
        raise ValueError("shortlist profile names must be unique")
    results = _read_json_object(Path(results_path), label="experiment results")
    if results.get("stage") != source_stage:
        raise ValueError("source_stage does not match experiment results")
    dataset_hash = results.get("dataset_hash")
    if not isinstance(dataset_hash, str) or not dataset_hash:
        raise ValueError("experiment results require dataset_hash")
    raw_profiles = results.get("profiles")
    if not isinstance(raw_profiles, list):
        raise ValueError("experiment results require profiles")
    raw_profile_results = results.get("results")
    if not isinstance(raw_profile_results, list):
        raise ValueError("experiment results require profile results")
    profile_by_name = {
        profile.get("name"): profile
        for profile in raw_profiles
        if isinstance(profile, dict) and isinstance(profile.get("name"), str)
    }
    missing = [name for name in selected_names if name not in profile_by_name]
    if missing:
        raise ValueError(f"shortlist profiles not found in results: {missing}")
    hard_gate_by_name = {
        item.get("profile", {}).get("name"): item.get("hard_gate_passed")
        for item in raw_profile_results
        if isinstance(item, dict) and isinstance(item.get("profile"), dict)
    }
    failed = [name for name in selected_names if hard_gate_by_name.get(name) is not True]
    if failed:
        raise ValueError(f"shortlist profiles failed hard gates: {failed}")
    payload: dict[str, Any] = {
        "version": 1,
        "source_stage": source_stage,
        "dataset_hash": dataset_hash,
        "profiles": [profile_by_name[name] for name in selected_names],
    }
    payload["shortlist_hash"] = _canonical_hash(payload)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return destination


def load_frozen_profile_shortlist(
    path: str | Path,
    *,
    expected_source_stage: int,
    dataset_hash: str,
) -> tuple[MemoryRetrievalExperimentProfile, ...]:
    payload = _read_json_object(Path(path), label="profile shortlist")
    if payload.get("version") != 1:
        raise ValueError("profile shortlist version must be 1")
    if payload.get("source_stage") != expected_source_stage:
        raise ValueError(
            f"profile shortlist must come from Stage {expected_source_stage}"
        )
    if payload.get("dataset_hash") != dataset_hash:
        raise ValueError("profile shortlist dataset_hash does not match benchmark")
    expected_hash = payload.get("shortlist_hash")
    hash_input = dict(payload)
    hash_input.pop("shortlist_hash", None)
    if expected_hash != _canonical_hash(hash_input):
        raise ValueError("profile shortlist hash mismatch")
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, list):
        raise ValueError("profile shortlist profiles must be a list")
    profiles = tuple(_profile_from_record(record) for record in raw_profiles)
    if expected_source_stage == 5:
        _require_finalists(profiles)
    else:
        _require_stage_bases(expected_source_stage + 1, profiles)
    return profiles


def rebase_finalist_shortlist_for_holdout_qrels(
    path: str | Path,
    *,
    source_benchmark: MemoryRetrievalBenchmark,
    benchmark: MemoryRetrievalBenchmark,
    approved_overlay_path: str | Path,
    output_path: str | Path,
) -> Path:
    source_path = Path(path)
    payload = _read_json_object(source_path, label="profile shortlist")
    source_dataset_hash = payload.get("dataset_hash")
    if not isinstance(source_dataset_hash, str) or not source_dataset_hash:
        raise ValueError("profile shortlist requires dataset_hash")
    profiles = load_frozen_profile_shortlist(
        source_path,
        expected_source_stage=5,
        dataset_hash=source_dataset_hash,
    )
    overlay_path = Path(approved_overlay_path)
    overlay = _read_yaml_object(overlay_path, label="holdout qrels overlay")
    if overlay.get("review_status") != "approved":
        raise ValueError("holdout qrels overlay must be approved")
    if overlay.get("split") != "holdout":
        raise ValueError("finalist shortlist rebase requires a holdout-only overlay")
    if overlay.get("source_dataset_hash") != source_dataset_hash:
        raise ValueError("holdout qrels overlay source hash does not match shortlist")
    source_benchmark.require_approved()
    benchmark.require_approved()
    if source_benchmark.content_hash != source_dataset_hash:
        raise ValueError("source benchmark hash does not match finalist shortlist")
    if benchmark.content_hash == source_dataset_hash:
        raise ValueError("rebased benchmark must have a new dataset hash")

    raw_judgments = overlay.get("judgments")
    if not isinstance(raw_judgments, list) or not raw_judgments:
        raise ValueError("holdout qrels overlay requires judgments")
    overlay_by_marker: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in raw_judgments:
        if not isinstance(raw, dict):
            raise ValueError("holdout qrels overlay judgments must be objects")
        query_id = raw.get("query_id")
        memory_key = raw.get("memory_key")
        if not isinstance(query_id, str) or not isinstance(memory_key, str):
            raise ValueError("holdout qrels overlay judgments require string keys")
        marker = (query_id, memory_key)
        if marker in overlay_by_marker:
            raise ValueError("holdout qrels overlay contains duplicate judgments")
        overlay_by_marker[marker] = raw

    _validate_holdout_qrels_only_rebase(
        source_benchmark=source_benchmark,
        benchmark=benchmark,
        overlay_by_marker=overlay_by_marker,
    )

    rebased = dict(payload)
    rebased.pop("shortlist_hash", None)
    rebased["selection_dataset_hash"] = payload.get(
        "selection_dataset_hash",
        source_dataset_hash,
    )
    rebased["dataset_hash"] = benchmark.content_hash
    rebased["holdout_adjudication"] = {
        "overlay_id": overlay.get("overlay_id"),
        "file": overlay_path.name,
        "sha256": hashlib.sha256(overlay_path.read_bytes()).hexdigest(),
        "source_dataset_hash": source_dataset_hash,
    }
    rebased["profiles"] = [profile.to_record() for profile in profiles]
    rebased["shortlist_hash"] = _canonical_hash(rebased)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(rebased, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return destination


def _validate_holdout_qrels_only_rebase(
    *,
    source_benchmark: MemoryRetrievalBenchmark,
    benchmark: MemoryRetrievalBenchmark,
    overlay_by_marker: dict[tuple[str, str], dict[str, Any]],
) -> None:
    if (
        source_benchmark.version != benchmark.version
        or source_benchmark.review_status != benchmark.review_status
        or source_benchmark.corpora != benchmark.corpora
    ):
        raise ValueError("holdout rebase may only add approved qrels")
    source_query_ids = tuple(query.id for query in source_benchmark.queries)
    rebased_query_ids = tuple(query.id for query in benchmark.queries)
    if source_query_ids != rebased_query_ids:
        raise ValueError("holdout rebase may only add approved qrels")

    remaining_markers = set(overlay_by_marker)
    for source_query, rebased_query in zip(
        source_benchmark.queries,
        benchmark.queries,
        strict=True,
    ):
        if replace(source_query, judgments=()) != replace(
            rebased_query,
            judgments=(),
        ):
            raise ValueError("holdout rebase may only add approved qrels")
        source_by_key = source_query.judgment_by_key
        rebased_by_key = rebased_query.judgment_by_key
        query_overlay = {
            memory_key: raw
            for (query_id, memory_key), raw in overlay_by_marker.items()
            if query_id == source_query.id
        }
        if query_overlay and source_query.split != "holdout":
            raise ValueError("holdout qrels overlay references a non-holdout query")
        if set(source_by_key) & set(query_overlay):
            raise ValueError("holdout qrels overlay must add new judgments")
        if set(rebased_by_key) != set(source_by_key) | set(query_overlay):
            raise ValueError("holdout rebase may only add approved qrels")
        if any(
            rebased_by_key[memory_key] != judgment
            for memory_key, judgment in source_by_key.items()
        ):
            raise ValueError("holdout rebase may only add approved qrels")
        for memory_key, raw in query_overlay.items():
            marker = (source_query.id, memory_key)
            remaining_markers.discard(marker)
            judgment = rebased_by_key[memory_key]
            if (
                judgment.relevance != raw.get("relevance")
                or judgment.dangerous != raw.get("dangerous")
                or list(judgment.danger_reasons) != raw.get("danger_reasons")
                or judgment.rationale != raw.get("rationale")
                or judgment.expected_lanes
            ):
                raise ValueError("rebased benchmark judgment disagrees with overlay")
    if remaining_markers:
        raise ValueError("holdout qrels overlay references an unknown query")


def _profile_from_record(record: Any) -> MemoryRetrievalExperimentProfile:
    if not isinstance(record, dict):
        raise ValueError("profile shortlist entries must be objects")
    name = record.get("name")
    parameters = record.get("parameters")
    changed_fields = record.get("changed_fields", [])
    if not isinstance(name, str) or not name.strip():
        raise ValueError("profile shortlist entries require a name")
    if not isinstance(parameters, dict):
        raise ValueError("profile shortlist entries require parameters")
    if not isinstance(changed_fields, list) or not all(
        isinstance(field, str) for field in changed_fields
    ):
        raise ValueError("profile shortlist changed_fields must be strings")
    try:
        parsed_parameters = MemoryRetrievalParameters(**parameters)
    except TypeError as exc:
        raise ValueError("profile shortlist parameters are invalid") from exc
    fingerprint = record.get("fingerprint")
    if fingerprint != parsed_parameters.fingerprint:
        raise ValueError("profile shortlist fingerprint mismatch")
    hypothesis_enabled = record.get("hypothesis_enabled", True)
    lexical_enabled = record.get("lexical_enabled", True)
    if not isinstance(hypothesis_enabled, bool) or not isinstance(
        lexical_enabled, bool
    ):
        raise ValueError("profile shortlist lane flags must be booleans")
    return MemoryRetrievalExperimentProfile(
        name=name.strip(),
        parameters=parsed_parameters,
        changed_fields=tuple(changed_fields),
        hypothesis_enabled=hypothesis_enabled,
        lexical_enabled=lexical_enabled,
    )


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain an object")
    return payload


def _read_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain an object")
    return payload


def _canonical_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _SeededSearchUniverse:
    corpora: tuple[RetrievalBenchmarkCorpus, ...]
    store: PostgresMemoryStore
    memory_id_by_key: dict[str, str]
    memory_by_id: dict[str, RetrievalBenchmarkMemory]
    corpus_id_by_key: dict[str, str]

    @property
    def memory_key_by_id(self) -> dict[str, str]:
        return {item_id: key for key, item_id in self.memory_id_by_key.items()}


@dataclass(frozen=True)
class _QueryRun:
    observation: RetrievalObservation
    trace: dict[str, Any]
    ranked_records: tuple[dict[str, Any], ...]
    snapshots: tuple[RetrievalCandidateSnapshot, ...]


def run_memory_retrieval_experiment(
    benchmark: MemoryRetrievalBenchmark,
    *,
    profiles: Sequence[MemoryRetrievalExperimentProfile],
    split: ExperimentSplit,
    ranking_time: datetime,
    db: PostgresDatabase,
    embedding_provider: EmbeddingProvider,
    embedding_identity: str,
    artifacts_dir: str | Path,
    formal: bool = False,
    unlock_holdout: bool = False,
    embedding_cache_fingerprint: str | None = None,
    experiment_id: str | None = None,
    verify_determinism: bool = True,
    stage: int | None = None,
) -> MemoryRetrievalExperimentReport:
    return asyncio.run(
        _run_memory_retrieval_experiment_async(
            benchmark,
            profiles=profiles,
            split=split,
            ranking_time=ranking_time,
            db=db,
            embedding_provider=embedding_provider,
            embedding_identity=embedding_identity,
            artifacts_dir=artifacts_dir,
            formal=formal,
            unlock_holdout=unlock_holdout,
            embedding_cache_fingerprint=embedding_cache_fingerprint,
            experiment_id=experiment_id,
            verify_determinism=verify_determinism,
            stage=stage,
        )
    )


def collect_memory_retrieval_judging_pool(
    benchmark: MemoryRetrievalBenchmark,
    *,
    profiles: Sequence[MemoryRetrievalExperimentProfile],
    split: ExperimentSplit,
    ranking_time: datetime,
    db: PostgresDatabase,
    embedding_provider: EmbeddingProvider,
    embedding_identity: str,
    embedding_cache_fingerprint: str,
    artifacts_dir: str | Path,
    experiment_id: str | None = None,
    unlock_holdout: bool = False,
) -> MemoryRetrievalJudgingPoolReport:
    return asyncio.run(
        _collect_memory_retrieval_judging_pool_async(
            benchmark,
            profiles=profiles,
            split=split,
            ranking_time=ranking_time,
            db=db,
            embedding_provider=embedding_provider,
            embedding_identity=embedding_identity,
            embedding_cache_fingerprint=embedding_cache_fingerprint,
            artifacts_dir=Path(artifacts_dir),
            experiment_id=experiment_id,
            unlock_holdout=unlock_holdout,
        )
    )


async def _collect_memory_retrieval_judging_pool_async(
    benchmark: MemoryRetrievalBenchmark,
    *,
    profiles: Sequence[MemoryRetrievalExperimentProfile],
    split: ExperimentSplit,
    ranking_time: datetime,
    db: PostgresDatabase,
    embedding_provider: EmbeddingProvider,
    embedding_identity: str,
    embedding_cache_fingerprint: str,
    artifacts_dir: Path,
    experiment_id: str | None,
    unlock_holdout: bool,
) -> MemoryRetrievalJudgingPoolReport:
    if split == "holdout" and not unlock_holdout:
        raise ValueError("holdout judging-pool collection requires explicit unlock")
    if split == "development" and unlock_holdout:
        raise ValueError("unlock_holdout is only valid for holdout judging pools")
    benchmark.require_approved()
    _validate_run_request(
        benchmark,
        profiles=profiles,
        split=split,
        formal=False,
        unlock_holdout=unlock_holdout,
        embedding_identity=embedding_identity,
        embedding_cache_fingerprint=embedding_cache_fingerprint,
    )
    if not embedding_cache_fingerprint:
        raise ValueError("judging-pool collection requires a frozen embedding cache")
    selected_queries, selected_corpora = _select_search_universe(benchmark, split)
    run_id = experiment_id or _new_experiment_id()
    registry = _ExperimentUserRegistry(db, experiment_id=run_id)
    pooled: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        seeded = await _seed_search_universe(
            selected_corpora,
            registry=registry,
            embedding_provider=embedding_provider,
            experiment_id=run_id,
        )
        for profile in profiles:
            for query in selected_queries:
                run = await _run_query(
                    query,
                    seeded=seeded,
                    parameters=profile.parameters,
                    ranking_time=_aware_datetime(ranking_time, field="ranking_time"),
                    embedding_provider=embedding_provider,
                    hypothesis_enabled=profile.hypothesis_enabled,
                    lexical_enabled=profile.lexical_enabled,
                )
                known_keys = set(query.judgment_by_key)
                for record in run.ranked_records:
                    memory_key = str(record["memory_key"])
                    if memory_key in known_keys:
                        continue
                    marker = (query.id, memory_key)
                    item = pooled.setdefault(
                        marker,
                        {
                            "query_id": query.id,
                            "family_id": query.family_id,
                            "raw_query": query.raw_query,
                            "memory_key": memory_key,
                            "memory_summary": seeded.memory_by_id[
                                str(record["runtime_id"])
                            ].summary,
                            "memory_corpus_id": seeded.corpus_id_by_key[memory_key],
                            "profile_ranks": {},
                        },
                    )
                    item["profile_ranks"][profile.name] = record["rank"]
        entries = tuple(
            pooled[key]
            for key in sorted(pooled, key=lambda value: (value[0], value[1]))
        )
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in run_id
        )
        json_path = artifacts_dir / f"{safe_id}-judging-pool.json"
        review_path = artifacts_dir / f"{safe_id}-judging-pool-review.md"
        payload = {
            "experiment_id": run_id,
            "split": split,
            "dataset_version": benchmark.version,
            "dataset_hash": benchmark.content_hash,
            "embedding_identity": embedding_identity,
            "embedding_cache_fingerprint": embedding_cache_fingerprint,
            "ranking_time": _aware_datetime(
                ranking_time,
                field="ranking_time",
            ).isoformat(),
            "profiles": [profile.to_record() for profile in profiles],
            "unknown_pairs": list(entries),
        }
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        review_path.write_text(
            _render_judging_pool_review(entries, benchmark=benchmark),
            encoding="utf-8",
        )
        return MemoryRetrievalJudgingPoolReport(
            experiment_id=run_id,
            split=split,
            dataset_hash=benchmark.content_hash,
            unknown_pair_count=len(entries),
            json_path=json_path,
            review_path=review_path,
        )
    finally:
        active_error = sys.exception()
        try:
            registry.cleanup()
        except Exception as cleanup_error:
            if active_error is None:
                raise
            active_error.add_note(
                f"experiment user cleanup also failed: {type(cleanup_error).__name__}"
            )


async def _run_memory_retrieval_experiment_async(
    benchmark: MemoryRetrievalBenchmark,
    *,
    profiles: Sequence[MemoryRetrievalExperimentProfile],
    split: ExperimentSplit,
    ranking_time: datetime,
    db: PostgresDatabase,
    embedding_provider: EmbeddingProvider,
    embedding_identity: str,
    artifacts_dir: str | Path,
    formal: bool,
    unlock_holdout: bool,
    embedding_cache_fingerprint: str | None,
    experiment_id: str | None,
    verify_determinism: bool,
    stage: int | None,
) -> MemoryRetrievalExperimentReport:
    _validate_run_request(
        benchmark,
        profiles=profiles,
        split=split,
        formal=formal,
        unlock_holdout=unlock_holdout,
        embedding_identity=embedding_identity,
        embedding_cache_fingerprint=embedding_cache_fingerprint,
    )
    normalized_ranking_time = _aware_datetime(ranking_time, field="ranking_time")
    selected_queries, selected_corpora = _select_search_universe(benchmark, split)
    run_id = experiment_id or _new_experiment_id()
    registry = _ExperimentUserRegistry(db, experiment_id=run_id)

    profile_results: list[dict[str, Any]] = []
    try:
        seeded = await _seed_search_universe(
            selected_corpora,
            registry=registry,
            embedding_provider=embedding_provider,
            experiment_id=run_id,
        )

        for profile in profiles:
            query_results: list[dict[str, Any]] = []
            query_metrics: list[QueryRetrievalMetrics] = []
            for query in selected_queries:
                first = await _run_query(
                    query,
                    seeded=seeded,
                    parameters=profile.parameters,
                    ranking_time=normalized_ranking_time,
                    embedding_provider=embedding_provider,
                    hypothesis_enabled=profile.hypothesis_enabled,
                    lexical_enabled=profile.lexical_enabled,
                )
                observation = first.observation
                stability: dict[str, Any] = {"checked": verify_determinism, "stable": True}
                if verify_determinism:
                    second = await _run_query(
                        query,
                        seeded=seeded,
                        parameters=profile.parameters,
                        ranking_time=normalized_ranking_time,
                        embedding_provider=embedding_provider,
                        hypothesis_enabled=profile.hypothesis_enabled,
                        lexical_enabled=profile.lexical_enabled,
                    )
                    stability = _stability_record(first, second)
                    if not stability["stable"]:
                        observation = replace(
                            observation,
                            hard_gate_failures=tuple(
                                dict.fromkeys(
                                    (
                                        *observation.hard_gate_failures,
                                        "nondeterministic_ranking",
                                    )
                                )
                            ),
                        )
                metrics = evaluate_retrieval_observation(query, observation)
                query_metrics.append(metrics)
                query_results.append(
                    {
                        "query_id": query.id,
                        "family_id": query.family_id,
                        "corpus_id": query.corpus_id,
                        "final_memory_keys": list(observation.final_memory_keys),
                        "candidate_memory_keys": {
                            lane: list(keys)
                            for lane, keys in observation.candidate_memory_keys.items()
                        },
                        "record_lanes": {
                            key: list(lanes)
                            for key, lanes in observation.record_lanes.items()
                        },
                        "ranked_records": list(first.ranked_records),
                        "trace": first.trace,
                        "metrics": metrics_to_record(metrics),
                        "stability": stability,
                    }
                )
            aggregate = aggregate_retrieval_metrics(query_metrics)
            profile_results.append(
                {
                    "profile": profile.to_record(),
                    "hard_gate_passed": all(
                        metric.hard_gate_passed for metric in query_metrics
                    ),
                    "aggregate": _aggregate_to_record(aggregate),
                    "queries": query_results,
                }
            )

        environment = {
            "git": _git_state(Path.cwd()),
            "database": _database_state(db),
            "embedding_identity": embedding_identity,
            "embedding_cache_fingerprint": embedding_cache_fingerprint,
            "ranking_time": normalized_ranking_time.isoformat(),
            "experiment_user_ids": list(registry.user_ids),
        }
        return _write_experiment_artifacts(
            experiment_id=run_id,
            stage=stage,
            split=split,
            formal=formal,
            benchmark=benchmark,
            profiles=profiles,
            selected_queries=selected_queries,
            profile_results=tuple(profile_results),
            environment=environment,
            artifacts_dir=Path(artifacts_dir),
        )
    finally:
        active_error = sys.exception()
        try:
            registry.cleanup()
        except Exception as cleanup_error:
            if active_error is None:
                raise
            active_error.add_note(
                f"experiment user cleanup also failed: {type(cleanup_error).__name__}"
            )


def _select_search_universe(
    benchmark: MemoryRetrievalBenchmark,
    split: ExperimentSplit,
) -> tuple[
    tuple[RetrievalBenchmarkQuery, ...],
    tuple[RetrievalBenchmarkCorpus, ...],
]:
    selected_queries = tuple(
        query for query in benchmark.queries if query.split == split
    )
    if not selected_queries:
        raise ValueError(f"benchmark contains no {split} queries")
    selected_corpus_ids = tuple(
        dict.fromkeys(query.corpus_id for query in selected_queries)
    )
    return selected_queries, tuple(
        benchmark.corpus_by_id[corpus_id] for corpus_id in selected_corpus_ids
    )


def build_stage_profiles(
    stage: int,
    *,
    base_profiles: Sequence[MemoryRetrievalExperimentProfile] = (),
) -> tuple[MemoryRetrievalExperimentProfile, ...]:
    baseline = MemoryRetrievalParameters()
    if stage == 0:
        _reject_unexpected_stage_bases(stage, base_profiles)
        return (
            MemoryRetrievalExperimentProfile("amadeus-baseline", baseline),
            MemoryRetrievalExperimentProfile(
                "akashic-inspired-reference",
                replace(
                    baseline,
                    vector_candidate_floor=15,
                    vector_candidate_multiplier=1,
                    lexical_rrf_weight=0.5,
                ),
                ("vector_candidate_floor", "vector_candidate_multiplier", "lexical_rrf_weight"),
            ),
        )
    if stage == 1:
        _reject_unexpected_stage_bases(stage, base_profiles)
        return tuple(
            MemoryRetrievalExperimentProfile(
                f"window-v{vector}-l{lexical}",
                replace(
                    baseline,
                    vector_candidate_floor=vector,
                    vector_candidate_multiplier=1,
                    lexical_candidate_floor=lexical,
                    lexical_candidate_multiplier=1,
                ),
                (
                    "vector_candidate_floor",
                    "vector_candidate_multiplier",
                    "lexical_candidate_floor",
                    "lexical_candidate_multiplier",
                ),
            )
            for vector in (15, 16, 32, 64)
            for lexical in (16, 30, 60)
        )
    if stage == 2:
        bases = _require_stage_bases(stage, base_profiles)
        return tuple(
            MemoryRetrievalExperimentProfile(
                f"{base.name}__fusion-w{weight:g}-k{rrf_k}",
                replace(
                    base.parameters,
                    lexical_rrf_weight=weight,
                    rrf_k=rrf_k,
                ),
                ("lexical_rrf_weight", "rrf_k"),
            )
            for base in bases
            for weight in (0.5, 0.75, 1.0, 1.25, 1.5)
            for rrf_k in (10, 30, 60, 90)
        )
    if stage == 3:
        bases = _require_stage_bases(stage, base_profiles)
        return tuple(
            MemoryRetrievalExperimentProfile(
                f"{base.name}__threshold-{threshold:.2f}",
                replace(base.parameters, semantic_threshold=threshold),
                ("semantic_threshold",),
            )
            for base in bases
            for threshold in (0.25, 0.30, 0.35, 0.40, 0.45)
        )
    if stage == 4:
        bases = _require_stage_bases(stage, base_profiles)
        return tuple(
            MemoryRetrievalExperimentProfile(
                f"{base.name}__hotness-baseline",
                base.parameters,
            )
            for base in bases
        )
    if stage == 5:
        bases = _require_stage_bases(stage, base_profiles)
        return (
            MemoryRetrievalExperimentProfile(
                "amadeus-baseline",
                MemoryRetrievalParameters(),
            ),
            *bases,
        )
    raise ValueError("stage must be between 0 and 5")


def _require_stage_bases(
    stage: int,
    base_profiles: Sequence[MemoryRetrievalExperimentProfile],
) -> tuple[MemoryRetrievalExperimentProfile, ...]:
    bases = tuple(base_profiles)
    if not bases:
        raise ValueError(f"Stage {stage} requires a frozen Stage {stage - 1} shortlist")
    if len(bases) > 2:
        raise ValueError("each stage shortlist may contain at most two profiles")
    names = [base.name for base in bases]
    if len(names) != len(set(names)):
        raise ValueError("stage shortlist profile names must be unique")
    return bases


def _require_finalists(
    profiles: Sequence[MemoryRetrievalExperimentProfile],
) -> tuple[MemoryRetrievalExperimentProfile, ...]:
    finalists = tuple(profiles)
    if not finalists or len(finalists) > 3:
        raise ValueError("finalist shortlist must contain one to three profiles")
    names = [profile.name for profile in finalists]
    if len(names) != len(set(names)):
        raise ValueError("finalist shortlist profile names must be unique")
    return finalists


def _reject_unexpected_stage_bases(
    stage: int,
    base_profiles: Sequence[MemoryRetrievalExperimentProfile],
) -> None:
    if base_profiles:
        raise ValueError(f"Stage {stage} does not accept base profiles")


async def _seed_search_universe(
    corpora: tuple[RetrievalBenchmarkCorpus, ...],
    *,
    registry: _ExperimentUserRegistry,
    embedding_provider: EmbeddingProvider,
    experiment_id: str,
) -> _SeededSearchUniverse:
    experiment_user_id = registry.reserve_user()
    experiment_store = PostgresMemoryStore(experiment_user_id, db=registry.db)
    other_memories = [
        memory
        for corpus in corpora
        for memory in corpus.memories
        if memory.owner == "other_user"
    ]
    other_store = (
        PostgresMemoryStore(registry.reserve_user(), db=registry.db)
        if other_memories
        else None
    )
    memory_id_by_key: dict[str, str] = {}
    memory_by_id: dict[str, RetrievalBenchmarkMemory] = {}
    corpus_id_by_key: dict[str, str] = {}
    for corpus in corpora:
        for memory in corpus.memories:
            store = experiment_store if memory.owner == "experiment" else other_store
            if store is None:  # pragma: no cover - guarded by other_memories
                raise RuntimeError("other-user store was not allocated")
            item_id = _benchmark_item_id(
                experiment_id,
                corpus_id=corpus.id,
                memory=memory,
            )
            embedding = await embedding_provider.embed(memory.summary)
            extra = {
                **memory.extra,
                "benchmark_memory_key": memory.key,
                "benchmark_corpus_id": corpus.id,
            }
            store.insert_item(
                item_id=item_id,
                memory_type=memory.memory_type,
                summary=memory.summary,
                content_hash=_content_hash(memory.summary, memory.memory_type),
                embedding=embedding,
                source_ref=_benchmark_source_ref(store.user_id, corpus.id, memory.key),
                happened_at=memory.happened_at,
                scope_channel=memory.scope_channel,
                scope_chat_id=memory.scope_chat_id,
                emotional_weight=memory.emotional_weight,
                extra=extra,
            )
            _freeze_seed_row(store, item_id=item_id, memory=memory)
            memory_id_by_key[memory.key] = item_id
            memory_by_id[item_id] = memory
            corpus_id_by_key[memory.key] = corpus.id
    return _SeededSearchUniverse(
        corpora=corpora,
        store=experiment_store,
        memory_id_by_key=memory_id_by_key,
        memory_by_id=memory_by_id,
        corpus_id_by_key=corpus_id_by_key,
    )


async def _run_query(
    query: RetrievalBenchmarkQuery,
    *,
    seeded: _SeededSearchUniverse,
    parameters: MemoryRetrievalParameters,
    ranking_time: datetime,
    embedding_provider: EmbeddingProvider,
    hypothesis_enabled: bool = True,
    lexical_enabled: bool = True,
) -> _QueryRun:
    snapshots: list[RetrievalCandidateSnapshot] = []
    retriever = MemoryRetriever(
        store=seeded.store,
        embedding_provider=embedding_provider,
        hypothesis_provider=_FixedHypothesisProvider(query),
        parameters=parameters,
        ranking_time=ranking_time,
        candidate_observer=snapshots.append,
        hypothesis_retrieval_enabled=hypothesis_enabled,
        lexical_retrieval_enabled=lexical_enabled,
    )
    memorizer = MemoryMemorizer(
        store=seeded.store,
        embedding_provider=embedding_provider,
    )
    engine = LongTermMemoryEngine(
        store=seeded.store,
        retriever=retriever,
        memorizer=memorizer,
        worker=PostResponseMemoryWorker(
            memorizer=memorizer,
            extractor=_NoopExtractor(),
        ),
    )
    result = await engine.recall(
        MemoryRecallRequest(
            text=query.raw_query,
            intent="answer",
            memory_types=query.memory_types,
            limit=8,
            time_start=_optional_datetime(query.time_start, field=f"{query.id}.time_start"),
            time_end=_optional_datetime(query.time_end, field=f"{query.id}.time_end"),
            scope=MemoryScope(
                channel=query.scope_channel,
                chat_id=query.scope_chat_id,
            ),
        )
    )
    scope_mode = str(result.trace.get("scope_mode") or "scoped")
    final_snapshot = next(
        (snapshot for snapshot in reversed(snapshots) if snapshot.scope_mode == scope_mode),
        None,
    )
    if final_snapshot is None:
        raise RuntimeError(f"{query.id}: candidate observer missed {scope_mode} attempt")
    key_by_id = seeded.memory_key_by_id
    candidate_memory_keys = _candidate_keys(
        query,
        snapshot=final_snapshot,
        key_by_id=key_by_id,
    )
    final_memory_keys = tuple(
        key_by_id.get(record.id, f"unknown:{record.id}") for record in result.records
    )
    record_lanes = {
        key_by_id.get(record.id, f"unknown:{record.id}"): tuple(
            str(lane) for lane in record.signals.get("lanes", [])
        )
        for record in result.records
    }
    hard_gate_failures = _hard_gate_failures(
        query,
        seeded=seeded,
        snapshots=tuple(snapshots),
        trace=result.trace,
    )
    ranked_records = tuple(
        {
            "rank": rank,
            "memory_key": key_by_id.get(record.id, f"unknown:{record.id}"),
            "runtime_id": record.id,
            "score": record.score,
            "signals": dict(record.signals),
        }
        for rank, record in enumerate(result.records, start=1)
    )
    return _QueryRun(
        observation=RetrievalObservation(
            query_id=query.id,
            final_memory_keys=final_memory_keys,
            candidate_memory_keys=candidate_memory_keys,
            record_lanes=record_lanes,
            hard_gate_failures=hard_gate_failures,
        ),
        trace=dict(result.trace),
        ranked_records=ranked_records,
        snapshots=tuple(snapshots),
    )


def _candidate_keys(
    query: RetrievalBenchmarkQuery,
    *,
    snapshot: RetrievalCandidateSnapshot,
    key_by_id: dict[str, str],
) -> dict[str, tuple[str, ...]]:
    lanes: dict[str, tuple[str, ...]] = {}
    used_labels: set[str] = set()
    for index, (query_text, ids) in enumerate(
        zip(snapshot.query_texts, snapshot.vector_groups, strict=True)
    ):
        if index == 0:
            label = "raw-vector"
        elif query.fixed_hypotheses.event and query_text == query.fixed_hypotheses.event and "event-vector" not in used_labels:
            label = "event-vector"
        elif query.fixed_hypotheses.general and query_text == query.fixed_hypotheses.general and "general-vector" not in used_labels:
            label = "general-vector"
        else:
            label = f"vector-{index}"
        used_labels.add(label)
        lanes[label] = tuple(key_by_id.get(item_id, f"unknown:{item_id}") for item_id in ids)
    lanes["lexical"] = tuple(
        key_by_id.get(item_id, f"unknown:{item_id}") for item_id in snapshot.lexical
    )
    union: list[str] = []
    seen: set[str] = set()
    for keys in lanes.values():
        for key in keys:
            if key not in seen:
                seen.add(key)
                union.append(key)
    lanes["union"] = tuple(union)
    return lanes


def _hard_gate_failures(
    query: RetrievalBenchmarkQuery,
    *,
    seeded: _SeededSearchUniverse,
    snapshots: tuple[RetrievalCandidateSnapshot, ...],
    trace: dict[str, Any],
) -> tuple[str, ...]:
    failures: list[str] = []
    lane_status = trace.get("lane_status")
    if isinstance(lane_status, dict):
        for lane, status in lane_status.items():
            if status in {"error", "degraded"}:
                failures.append(f"lane_{lane}_{status}")
    errors = trace.get("errors")
    if isinstance(errors, list) and errors:
        failures.append("retrieval_error")

    for snapshot in snapshots:
        candidate_ids = {
            *snapshot.lexical,
            *(item_id for group in snapshot.vector_groups for item_id in group),
        }
        for item_id in candidate_ids:
            memory = seeded.memory_by_id.get(item_id)
            if memory is None:
                failures.append("candidate_unknown_id")
                continue
            if memory.owner != "experiment":
                failures.append("user_isolation_candidate_leak")
            if memory.status != "active":
                failures.append("status_candidate_leak")
            if query.memory_types and memory.memory_type not in query.memory_types:
                failures.append("memory_type_candidate_leak")
            if not _passes_time_filter(memory, query):
                failures.append("time_candidate_leak")
            if snapshot.scope_mode == "scoped" and not _passes_scope_filter(memory, query):
                failures.append("scope_candidate_leak")
    return tuple(dict.fromkeys(failures))


def _passes_scope_filter(
    memory: RetrievalBenchmarkMemory,
    query: RetrievalBenchmarkQuery,
) -> bool:
    if query.scope_channel is not None and memory.scope_channel != query.scope_channel:
        return False
    if query.scope_chat_id is not None and memory.scope_chat_id != query.scope_chat_id:
        return False
    return True


def _passes_time_filter(
    memory: RetrievalBenchmarkMemory,
    query: RetrievalBenchmarkQuery,
) -> bool:
    if query.time_start is None and query.time_end is None:
        return True
    if memory.happened_at is None:
        return False
    happened_at = _aware_datetime_string(memory.happened_at, field="happened_at")
    time_start = _optional_datetime(query.time_start, field="time_start")
    time_end = _optional_datetime(query.time_end, field="time_end")
    if time_start is not None and happened_at < time_start:
        return False
    if time_end is not None and happened_at > time_end:
        return False
    return True


def _freeze_seed_row(
    store: PostgresMemoryStore,
    *,
    item_id: str,
    memory: RetrievalBenchmarkMemory,
) -> None:
    with store.db.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE memory_items
                SET updated_at = %s::timestamptz,
                    reinforcement = %s,
                    emotional_weight = %s,
                    status = %s,
                    embedding = CASE WHEN %s THEN NULL ELSE embedding END
                WHERE user_id = %s AND id = %s
                """,
                (
                    memory.updated_at,
                    memory.reinforcement,
                    memory.emotional_weight,
                    memory.status,
                    memory.embedding_mode == "null",
                    store.user_id,
                    item_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"seeded memory {item_id!r} was not found")
        conn.commit()


class _ExperimentUserRegistry:
    def __init__(self, db: PostgresDatabase, *, experiment_id: str) -> None:
        self.db = db
        self.experiment_id = experiment_id
        self._user_ids: list[int] = []

    @property
    def user_ids(self) -> tuple[int, ...]:
        return tuple(self._user_ids)

    def reserve_user(self) -> int:
        for _attempt in range(100):
            user_id = 1_500_000_000 + secrets.randbelow(500_000_000)
            with self.db.connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO users (id, metadata, updated_at)
                        VALUES (%s, %s, now())
                        ON CONFLICT (id) DO NOTHING
                        RETURNING id
                        """,
                        (
                            user_id,
                            Jsonb(
                                {
                                    "memory_retrieval_experiment_id": self.experiment_id
                                }
                            ),
                        ),
                    )
                    reserved = cursor.fetchone()
                conn.commit()
            if reserved is not None:
                self._user_ids.append(user_id)
                return user_id
        raise RuntimeError("failed to reserve an isolated PostgreSQL experiment user")

    def cleanup(self) -> None:
        if not self._user_ids:
            return
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM users
                    WHERE id = ANY(%s)
                      AND metadata->>'memory_retrieval_experiment_id' = %s
                    """,
                    (list(self._user_ids), self.experiment_id),
                )
            conn.commit()


@dataclass(frozen=True)
class _FixedHypothesisProvider:
    query: RetrievalBenchmarkQuery

    async def generate(self, query: str, *, style: str) -> str:
        del query
        if style == "event":
            return self.query.fixed_hypotheses.event
        if style == "general":
            return self.query.fixed_hypotheses.general
        raise ValueError(f"unsupported hypothesis style: {style}")


@dataclass(frozen=True)
class _NoopExtractor:
    async def extract(
        self,
        *,
        session: SessionRef,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        del session, messages
        return []


def _validate_run_request(
    benchmark: MemoryRetrievalBenchmark,
    *,
    profiles: Sequence[MemoryRetrievalExperimentProfile],
    split: ExperimentSplit,
    formal: bool,
    unlock_holdout: bool,
    embedding_identity: str,
    embedding_cache_fingerprint: str | None,
) -> None:
    if split not in {"development", "holdout"}:
        raise ValueError("split must be 'development' or 'holdout'")
    if not profiles:
        raise ValueError("at least one retrieval profile is required")
    profile_names = [profile.name for profile in profiles]
    if any(not name.strip() for name in profile_names):
        raise ValueError("profile names must not be empty")
    if len(profile_names) != len(set(profile_names)):
        raise ValueError("profile names must be unique")
    if not embedding_identity.strip():
        raise ValueError("embedding_identity is required")
    if split == "holdout" and not unlock_holdout:
        raise ValueError("holdout requires explicit unlock_holdout=True")
    if split == "development" and unlock_holdout:
        raise ValueError("unlock_holdout is only valid for holdout experiments")
    if formal:
        benchmark.require_approved()
        validate_v1_distribution(benchmark)
        if not embedding_cache_fingerprint:
            raise ValueError("formal experiments require a frozen embedding cache")


def _stability_record(first: _QueryRun, second: _QueryRun) -> dict[str, Any]:
    first_observation = first.observation
    second_observation = second.observation
    stable = (
        first_observation.final_memory_keys == second_observation.final_memory_keys
        and first_observation.candidate_memory_keys
        == second_observation.candidate_memory_keys
        and first.trace.get("lane_status") == second.trace.get("lane_status")
    )
    return {
        "checked": True,
        "stable": stable,
        "second_final_memory_keys": list(second_observation.final_memory_keys),
        "second_candidate_memory_keys": {
            lane: list(keys)
            for lane, keys in second_observation.candidate_memory_keys.items()
        },
    }


def _aggregate_to_record(report: RetrievalAggregateReport) -> dict[str, Any]:
    return {
        "overall": {
            "family_count": report.overall.family_count,
            "variant_count": report.overall.variant_count,
            "values": dict(report.overall.values),
        },
        "strata": {
            name: {
                "family_count": summary.family_count,
                "variant_count": summary.variant_count,
                "values": dict(summary.values),
            }
            for name, summary in report.strata.items()
        },
    }


def _render_judging_pool_review(
    entries: tuple[dict[str, Any], ...],
    *,
    benchmark: MemoryRetrievalBenchmark,
) -> str:
    lines = [
        "# 长期记忆检索 unknown judging pool",
        "",
        f"- 数据集：`{benchmark.version}`",
        f"- 数据集哈希：`{benchmark.content_hash}`",
        f"- 待判定 query-memory 对：`{len(entries)}`",
        "",
        "这些记忆进入过至少一个 profile 的 top-8，但尚无人工 qrel。",
        "请逐项标注 0～3 relevance、dangerous 与理由；完成前不得用于正式参数比较。",
        "",
    ]
    for index, entry in enumerate(entries, start=1):
        profile_ranks = ", ".join(
            f"{name}=#{rank}"
            for name, rank in sorted(entry["profile_ranks"].items())
        )
        lines.extend(
            [
                f"## {index}. {entry['query_id']} × {entry['memory_key']}",
                "",
                f"- Query：`{entry['raw_query']}`",
                f"- Memory：{entry['memory_summary']}",
                f"- 来源 corpus：`{entry['memory_corpus_id']}`",
                f"- 命中排名：{profile_ranks}",
                "- [ ] relevance：`0 / 1 / 2 / 3`",
                "- [ ] dangerous：`true / false`",
                "- [ ] rationale 已填写",
                "",
            ]
        )
    return "\n".join(lines)


def _write_experiment_artifacts(
    *,
    experiment_id: str,
    stage: int | None,
    split: ExperimentSplit,
    formal: bool,
    benchmark: MemoryRetrievalBenchmark,
    profiles: Sequence[MemoryRetrievalExperimentProfile],
    selected_queries: tuple[RetrievalBenchmarkQuery, ...],
    profile_results: tuple[dict[str, Any], ...],
    environment: dict[str, Any],
    artifacts_dir: Path,
) -> MemoryRetrievalExperimentReport:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(character if character.isalnum() or character in "-_" else "-" for character in experiment_id)
    results_path = artifacts_dir / f"{safe_id}-memory-retrieval-results.json"
    csv_path = artifacts_dir / f"{safe_id}-memory-retrieval-results.csv"
    summary_path = artifacts_dir / f"{safe_id}-memory-retrieval-summary.md"
    payload = {
        "experiment_id": experiment_id,
        "stage": stage,
        "split": split,
        "formal": formal,
        "dataset_version": benchmark.version,
        "dataset_hash": benchmark.content_hash,
        "environment": environment,
        "profiles": [profile.to_record() for profile in profiles],
        "results": list(profile_results),
    }
    results_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_csv(csv_path, profile_results)
    summary_path.write_text(
        _render_summary_markdown(
            experiment_id=experiment_id,
            stage=stage,
            split=split,
            formal=formal,
            benchmark=benchmark,
            profile_results=profile_results,
        ),
        encoding="utf-8",
    )
    return MemoryRetrievalExperimentReport(
        experiment_id=experiment_id,
        stage=stage,
        split=split,
        formal=formal,
        dataset_hash=benchmark.content_hash,
        profile_count=len(profiles),
        query_count=len(selected_queries),
        results_path=results_path,
        csv_path=csv_path,
        summary_path=summary_path,
        profile_results=profile_results,
    )


def _write_csv(path: Path, profile_results: tuple[dict[str, Any], ...]) -> None:
    fieldnames = [
        "profile",
        "profile_fingerprint",
        "query_id",
        "family_id",
        "hard_gate_passed",
        "recall_at_8",
        "precision_at_8",
        "returned_precision_at_8",
        "mrr_at_8",
        "ndcg_at_8",
        "all_required_recalled_at_8",
        "strict_lexical_only_recall_at_8",
        "dangerous_hit_at_8",
        "no_answer_false_positive",
        "hotness_pair_accuracy",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for profile_result in profile_results:
            profile = profile_result["profile"]
            for query_result in profile_result["queries"]:
                metrics = query_result["metrics"]
                writer.writerow(
                    {
                        "profile": profile["name"],
                        "profile_fingerprint": profile["fingerprint"],
                        "query_id": query_result["query_id"],
                        "family_id": query_result["family_id"],
                        **{field: metrics.get(field) for field in fieldnames[4:]},
                    }
                )


def _render_summary_markdown(
    *,
    experiment_id: str,
    stage: int | None,
    split: ExperimentSplit,
    formal: bool,
    benchmark: MemoryRetrievalBenchmark,
    profile_results: tuple[dict[str, Any], ...],
) -> str:
    lines = [
        "# 长期记忆检索参数实验",
        "",
        f"- 实验：`{experiment_id}`",
        f"- Stage：`{stage if stage is not None else 'unspecified'}`",
        f"- 数据集：`{benchmark.version}`",
        f"- 数据集哈希：`{benchmark.content_hash}`",
        f"- split：`{split}`",
        f"- 正式实验：`{str(formal).lower()}`",
        "- 延迟指标：未采集（本任务只比较召回质量与可靠性）",
        "",
        "| Profile | 硬门 | Recall@8 | Precision@8 | MRR@8 | nDCG@8 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for profile_result in profile_results:
        profile = profile_result["profile"]
        values = profile_result["aggregate"]["overall"]["values"]
        lines.append(
            "| {name} | {gate} | {recall} | {precision} | {mrr} | {ndcg} |".format(
                name=profile["name"],
                gate="通过" if profile_result["hard_gate_passed"] else "失败",
                recall=_format_metric(values.get("recall_at_8")),
                precision=_format_metric(values.get("precision_at_8")),
                mrr=_format_metric(values.get("mrr_at_8")),
                ndcg=_format_metric(values.get("ndcg_at_8")),
            )
        )
    lines.extend(("", "正式参数选择必须另行应用预注册的分层决策规则。", ""))
    return "\n".join(lines)


def _format_metric(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"


def _database_state(db: PostgresDatabase) -> dict[str, Any]:
    with db.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SHOW server_version")
            server_version = str(cursor.fetchone()["server_version"])
            cursor.execute(
                """
                SELECT extname, extversion
                FROM pg_extension
                WHERE extname = ANY(%s)
                ORDER BY extname
                """,
                (["vector", "pg_trgm"],),
            )
            extensions = {
                str(row["extname"]): str(row["extversion"])
                for row in cursor.fetchall()
            }
            cursor.execute("SELECT version_num FROM alembic_version")
            migration_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'memory_items'
                ORDER BY indexname
                """
            )
            indexes = [str(row["indexname"]) for row in cursor.fetchall()]
    return {
        "server_version": server_version,
        "extensions": extensions,
        "migration_heads": [str(row["version_num"]) for row in migration_rows],
        "memory_indexes": indexes,
    }


def _git_state(workspace: Path) -> dict[str, Any]:
    commit = _git_output(workspace, "rev-parse", "HEAD")
    status = _git_output(workspace, "status", "--porcelain=v1", "--untracked-files=all")
    diff = _git_output(workspace, "diff", "--binary", "HEAD")
    untracked = _git_output(
        workspace,
        "ls-files",
        "--others",
        "--exclude-standard",
    ).splitlines()
    digest = hashlib.sha256()
    digest.update(status.encode("utf-8"))
    digest.update(diff.encode("utf-8"))
    for relative in sorted(filter(None, untracked)):
        path = workspace / relative
        if path.is_file():
            digest.update(relative.encode("utf-8"))
            digest.update(path.read_bytes())
    return {
        "commit": commit,
        "dirty": bool(status.strip()),
        "workspace_fingerprint": digest.hexdigest(),
    }


def _git_output(workspace: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _benchmark_item_id(
    experiment_id: str,
    *,
    corpus_id: str,
    memory: RetrievalBenchmarkMemory,
) -> str:
    stable_digest = hashlib.sha256(
        f"{corpus_id}:{memory.owner}:{memory.key}".encode()
    ).hexdigest()[:24]
    run_digest = hashlib.sha256(experiment_id.encode()).hexdigest()[:12]
    return f"eval_{stable_digest}_{run_digest}"


def _benchmark_source_ref(user_id: int, corpus_id: str, memory_key: str) -> str:
    digest = hashlib.blake2b(f"{corpus_id}:{memory_key}".encode(), digest_size=4).hexdigest()
    return json.dumps([f"session:{user_id}:1:{int(digest, 16)}"]) + f"#benchmark:{memory_key}"


def _new_experiment_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"memory-retrieval-{timestamp}-{secrets.token_hex(3)}"


def _aware_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return value.astimezone(UTC)


def _aware_datetime_string(value: str, *, field: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO datetime") from exc
    return _aware_datetime(parsed, field=field)


def _optional_datetime(value: str | None, *, field: str) -> datetime | None:
    return None if value is None else _aware_datetime_string(value, field=field)
