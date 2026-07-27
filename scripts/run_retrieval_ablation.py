"""在冻结的 memory retrieval benchmark 上执行 feature ablation。

四组 profile 逐步叠加检索特性，回答"每个机制贡献多少召回/排序质量"：

  0. vector-raw      仅原始 query 向量检索（无假设、无词法、无热度）
  1. +dual-query     加 event/general 双假设改写
  2. +lexical-rrf    加词法通道与 RRF 融合
  3. full-baseline   加 hotness 融合（= 生产默认参数）

与正式参数实验共享同一冻结 dataset、embedding cache、ranking time 与
PostgreSQL 环境；本脚本只做 development split 的 informal 对照，不触碰
locked holdout，也不改变任何生产默认参数。

口径说明（池化假设）：ablation 配置可能把从未被正式实验召回过、因此没有
人工标注的 memory 排进 top-8。本脚本给所有未标注的 (query, memory) 组合
补 relevance=0 的临时 judgment，使指标可计算：

  - Recall@8 / MRR@8 / nDCG@8 相对冻结 qrels 是精确值（未标注项 gain=0，
    不进入 relevant 集合，也不改变 ideal DCG）；
  - Precision@8 对补标项按不相关计，是下界；
  - 实际进入 top-8 的未标注 pair 会被导出到 unknown-pairs 文件，人工补标
    后可将本结果升级为正式口径。

用法：
  .venv/Scripts/python.exe scripts/run_retrieval_ablation.py \
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
    MemoryRetrievalBenchmark,
    RetrievalJudgment,
    load_memory_retrieval_benchmark,
)
from amadeus.evaluation.memory_retrieval_cli import (
    _embedding_identity,
    _parse_ranking_time,
    _required_embedding_model,
)
from amadeus.evaluation.memory_retrieval_experiment import (
    MemoryRetrievalExperimentProfile,
    _select_search_universe,
    run_memory_retrieval_experiment,
)
from amadeus.memory.retrieval_parameters import MemoryRetrievalParameters

DEFAULT_BENCHMARK = "tests/evaluation/cases/memory_retrieval_benchmark_v1.yaml"
DEFAULT_ARTIFACTS = "runtime-artifacts/evaluation/retrieval-ablation"
FROZEN_RANKING_TIME = "2026-07-12T04:00:00+00:00"
PROVISIONAL_RATIONALE = (
    "ablation provisional: pooled candidate without human judgment, "
    "treated as not relevant until adjudicated"
)

SUMMARY_METRICS = (
    "recall_at_8",
    "mrr_at_8",
    "ndcg_at_8",
    "precision_at_8",
    "strict_lexical_only_recall_at_8",
    "no_answer_false_positive",
    "hard_gate_passed",
)


def build_ablation_profiles() -> tuple[MemoryRetrievalExperimentProfile, ...]:
    # 本消融测量的是检索通道（假设/词法/热度）的贡献，评测口径冻结于
    # abstention 门发布之前；显式关门以保证与已发布 artifact 可复现对照。
    # 门本身的对照见 scripts/run_abstention_calibration.py。
    baseline = replace(
        MemoryRetrievalParameters(),
        abstention_semantic_floor=0.0,
        abstention_confident_semantic=1.0,
    )
    hotness_off = replace(baseline, hotness_alpha=0.0)
    return (
        MemoryRetrievalExperimentProfile(
            name="ablation-0-vector-raw",
            parameters=hotness_off,
            changed_fields=("hotness_alpha",),
            hypothesis_enabled=False,
            lexical_enabled=False,
        ),
        MemoryRetrievalExperimentProfile(
            name="ablation-1-dual-query",
            parameters=hotness_off,
            changed_fields=("hotness_alpha",),
            hypothesis_enabled=True,
            lexical_enabled=False,
        ),
        MemoryRetrievalExperimentProfile(
            name="ablation-2-lexical-rrf",
            parameters=hotness_off,
            changed_fields=("hotness_alpha",),
            hypothesis_enabled=True,
            lexical_enabled=True,
        ),
        MemoryRetrievalExperimentProfile(
            name="ablation-3-full-baseline",
            parameters=baseline,
            hypothesis_enabled=True,
            lexical_enabled=True,
        ),
    )


def pad_unjudged_pairs(
    benchmark: MemoryRetrievalBenchmark,
    split: str,
) -> tuple[MemoryRetrievalBenchmark, dict[str, frozenset[str]]]:
    """为 split 搜索宇宙中未标注的 (query, memory) 组合补 relevance=0 judgment。

    实验的搜索宇宙是该 split 全部 corpus 的合并集合，query 可能召回自身
    corpus 之外的 memory，因此 padding 范围必须与 seeded universe 一致。
    """
    selected_queries, selected_corpora = _select_search_universe(benchmark, split)
    universe_keys: set[str] = set()
    for corpus in selected_corpora:
        universe_keys |= corpus.memory_keys
    selected_ids = {query.id for query in selected_queries}
    provisional: dict[str, frozenset[str]] = {}
    padded_queries = []
    for query in benchmark.queries:
        if query.id not in selected_ids:
            padded_queries.append(query)
            continue
        judged = set(query.judgment_by_key)
        missing = sorted(universe_keys - judged)
        provisional[query.id] = frozenset(missing)
        if not missing:
            padded_queries.append(query)
            continue
        synthetic = tuple(
            RetrievalJudgment(
                memory_key=key,
                relevance=0,
                dangerous=False,
                rationale=PROVISIONAL_RATIONALE,
            )
            for key in missing
        )
        padded_queries.append(
            replace(query, judgments=(*query.judgments, *synthetic))
        )
    return replace(benchmark, queries=tuple(padded_queries)), provisional


def report_unknown_hits(
    profile_results,
    provisional: dict[str, frozenset[str]],
    output_path: Path,
) -> int:
    """导出实际进入 top-8 的未标注 pair，供人工补标。"""
    lines = [
        "# Ablation 未标注 top-8 命中（待人工补标）",
        "",
        "| profile | query_id | memory_key | rank |",
        "|---|---|---|---:|",
    ]
    count = 0
    for profile_result in profile_results:
        profile_name = profile_result["profile"]["name"]
        for query_result in profile_result["queries"]:
            query_id = query_result["query_id"]
            unlabeled = provisional.get(query_id, frozenset())
            for rank, key in enumerate(
                query_result["final_memory_keys"], start=1
            ):
                if key in unlabeled:
                    lines.append(
                        f"| {profile_name} | {query_id} | {key} | {rank} |"
                    )
                    count += 1
    lines.append("")
    lines.append(f"共 {count} 个 pair。补标并合并 qrels 后可复跑升级为正式口径。")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count


def print_summary(profile_results) -> None:
    header = ["profile", *SUMMARY_METRICS]
    print("\t".join(header))
    for profile_result in profile_results:
        aggregate = profile_result["aggregate"]["overall"]["values"]
        row = [profile_result["profile"]["name"]]
        for metric in SUMMARY_METRICS:
            value = aggregate.get(metric)
            row.append("-" if value is None else f"{value:.4f}")
        print("\t".join(row))


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
    padded_benchmark, provisional = pad_unjudged_pairs(benchmark, "development")
    db = PostgresDatabase(
        PostgresConfig(dsn=normalize_psycopg_dsn(config.postgres_dsn))
    )
    db.open()
    try:
        report = run_memory_retrieval_experiment(
            padded_benchmark,
            profiles=build_ablation_profiles(),
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

    results = json.loads(report.results_path.read_text(encoding="utf-8"))
    profile_results = results["results"]
    unknown_path = report.results_path.with_name(
        report.results_path.stem + "-unknown-pairs.md"
    )
    unknown_count = report_unknown_hits(profile_results, provisional, unknown_path)

    print_summary(profile_results)
    print(f"results={report.results_path.resolve()}")
    print(f"csv={report.csv_path.resolve()}")
    print(f"summary={report.summary_path.resolve()}")
    print(f"unknown_pairs={unknown_count} -> {unknown_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
