from __future__ import annotations

import argparse
from types import SimpleNamespace


def test_run_eval_memory_recall_prints_summary(monkeypatch, capsys, tmp_path):
    from amadeus.app.cli import _run_eval_memory_recall

    captured: dict[str, object] = {}

    def fake_run_memory_recall_evaluation(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            total_cases=3,
            passed_cases=2,
            failed_case_ids=["case-b"],
            experiment_name="amadeus-memory-recall-001",
            experiment_url="https://smith.example.test/e/1",
            summary_path=tmp_path / "summary.md",
            results_path=tmp_path / "results.json",
        )

    monkeypatch.setattr(
        "amadeus.app.cli.run_memory_recall_evaluation",
        fake_run_memory_recall_evaluation,
    )
    args = argparse.Namespace(
        env=tmp_path / ".env",
        case_file=tmp_path / "cases.yaml",
        dataset_name="amadeus-memory-recall-v1",
        experiment_prefix="amadeus-memory-recall",
        judge_model=None,
        artifacts_dir=tmp_path / "runtime-artifacts" / "evaluation",
    )

    _run_eval_memory_recall(args)

    output = capsys.readouterr().out
    assert captured["dataset_name"] == "amadeus-memory-recall-v1"
    assert "Total cases: 3" in output
    assert "Passed cases: 2" in output
    assert "Failed cases: case-b" in output
    assert "LangSmith experiment: amadeus-memory-recall-001" in output


def test_run_eval_memory_quality_prints_summary(monkeypatch, capsys, tmp_path):
    from amadeus.app.cli import _run_eval_memory_quality

    captured: dict[str, object] = {}

    def fake_run_memory_quality_evaluation(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            total_cases=5,
            passed_cases=3,
            failed_case_ids=["quality-b", "quality-c"],
            experiment_name="amadeus-memory-quality-001",
            experiment_url="https://smith.example.test/e/quality-1",
            summary_path=tmp_path / "quality-summary.md",
            results_path=tmp_path / "quality-results.json",
        )

    monkeypatch.setattr(
        "amadeus.app.cli.run_memory_quality_evaluation",
        fake_run_memory_quality_evaluation,
    )
    args = argparse.Namespace(
        env=tmp_path / ".env",
        case_file=tmp_path / "quality-cases.yaml",
        dataset_name="amadeus-memory-quality-v1",
        experiment_prefix="amadeus-memory-quality",
        judge_model=None,
        artifacts_dir=tmp_path / "runtime-artifacts" / "evaluation",
    )

    _run_eval_memory_quality(args)

    output = capsys.readouterr().out
    assert captured["dataset_name"] == "amadeus-memory-quality-v1"
    assert "Total cases: 5" in output
    assert "Passed cases: 3" in output
    assert "Failed cases: quality-b, quality-c" in output
    assert "LangSmith experiment: amadeus-memory-quality-001" in output
