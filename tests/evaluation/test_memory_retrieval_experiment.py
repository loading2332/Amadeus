from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from amadeus.evaluation.memory_retrieval_benchmark import (
    FixedRetrievalHypotheses,
    MemoryRetrievalBenchmark,
    RetrievalBenchmarkCorpus,
    RetrievalBenchmarkMemory,
    RetrievalBenchmarkQuery,
    RetrievalJudgment,
)
from amadeus.evaluation.memory_retrieval_experiment import (
    MemoryRetrievalExperimentProfile,
    build_stage_profiles,
    collect_memory_retrieval_judging_pool,
    freeze_profile_shortlist,
    load_frozen_profile_shortlist,
    rebase_finalist_shortlist_for_holdout_qrels,
    run_memory_retrieval_experiment,
)
from amadeus.memory.retrieval_parameters import MemoryRetrievalParameters
from tests.db.pgvector_helpers import pad_embedding
from tests.db.postgres_helpers import clean_postgres


class DeterministicEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        del text
        return pad_embedding([1.0, 0.0, 0.0])


def _benchmark() -> MemoryRetrievalBenchmark:
    corpus = RetrievalBenchmarkCorpus(
        id="lexical-rescue",
        memories=(
            RetrievalBenchmarkMemory(
                key="lexical-target",
                summary="部署标识 ZXQ-4917 必须写入发布记录。",
                memory_type="procedure",
                updated_at="2026-07-01T00:00:00+00:00",
                embedding_mode="null",
            ),
            RetrievalBenchmarkMemory(
                key="vector-decoy",
                summary="普通部署流程不包含目标标识。",
                memory_type="procedure",
                updated_at="2026-07-01T00:00:00+00:00",
            ),
            RetrievalBenchmarkMemory(
                key="other-user-danger",
                summary="另一个用户的 ZXQ-4917 私有部署记录。",
                memory_type="procedure",
                updated_at="2026-07-01T00:00:00+00:00",
                owner="other_user",
            ),
        ),
    )
    query = RetrievalBenchmarkQuery(
        id="lexical-rescue-query",
        family_id="lexical-rescue-family",
        corpus_id=corpus.id,
        split="development",
        review_status="draft",
        review_batch=1,
        product_scenario="project_assistant",
        memory_capability="information_extraction",
        language="mixed",
        raw_query="ZXQ-4917",
        fixed_hypotheses=FixedRetrievalHypotheses(),
        strata=("mixed", "lexical-only", "identifier"),
        judgments=(
            RetrievalJudgment(
                "lexical-target",
                3,
                False,
                "exact identifier answer",
                expected_lanes=("lexical",),
            ),
            RetrievalJudgment("vector-decoy", 0, False, "irrelevant vector decoy"),
            RetrievalJudgment(
                "shared-pool-decoy",
                0,
                False,
                "known distractor from another corpus in the shared split pool",
            ),
            RetrievalJudgment(
                "other-user-danger",
                0,
                True,
                "belongs to another user",
                danger_reasons=("cross_user",),
            ),
        ),
        required_memory_keys=("lexical-target",),
        rationale="prove lexical rescue and user isolation",
    )
    background_query = RetrievalBenchmarkQuery(
        id="shared-background-query",
        family_id="shared-background-family",
        corpus_id="shared-background",
        split="development",
        review_status="draft",
        review_batch=1,
        product_scenario="project_assistant",
        memory_capability="information_extraction",
        language="mixed",
        raw_query="背景讨论",
        fixed_hypotheses=FixedRetrievalHypotheses(),
        strata=("mixed", "shared-search-universe"),
        judgments=(
            RetrievalJudgment(
                "shared-pool-decoy",
                3,
                False,
                "direct answer for the background family",
            ),
            RetrievalJudgment("lexical-target", 0, False, "other family target"),
            RetrievalJudgment("vector-decoy", 0, False, "other family decoy"),
            RetrievalJudgment(
                "other-user-danger",
                0,
                True,
                "belongs to another user",
                danger_reasons=("cross_user",),
            ),
        ),
        required_memory_keys=("shared-pool-decoy",),
        rationale="make the second corpus part of the development search universe",
    )
    return MemoryRetrievalBenchmark(
        version="memory-retrieval-test",
        review_status="draft",
        corpora=(
            corpus,
            RetrievalBenchmarkCorpus(
                id="shared-background",
                memories=(
                    RetrievalBenchmarkMemory(
                        key="shared-pool-decoy",
                        summary="ZXQ-4917 的背景讨论没有发布要求。",
                        memory_type="procedure",
                        updated_at="2026-07-01T00:00:00+00:00",
                    ),
                ),
            ),
        ),
        queries=(query, background_query),
    )


def test_real_postgres_runner_isolated_public_recall_and_artifacts(
    tmp_path: Path,
) -> None:
    db = clean_postgres()
    try:
        with db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (id, metadata, updated_at)
                    VALUES (42, '{}'::jsonb, now())
                    ON CONFLICT (id) DO NOTHING
                    """
                )
            conn.commit()

        report = run_memory_retrieval_experiment(
            _benchmark(),
            profiles=(
                MemoryRetrievalExperimentProfile(
                    "baseline",
                    MemoryRetrievalParameters(),
                ),
            ),
            split="development",
            ranking_time=datetime(2026, 7, 12, tzinfo=UTC),
            db=db,
            embedding_provider=DeterministicEmbeddingProvider(),
            embedding_identity="fake:test-1024",
            artifacts_dir=tmp_path,
            formal=False,
            experiment_id="runner-integration",
        )

        assert report.profile_count == 1
        assert report.query_count == 2
        assert report.results_path.exists()
        assert report.csv_path.exists()
        assert report.summary_path.exists()
        query_result = report.profile_results[0]["queries"][0]
        assert "lexical-target" in query_result["final_memory_keys"]
        assert "shared-pool-decoy" in query_result["candidate_memory_keys"]["union"]
        assert "other-user-danger" not in query_result["candidate_memory_keys"]["union"]
        assert query_result["metrics"]["recall_at_8"] == 1.0
        assert query_result["metrics"]["strict_lexical_only_recall_at_8"] == 1.0
        assert query_result["metrics"]["hard_gate_passed"] is True
        assert query_result["stability"]["stable"] is True

        renamed_report = run_memory_retrieval_experiment(
            _benchmark(),
            profiles=(
                MemoryRetrievalExperimentProfile(
                    "baseline",
                    MemoryRetrievalParameters(),
                ),
            ),
            split="development",
            ranking_time=datetime(2026, 7, 12, tzinfo=UTC),
            db=db,
            embedding_provider=DeterministicEmbeddingProvider(),
            embedding_identity="fake:test-1024",
            artifacts_dir=tmp_path / "renamed",
            formal=False,
            experiment_id="runner-integration-renamed",
        )
        first_queries = report.profile_results[0]["queries"]
        renamed_queries = renamed_report.profile_results[0]["queries"]
        assert [item["final_memory_keys"] for item in renamed_queries] == [
            item["final_memory_keys"] for item in first_queries
        ]
        assert [item["candidate_memory_keys"] for item in renamed_queries] == [
            item["candidate_memory_keys"] for item in first_queries
        ]

        payload = json.loads(report.results_path.read_text(encoding="utf-8"))
        experiment_user_ids = payload["environment"]["experiment_user_ids"]
        assert len(experiment_user_ids) == 2
        assert "elapsed_ms" not in report.results_path.read_text(encoding="utf-8")
        assert "p95" not in report.results_path.read_text(encoding="utf-8").lower()
        with db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM users WHERE id = ANY(%s)",
                    (experiment_user_ids,),
                )
                assert cursor.fetchall() == []
                cursor.execute("SELECT id FROM users WHERE id = 42")
                assert cursor.fetchone() is not None
    finally:
        db.close()


def test_formal_runner_rejects_draft_before_seeding(tmp_path: Path) -> None:
    db = clean_postgres()
    try:
        with pytest.raises(ValueError, match="approved dataset"):
            run_memory_retrieval_experiment(
                _benchmark(),
                profiles=(
                    MemoryRetrievalExperimentProfile(
                        "baseline",
                        MemoryRetrievalParameters(),
                    ),
                ),
                split="development",
                ranking_time=datetime(2026, 7, 12, tzinfo=UTC),
                db=db,
                embedding_provider=DeterministicEmbeddingProvider(),
                embedding_identity="fake:test-1024",
                embedding_cache_fingerprint="frozen-cache",
                artifacts_dir=tmp_path,
                formal=True,
            )
    finally:
        db.close()


def test_judging_pool_collects_cross_corpus_unknown_without_grading_it(
    tmp_path: Path,
) -> None:
    benchmark = _benchmark()
    first_query = benchmark.queries[0]
    benchmark = replace(
        benchmark,
        review_status="approved",
        queries=(
            replace(
                first_query,
                review_status="approved",
                judgments=tuple(
                    judgment
                    for judgment in first_query.judgments
                    if judgment.memory_key != "shared-pool-decoy"
                ),
            ),
            replace(benchmark.queries[1], review_status="approved"),
        ),
    )
    db = clean_postgres()
    try:
        report = collect_memory_retrieval_judging_pool(
            benchmark,
            profiles=(
                MemoryRetrievalExperimentProfile(
                    "baseline",
                    MemoryRetrievalParameters(),
                ),
            ),
            split="development",
            ranking_time=datetime(2026, 7, 12, tzinfo=UTC),
            db=db,
            embedding_provider=DeterministicEmbeddingProvider(),
            embedding_identity="fake:test-1024",
            embedding_cache_fingerprint="frozen-cache",
            artifacts_dir=tmp_path,
            experiment_id="judging-pool-integration",
        )

        payload = json.loads(report.json_path.read_text(encoding="utf-8"))
        assert report.unknown_pair_count == 1
        assert payload["unknown_pairs"][0]["memory_key"] == "shared-pool-decoy"
        assert "relevance：`0 / 1 / 2 / 3`" in report.review_path.read_text(
            encoding="utf-8"
        )
    finally:
        db.close()


def test_holdout_judging_pool_requires_explicit_unlock(tmp_path: Path) -> None:
    benchmark = _benchmark()
    benchmark = replace(
        benchmark,
        review_status="approved",
        queries=tuple(
            replace(query, split="holdout", review_status="approved")
            for query in benchmark.queries
        ),
    )
    db = clean_postgres()
    try:
        with pytest.raises(ValueError, match="explicit unlock"):
            collect_memory_retrieval_judging_pool(
                benchmark,
                profiles=(
                    MemoryRetrievalExperimentProfile(
                        "finalist",
                        MemoryRetrievalParameters(),
                    ),
                ),
                split="holdout",
                ranking_time=datetime(2026, 7, 12, tzinfo=UTC),
                db=db,
                embedding_provider=DeterministicEmbeddingProvider(),
                embedding_identity="fake:test-1024",
                embedding_cache_fingerprint="frozen-cache",
                artifacts_dir=tmp_path,
                experiment_id="locked-holdout-pool",
            )

        report = collect_memory_retrieval_judging_pool(
            benchmark,
            profiles=(
                MemoryRetrievalExperimentProfile(
                    "finalist",
                    MemoryRetrievalParameters(),
                ),
            ),
            split="holdout",
            ranking_time=datetime(2026, 7, 12, tzinfo=UTC),
            db=db,
            embedding_provider=DeterministicEmbeddingProvider(),
            embedding_identity="fake:test-1024",
            embedding_cache_fingerprint="frozen-cache",
            artifacts_dir=tmp_path,
            experiment_id="unlocked-holdout-pool",
            unlock_holdout=True,
        )

        assert report.split == "holdout"
        payload = json.loads(report.json_path.read_text(encoding="utf-8"))
        assert payload["split"] == "holdout"
    finally:
        db.close()


def test_stage_profiles_match_preregistered_search_space() -> None:
    assert len(build_stage_profiles(0)) == 2
    assert len(build_stage_profiles(1)) == 12
    base = (
        MemoryRetrievalExperimentProfile(
            "stage-1-winner",
            MemoryRetrievalParameters(
                vector_candidate_floor=64,
                vector_candidate_multiplier=1,
                lexical_candidate_floor=60,
                lexical_candidate_multiplier=1,
            ),
        ),
    )
    with pytest.raises(ValueError, match="frozen Stage 1 shortlist"):
        build_stage_profiles(2)
    assert len(build_stage_profiles(2, base_profiles=base)) == 20
    assert len(build_stage_profiles(3, base_profiles=base)) == 5
    stage_four = build_stage_profiles(4, base_profiles=base)
    assert len(stage_four) == 1
    assert stage_four[0].name == "stage-1-winner__hotness-baseline"
    assert stage_four[0].parameters == base[0].parameters
    stage_five = build_stage_profiles(5, base_profiles=stage_four)
    assert [profile.name for profile in stage_five] == [
        "amadeus-baseline",
        "stage-1-winner__hotness-baseline",
    ]
    assert stage_five[0].parameters == MemoryRetrievalParameters()
    inherited = build_stage_profiles(2, base_profiles=base)[0].parameters
    assert inherited.vector_candidate_floor == 64
    assert inherited.lexical_candidate_floor == 60
    with pytest.raises(ValueError, match="frozen Stage 4 shortlist"):
        build_stage_profiles(5)
    with pytest.raises(ValueError, match="between 0 and 5"):
        build_stage_profiles(6)


def test_frozen_shortlist_round_trips_and_rejects_dataset_drift(
    tmp_path: Path,
) -> None:
    profile = MemoryRetrievalExperimentProfile(
        "window-v64-l60",
        MemoryRetrievalParameters(
            vector_candidate_floor=64,
            vector_candidate_multiplier=1,
            lexical_candidate_floor=60,
            lexical_candidate_multiplier=1,
        ),
        (
            "vector_candidate_floor",
            "vector_candidate_multiplier",
            "lexical_candidate_floor",
            "lexical_candidate_multiplier",
        ),
    )
    results_path = tmp_path / "stage-1-results.json"
    results_path.write_text(
        json.dumps(
            {
                "dataset_hash": "dataset-v1",
                "stage": 1,
                "profiles": [profile.to_record()],
                "results": [
                    {
                        "profile": profile.to_record(),
                        "hard_gate_passed": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    shortlist_path = freeze_profile_shortlist(
        results_path,
        profile_names=(profile.name,),
        source_stage=1,
        output_path=tmp_path / "stage-1-shortlist.json",
    )
    loaded = load_frozen_profile_shortlist(
        shortlist_path,
        expected_source_stage=1,
        dataset_hash="dataset-v1",
    )

    assert loaded == (profile,)
    with pytest.raises(ValueError, match="dataset_hash"):
        load_frozen_profile_shortlist(
            shortlist_path,
            expected_source_stage=1,
            dataset_hash="changed-dataset",
        )


def test_finalist_shortlist_rebases_only_for_approved_holdout_qrels(
    tmp_path: Path,
) -> None:
    profiles = (
        MemoryRetrievalExperimentProfile(
            "amadeus-baseline",
            MemoryRetrievalParameters(),
        ),
        MemoryRetrievalExperimentProfile(
            "conservative",
            replace(MemoryRetrievalParameters(), vector_candidate_floor=15),
        ),
        MemoryRetrievalExperimentProfile(
            "exploratory",
            replace(MemoryRetrievalParameters(), lexical_rrf_weight=0.75),
        ),
    )
    draft = _benchmark()
    approved = replace(
        draft,
        review_status="approved",
        queries=tuple(
            replace(query, split="holdout", review_status="approved")
            for query in draft.queries
        ),
    )
    approved_query = approved.queries[0]
    added_judgment = approved_query.judgment_by_key["vector-decoy"]
    source_benchmark = replace(
        approved,
        queries=(
            replace(
                approved_query,
                judgments=tuple(
                    judgment
                    for judgment in approved_query.judgments
                    if judgment.memory_key != added_judgment.memory_key
                ),
            ),
            *approved.queries[1:],
        ),
    )
    benchmark = replace(
        source_benchmark,
        queries=(
            replace(
                source_benchmark.queries[0],
                judgments=(*source_benchmark.queries[0].judgments, added_judgment),
            ),
            *source_benchmark.queries[1:],
        ),
    )
    results_path = tmp_path / "stage-5-results.json"
    results_path.write_text(
        json.dumps(
            {
                "dataset_hash": source_benchmark.content_hash,
                "stage": 5,
                "profiles": [profile.to_record() for profile in profiles],
                "results": [
                    {
                        "profile": profile.to_record(),
                        "hard_gate_passed": True,
                    }
                    for profile in profiles
                ],
            }
        ),
        encoding="utf-8",
    )
    shortlist_path = freeze_profile_shortlist(
        results_path,
        profile_names=tuple(profile.name for profile in profiles),
        source_stage=5,
        output_path=tmp_path / "stage-5-finalists.json",
    )
    query = benchmark.queries[0]
    overlay_path = tmp_path / "holdout-qrels.yaml"
    overlay_path.write_text(
        yaml.safe_dump(
            {
                "overlay_id": "holdout-finalists-1",
                "review_status": "approved",
                "split": "holdout",
                "source_dataset_hash": source_benchmark.content_hash,
                "judgments": [
                    {
                        "query_id": query.id,
                        "memory_key": added_judgment.memory_key,
                        "relevance": added_judgment.relevance,
                        "dangerous": added_judgment.dangerous,
                        "danger_reasons": list(added_judgment.danger_reasons),
                        "rationale": added_judgment.rationale,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    rebased_path = rebase_finalist_shortlist_for_holdout_qrels(
        shortlist_path,
        source_benchmark=source_benchmark,
        benchmark=benchmark,
        approved_overlay_path=overlay_path,
        output_path=tmp_path / "stage-5-finalists-rebased.json",
    )
    loaded = load_frozen_profile_shortlist(
        rebased_path,
        expected_source_stage=5,
        dataset_hash=benchmark.content_hash,
    )

    assert loaded == profiles
    payload = json.loads(rebased_path.read_text(encoding="utf-8"))
    assert payload["selection_dataset_hash"] == source_benchmark.content_hash
    assert payload["holdout_adjudication"]["overlay_id"] == "holdout-finalists-1"

    changed_corpus = replace(
        benchmark.corpora[0],
        memories=(
            replace(benchmark.corpora[0].memories[0], summary="drifted summary"),
            *benchmark.corpora[0].memories[1:],
        ),
    )
    with pytest.raises(ValueError, match="only add approved qrels"):
        rebase_finalist_shortlist_for_holdout_qrels(
            shortlist_path,
            source_benchmark=source_benchmark,
            benchmark=replace(
                benchmark,
                corpora=(changed_corpus, *benchmark.corpora[1:]),
            ),
            approved_overlay_path=overlay_path,
            output_path=tmp_path / "changed-corpus.json",
        )

    extra_judgment = RetrievalJudgment(
        "unexpected-extra",
        0,
        False,
        "not present in the approved overlay",
    )
    with pytest.raises(ValueError, match="only add approved qrels"):
        rebase_finalist_shortlist_for_holdout_qrels(
            shortlist_path,
            source_benchmark=source_benchmark,
            benchmark=replace(
                benchmark,
                queries=(
                    replace(
                        benchmark.queries[0],
                        judgments=(
                            *benchmark.queries[0].judgments,
                            extra_judgment,
                        ),
                    ),
                    *benchmark.queries[1:],
                ),
            ),
            approved_overlay_path=overlay_path,
            output_path=tmp_path / "extra-qrel.json",
        )

    rejected_overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8"))
    rejected_overlay["split"] = "development"
    overlay_path.write_text(
        yaml.safe_dump(rejected_overlay, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="holdout-only"):
        rebase_finalist_shortlist_for_holdout_qrels(
            shortlist_path,
            source_benchmark=source_benchmark,
            benchmark=benchmark,
            approved_overlay_path=overlay_path,
            output_path=tmp_path / "rejected.json",
        )
