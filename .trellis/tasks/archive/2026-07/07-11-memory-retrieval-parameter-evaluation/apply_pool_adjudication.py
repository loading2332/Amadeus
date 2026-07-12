from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--source-dataset-hash", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--approved-at", default=date.today().isoformat())
    parser.add_argument("--expected-count", type=int)
    args = parser.parse_args()

    proposal_path = Path(args.proposal)
    proposal = _object(
        json.loads(proposal_path.read_text(encoding="utf-8")),
        label="proposal",
    )
    if proposal.get("review_status") != "draft":
        raise ValueError("proposal must be draft before user approval is recorded")
    expected_hash = proposal.get("dataset_hash_before_adjudication")
    if expected_hash != args.source_dataset_hash:
        raise ValueError("proposal dataset hash does not match the approved source hash")

    proposal_round = proposal.get("proposal_round", "primary")
    if proposal_round not in {
        "primary",
        "supplemental-1",
        "supplemental-2",
        "supplemental-3",
        "supplemental-4",
        "supplemental-5",
        "holdout-supplemental-1",
    }:
        raise ValueError(
            "proposal_round must be primary or an approved supplemental round"
        )
    proposal_expected_count = proposal.get("expected_adjudication_count")
    if proposal_expected_count is None and proposal_round == "primary":
        proposal_expected_count = 280
    if (
        isinstance(proposal_expected_count, bool)
        or not isinstance(proposal_expected_count, int)
        or proposal_expected_count <= 0
    ):
        raise ValueError("proposal requires a positive expected_adjudication_count")
    if args.expected_count is not None and args.expected_count != proposal_expected_count:
        raise ValueError("--expected-count disagrees with the proposal")
    expected_count = args.expected_count or proposal_expected_count
    split = proposal.get("split", "development")
    if split not in {"development", "holdout"}:
        raise ValueError("proposal split must be development or holdout")
    expected_split = (
        "holdout" if proposal_round == "holdout-supplemental-1" else "development"
    )
    if split != expected_split:
        raise ValueError(f"{proposal_round} proposal must use split={expected_split}")

    raw_adjudications = proposal.get("adjudications")
    if (
        not isinstance(raw_adjudications, list)
        or len(raw_adjudications) != expected_count
    ):
        raise ValueError(
            f"approved {proposal_round} pool must contain {expected_count} adjudications"
        )
    judgments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_adjudications):
        item = _object(raw, label=f"adjudications[{index}]")
        query_id = _string(item.get("query_id"), label="query_id")
        memory_key = _string(item.get("memory_key"), label="memory_key")
        marker = (query_id, memory_key)
        if marker in seen:
            raise ValueError(f"duplicate adjudication: {marker}")
        seen.add(marker)
        relevance = item.get("proposed_relevance")
        dangerous = item.get("proposed_dangerous")
        danger_reasons = item.get("proposed_danger_reasons")
        if isinstance(relevance, bool) or not isinstance(relevance, int):
            raise ValueError(f"{marker}: relevance must be an integer")
        if relevance < 0 or relevance > 3:
            raise ValueError(f"{marker}: relevance must be between 0 and 3")
        if not isinstance(dangerous, bool):
            raise ValueError(f"{marker}: dangerous must be boolean")
        if not isinstance(danger_reasons, list) or not all(
            isinstance(reason, str) and reason.strip() for reason in danger_reasons
        ):
            raise ValueError(f"{marker}: danger reasons must be strings")
        if dangerous != bool(danger_reasons):
            raise ValueError(f"{marker}: dangerous and danger reasons disagree")
        judgments.append(
            {
                "query_id": query_id,
                "memory_key": memory_key,
                "relevance": relevance,
                "dangerous": dangerous,
                "danger_reasons": danger_reasons,
                "rationale": _string(
                    item.get("proposed_rationale"),
                    label="proposed_rationale",
                ),
            }
        )

    output_version = f"memory-retrieval-v1-{split}-pool-qrels"
    if proposal_round == "holdout-supplemental-1":
        output_version = f"{output_version}-supplemental-1"
    elif proposal_round != "primary":
        output_version = f"{output_version}-{proposal_round}"
    output = {
        "version": output_version,
        "overlay_id": proposal_round,
        "review_status": "approved",
        "split": split,
        "approved_by": _string(args.approved_by, label="approved_by"),
        "approved_at": _string(args.approved_at, label="approved_at"),
        "source_dataset_hash": expected_hash,
        "source_proposal": {
            "file": proposal_path.name,
            "sha256": hashlib.sha256(proposal_path.read_bytes()).hexdigest(),
            "version": proposal.get("version"),
            "proposal_round": proposal_round,
            "source_pools": [
                {
                    "file": Path(pool["path"]).name,
                    "artifact_group": _artifact_group(Path(pool["path"])),
                    "sha256": pool["sha256"],
                }
                for pool in proposal.get("source_pools", [])
                if isinstance(pool, dict)
                and isinstance(pool.get("path"), str)
                and isinstance(pool.get("sha256"), str)
            ],
        },
        "judgments": judgments,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    try:
        temp_path.write_text(
            yaml.safe_dump(output, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        written = yaml.safe_load(temp_path.read_text(encoding="utf-8"))
        if written != output:
            raise ValueError("approved qrels overlay failed round-trip validation")
        temp_path.replace(output_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return 0


def _object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _artifact_group(path: Path) -> str:
    if path.parent.name in {"completeness", "formal"}:
        return path.parent.parent.name
    return path.parent.name


if __name__ == "__main__":
    raise SystemExit(main())
