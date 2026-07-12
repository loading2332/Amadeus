from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

METRICS = (
    "recall_at_8",
    "all_required_recalled_at_8",
    "precision_at_8",
    "mrr_at_8",
    "ndcg_at_8",
)
PRACTICAL_EQUIVALENCE = 1 / 18


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-markdown", required=True)
    parser.add_argument("--baseline", default="amadeus-baseline")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20_260_712)
    args = parser.parse_args()

    if args.bootstrap_samples <= 0:
        raise ValueError("--bootstrap-samples must be positive")
    payload = _object(
        json.loads(Path(args.results).read_text(encoding="utf-8")),
        label="holdout results",
    )
    if payload.get("stage") != 5 or payload.get("split") != "holdout":
        raise ValueError("comparison requires Stage 5 holdout results")
    if payload.get("formal") is not True:
        raise ValueError("comparison requires a formal holdout run")

    raw_results = payload.get("results")
    if not isinstance(raw_results, list) or len(raw_results) < 2:
        raise ValueError("comparison requires a baseline and at least one candidate")
    result_by_name = {
        _profile_name(result): _object(result, label="profile result")
        for result in raw_results
    }
    baseline = result_by_name.get(args.baseline)
    if baseline is None:
        raise ValueError(f"baseline profile not found: {args.baseline}")

    family_metrics = {
        name: _family_metrics(result) for name, result in result_by_name.items()
    }
    family_ids = tuple(sorted(family_metrics[args.baseline]))
    if len(family_ids) != 18:
        raise ValueError("holdout comparison requires exactly 18 families")
    for name, metrics in family_metrics.items():
        if tuple(sorted(metrics)) != family_ids:
            raise ValueError(f"profile family set drifted: {name}")

    comparisons = []
    for name in result_by_name:
        if name == args.baseline:
            continue
        comparisons.append(
            _compare_profile(
                baseline_name=args.baseline,
                candidate_name=name,
                baseline=family_metrics[args.baseline],
                candidate=family_metrics[name],
                family_ids=family_ids,
                bootstrap_samples=args.bootstrap_samples,
                seed=args.seed,
            )
        )

    output = {
        "version": 1,
        "dataset_hash": payload.get("dataset_hash"),
        "experiment_id": payload.get("experiment_id"),
        "practical_equivalence_threshold": PRACTICAL_EQUIVALENCE,
        "bootstrap_samples": args.bootstrap_samples,
        "bootstrap_seed": args.seed,
        "profiles": [
            _profile_summary(name, result)
            for name, result in result_by_name.items()
        ],
        "comparisons": comparisons,
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    Path(args.output_markdown).write_text(
        _render_markdown(output),
        encoding="utf-8",
    )
    return 0


def _profile_name(raw: Any) -> str:
    result = _object(raw, label="profile result")
    profile = _object(result.get("profile"), label="profile")
    name = profile.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("profile requires a name")
    return name


def _family_metrics(result: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    raw_queries = result.get("queries")
    if not isinstance(raw_queries, list):
        raise ValueError("profile result requires queries")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw_query in raw_queries:
        query = _object(raw_query, label="query result")
        family_id = query.get("family_id")
        if not isinstance(family_id, str) or not family_id:
            raise ValueError("query result requires family_id")
        grouped[family_id].append(_object(query.get("metrics"), label="query metrics"))

    output: dict[str, dict[str, float | None]] = {}
    for family_id, variants in grouped.items():
        output[family_id] = {
            metric: _mean_optional(variant.get(metric) for variant in variants)
            for metric in METRICS
        }
    return output


def _mean_optional(values: Any) -> float | None:
    present: list[float] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            present.append(float(value))
        elif isinstance(value, (int, float)):
            present.append(float(value))
        else:
            raise ValueError("metric values must be numeric or null")
    return fmean(present) if present else None


def _compare_profile(
    *,
    baseline_name: str,
    candidate_name: str,
    baseline: dict[str, dict[str, float | None]],
    candidate: dict[str, dict[str, float | None]],
    family_ids: tuple[str, ...],
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    family_rows = []
    metric_differences: dict[str, list[float]] = {metric: [] for metric in METRICS}
    for family_id in family_ids:
        row: dict[str, Any] = {"family_id": family_id}
        for metric in METRICS:
            baseline_value = baseline[family_id][metric]
            candidate_value = candidate[family_id][metric]
            if (baseline_value is None) != (candidate_value is None):
                raise ValueError(
                    f"metric availability drifted for {family_id}/{metric}"
                )
            if baseline_value is None:
                difference = None
            else:
                assert candidate_value is not None
                difference = candidate_value - baseline_value
            row[metric] = {
                "baseline": baseline_value,
                "candidate": candidate_value,
                "difference": difference,
            }
            if difference is not None:
                metric_differences[metric].append(difference)
        family_rows.append(row)

    metric_summary = {}
    for metric, differences in metric_differences.items():
        point_difference = fmean(differences)
        lower, upper = _bootstrap_interval(
            differences,
            samples=bootstrap_samples,
            seed=_metric_seed(seed, candidate_name, metric),
        )
        metric_summary[metric] = {
            "evaluable_family_count": len(differences),
            "point_difference": point_difference,
            "bootstrap_95_lower": lower,
            "bootstrap_95_upper": upper,
        }

    recall_difference = metric_summary["recall_at_8"]["point_difference"]
    return {
        "baseline": baseline_name,
        "candidate": candidate_name,
        "recall_practically_equivalent": (
            abs(recall_difference) < PRACTICAL_EQUIVALENCE
        ),
        "metric_summary": metric_summary,
        "families": family_rows,
    }


def _bootstrap_interval(
    values: list[float],
    *,
    samples: int,
    seed: int,
) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap requires at least one paired value")
    rng = random.Random(seed)
    size = len(values)
    means = sorted(
        fmean(values[rng.randrange(size)] for _ in range(size))
        for _ in range(samples)
    )
    lower_index = int(0.025 * (samples - 1))
    upper_index = int(0.975 * (samples - 1))
    return means[lower_index], means[upper_index]


def _metric_seed(seed: int, candidate: str, metric: str) -> int:
    text = f"{candidate}\0{metric}".encode()
    return seed + int.from_bytes(hashlib.sha256(text).digest()[:8], "big")


def _profile_summary(name: str, result: dict[str, Any]) -> dict[str, Any]:
    aggregate = _object(result.get("aggregate"), label="aggregate")
    overall = _object(aggregate.get("overall"), label="overall aggregate")
    values = _object(overall.get("values"), label="overall values")
    queries = result.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("profile result requires non-empty queries")
    return {
        "name": name,
        "hard_gate_passed": result.get("hard_gate_passed") is True,
        "metrics": {metric: values.get(metric) for metric in METRICS},
        "dangerous_hit_at_8": values.get("dangerous_hit_at_8"),
        "no_answer_false_positive": values.get("no_answer_false_positive"),
        "average_candidate_counts": {
            key: fmean(
                float(
                    _object(
                        _object(query, label="query result")
                        .get("trace"),
                        label="query trace",
                    )["candidate_counts"][key]
                )
                for query in queries
            )
            for key in ("vector", "lexical", "union", "final")
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Locked holdout 配对分析",
        "",
        f"- Dataset hash：`{payload['dataset_hash']}`",
        f"- Experiment：`{payload['experiment_id']}`",
        "- Holdout families：`18`",
        "- Practical-equivalence：`1/18 = 5.56pp`",
        f"- Bootstrap：`{payload['bootstrap_samples']}` 次，seed "
        f"`{payload['bootstrap_seed']}`",
        "",
        "## 总体结果",
        "",
        "| Profile | 硬门 | Recall@8 | All required | Precision@8 | MRR@8 | nDCG@8 | Avg union |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for profile in payload["profiles"]:
        metrics = profile["metrics"]
        lines.append(
            "| "
            f"`{profile['name']}` | "
            f"{'通过' if profile['hard_gate_passed'] else '失败'} | "
            f"{_number(metrics['recall_at_8'])} | "
            f"{_number(metrics['all_required_recalled_at_8'])} | "
            f"{_number(metrics['precision_at_8'])} | "
            f"{_number(metrics['mrr_at_8'])} | "
            f"{_number(metrics['ndcg_at_8'])} | "
            f"{_number(profile['average_candidate_counts']['union'])} |"
        )

    lines.extend(
        [
            "",
            "## 配对区间",
            "",
            "区间基于同一 family 的 candidate - baseline 差值重采样。Recall 只在有正例的 family 上计算；abstention family 不进入 Recall 分母。",
            "",
            "| Candidate | Recall Δ / 95% CI | MRR Δ / 95% CI | nDCG Δ / 95% CI | Recall 判定 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for comparison in payload["comparisons"]:
        summary = comparison["metric_summary"]
        lines.append(
            f"| `{comparison['candidate']}` | "
            f"{_interval(summary['recall_at_8'])} | "
            f"{_interval(summary['mrr_at_8'])} | "
            f"{_interval(summary['ndcg_at_8'])} | "
            f"{'相当' if comparison['recall_practically_equivalent'] else '方向性变化'} |"
        )

    for comparison in payload["comparisons"]:
        lines.extend(
            [
                "",
                f"## 逐 family：`{comparison['candidate']}`",
                "",
                "| Family | Baseline R | Candidate R | ΔR | ΔMRR | ΔnDCG |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in comparison["families"]:
            lines.append(
                f"| `{row['family_id']}` | "
                f"{_number(row['recall_at_8']['baseline'])} | "
                f"{_number(row['recall_at_8']['candidate'])} | "
                f"{_number(row['recall_at_8']['difference'])} | "
                f"{_number(row['mrr_at_8']['difference'])} | "
                f"{_number(row['ndcg_at_8']['difference'])} |"
            )
    lines.append("")
    return "\n".join(lines)


def _interval(summary: dict[str, Any]) -> str:
    return (
        f"{_number(summary['point_difference'])} / "
        f"[{_number(summary['bootstrap_95_lower'])}, "
        f"{_number(summary['bootstrap_95_upper'])}]"
    )


def _number(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.4f}"


def _object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
