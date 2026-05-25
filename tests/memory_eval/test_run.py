import json
import subprocess
from pathlib import Path

from amadeus.memory_eval.run import build_run_report, run_grouped_eval
from amadeus.memory_eval.trace_io import load_trace_jsonl


ROOT = Path(__file__).resolve().parents[2]


def test_run_grouped_eval_writes_trace_jsonl_for_locomo(tmp_path: Path) -> None:
    output_path = tmp_path / "locomo-traces.jsonl"

    traces = run_grouped_eval(
        dataset="locomo",
        benchmark_root=ROOT / "memorybenchmarks",
        strategy_name="lexical",
        group_limit=1,
        output_path=output_path,
    )

    loaded = list(load_trace_jsonl(output_path))
    assert traces
    assert len(loaded) == len(traces)
    assert loaded[0].dataset_name == "locomo"
    assert loaded[0].group_id == "conv-26"
    assert loaded[0].memory_strategy == "lexical"
    assert loaded[0].artifact_ids_indexed
    assert loaded[0].score is not None
    assert loaded[0].score_details["scorer"] == "locomo_qa_f1_approx"


def test_build_run_report_summarizes_trace_output(tmp_path: Path) -> None:
    output_path = tmp_path / "locomo-traces.jsonl"

    report = build_run_report(
        dataset="locomo",
        benchmark_root=ROOT / "memorybenchmarks",
        strategy_name="lexical",
        group_limit=1,
        output_path=output_path,
    )

    assert report["dataset"] == "locomo"
    assert report["strategy"] == "lexical"
    assert report["status"] == "ok"
    assert report["group_count"] == 1
    assert report["trace_count"] > 1
    assert report["output_path"] == str(output_path)
    assert report["scores"]["scored_count"] == report["trace_count"]
    assert "answer_f1" in report["scores"]["mean_score_details"]


def test_run_cli_prints_report_and_writes_jsonl(tmp_path: Path) -> None:
    output_path = tmp_path / "locomo-traces.jsonl"

    completed = subprocess.run(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            "-m",
            "amadeus.memory_eval.run",
            "--dataset",
            "locomo",
            "--benchmark-root",
            str(ROOT / "memorybenchmarks"),
            "--strategy",
            "lexical",
            "--group-limit",
            "1",
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert payload["scores"]["scored_count"] == payload["trace_count"]
    assert output_path.exists()
