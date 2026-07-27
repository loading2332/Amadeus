"""abstention 置信度门的校准验证运行（development split，informal）。

四组 profile 在冻结基准上对照：

  0. gate-off        floor=0.0（当前生产行为）
  1. f045-c070       floor=0.45, confident=0.70
  2. f050-c070       floor=0.50, confident=0.70
  3. f050-c075       floor=0.50, confident=0.75

除既有指标（Recall/MRR/nDCG/硬门）外，运行后从 results JSON 后处理统计：
无答案查询误注入条数、有答案查询无关/相关注入条数、灰区(uncertain)条数。

口径与 run_retrieval_ablation.py 相同：development split、池化假设补
relevance=0 临时 judgment、不触碰 locked holdout。

用法：
  .venv/Scripts/python.exe scripts/run_abstention_calibration.py \
      --cache C:/Users/Zinc/.amadeus/evaluation/memory-retrieval-v1/text-embedding-v4-1024.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from amadeus.app.bootstrap import load_runtime_config
from amadeus.db import PostgresConfig, PostgresDatabase, normalize_psycopg_dsn
from amadeus.evaluation.embedding_cache import (
    FileEmbeddingCacheProvider,
    benchmark_embedding_input_hash,
)
from amadeus.evaluation.memory_retrieval_benchmark import (
    load_memory_retrieval_benchmark,
)
from amadeus.evaluation.memory_retrieval_cli import (
    _embedding_identity,
    _parse_ranking_time,
    _required_embedding_model,
)
from amadeus.evaluation.memory_retrieval_experiment import (
    MemoryRetrievalExperimentProfile,
    run_memory_retrieval_experiment,
)
from amadeus.memory.retrieval_parameters import MemoryRetrievalParameters
from run_retrieval_ablation import pad_unjudged_pairs  # 复用池化补标

DEFAULT_BENCHMARK = "tests/evaluation/cases/memory_retrieval_benchmark_v1.yaml"
DEFAULT_ARTIFACTS = "runtime-artifacts/evaluation/abstention-gate"
FROZEN_RANKING_TIME = "2026-07-12T04:00:00+00:00"


def build_profiles() -> tuple[MemoryRetrievalExperimentProfile, ...]:
    # gate-off 基线必须显式关门：默认参数自 2026-07-27 起已开启校准值
    # （floor=0.50 / confident=0.70），不能再依赖默认值表达"关门"。
    off = replace(
        MemoryRetrievalParameters(),
        abstention_semantic_floor=0.0,
        abstention_confident_semantic=1.0,
    )

    def gate(floor: float, confident: float) -> MemoryRetrievalParameters:
        return replace(
            off,
            abstention_semantic_floor=floor,
            abstention_confident_semantic=confident,
        )

    return (
        MemoryRetrievalExperimentProfile(
            name="gate-off",
            parameters=off,
            changed_fields=(
                "abstention_semantic_floor",
                "abstention_confident_semantic",
            ),
        ),
        MemoryRetrievalExperimentProfile(
            name="gate-f045-c070",
            parameters=gate(0.45, 0.70),
            changed_fields=(
                "abstention_semantic_floor",
                "abstention_confident_semantic",
            ),
        ),
        MemoryRetrievalExperimentProfile(
            name="gate-f050-c070",
            parameters=gate(0.50, 0.70),
            changed_fields=(
                "abstention_semantic_floor",
                "abstention_confident_semantic",
            ),
        ),
        MemoryRetrievalExperimentProfile(
            name="gate-f050-c075",
            parameters=gate(0.50, 0.75),
            changed_fields=(
                "abstention_semantic_floor",
                "abstention_confident_semantic",
            ),
        ),
    )


def summarize_injection(results_path: Path, benchmark_path: str) -> list[dict]:
    import yaml

    bench = yaml.safe_load(Path(benchmark_path).read_text(encoding="utf-8"))
    relevant_by = {
        q["id"]: {
            j["memory_key"]
            for j in q.get("judgments", [])
            if j.get("relevance", 0) >= 2 and not j.get("dangerous")
        }
        for q in bench["queries"]
    }
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    rows = []
    for profile_result in payload["results"]:
        abst_items = 0
        ans_rel = 0
        ans_irrel = 0
        uncertain = 0
        for q in profile_result["queries"]:
            is_abst = q["metrics"].get("no_answer_false_positive") is not None
            rel = relevant_by.get(q["query_id"], set())
            for rec in q["ranked_records"]:
                if rec["signals"].get("uncertain"):
                    uncertain += 1
                if is_abst:
                    abst_items += 1
                elif rec["memory_key"] in rel:
                    ans_rel += 1
                else:
                    ans_irrel += 1
        agg = profile_result["aggregate"]["overall"]["values"]
        rows.append(
            {
                "profile": profile_result["profile"]["name"],
                "abst_injected": abst_items,
                "answerable_relevant": ans_rel,
                "answerable_irrelevant": ans_irrel,
                "uncertain": uncertain,
                "recall_at_8": agg.get("recall_at_8"),
                "mrr_at_8": agg.get("mrr_at_8"),
                "ndcg_at_8": agg.get("ndcg_at_8"),
                "hard_gate_passed": agg.get("hard_gate_passed"),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", default=DEFAULT_BENCHMARK)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--cache", required=True)
    parser.add_argument("--dimensions", type=int, default=1024)
    parser.add_argument("--ranking-time", default=FROZEN_RANKING_TIME)
    parser.add_argument("--artifacts", default=DEFAULT_ARTIFACTS)
    args = parser.parse_args()

    benchmark = load_memory_retrieval_benchmark(args.benchmark)
    config = load_runtime_config(env_path=args.env)
    embedding_model = _required_embedding_model(config.embedding_model)
    identity = _embedding_identity(
        base_url=config.embedding_base_url,
        model=embedding_model,
        dimensions=args.dimensions,
    )
    cache = FileEmbeddingCacheProvider(
        args.cache,
        identity=identity,
        dimensions=args.dimensions,
        input_hash=benchmark_embedding_input_hash(benchmark),
    )
    padded_benchmark, _provisional = pad_unjudged_pairs(benchmark, "development")
    db = PostgresDatabase(
        PostgresConfig(dsn=normalize_psycopg_dsn(config.postgres_dsn))
    )
    db.open()
    try:
        report = run_memory_retrieval_experiment(
            padded_benchmark,
            profiles=build_profiles(),
            split="development",
            ranking_time=_parse_ranking_time(args.ranking_time),
            db=db,
            embedding_provider=cache,
            embedding_identity=identity,
            embedding_cache_fingerprint=cache.fingerprint,
            artifacts_dir=Path(args.artifacts),
            formal=False,
            unlock_holdout=False,
            verify_determinism=True,
        )
    finally:
        db.close()

    rows = summarize_injection(report.results_path, args.benchmark)
    header = (
        "profile\tabst注入\t有答案相关\t有答案无关\tuncertain\t"
        "Recall@8\tMRR@8\tnDCG@8\t硬门"
    )
    print(header)
    for row in rows:
        print(
            f"{row['profile']}\t{row['abst_injected']}\t"
            f"{row['answerable_relevant']}\t{row['answerable_irrelevant']}\t"
            f"{row['uncertain']}\t{row['recall_at_8']:.4f}\t"
            f"{row['mrr_at_8']:.4f}\t{row['ndcg_at_8']:.4f}\t"
            f"{row['hard_gate_passed']:.4f}"
        )
    print(f"results={report.results_path.resolve()}")
    print(f"summary={report.summary_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
