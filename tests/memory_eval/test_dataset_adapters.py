from pathlib import Path

from amadeus.memory_eval.datasets.locomo import load_locomo_cases, load_locomo_groups
from amadeus.memory_eval.datasets.longmemeval_v2 import (
    load_longmemeval_v2_cases,
    load_longmemeval_v2_groups,
)
from amadeus.memory_eval.datasets.personamem import load_personamem_cases, load_personamem_groups


ROOT = Path(__file__).resolve().parents[2]


def test_locomo_adapter_loads_real_repo_sample() -> None:
    cases = list(
        load_locomo_cases(
            ROOT / "memorybenchmarks" / "locomo" / "data" / "locomo10.json",
            limit=2,
        )
    )

    first = cases[0]
    assert len(cases) == 2
    assert first.dataset_name == "locomo"
    assert first.case_id.startswith("conv-26:qa:")
    assert first.task_type == "long_conversation_qa"
    assert first.query == "When did Caroline go to the LGBTQ support group?"
    assert first.gold_answer == "7 May 2023"
    assert first.gold_evidence_ids == ("D1:3",)
    assert first.memory_artifacts
    assert first.native_payload["sample_id"] == "conv-26"


def test_locomo_adapter_groups_one_conversation_with_many_questions() -> None:
    groups = list(
        load_locomo_groups(
            ROOT / "memorybenchmarks" / "locomo" / "data" / "locomo10.json",
            limit=1,
        )
    )

    assert len(groups) == 1
    group = groups[0]
    assert group.dataset_name == "locomo"
    assert group.group_id == "conv-26"
    assert group.memory_artifacts
    assert len(group.cases) > 1
    assert group.cases[0].group_id == "conv-26"
    assert group.cases[0].case_id == "conv-26:qa:0"
    assert group.cases[0].memory_artifacts == ()
    assert group.native_payload["sample_id"] == "conv-26"


def test_personamem_adapter_reads_questions_and_shared_context(tmp_path: Path) -> None:
    questions = tmp_path / "questions_32k.csv"
    contexts = tmp_path / "shared_contexts_32k.jsonl"
    questions.write_text(
        "persona_id,question_id,question_type,topic,context_length_in_tokens,"
        "context_length_in_letters,distance_to_ref_in_blocks,distance_to_ref_in_tokens,"
        "num_irrelevant_tokens,distance_to_ref_proportion_in_context,"
        "user_question_or_message,correct_answer,all_options,shared_context_id,"
        "end_index_in_shared_context\n"
        "persona-1,q-1,preference,travel,12,50,1,8,0,0.5,"
        "\"Where should I go?\",(b),\"(a) Beach (b) Museum\",ctx-1,2\n",
        encoding="utf-8",
    )
    contexts.write_text(
        '{"ctx-1": [{"role": "user", "content": "I prefer museums."}, '
        '{"role": "assistant", "content": "I will remember that."}, '
        '{"role": "user", "content": "Ignore this later turn."}]}\n',
        encoding="utf-8",
    )

    cases = list(load_personamem_cases(questions, contexts))

    assert len(cases) == 1
    case = cases[0]
    assert case.dataset_name == "personamem"
    assert case.case_id == "q-1"
    assert case.task_type == "personalized_response_mcq"
    assert case.gold_answer == "(b)"
    assert len(case.memory_artifacts) == 2
    assert case.native_payload["question"]["persona_id"] == "persona-1"


def test_personamem_adapter_groups_by_shared_context_slice(tmp_path: Path) -> None:
    questions = tmp_path / "questions_32k.csv"
    contexts = tmp_path / "shared_contexts_32k.jsonl"
    questions.write_text(
        "persona_id,question_id,question_type,topic,context_length_in_tokens,"
        "context_length_in_letters,distance_to_ref_in_blocks,distance_to_ref_in_tokens,"
        "num_irrelevant_tokens,distance_to_ref_proportion_in_context,"
        "user_question_or_message,correct_answer,all_options,shared_context_id,"
        "end_index_in_shared_context\n"
        "persona-1,q-1,preference,travel,12,50,1,8,0,0.5,"
        "\"Where should I go?\",(b),\"(a) Beach (b) Museum\",ctx-1,2\n"
        "persona-1,q-2,preference,travel,12,50,1,8,0,0.5,"
        "\"What do I like?\",museums,\"\",ctx-1,2\n"
        "persona-1,q-3,preference,travel,12,50,1,8,0,0.5,"
        "\"What should be ignored?\",nothing,\"\",ctx-1,3\n",
        encoding="utf-8",
    )
    contexts.write_text(
        '{"ctx-1": [{"role": "user", "content": "I prefer museums."}, '
        '{"role": "assistant", "content": "I will remember that."}, '
        '{"role": "user", "content": "Ignore this later turn."}]}\n',
        encoding="utf-8",
    )

    groups = list(load_personamem_groups(questions, contexts))

    assert [group.group_id for group in groups] == ["ctx-1:until:2", "ctx-1:until:3"]
    assert len(groups[0].memory_artifacts) == 2
    assert [case.case_id for case in groups[0].cases] == ["q-1", "q-2"]
    assert groups[0].cases[0].memory_artifacts == ()
    assert groups[1].cases[0].case_id == "q-3"


def test_longmemeval_v2_adapter_reads_runtime_files(tmp_path: Path) -> None:
    questions = tmp_path / "questions.json"
    haystack = tmp_path / "haystack.json"
    trajectories = tmp_path / "trajectories.json"
    questions.write_text(
        '[{"id": "q1", "domain": "web", "question": "Where is the export button?", '
        '"answer": "top right", "question_type": "static-environment"}]',
        encoding="utf-8",
    )
    haystack.write_text('{"q1": ["t1"]}', encoding="utf-8")
    trajectories.write_text(
        '[{"id": "t1", "domain": "web", "steps": [{"text": "The export button is top right."}]}]',
        encoding="utf-8",
    )

    cases = list(load_longmemeval_v2_cases(questions, haystack, trajectories))

    assert len(cases) == 1
    case = cases[0]
    assert case.dataset_name == "longmemeval_v2"
    assert case.case_id == "q1"
    assert case.task_type == "static-environment"
    assert case.gold_answer == "top right"
    assert case.gold_evidence_ids == ("t1",)
    assert case.memory_artifacts[0].artifact_id == "trajectory:t1"
    assert case.native_payload["haystack"] == ["t1"]


def test_longmemeval_v2_adapter_groups_question_haystack(tmp_path: Path) -> None:
    questions = tmp_path / "questions.json"
    haystack = tmp_path / "haystack.json"
    trajectories = tmp_path / "trajectories.json"
    questions.write_text(
        '[{"id": "q1", "domain": "web", "question": "Where is the export button?", '
        '"answer": "top right", "question_type": "static-environment"}]',
        encoding="utf-8",
    )
    haystack.write_text('{"q1": ["t1"]}', encoding="utf-8")
    trajectories.write_text(
        '[{"id": "t1", "domain": "web", "steps": [{"text": "The export button is top right."}]}]',
        encoding="utf-8",
    )

    groups = list(load_longmemeval_v2_groups(questions, haystack, trajectories))

    assert len(groups) == 1
    group = groups[0]
    assert group.dataset_name == "longmemeval_v2"
    assert group.group_id == "q1:haystack"
    assert group.memory_artifacts[0].artifact_id == "trajectory:t1"
    assert [case.case_id for case in group.cases] == ["q1"]
    assert group.cases[0].group_id == "q1:haystack"
    assert group.cases[0].memory_artifacts == ()
