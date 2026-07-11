from __future__ import annotations

import asyncio
import hashlib
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
    MemoryRecallCase,
    case_from_record,
    load_memory_recall_cases,
)
from amadeus.evaluation.evaluators import (
    answer_rules_evaluator,
    elapsed_summary_evaluator,
    make_llm_judge_evaluator,
    source_ref_evaluator,
    summarize_result_rows,
    trace_evaluator,
)
from amadeus.evaluation.langsmith_sync import (
    build_langsmith_client,
    sync_memory_recall_dataset,
)
from amadeus.memory.engine import MemoryWriteRequest
from amadeus.session.identity import SessionRef
from amadeus.tools.base import ToolExecutionRequest


@dataclass(frozen=True)
class MemoryRecallEvaluationReport:
    dataset_name: str
    experiment_name: str
    experiment_url: str | None
    total_cases: int
    passed_cases: int
    failed_case_ids: list[str]
    summary_path: Path
    results_path: Path


def run_memory_recall_case(
    case: MemoryRecallCase,
    *,
    env_path: str | Path,
    app_builder: Any = build_passive_app,
    client: Any | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        _run_memory_recall_case_async(
            case,
            env_path=env_path,
            app_builder=app_builder,
            client=client,
        )
    )


def run_memory_recall_evaluation(
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
) -> MemoryRecallEvaluationReport:
    _validate_memory_recall_eval_config(env_path)
    cases = load_memory_recall_cases(case_file)
    langsmith_client = client or build_langsmith_client(env_path=env_path)
    sync_memory_recall_dataset(
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
        return run_memory_recall_case(
            case_from_record(case_payload),
            env_path=env_path,
            app_builder=app_builder,
            client=chat_client,
        )

    experiment = evaluate(
        target,
        data=dataset_name,
        evaluators=[
            trace_evaluator,
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
    summary_path = artifacts_root / f"{timestamp}-memory-recall-summary.md"
    results_path = artifacts_root / f"{timestamp}-memory-recall-results.json"
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
    return MemoryRecallEvaluationReport(
        dataset_name=dataset_name,
        experiment_name=experiment_name,
        experiment_url=experiment_url,
        total_cases=summary["total_cases"],
        passed_cases=summary["passed_cases"],
        failed_case_ids=list(summary["failed_case_ids"]),
        summary_path=summary_path,
        results_path=results_path,
    )


def _validate_memory_recall_eval_config(env_path: str | Path) -> None:
    config = load_runtime_config(env_path=env_path)
    if not config.long_term_memory_enabled:
        raise ValueError(
            "memory recall evaluation requires AMADEUS_LONG_TERM_MEMORY_ENABLED=1"
        )


async def _run_memory_recall_case_async(
    case: MemoryRecallCase,
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
            source_session = _eval_session_ref(case.id, kind="source")
            source_message_ids = _seed_session_messages(
                app,
                session=source_session,
                case=case,
            )
            await _seed_long_term_memories(app, case, source_message_ids)
            if case.mode == "runtime_turn":
                output = await _run_runtime_turn_case(app, case)
            elif case.mode == "recall_tool":
                output = await _run_recall_tool_case(app, case)
            else:  # pragma: no cover - guarded by case parser
                raise ValueError(f"unsupported case mode: {case.mode}")
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
    session: SessionRef,
    case: MemoryRecallCase,
) -> list[str]:
    turn_session = app.session_manager.get_or_create(session)
    for message in case.seed_session_messages:
        extra: dict[str, Any] = {}
        if message.timestamp is not None:
            extra["timestamp"] = message.timestamp
        turn_session.add_message(message.role, message.content, **extra)
    app.session_manager.save(turn_session)
    return [str(message.get("id") or "") for message in turn_session.messages]


async def _seed_long_term_memories(
    app: PassiveApp,
    case: MemoryRecallCase,
    source_message_ids: list[str],
) -> None:
    memory_engine = app.runtime.memory_engine
    if memory_engine is None:
        raise ValueError(
            "memory recall evaluation requires AMADEUS_LONG_TERM_MEMORY_ENABLED=1"
        )
    for memory in case.seed_long_term_memories:
        source_ref = memory.source_ref or _source_ref_from_indexes(
            case.id,
            source_message_ids,
            memory.source_message_indexes,
        )
        happened_at = memory.happened_at or _happened_at_from_source_indexes(
            case,
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


async def _run_runtime_turn_case(
    app: PassiveApp,
    case: MemoryRecallCase,
) -> dict[str, Any]:
    result = await app.runtime.run_turn(
        session=_eval_session_ref(case.id, kind="turn"),
        user_message=str(case.input_payload["user_message"]),
    )
    rendered_context = "\n".join(
        str(message.get("content") or "") for message in result.context.messages
    )
    return {
        "assistant_response": result.assistant_response,
        "memory_trace": dict(result.memory_trace),
        "tool_chain": list(result.tool_chain),
        "recall_items": [],
        "fetched_messages": [],
        "source_refs": [],
        "rendered_context": rendered_context,
        "error": None,
    }


def _eval_session_ref(case_id: str, *, kind: str) -> SessionRef:
    digest = hashlib.blake2b(f"{kind}:{case_id}".encode(), digest_size=8).digest()
    session_id = int.from_bytes(digest, "big") & ((1 << 31) - 1)
    return SessionRef(user_id=1, session_id=max(1, session_id))


async def _run_recall_tool_case(
    app: PassiveApp,
    case: MemoryRecallCase,
) -> dict[str, Any]:
    recall_execution = await app.tool_executor.execute(
        ToolExecutionRequest(
            tool_name="recall_memory",
            arguments={"query": str(case.input_payload["recall_query"])},
        )
    )
    recall_result = recall_execution.output
    recall_output = recall_result.output if isinstance(recall_result.output, dict) else {}
    recall_items = recall_output.get("items") if isinstance(recall_output, dict) else []
    source_refs = _collect_source_refs(recall_items if isinstance(recall_items, list) else [])
    fetched_messages: list[dict[str, Any]] = []
    if source_refs:
        fetch_execution = await app.tool_executor.execute(
            ToolExecutionRequest(
                tool_name="fetch_messages",
                arguments={"source_refs": source_refs},
            )
        )
        fetch_result = fetch_execution.output
        if isinstance(fetch_result.output, dict):
            raw_messages = fetch_result.output.get("messages")
            if isinstance(raw_messages, list):
                fetched_messages = [
                    message for message in raw_messages if isinstance(message, dict)
                ]
    return {
        "assistant_response": "",
        "memory_trace": dict(recall_output.get("trace", {})),
        "tool_chain": [],
        "recall_items": recall_items if isinstance(recall_items, list) else [],
        "fetched_messages": fetched_messages,
        "source_refs": source_refs,
        "rendered_context": "",
        "error": recall_output.get("error") if recall_result.is_error else None,
    }


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
    case: MemoryRecallCase,
    indexes: tuple[int, ...],
) -> str | None:
    for index in indexes:
        if 0 <= index < len(case.seed_session_messages):
            return case.seed_session_messages[index].timestamp
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
            "# Memory Recall Evaluation",
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
