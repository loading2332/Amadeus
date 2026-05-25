import json
import subprocess
from pathlib import Path

from amadeus.memory_eval.smoke import build_smoke_report


ROOT = Path(__file__).resolve().parents[2]


def test_build_smoke_report_for_locomo_real_data() -> None:
    report = build_smoke_report(
        dataset="locomo",
        benchmark_root=ROOT / "memorybenchmarks",
        limit=1,
    )

    assert report["dataset"] == "locomo"
    assert report["status"] == "ok"
    assert report["case_count"] == 1
    assert report["cases"][0]["case_id"].startswith("conv-26:qa:")
    assert report["cases"][0]["artifact_count"] > 0
    assert report["cases"][0]["native_payload_keys"] == ["qa", "qa_index", "sample", "sample_id"]


def test_build_smoke_report_for_missing_personamem_data(tmp_path: Path) -> None:
    report = build_smoke_report(
        dataset="personamem",
        benchmark_root=tmp_path,
        limit=1,
    )

    assert report["dataset"] == "personamem"
    assert report["status"] == "missing_data"
    assert "questions_32k.csv" in report["missing_paths"][0]
    assert "HuggingFace" in report["prepare_hint"]


def test_smoke_cli_prints_json() -> None:
    completed = subprocess.run(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            "-m",
            "amadeus.memory_eval.smoke",
            "--dataset",
            "locomo",
            "--benchmark-root",
            str(ROOT / "memorybenchmarks"),
            "--limit",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["dataset"] == "locomo"
    assert payload["status"] == "ok"
