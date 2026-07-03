from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from langsmith.evaluation.evaluator import EvaluationResult

from amadeus.app.bootstrap import load_runtime_config
from amadeus.provider import LLMProvider


def trace_evaluator(run: Any, example: Any) -> EvaluationResult:
    outputs = _run_outputs(run)
    expect = _example_expect(example)
    trace = _dict(outputs.get("memory_trace"))
    failures: list[str] = []

    expected_intent = _optional_string(expect.get("memory_intent"))
    if expected_intent is not None and str(trace.get("intent") or "") != expected_intent:
        failures.append(
            f"memory_intent expected {expected_intent!r}, got {trace.get('intent')!r}"
        )
    candidate_count_min = _int(expect.get("candidate_count_min"))
    candidate_count = _int(trace.get("candidate_count"))
    if candidate_count < candidate_count_min:
        failures.append(
            f"candidate_count expected >= {candidate_count_min}, got {candidate_count}"
        )
    injected_count_min = _int(expect.get("injected_count_min"))
    injected_ids = _string_list(trace.get("injected_ids"))
    if len(injected_ids) < injected_count_min:
        failures.append(
            f"injected_count expected >= {injected_count_min}, got {len(injected_ids)}"
        )
    rendered_context = str(outputs.get("rendered_context") or "")
    for expected in _string_list(expect.get("context_contains")):
        if expected not in rendered_context:
            failures.append(f"context missing substring {expected!r}")
    observed_fallbacks = set(_string_list(trace.get("fallbacks")))
    scope_mode = str(trace.get("scope_mode") or "").strip()
    if scope_mode:
        observed_fallbacks.add(scope_mode)
    for fallback in _string_list(expect.get("fallbacks_contains")):
        if fallback not in observed_fallbacks:
            failures.append(f"fallback {fallback!r} not found in trace")

    return EvaluationResult(
        key="trace",
        score=not failures,
        comment="; ".join(failures) if failures else "trace expectations satisfied",
    )


def source_ref_evaluator(run: Any, example: Any) -> EvaluationResult:
    outputs = _run_outputs(run)
    expect = _example_expect(example)
    failures: list[str] = []
    if bool(expect.get("source_ref_required")):
        recall_items = outputs.get("recall_items")
        if isinstance(recall_items, list) and recall_items:
            if not any(str(item.get("source_ref") or "").strip() for item in recall_items if isinstance(item, dict)):
                failures.append("source_ref is missing from recall items")
        else:
            written_memories = outputs.get("written_memories")
            if not isinstance(written_memories, list) or not written_memories:
                failures.append("recall_items and written_memories are empty")
            elif not any(
                str(item.get("source_ref") or "").strip()
                for item in written_memories
                if isinstance(item, dict)
            ):
                failures.append("source_ref is missing from written memories")
    fetched_messages = outputs.get("fetched_messages")
    fetched_text = "\n".join(
        str(message.get("content") or "")
        for message in fetched_messages
        if isinstance(message, dict)
    ) if isinstance(fetched_messages, list) else ""
    for expected in _string_list(expect.get("fetched_messages_contains")):
        if expected not in fetched_text:
            failures.append(f"fetched_messages missing substring {expected!r}")
    return EvaluationResult(
        key="source_ref",
        score=not failures,
        comment="; ".join(failures) if failures else "source_ref expectations satisfied",
    )


def write_presence_evaluator(run: Any, example: Any) -> EvaluationResult:
    outputs = _run_outputs(run)
    expect = _example_expect(example)
    failures: list[str] = []
    write_trace = _dict(outputs.get("write_trace"))
    written_count = _int(write_trace.get("written_count"))
    write_count_min = _int(expect.get("write_count_min"))
    if written_count < write_count_min:
        failures.append(
            f"write_count expected >= {write_count_min}, got {written_count}"
        )

    written_text = "\n".join(_memory_summaries(outputs.get("written_memories")))
    for expected in _string_list(expect.get("written_summaries_contains")):
        if expected not in written_text:
            failures.append(f"written_memories missing substring {expected!r}")

    active_text = "\n".join(_memory_summaries(outputs.get("active_memories")))
    for expected in _string_list(expect.get("active_summaries_contains")):
        if expected not in active_text:
            failures.append(f"active_memories missing substring {expected!r}")

    return EvaluationResult(
        key="write_presence",
        score=not failures,
        comment="; ".join(failures) if failures else "write presence expectations satisfied",
    )


def write_absence_evaluator(run: Any, example: Any) -> EvaluationResult:
    outputs = _run_outputs(run)
    expect = _example_expect(example)
    failures: list[str] = []
    write_trace = _dict(outputs.get("write_trace"))
    write_count_max = expect.get("write_count_max")
    if write_count_max is not None:
        written_count = _int(write_trace.get("written_count"))
        max_allowed = _int(write_count_max)
        if written_count > max_allowed:
            failures.append(
                f"write_count expected <= {max_allowed}, got {written_count}"
            )

    active_text = "\n".join(_memory_summaries(outputs.get("active_memories")))
    for unexpected in _string_list(expect.get("active_summaries_not_contains")):
        if unexpected in active_text:
            failures.append(f"active_memories unexpectedly contains {unexpected!r}")

    return EvaluationResult(
        key="write_absence",
        score=not failures,
        comment="; ".join(failures) if failures else "write absence expectations satisfied",
    )


def memory_type_evaluator(run: Any, example: Any) -> EvaluationResult:
    outputs = _run_outputs(run)
    expect = _example_expect(example)
    expected_types = _string_list(expect.get("memory_types_contains"))
    if not expected_types:
        return EvaluationResult(
            key="memory_types",
            score=True,
            comment="no memory type expectations",
        )
    written_memories = outputs.get("written_memories")
    observed = {
        str(item.get("memory_type") or "").strip()
        for item in written_memories
        if isinstance(written_memories, list) and isinstance(item, dict)
    }
    failures = [
        f"missing memory_type {memory_type!r}"
        for memory_type in expected_types
        if memory_type not in observed
    ]
    return EvaluationResult(
        key="memory_types",
        score=not failures,
        comment="; ".join(failures) if failures else "memory type expectations satisfied",
    )


def conflict_evaluator(run: Any, example: Any) -> EvaluationResult:
    outputs = _run_outputs(run)
    expect = _example_expect(example)
    failures: list[str] = []
    active_text = "\n".join(_memory_summaries(outputs.get("active_memories")))
    superseded_text = "\n".join(_memory_summaries(outputs.get("superseded_memories")))

    for expected in _string_list(expect.get("superseded_summaries_contains")):
        if expected not in superseded_text:
            failures.append(f"superseded_memories missing substring {expected!r}")
    for unexpected in _string_list(expect.get("active_summaries_not_contains")):
        if unexpected in active_text:
            failures.append(f"active_memories unexpectedly contains {unexpected!r}")

    return EvaluationResult(
        key="conflict",
        score=not failures,
        comment="; ".join(failures) if failures else "conflict expectations satisfied",
    )


def answer_rules_evaluator(run: Any, example: Any) -> EvaluationResult:
    expect = _example_expect(example)
    keywords = _string_list(expect.get("answer_keywords_any"))
    if not keywords:
        return EvaluationResult(
            key="answer_rules",
            score=True,
            comment="no answer keyword expectations",
        )
    response_text = _response_text(_run_outputs(run))
    if any(keyword in response_text for keyword in keywords):
        return EvaluationResult(
            key="answer_rules",
            score=True,
            comment="matched expected answer keywords",
        )
    return EvaluationResult(
        key="answer_rules",
        score=False,
        comment=f"answer did not match any expected keywords: {keywords}",
    )


def llm_judge_evaluator(
    run: Any,
    example: Any,
    *,
    judge: Callable[[str, str], tuple[bool, str]] | None = None,
    judge_model: str | None = None,
    env_path: str | Path = ".env",
    client: Any | None = None,
) -> EvaluationResult:
    answer_rule_result = answer_rules_evaluator(run, example)
    if answer_rule_result.score is False:
        return EvaluationResult(
            key="llm_judge",
            score=None,
            value="skipped",
            comment=f"skipped because answer_rules failed: {answer_rule_result.comment}",
        )
    expect = _example_expect(example)
    rubric = str(expect.get("judge_rubric") or "").strip()
    if not rubric:
        return EvaluationResult(
            key="llm_judge",
            score=None,
            value="skipped",
            comment="skipped because judge_rubric is empty",
        )
    response_text = _response_text(_run_outputs(run))
    if not response_text:
        return EvaluationResult(
            key="llm_judge",
            score=None,
            value="skipped",
            comment="skipped because no answer or memory text is available",
        )
    judge_fn = judge or _build_llm_judge(
        judge_model=judge_model,
        env_path=env_path,
        client=client,
    )
    passed, comment = judge_fn(response_text, rubric)
    if passed is None:
        return EvaluationResult(
            key="llm_judge",
            score=None,
            value="skipped",
            comment=comment,
        )
    return EvaluationResult(
        key="llm_judge",
        score=passed,
        comment=comment,
    )


def make_llm_judge_evaluator(
    *,
    judge_model: str | None,
    env_path: str | Path,
    client: Any | None = None,
) -> Callable[[Any, Any], EvaluationResult]:
    def _evaluate(run: Any, example: Any) -> EvaluationResult:
        return llm_judge_evaluator(
            run,
            example,
            judge_model=judge_model,
            env_path=env_path,
            client=client,
        )

    return _evaluate


def elapsed_summary_evaluator(runs: Sequence[Any], examples: Sequence[Any]) -> EvaluationResult:
    del examples
    elapsed_values = [
        _int(_dict(getattr(run, "outputs", None)).get("elapsed_ms"))
        for run in runs
    ]
    valid = [value for value in elapsed_values if value > 0]
    average = (sum(valid) / len(valid)) if valid else 0.0
    return EvaluationResult(
        key="avg_elapsed_ms",
        score=average,
        comment=f"average elapsed_ms={average:.2f}",
    )


def summarize_result_rows(rows: list[Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    failed_case_ids: list[str] = []
    for row in rows:
        example = _member(row, "example")
        run = _member(row, "run")
        evaluation_results = _member(row, "evaluation_results")
        example_inputs = _dict(_member(example, "inputs"))
        case_record = _dict(example_inputs.get("case"))
        case_id = str(case_record.get("id") or _member(example, "id") or "")
        run_outputs = _dict(_member(run, "outputs"))
        results = list(_member(evaluation_results, "results") or [])
        eval_payload = [
            {
                "key": getattr(result, "key", ""),
                "score": getattr(result, "score", None),
                "value": getattr(result, "value", None),
                "comment": getattr(result, "comment", None),
            }
            for result in results
        ]
        row_error = str(run_outputs.get("error") or "").strip()
        passed = not row_error and bool(results) and all(
            _evaluation_result_passes(result) for result in results
        )
        if not passed:
            failed_case_ids.append(case_id)
        records.append(
            {
                "case_id": case_id,
                "title": case_record.get("title"),
                "mode": case_record.get("mode"),
                "passed": passed,
                "assistant_response": run_outputs.get("assistant_response"),
                "elapsed_ms": run_outputs.get("elapsed_ms"),
                "error": row_error or None,
                "evaluations": eval_payload,
            }
        )
    total_cases = len(records)
    passed_cases = sum(1 for record in records if record["passed"])
    return {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_case_ids": failed_case_ids,
        "records": records,
    }


def _build_llm_judge(
    *,
    judge_model: str | None,
    env_path: str | Path,
    client: Any | None,
) -> Callable[[str, str], tuple[bool | None, str]]:
    config = load_runtime_config(env_path=env_path)
    model = judge_model or os.environ.get("AMADEUS_EVAL_JUDGE_MODEL") or config.provider.model
    provider = LLMProvider(config.provider, client=client)

    def _judge(answer: str, rubric: str) -> tuple[bool | None, str]:
        response = asyncio.run(
            provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are an evaluation judge. Return strict JSON only.",
                    },
                    {
                        "role": "user",
                        "content": (
                            "Evaluate whether the answer satisfies the rubric.\n"
                            f"Rubric:\n{rubric}\n\n"
                            f"Answer:\n{answer}\n\n"
                            'Return JSON: {"pass": true|false, "comment": "..."}'
                        ),
                    },
                ],
                model=model,
                max_tokens=256,
                disable_thinking=True,
            )
        )
        payload = _parse_json_object(str(response.content or ""))
        if "pass" not in payload:
            return None, "skipped because judge returned unparsable output"
        passed = _bool_value(payload.get("pass"))
        comment = str(payload.get("comment") or "").strip() or "no judge comment"
        return passed, comment

    return _judge


def _member(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "pass", "passed"}
    return bool(value)


def _run_outputs(run: Any) -> dict[str, Any]:
    return _dict(getattr(run, "outputs", None))


def _example_expect(example: Any) -> dict[str, Any]:
    outputs = _dict(getattr(example, "outputs", None))
    return _dict(outputs.get("expect"))


def _response_text(outputs: dict[str, Any]) -> str:
    assistant_response = str(outputs.get("assistant_response") or "").strip()
    if assistant_response:
        return assistant_response
    memory_sections: list[str] = []
    for title, key in (
        ("Written memories", "written_memories"),
        ("Active memories", "active_memories"),
        ("Superseded memories", "superseded_memories"),
    ):
        memories = outputs.get(key)
        if isinstance(memories, list):
            lines = _memory_summaries(memories)
            if lines:
                memory_sections.append(f"{title}:\n" + "\n".join(f"- {line}" for line in lines))
    memory_text = "\n\n".join(memory_sections).strip()
    if memory_text:
        return memory_text
    items = outputs.get("recall_items")
    if not isinstance(items, list):
        return ""
    return "\n".join(
        str(item.get("summary") or "")
        for item in items
        if isinstance(item, dict)
    ).strip()


def _evaluation_result_passes(result: Any) -> bool:
    value = getattr(result, "value", None)
    if value == "skipped":
        return False
    score = getattr(result, "score", None)
    if isinstance(score, bool):
        return score
    if isinstance(score, (int, float)):
        return score > 0
    return False


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _memory_summaries(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item.get("summary") or "").strip()
        for item in value
        if isinstance(item, dict) and str(item.get("summary") or "").strip()
    ]


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0
