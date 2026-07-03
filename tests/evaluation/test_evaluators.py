from __future__ import annotations

from types import SimpleNamespace

from amadeus.evaluation.evaluators import (
    answer_rules_evaluator,
    conflict_evaluator,
    llm_judge_evaluator,
    memory_type_evaluator,
    summarize_result_rows,
    source_ref_evaluator,
    trace_evaluator,
    write_absence_evaluator,
    write_presence_evaluator,
)


def test_trace_evaluator_reports_field_level_differences():
    run = SimpleNamespace(
        outputs={
            "memory_trace": {
                "intent": "context",
                "candidate_count": 0,
                "injected_ids": [],
                "fallbacks": [],
                "scope_mode": "scoped",
            },
            "rendered_context": "",
        }
    )
    example = SimpleNamespace(
        outputs={
            "expect": {
                "memory_intent": "context",
                "candidate_count_min": 1,
                "injected_count_min": 1,
                "context_contains": ["中文"],
                "fallbacks_contains": ["global-fallback"],
            }
        }
    )

    result = trace_evaluator(run, example)

    assert result.score is False
    assert "candidate_count" in str(result.comment)
    assert "injected_count" in str(result.comment)
    assert "global-fallback" in str(result.comment)


def test_source_ref_evaluator_reports_missing_fetchability():
    run = SimpleNamespace(
        outputs={
            "recall_items": [
                {"id": "mem_1", "summary": "profile", "source_ref": "", "evidence": []}
            ],
            "fetched_messages": [],
        }
    )
    example = SimpleNamespace(
        outputs={
            "expect": {
                "source_ref_required": True,
                "fetched_messages_contains": ["面试项目"],
            }
        }
    )

    result = source_ref_evaluator(run, example)

    assert result.score is False
    assert "source_ref" in str(result.comment)
    assert "fetched_messages" in str(result.comment)


def test_llm_judge_evaluator_skips_when_answer_rules_fail():
    run = SimpleNamespace(outputs={"assistant_response": "assistant reply"})
    example = SimpleNamespace(
        outputs={
            "expect": {
                "answer_keywords_any": ["中文"],
                "judge_rubric": "must say Chinese",
            }
        }
    )

    result = llm_judge_evaluator(
        run,
        example,
        judge=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("judge must not run")),
    )

    assert result.value == "skipped"
    assert "answer_rules" in str(result.comment)


def test_answer_rules_evaluator_accepts_matching_keyword():
    run = SimpleNamespace(outputs={"assistant_response": "之后默认用中文回复。"})
    example = SimpleNamespace(
        outputs={"expect": {"answer_keywords_any": ["中文"]}}
    )

    result = answer_rules_evaluator(run, example)

    assert result.score is True


def test_summarize_result_rows_handles_mapping_rows():
    rows = [
        {
            "example": {
                "id": "example-1",
                "inputs": {
                    "case": {
                        "id": "case-1",
                        "title": "broken case",
                        "mode": "runtime_turn",
                    }
                },
            },
            "run": {
                "outputs": {
                    "assistant_response": "",
                    "elapsed_ms": 12,
                    "error": "memory recall evaluation requires AMADEUS_LONG_TERM_MEMORY_ENABLED=1",
                }
            },
            "evaluation_results": {"results": []},
        }
    ]

    summary = summarize_result_rows(rows)

    assert summary["total_cases"] == 1
    assert summary["passed_cases"] == 0
    assert summary["failed_case_ids"] == ["case-1"]
    assert summary["records"][0]["error"]


def test_summarize_result_rows_treats_skipped_evaluation_as_failure():
    row = {
        "example": {
            "id": "example-1",
            "inputs": {
                "case": {
                    "id": "case-1",
                    "title": "skipped judge",
                    "mode": "post_response_write",
                }
            },
        },
        "run": {
            "outputs": {
                "assistant_response": "",
                "elapsed_ms": 7,
            }
        },
        "evaluation_results": {
            "results": [
                SimpleNamespace(
                    key="llm_judge",
                    score=None,
                    value="skipped",
                    comment="skipped because judge returned unparsable output",
                )
            ]
        },
    }

    summary = summarize_result_rows([row])

    assert summary["total_cases"] == 1
    assert summary["passed_cases"] == 0
    assert summary["failed_case_ids"] == ["case-1"]


def test_write_presence_evaluator_reports_missing_written_summary_and_count():
    run = SimpleNamespace(
        outputs={
            "write_trace": {"candidate_count": 1, "written_count": 0},
            "written_memories": [],
            "active_memories": [],
        }
    )
    example = SimpleNamespace(
        outputs={
            "expect": {
                "write_count_min": 1,
                "written_summaries_contains": ["中文"],
                "active_summaries_contains": ["中文"],
            }
        }
    )

    result = write_presence_evaluator(run, example)

    assert result.score is False
    assert "write_count" in str(result.comment)
    assert "written_memories" in str(result.comment)
    assert "active_memories" in str(result.comment)


def test_write_absence_evaluator_rejects_unexpected_memory_write():
    run = SimpleNamespace(
        outputs={
            "write_trace": {"written_count": 1},
            "written_memories": [{"summary": "用户当前短期在线"}],
            "active_memories": [{"summary": "用户当前短期在线"}],
        }
    )
    example = SimpleNamespace(
        outputs={
            "expect": {
                "write_count_max": 0,
                "active_summaries_not_contains": ["短期在线"],
            }
        }
    )

    result = write_absence_evaluator(run, example)

    assert result.score is False
    assert "write_count" in str(result.comment)
    assert "短期在线" in str(result.comment)


def test_memory_type_and_conflict_evaluators_report_field_level_gaps():
    run = SimpleNamespace(
        outputs={
            "written_memories": [
                {"summary": "用户默认偏好中文回复", "memory_type": "event"}
            ],
            "active_memories": [
                {"summary": "用户默认偏好中文回复", "memory_type": "event"},
                {"summary": "用户以前偏好英文回复", "memory_type": "preference"},
            ],
            "superseded_memories": [],
        }
    )
    example = SimpleNamespace(
        outputs={
            "expect": {
                "memory_types_contains": ["preference"],
                "superseded_summaries_contains": ["英文"],
                "active_summaries_not_contains": ["英文"],
            }
        }
    )

    type_result = memory_type_evaluator(run, example)
    conflict_result = conflict_evaluator(run, example)

    assert type_result.score is False
    assert "preference" in str(type_result.comment)
    assert conflict_result.score is False
    assert "superseded_memories" in str(conflict_result.comment)
    assert "active_memories" in str(conflict_result.comment)
