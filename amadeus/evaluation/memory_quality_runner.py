from __future__ import annotations

import asyncio
import json
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from langsmith import Client, evaluate

from amadeus.app.bootstrap import PassiveApp, build_passive_app, load_runtime_config
from amadeus.evaluation.cases import (
    MemoryQualityCase,
    load_memory_quality_cases,
    quality_case_from_record,
)
from amadeus.evaluation.evaluators import (
    answer_rules_evaluator,
    conflict_evaluator,
    elapsed_summary_evaluator,
    make_llm_judge_evaluator,
    memory_type_evaluator,
    source_ref_evaluator,
    summarize_result_rows,
    write_absence_evaluator,
    write_presence_evaluator,
)
from amadeus.evaluation.langsmith_sync import (
    build_langsmith_client,
    sync_memory_quality_dataset,
)
from amadeus.memory.engine import MemoryWriteRequest


@dataclass(frozen=True)
class MemoryQualityEvaluationReport:
    dataset_name: str
    experiment_name: str
    experiment_url: str | None
    total_cases: int
    passed_cases: int
    failed_case_ids: list[str]
    summary_path: Path
    results_path: Path


def run_memory_quality_case(
    case: MemoryQualityCase,
    *,
    env_path: str | Path,
    app_builder: Any = build_passive_app,
    client: Any | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        _run_memory_quality_case_async(
            case,
            env_path=env_path,
            app_builder=app_builder,
            client=client,
        )
    )


def run_memory_quality_evaluation(
    *,
    env_path: str | Path,
    case_file: str | Path,
    dataset_name: str,
    experiment_prefix: str,
    judge_model: str | None = None,
    artifacts_dir: str | Path = Path("runtime-artifacts") / "evaluation",
    client: Client | Any | None = None,
    app_builder: Any = build_passive_app,
    client_factory: Any | None = None,
    judge_client: Any | None = None,
) -> MemoryQualityEvaluationReport:
    _validate_memory_quality_eval_config(env_path)
    cases = load_memory_quality_cases(case_file)
    langsmith_client = client or build_langsmith_client(env_path=env_path)
    sync_memory_quality_dataset(
        cases,
        dataset_name=dataset_name,
        env_path=env_path,
        client=langsmith_client,
    )

    def target(inputs: dict[str, Any]) -> dict[str, Any]:
        case_payload = inputs.get("case")
        if not isinstance(case_payload, dict):
            raise ValueError("LangSmith example inputs must contain a 'case' object")
        chat_client = client_factory() if client_factory is not None else None
        return run_memory_quality_case(
            quality_case_from_record(case_payload),
            env_path=env_path,
            app_builder=app_builder,
            client=chat_client,
        )

    experiment = evaluate(
        target,
        data=dataset_name,
        evaluators=[
            write_presence_evaluator,
            write_absence_evaluator,
            memory_type_evaluator,
            conflict_evaluator,
            source_ref_evaluator,
            answer_rules_evaluator,
            make_llm_judge_evaluator(
                judge_model=judge_model,
                env_path=env_path,
                client=judge_client,
            ),
        ],
        summary_evaluators=[elapsed_summary_evaluator],
        experiment_prefix=experiment_prefix,
        client=langsmith_client,
        blocking=True,
        upload_results=True,
        max_concurrency=1,
    )
    experiment.wait()
    rows = list(experiment)
    summary = summarize_result_rows(rows)
    artifacts_root = Path(artifacts_dir)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    summary_path = artifacts_root / f"{timestamp}-memory-quality-summary.md"
    results_path = artifacts_root / f"{timestamp}-memory-quality-results.json"
    experiment_name = str(getattr(experiment, "experiment_name", "") or "")
    experiment_url = getattr(experiment, "url", None)
    results_payload = {
        "dataset_name": dataset_name,
        "experiment_name": experiment_name,
        "experiment_url": experiment_url,
        **summary,
    }
    results_path.write_text(
        json.dumps(results_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(
        _render_summary_markdown(
            dataset_name=dataset_name,
            experiment_name=experiment_name,
            experiment_url=experiment_url,
            total_cases=summary["total_cases"],
            passed_cases=summary["passed_cases"],
            failed_case_ids=summary["failed_case_ids"],
        ),
        encoding="utf-8",
    )
    return MemoryQualityEvaluationReport(
        dataset_name=dataset_name,
        experiment_name=experiment_name,
        experiment_url=experiment_url,
        total_cases=summary["total_cases"],
        passed_cases=summary["passed_cases"],
        failed_case_ids=list(summary["failed_case_ids"]),
        summary_path=summary_path,
        results_path=results_path,
    )


def _validate_memory_quality_eval_config(env_path: str | Path) -> None:
    config = load_runtime_config(env_path=env_path)
    if not config.long_term_memory_enabled:
        raise ValueError(
            "memory quality evaluation requires AMADEUS_LONG_TERM_MEMORY_ENABLED=1"
        )


async def _run_memory_quality_case_async(
    case: MemoryQualityCase,
    *,
    env_path: str | Path,
    app_builder: Any,
    client: Any | None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    with tempfile.TemporaryDirectory(
        prefix=f"amadeus-eval-{case.id}-",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        workspace_root = Path(temp_dir)
        app = app_builder(
            workspace_root=workspace_root,
            env_path=env_path,
            client=client,
        )
        if not isinstance(app, PassiveApp):
            raise TypeError("evaluation app_builder must return PassiveApp")
        try:
            await app.start()
            source_session_key = f"eval-source:{case.id}"
            source_message_ids = _seed_session_messages(
                app,
                session_key=source_session_key,
                messages=case.seed_session_messages,
            )
            await _seed_long_term_memories(app, case, source_message_ids)
            output = await _run_write_case(
                app,
                case,
            )
        finally:
            await app.aclose()
            memory_engine = app.runtime.memory_engine
            if memory_engine is not None:
                memory_engine.store.close()
    output["elapsed_ms"] = int((time.perf_counter() - started_at) * 1000)
    return output


def _seed_session_messages(
    app: PassiveApp,
    *,
    session_key: str,
    messages: tuple[Any, ...],
) -> list[str]:
    session = app.session_manager.get_or_create(session_key)
    for message in messages:
        extra: dict[str, Any] = {}
        if message.timestamp is not None:
            extra["timestamp"] = message.timestamp
        session.add_message(message.role, message.content, **extra)
    app.session_manager.save(session)
    return [str(message.get("id") or "") for message in session.messages]


async def _seed_long_term_memories(
    app: PassiveApp,
    case: MemoryQualityCase,
    source_message_ids: list[str],
) -> None:
    memory_engine = app.runtime.memory_engine
    if memory_engine is None:
        raise ValueError(
            "memory quality evaluation requires AMADEUS_LONG_TERM_MEMORY_ENABLED=1"
        )
    for memory in case.seed_long_term_memories:
        source_ref = memory.source_ref or _source_ref_from_indexes(
            case.id,
            source_message_ids,
            memory.source_message_indexes,
        )
        happened_at = memory.happened_at or _happened_at_from_source_indexes(
            case.seed_session_messages,
            memory.source_message_indexes,
        )
        await memory_engine.memorize(
            MemoryWriteRequest(
                summary=memory.summary,
                memory_type=memory.memory_type,
                source_ref=source_ref,
                happened_at=happened_at,
                extra=dict(memory.extra),
            )
        )


async def _run_write_case(
    app: PassiveApp,
    case: MemoryQualityCase,
) -> dict[str, Any]:
    memory_engine = app.runtime.memory_engine
    if memory_engine is None:
        raise ValueError(
            "memory quality evaluation requires AMADEUS_LONG_TERM_MEMORY_ENABLED=1"
        )
    turn_session_key = f"eval-turn:{case.id}"
    _seed_session_messages(
        app,
        session_key=turn_session_key,
        messages=case.turn_messages,
    )
    turn_session = app.session_manager.get_or_create(turn_session_key)
    write_trace = await memory_engine.run_post_response(
        session_key=turn_session_key,
        messages=list(turn_session.messages),
        explicit_memory_ids=[],
    )

    written_ids = [
        str(item_id).strip()
        for item_id in write_trace.get("written_ids", [])
        if str(item_id).strip()
    ]
    written_memories = memory_engine.store.get_items_by_ids(written_ids)
    active_memories = memory_engine.store.list_active_items()
    superseded_memories = _collect_superseded_memories(
        memory_engine.store,
        case=case,
        written_memories=written_memories,
    )

    recall_items: list[dict[str, Any]] = []
    fetched_messages: list[dict[str, Any]] = []
    source_refs = _collect_source_refs_from_memories(written_memories)
    memory_trace: dict[str, Any] = {}
    if case.mode == "write_then_recall":
        recall_result, _recall_trace = await app.tool_executor.execute_async(
            "recall_memory",
            {"query": str(case.input_payload["recall_query"])},
        )
        recall_output = (
            recall_result.output if isinstance(recall_result.output, dict) else {}
        )
        raw_items = recall_output.get("items")
        recall_items = raw_items if isinstance(raw_items, list) else []
        memory_trace = dict(recall_output.get("trace", {}))
        source_refs = _collect_source_refs(recall_items)
        if source_refs:
            fetch_result, _fetch_trace = app.tool_executor.execute(
                "fetch_messages",
                {"source_refs": source_refs},
            )
            if isinstance(fetch_result.output, dict):
                raw_messages = fetch_result.output.get("messages")
                if isinstance(raw_messages, list):
                    fetched_messages = [
                        message for message in raw_messages if isinstance(message, dict)
                    ]

    return {
        "assistant_response": "",
        "write_trace": dict(write_trace),
        "memory_trace": memory_trace,
        "tool_chain": [],
        "active_memories": active_memories,
        "superseded_memories": superseded_memories,
        "written_memories": written_memories,
        "recall_items": recall_items,
        "fetched_messages": fetched_messages,
        "source_refs": source_refs,
        "error": None,
    }


def _collect_superseded_memories(
    store: Any,
    *,
    case: MemoryQualityCase,
    written_memories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    source_refs = {
        str(memory.source_ref or "").strip()
        for memory in case.seed_long_term_memories
        if str(memory.source_ref or "").strip()
    }
    source_refs.update(
        str(item.get("source_ref") or "").strip()
        for item in written_memories
        if str(item.get("source_ref") or "").strip()
    )
    for source_ref in source_refs:
        for item in store.find_items_by_source_ref(source_ref):
            item_id = str(item.get("id") or "").strip()
            if not item_id or item_id in seen_ids:
                continue
            if str(item.get("status") or "") == "active":
                continue
            seen_ids.add(item_id)
            results.append(item)
    return results


def _collect_source_refs(items: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source_ref = str(item.get("source_ref") or "").strip()
        if source_ref and source_ref not in seen:
            seen.add(source_ref)
            result.append(source_ref)
        evidence = item.get("evidence")
        if not isinstance(evidence, list):
            continue
        for ref in evidence:
            if not isinstance(ref, dict):
                continue
            evidence_ref = str(ref.get("source_ref") or "").strip()
            if evidence_ref and evidence_ref not in seen:
                seen.add(evidence_ref)
                result.append(evidence_ref)
    return result


def _collect_source_refs_from_memories(items: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        source_ref = str(item.get("source_ref") or "").strip()
        if source_ref and source_ref not in seen:
            seen.add(source_ref)
            result.append(source_ref)
    return result


def _source_ref_from_indexes(
    case_id: str,
    message_ids: list[str],
    indexes: tuple[int, ...],
) -> str:
    selected_ids: list[str] = []
    for index in indexes:
        if 0 <= index < len(message_ids):
            selected_ids.append(message_ids[index])
    if not selected_ids:
        raise ValueError(f"{case_id}: source_message_indexes resolved to no ids")
    return json.dumps(selected_ids, ensure_ascii=False)


def _happened_at_from_source_indexes(
    messages: tuple[Any, ...],
    indexes: tuple[int, ...],
) -> str | None:
    for index in indexes:
        if 0 <= index < len(messages):
            return messages[index].timestamp
    return None


def _render_summary_markdown(
    *,
    dataset_name: str,
    experiment_name: str,
    experiment_url: str | None,
    total_cases: int,
    passed_cases: int,
    failed_case_ids: list[str],
) -> str:
    failed_text = ", ".join(failed_case_ids) if failed_case_ids else "-"
    url_text = experiment_url or "-"
    return "\n".join(
        [
            "# Memory Quality Evaluation",
            "",
            f"- Dataset: `{dataset_name}`",
            f"- Experiment: `{experiment_name}`",
            f"- LangSmith URL: {url_text}",
            f"- Total cases: {total_cases}",
            f"- Passed cases: {passed_cases}",
            f"- Failed cases: {failed_text}",
            "",
        ]
    )
