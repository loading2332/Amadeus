from __future__ import annotations

from collections import Counter
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
    load_memory_retrieval_benchmark,
    validate_v1_distribution,
)

_VALID_BENCHMARK = """
version: memory-retrieval-v1
review_status: draft
corpora:
  - id: preference-update
    memories:
      - key: current
        summary: 用户目前需要无麸质餐食。
        memory_type: preference
        updated_at: "2026-07-01T08:00:00+08:00"
        reinforcement: 3
        emotional_weight: 2
      - key: obsolete
        summary: 用户以前经常选择普通披萨。
        memory_type: preference
        updated_at: "2025-08-01T08:00:00+08:00"
        status: superseded
queries:
  - id: dinner-now-zh
    family_id: dinner-now
    corpus_id: preference-update
    split: development
    review_status: draft
    review_batch: 1
    product_scenario: personal_assistant
    memory_capability: knowledge_update
    language: zh
    raw_query: 晚餐给我推荐什么？
    fixed_hypotheses:
      event: 用户更新过饮食限制。
      general: 用户当前的饮食偏好。
    strata: [zh, both-lanes, preference, knowledge-update]
    expected_abstention: false
    required_memory_keys: [current]
    judgments:
      - memory_key: current
        relevance: 3
        dangerous: false
        expected_lanes: [vector, lexical]
        rationale: 当前有效且直接约束推荐。
      - memory_key: obsolete
        relevance: 1
        dangerous: true
        danger_reasons: [superseded]
        rationale: 主题相关但已经失效。
    rationale: 验证更新后的偏好必须覆盖旧偏好。
""".strip()


def _write(tmp_path: Path, content: str = _VALID_BENCHMARK) -> Path:
    path = tmp_path / "benchmark.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_memory_retrieval_benchmark_parses_typed_contract(tmp_path: Path) -> None:
    benchmark = load_memory_retrieval_benchmark(
        _write(tmp_path),
        enforce_v1_distribution=False,
    )

    assert benchmark.version == "memory-retrieval-v1"
    assert benchmark.review_status == "draft"
    assert benchmark.family_ids == ("dinner-now",)
    assert benchmark.review_batches() == {1: ("dinner-now",)}
    assert len(benchmark.content_hash) == 64
    query = benchmark.queries[0]
    assert query.relevant_memory_keys == {"current"}
    assert query.dangerous_memory_keys == {"obsolete"}
    assert query.judgment_by_key["current"].expected_lanes == (
        "vector",
        "lexical",
    )


def test_yaml_null_embedding_mode_means_lexical_only(tmp_path: Path) -> None:
    content = _VALID_BENCHMARK.replace(
        "updated_at: \"2026-07-01T08:00:00+08:00\"",
        'updated_at: "2026-07-01T08:00:00+08:00"\n        embedding_mode: null',
        1,
    )

    benchmark = load_memory_retrieval_benchmark(
        _write(tmp_path, content),
        enforce_v1_distribution=False,
    )

    assert benchmark.corpora[0].memories[0].embedding_mode == "null"


def test_query_can_judge_memory_from_another_corpus_in_same_split(
    tmp_path: Path,
) -> None:
    background = """
  - id: shared-background
    memories:
      - key: shared-decoy
        summary: 另一条同 split 的已知干扰记忆。
        memory_type: fact
        updated_at: "2026-07-01T08:00:00+08:00"
"""
    second_query = """
  - id: background-query
    family_id: background-family
    corpus_id: shared-background
    split: development
    review_status: draft
    review_batch: 1
    product_scenario: personal_assistant
    memory_capability: information_extraction
    language: zh
    raw_query: 背景问题
    fixed_hypotheses: {}
    strata: [zh, shared-pool]
    expected_abstention: false
    required_memory_keys: [shared-decoy]
    judgments:
      - memory_key: shared-decoy
        relevance: 3
        dangerous: false
        rationale: 背景 family 的直接答案。
    rationale: 让背景 corpus 属于 development 搜索池。
"""
    content = _VALID_BENCHMARK.replace("queries:", f"{background}queries:")
    content = content.replace(
        "    rationale: 验证更新后的偏好必须覆盖旧偏好。",
        """      - memory_key: shared-decoy
        relevance: 0
        dangerous: false
        rationale: 同一搜索池中的已审核干扰项。
    rationale: 验证更新后的偏好必须覆盖旧偏好。""",
    )

    benchmark = load_memory_retrieval_benchmark(
        _write(tmp_path, f"{content}\n{second_query}"),
        enforce_v1_distribution=False,
    )

    assert benchmark.queries[0].judgment_by_key["shared-decoy"].relevance == 0


def test_formal_experiment_rejects_draft_dataset(tmp_path: Path) -> None:
    benchmark = load_memory_retrieval_benchmark(
        _write(tmp_path),
        enforce_v1_distribution=False,
    )

    with pytest.raises(ValueError, match="approved dataset"):
        benchmark.require_approved()


def test_batch_one_draft_has_ten_development_calibration_families() -> None:
    case_file = (
        Path(__file__).parent
        / "cases"
        / "memory_retrieval_benchmark_v1_batch_1_draft.yaml"
    )

    benchmark = load_memory_retrieval_benchmark(
        case_file,
        enforce_v1_distribution=False,
    )

    assert benchmark.review_status == "draft"
    assert len(benchmark.corpora) == 10
    assert len(benchmark.family_ids) == 10
    assert benchmark.review_batches() == {1: benchmark.family_ids}
    assert {query.split for query in benchmark.queries} == {"development"}
    assert {query.review_status for query in benchmark.queries} == {"approved"}
    assert Counter(query.product_scenario for query in benchmark.queries) == {
        "personal_assistant": 4,
        "project_assistant": 4,
        "stress": 2,
    }
    assert {query.memory_capability for query in benchmark.queries} == {
        "information_extraction",
        "cross_session",
        "knowledge_update",
        "temporal_reasoning",
        "abstention",
    }


def test_full_draft_has_registered_v1_distribution_and_all_queries_approved() -> None:
    case_file = (
        Path(__file__).parent
        / "cases"
        / "memory_retrieval_benchmark_v1_draft.yaml"
    )

    benchmark = load_memory_retrieval_benchmark(case_file)

    assert benchmark.review_status == "draft"
    assert len(benchmark.family_ids) == 60
    assert {batch: len(families) for batch, families in benchmark.review_batches().items()} == {
        1: 10,
        2: 10,
        3: 10,
        4: 10,
        5: 10,
        6: 10,
    }
    assert Counter(query.split for query in benchmark.queries) == {
        "development": 42,
        "holdout": 18,
    }
    assert {query.review_status for query in benchmark.queries} == {"approved"}

    with pytest.raises(ValueError, match="approved dataset"):
        benchmark.require_approved()


def test_approved_v1_is_formal_and_content_hash_is_frozen() -> None:
    case_file = Path(__file__).parent / "cases" / "memory_retrieval_benchmark_v1.yaml"

    benchmark = load_memory_retrieval_benchmark(case_file)

    benchmark.require_approved()
    assert benchmark.review_status == "approved"
    assert sum(len(query.judgments) for query in benchmark.queries) == 602
    assert len(benchmark.content_hash) == 64
    assert benchmark.content_hash.isalnum()
    freeze_record = (
        Path(__file__).parents[2]
        / ".trellis"
        / "tasks"
        / "07-11-memory-retrieval-parameter-evaluation"
        / "review"
        / "dataset-freeze.md"
    ).read_text(encoding="utf-8")
    assert f"Dataset SHA-256：`{benchmark.content_hash}`" in freeze_record


def test_approved_development_pool_overlay_is_complete_and_portable() -> None:
    case_file = (
        Path(__file__).parent
        / "cases"
        / "memory_retrieval_benchmark_v1_development_pool_qrels.yaml"
    )

    payload = yaml.safe_load(case_file.read_text(encoding="utf-8"))

    assert payload["review_status"] == "approved"
    assert len(payload["judgments"]) == 280
    assert payload["source_proposal"]["file"] == (
        "development-adjudication-proposal.json"
    )
    assert all(
        "\\" not in source["file"] and "/" not in source["file"]
        for source in payload["source_proposal"]["source_pools"]
    )


def test_approved_supplemental_pool_overlay_is_complete_and_portable() -> None:
    case_file = (
        Path(__file__).parent
        / "cases"
        / "memory_retrieval_benchmark_v1_development_pool_qrels_supplemental_1.yaml"
    )

    payload = yaml.safe_load(case_file.read_text(encoding="utf-8"))

    assert payload["version"] == (
        "memory-retrieval-v1-development-pool-qrels-supplemental-1"
    )
    assert payload["review_status"] == "approved"
    assert payload["overlay_id"] == "supplemental-1"
    assert payload["source_dataset_hash"] == (
        "2558260d47c55c3a1c740f19abe8bcf4b013657e226ee427e9b978e356f12d3a"
    )
    assert {
        source["file"]: source["sha256"]
        for source in payload["source_proposal"]["source_pools"]
    } == {
        "memory-retrieval-v1-pool-verification-stage-0-judging-pool.json": (
            "12fcb88eaa775bc36c3a7dfb10095924b598573f6e1fe71c80be0ea80e11ccef"
        ),
        "memory-retrieval-v1-pool-verification-stage-1-judging-pool.json": (
            "2a57512f578abc72eed5ffd5f5c76ffa976edb502c8ace5bdf2ed19c2d0d3463"
        ),
    }
    assert {
        (judgment["query_id"], judgment["memory_key"])
        for judgment in payload["judgments"]
    } == {
        (
            "project_incident_root_cause_en",
            "personal_allergy_restaurant_related",
        ),
        (
            "personal_allergy_restaurant_en",
            "project_env_variable_irrelevant",
        ),
        (
            "project_storage_adr_en",
            "personal_bookmark_article_irrelevant",
        ),
        (
            "project_test_command_en",
            "personal_allergy_restaurant_answer",
        ),
    }
    assert len(payload["judgments"]) == 4
    assert all(
        judgment["relevance"] == 0
        and judgment["dangerous"] is False
        and judgment["danger_reasons"] == []
        for judgment in payload["judgments"]
    )


def test_approved_supplemental_two_overlay_is_complete_and_portable() -> None:
    case_file = (
        Path(__file__).parent
        / "cases"
        / "memory_retrieval_benchmark_v1_development_pool_qrels_supplemental_2.yaml"
    )

    payload = yaml.safe_load(case_file.read_text(encoding="utf-8"))

    assert payload["version"] == (
        "memory-retrieval-v1-development-pool-qrels-supplemental-2"
    )
    assert payload["review_status"] == "approved"
    assert payload["overlay_id"] == "supplemental-2"
    assert payload["source_dataset_hash"] == (
        "9721b7b6264ab69b7e238c8af7175be10e1cb984729b05b32720c47d1b930d1c"
    )
    assert {
        (source["artifact_group"], source["sha256"])
        for source in payload["source_proposal"]["source_pools"]
    } == {
        (
            "stage-0",
            "bd44e5dea577c896f39213b619150ed8307eef5dd0809750f908ede97795fa4b",
        ),
        (
            "stage-1",
            "716396898ee3d14890f5499ae44640724f9feb1bc32115fc4eb0449c229c1853",
        ),
    }
    assert {
        (judgment["query_id"], judgment["memory_key"])
        for judgment in payload["judgments"]
    } == {
        (
            "project_incident_root_cause_en",
            "personal_bookmark_article_irrelevant",
        ),
        (
            "project_test_command_en",
            "personal_bookmark_article_irrelevant",
        ),
    }
    assert len(payload["judgments"]) == 2
    assert all(
        judgment["relevance"] == 0
        and judgment["dangerous"] is False
        and judgment["danger_reasons"] == []
        for judgment in payload["judgments"]
    )


def test_approved_supplemental_three_overlay_is_complete_and_portable() -> None:
    case_file = (
        Path(__file__).parent
        / "cases"
        / "memory_retrieval_benchmark_v1_development_pool_qrels_supplemental_3.yaml"
    )

    payload = yaml.safe_load(case_file.read_text(encoding="utf-8"))

    assert payload["version"] == (
        "memory-retrieval-v1-development-pool-qrels-supplemental-3"
    )
    assert payload["review_status"] == "approved"
    assert payload["overlay_id"] == "supplemental-3"
    assert payload["source_dataset_hash"] == (
        "d12a51ecab44c4fef5a3fb2da01d6f7a898225660e320bc79ccd08ef994050b9"
    )
    assert {
        (source["artifact_group"], source["sha256"])
        for source in payload["source_proposal"]["source_pools"]
    } == {
        (
            "stage-0",
            "a8eaa9cd90d3afd146868f6ff2e841fdc1107feaf0425debe1bbbea5bf756167",
        ),
        (
            "stage-1",
            "ff7b157534be7bad2acf89655e3e7bc15d85127fd7b5aa914bfa98cdf0e6430f",
        ),
    }
    judgments = {
        (item["query_id"], item["memory_key"]): (
            item["relevance"],
            item["dangerous"],
            item["danger_reasons"],
        )
        for item in payload["judgments"]
    }
    assert judgments == {
        ("project_multi_evidence_release_mixed", "generic_release_rule"): (
            1,
            False,
            [],
        ),
        ("project_multi_evidence_release_mixed", "release_identifier_rule"): (
            1,
            False,
            [],
        ),
        ("project_release_date_zh", "stress_time_boundary_answer"): (
            0,
            False,
            [],
        ),
        ("stress_scope_channel_zh", "release_identifier_rule"): (
            0,
            False,
            [],
        ),
    }


def test_approved_supplemental_four_overlay_is_complete_and_portable() -> None:
    case_file = (
        Path(__file__).parent
        / "cases"
        / "memory_retrieval_benchmark_v1_development_pool_qrels_supplemental_4.yaml"
    )

    payload = yaml.safe_load(case_file.read_text(encoding="utf-8"))

    assert payload["version"] == (
        "memory-retrieval-v1-development-pool-qrels-supplemental-4"
    )
    assert payload["review_status"] == "approved"
    assert payload["overlay_id"] == "supplemental-4"
    assert payload["source_dataset_hash"] == (
        "ea6f0b38a3306cc76837c3802722532a8af553c63c1362d3a858db0fda6cf6ba"
    )
    assert {
        (source["artifact_group"], source["sha256"])
        for source in payload["source_proposal"]["source_pools"]
    } == {
        (
            "stage-2",
            "f255e5ec671b0af165b491fd8e74060f9cc623c62d1197cef7062da02f25e79e",
        ),
    }
    judgments = {
        (item["query_id"], item["memory_key"]): (
            item["relevance"],
            item["dangerous"],
            item["danger_reasons"],
        )
        for item in payload["judgments"]
    }
    assert judgments == {
        ("personal_allergy_restaurant_en", "personal_bookmark_article_irrelevant"): (
            0,
            False,
            [],
        ),
        ("personal_hotness_contact_zh", "project_feature_owner_irrelevant"): (
            0,
            False,
            [],
        ),
        ("project_storage_adr_en", "own_deploy_region"): (0, False, []),
        ("project_test_command_en", "project_error_policy_irrelevant"): (
            1,
            False,
            [],
        ),
        ("stress_unknown_city_abstention_zh", "accepted_api_field"): (
            0,
            False,
            [],
        ),
    }


def test_approved_supplemental_five_overlay_is_complete_and_portable() -> None:
    case_file = (
        Path(__file__).parent
        / "cases"
        / "memory_retrieval_benchmark_v1_development_pool_qrels_supplemental_5.yaml"
    )

    payload = yaml.safe_load(case_file.read_text(encoding="utf-8"))

    assert payload["version"] == (
        "memory-retrieval-v1-development-pool-qrels-supplemental-5"
    )
    assert payload["review_status"] == "approved"
    assert payload["overlay_id"] == "supplemental-5"
    assert payload["source_dataset_hash"] == (
        "1c8aabe55f717a53c27f2343cb5d62dbd1e9dc0606e5b70607d6c2e0e2a1c574"
    )
    assert {
        (source["artifact_group"], source["sha256"])
        for source in payload["source_proposal"]["source_pools"]
    } == {
        (
            "stage-3",
            "61cd025bf4fda995759fa0e67055f1b06abcc18edfde96cc55a760f5867cf292",
        ),
    }
    judgments = {
        (item["query_id"], item["memory_key"]): (
            item["relevance"],
            item["dangerous"],
            item["danger_reasons"],
        )
        for item in payload["judgments"]
    }
    assert len(judgments) == 21
    assert judgments[("project_error_policy_en", "incident_mitigation")] == (
        1,
        False,
        [],
    )
    assert judgments[
        ("stress_cross_user_region_zh", "stress_scope_channel_answer")
    ] == (0, True, ["private_secret", "wrong_scope"])
    ordinary = {
        marker: judgment
        for marker, judgment in judgments.items()
        if marker
        not in {
            ("project_error_policy_en", "incident_mitigation"),
            ("stress_cross_user_region_zh", "stress_scope_channel_answer"),
        }
    }
    assert len(ordinary) == 19
    assert set(ordinary) == {
        ("personal_appointment_time_zh", "similar_flight_number"),
        ("personal_bookmark_article_en", "project_feature_owner_related"),
        ("personal_dietary_update_zh", "concise_style_preference"),
        ("personal_family_birthday_zh", "passport_renewal"),
        ("personal_family_birthday_zh", "wrong_chat_release_note"),
        ("personal_home_temperature_zh", "project_feature_owner_related"),
        ("personal_home_temperature_zh", "shanghai_hotel_preference"),
        ("personal_medicine_instruction_zh", "concise_style_preference"),
        ("personal_medicine_instruction_zh", "family_doctor_name"),
        ("personal_shared_shopping_zh", "personal_unknown_parking_irrelevant"),
        ("personal_train_seat_mixed", "memory_eval_owner"),
        ("personal_two_character_cjk_zh", "family_doctor_name"),
        ("personal_two_character_cjk_zh", "osaka_trip_history"),
        ("personal_two_character_cjk_zh", "passport_renewal"),
        ("personal_unknown_parking_zh", "family_doctor_name"),
        ("personal_unknown_parking_zh", "personal_coffee_update_answer"),
        ("personal_weekly_class_zh", "stress_time_boundary_related"),
        ("project_identifier_lexical_mixed", "stress_scope_channel_irrelevant"),
        ("project_incident_root_cause_en", "project_unknown_pr_related"),
    }
    assert all(judgment == (0, False, []) for judgment in ordinary.values())


def test_approved_holdout_pool_overlay_is_complete_and_holdout_only() -> None:
    cases_dir = Path(__file__).parent / "cases"
    case_file = (
        cases_dir
        / "memory_retrieval_benchmark_v1_holdout_pool_qrels_supplemental_1.yaml"
    )
    payload = yaml.safe_load(case_file.read_text(encoding="utf-8"))

    assert payload["version"] == (
        "memory-retrieval-v1-holdout-pool-qrels-supplemental-1"
    )
    assert payload["review_status"] == "approved"
    assert payload["split"] == "holdout"
    assert payload["overlay_id"] == "holdout-supplemental-1"
    assert payload["source_dataset_hash"] == (
        "2748c90799831d4c9eccabb8dc96c02c3cefa793cf530a1c92beec3a136571dd"
    )
    assert payload["source_proposal"]["sha256"] == (
        "1b3ff0117c44d2bbca08195f4f76e6a61996351e1623dc5cebfacd4a3aa5e662"
    )
    assert len(payload["judgments"]) == 103
    assert Counter(item["relevance"] for item in payload["judgments"]) == {
        0: 100,
        1: 3,
    }
    assert all(item["dangerous"] is False for item in payload["judgments"])

    benchmark = load_memory_retrieval_benchmark(
        cases_dir / "memory_retrieval_benchmark_v1.yaml"
    )
    query_by_id = {query.id: query for query in benchmark.queries}
    assert all(
        query_by_id[item["query_id"]].split == "holdout"
        for item in payload["judgments"]
    )


def test_approved_fixture_correction_is_complete_and_applied() -> None:
    cases_dir = Path(__file__).parent / "cases"
    correction_path = (
        cases_dir / "memory_retrieval_benchmark_v1_fixture_correction_1.yaml"
    )
    payload = yaml.safe_load(correction_path.read_text(encoding="utf-8"))

    assert payload["version"] == "memory-retrieval-v1-fixture-correction-1"
    assert payload["review_status"] == "approved"
    assert payload["source_dataset_hash"] == (
        "4daf138fcd02540f13bf8b70eb593ad90e769a224c0b2466cd5344ceacad8a7b"
    )
    assert len(payload["memory_updates"]) == 19
    assert len(payload["query_updates"]) == 6
    assert len(payload["judgment_updates"]) == 2
    assert {
        (item["stage"], item["sha256"])
        for item in payload["source_experiments"]
    } == {
        (
            0,
            "ef1431e3d5cb8cc3674b1bb2e3e87d33408e80838338300f21f3044f9f35ab34",
        ),
        (
            1,
            "7f8130cc7f20b5ed8bd3883eb3491ec2f93bf9b57d6ec9d09d00707a3a4d9931",
        ),
    }

    benchmark = load_memory_retrieval_benchmark(
        cases_dir / "memory_retrieval_benchmark_v1.yaml"
    )
    memory_by_key = {
        memory.key: memory
        for corpus in benchmark.corpora
        for memory in corpus.memories
    }
    query_by_id = {query.id: query for query in benchmark.queries}
    assert memory_by_key["project_release_date_related"].status == "superseded"
    assert (
        memory_by_key["stress_scope_channel_related"].scope_channel,
        memory_by_key["stress_scope_channel_related"].scope_chat_id,
    ) == ("telegram", "private-other")
    assert {
        query_id: (
            query_by_id[query_id].scope_channel,
            query_by_id[query_id].scope_chat_id,
        )
        for query_id in (
            "project_identifier_lexical_mixed",
            "personal_airport_pickup_mixed",
            "project_deploy_rollback_mixed",
            "stress_scope_channel_zh",
            "personal_unknown_wifi_mixed",
            "stress_forgotten_secret_zh",
        )
    } == {
        "project_identifier_lexical_mixed": ("telegram", "project-amadeus"),
        "personal_airport_pickup_mixed": ("telegram", "personal-travel"),
        "project_deploy_rollback_mixed": ("telegram", "project-ops"),
        "stress_scope_channel_zh": ("telegram", "project-amadeus"),
        "personal_unknown_wifi_mixed": ("telegram", "personal-home"),
        "stress_forgotten_secret_zh": ("telegram", "personal-security"),
    }
    scope_judgment = query_by_id["stress_scope_channel_zh"].judgment_by_key[
        "stress_scope_channel_related"
    ]
    release_judgment = query_by_id["project_release_date_zh"].judgment_by_key[
        "project_release_date_related"
    ]
    assert scope_judgment.dangerous is True
    assert scope_judgment.danger_reasons == ("private_secret", "wrong_scope")
    assert release_judgment.dangerous is True
    assert release_judgment.danger_reasons == (
        "superseded",
        "obsolete_version",
    )


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("danger_reasons: [superseded]", "danger_reasons: []", "danger_reasons"),
        ("expected_abstention: false", "expected_abstention: true", "abstention"),
        ("relevance: 3", "relevance: 1", "required keys"),
        ("memory_key: current", "memory_key: missing", "unknown memories"),
    ],
)
def test_benchmark_rejects_invalid_qrels(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
) -> None:
    path = _write(tmp_path, _VALID_BENCHMARK.replace(old, new, 1))

    with pytest.raises(ValueError, match=message):
        load_memory_retrieval_benchmark(path, enforce_v1_distribution=False)


def test_benchmark_rejects_query_family_split_leakage(tmp_path: Path) -> None:
    second_query = """
  - id: dinner-now-en
    family_id: dinner-now
    corpus_id: preference-update
    split: holdout
    review_status: draft
    review_batch: 6
    product_scenario: personal_assistant
    memory_capability: knowledge_update
    language: en
    raw_query: What should I have for dinner?
    fixed_hypotheses: {}
    strata: [en, vector, preference]
    expected_abstention: false
    required_memory_keys: [current]
    judgments:
      - memory_key: current
        relevance: 3
        dangerous: false
        rationale: Current dietary constraint.
    rationale: English paraphrase of the same family.
"""
    path = _write(tmp_path, f"{_VALID_BENCHMARK}\n{second_query}")

    with pytest.raises(ValueError, match="crosses benchmark splits"):
        load_memory_retrieval_benchmark(path, enforce_v1_distribution=False)


def test_benchmark_rejects_seed_rows_that_would_reinforce_each_other(
    tmp_path: Path,
) -> None:
    duplicated = _VALID_BENCHMARK.replace(
        "用户以前经常选择普通披萨。",
        "用户目前需要无麸质餐食。",
    )

    with pytest.raises(ValueError, match="owner/type/summary"):
        load_memory_retrieval_benchmark(
            _write(tmp_path, duplicated),
            enforce_v1_distribution=False,
        )


def test_validate_v1_distribution_accepts_required_family_shape() -> None:
    split_scenarios = [
        ("development", "personal_assistant", 21),
        ("development", "project_assistant", 15),
        ("development", "stress", 6),
        ("holdout", "personal_assistant", 9),
        ("holdout", "project_assistant", 6),
        ("holdout", "stress", 3),
    ]
    capabilities = (
        "information_extraction",
        "cross_session",
        "knowledge_update",
        "temporal_reasoning",
        "abstention",
    )
    queries: list[RetrievalBenchmarkQuery] = []
    family_index = 0
    for split, scenario, count in split_scenarios:
        for _ in range(count):
            batch = min(6, family_index // 10 + 1)
            family_id = f"family-{family_index:02d}"
            queries.append(
                RetrievalBenchmarkQuery(
                    id=f"query-{family_index:02d}",
                    family_id=family_id,
                    corpus_id="corpus",
                    split=split,
                    review_status="draft",
                    review_batch=batch,
                    product_scenario=scenario,
                    memory_capability=capabilities[
                        family_index % len(capabilities)
                    ],
                    language="zh",
                    raw_query="query",
                    fixed_hypotheses=FixedRetrievalHypotheses(),
                    strata=("zh",),
                    judgments=(
                        RetrievalJudgment(
                            memory_key="memory",
                            relevance=3,
                            dangerous=False,
                            rationale="relevant",
                        ),
                    ),
                    rationale="distribution fixture",
                )
            )
            family_index += 1
    benchmark = MemoryRetrievalBenchmark(
        version="memory-retrieval-v1",
        review_status="draft",
        corpora=(
            RetrievalBenchmarkCorpus(
                id="corpus",
                memories=tuple(
                    RetrievalBenchmarkMemory(
                        key="memory" if index == 0 else f"decoy-{index}",
                        summary=f"memory {index}",
                        memory_type="fact",
                        updated_at="2026-07-01T00:00:00+00:00",
                    )
                    for index in range(65)
                ),
            ),
        ),
        queries=tuple(queries),
    )

    validate_v1_distribution(benchmark)
