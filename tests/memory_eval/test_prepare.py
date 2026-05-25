import json
import subprocess
from pathlib import Path

from amadeus.memory_eval.prepare import get_dataset_preparation_status


ROOT = Path(__file__).resolve().parents[2]


def test_locomo_preparation_status_is_ready_with_cloned_data() -> None:
    status = get_dataset_preparation_status(
        "locomo",
        benchmark_root=ROOT / "memorybenchmarks",
    )

    assert status.dataset == "locomo"
    assert status.status == "ready"
    assert status.ready_for_smoke is True
    assert status.ready_for_official_run is True
    assert status.missing_paths == ()
    assert "data/locomo10.json" in status.notes[0]


def test_personamem_preparation_status_reports_missing_huggingface_files(tmp_path: Path) -> None:
    status = get_dataset_preparation_status("personamem", benchmark_root=tmp_path)

    assert status.dataset == "personamem"
    assert status.status == "missing_data"
    assert status.ready_for_smoke is False
    assert status.ready_for_official_run is False
    assert any("questions_32k.csv" in path for path in status.missing_paths)
    assert any("huggingface.co/datasets/bowen-upenn/PersonaMem" in command for command in status.prepare_commands)


def test_longmemeval_v2_preparation_status_reports_runtime_files(tmp_path: Path) -> None:
    status = get_dataset_preparation_status("longmemeval_v2", benchmark_root=tmp_path)

    assert status.dataset == "longmemeval_v2"
    assert status.status == "missing_data"
    assert status.ready_for_smoke is False
    assert any("runtime_questions.json" in path for path in status.missing_paths)
    assert any("download_data.py" in command for command in status.prepare_commands)
    assert any("materialize" in note.lower() for note in status.notes)


def test_prepare_cli_prints_json_status() -> None:
    completed = subprocess.run(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            "-m",
            "amadeus.memory_eval.prepare",
            "--dataset",
            "personamem",
            "--benchmark-root",
            str(ROOT / "memorybenchmarks"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["dataset"] == "personamem"
    assert payload["status"] == "missing_data"
    assert payload["ready_for_smoke"] is False
