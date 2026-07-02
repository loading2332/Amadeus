from __future__ import annotations

from types import SimpleNamespace

from amadeus.evaluation.evaluators import (
    answer_rules_evaluator,
    llm_judge_evaluator,
    summarize_result_rows,
    source_ref_evaluator,
    trace_evaluator,
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
