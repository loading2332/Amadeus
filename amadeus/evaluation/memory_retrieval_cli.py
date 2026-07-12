from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from amadeus.app.bootstrap import load_runtime_config
from amadeus.db import PostgresConfig, PostgresDatabase, normalize_psycopg_dsn
from amadeus.evaluation.embedding_cache import (
    FileEmbeddingCacheProvider,
    benchmark_embedding_input_hash,
    populate_benchmark_embedding_cache,
)
from amadeus.evaluation.memory_retrieval_benchmark import (
    MemoryRetrievalBenchmark,
    load_memory_retrieval_benchmark,
)
from amadeus.evaluation.memory_retrieval_experiment import (
    MemoryRetrievalExperimentProfile,
    build_stage_profiles,
    collect_memory_retrieval_judging_pool,
    freeze_profile_shortlist,
    load_frozen_profile_shortlist,
    rebase_finalist_shortlist_for_holdout_qrels,
    run_memory_retrieval_experiment,
)
from amadeus.memory.providers import OpenAIEmbeddingConfig, OpenAIEmbeddingProvider


class _ClosableEmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...

    async def aclose(self) -> None: ...


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "prepare-cache":
        return _prepare_cache(args)
    if args.command == "run":
        return _run_experiment(args)
    if args.command == "freeze-shortlist":
        return _freeze_shortlist(args)
    if args.command == "rebase-shortlist":
        return _rebase_shortlist(args)
    if args.command == "collect-pool":
        return _collect_pool(args)
    parser.error("a command is required")
    return 2  # pragma: no cover


def _prepare_cache(args: Any) -> int:
    benchmark = load_memory_retrieval_benchmark(args.benchmark)
    config = load_runtime_config(env_path=args.env)
    embedding_model = _required_embedding_model(config.embedding_model)
    identity = _embedding_identity(
        base_url=config.embedding_base_url,
        model=embedding_model,
        dimensions=args.dimensions,
    )
    provider = OpenAIEmbeddingProvider(
        OpenAIEmbeddingConfig(
            api_key=str(config.embedding_api_key or config.provider.api_key),
            base_url=config.embedding_base_url,
            model=embedding_model,
            timeout_seconds=config.provider.timeout_seconds,
        )
    )
    cache = FileEmbeddingCacheProvider(
        args.cache,
        identity=identity,
        dimensions=args.dimensions,
        input_hash=benchmark_embedding_input_hash(benchmark),
        underlying=provider,
        allow_misses=True,
    )
    fingerprint = asyncio.run(
        _populate_cache_and_close(
            benchmark=benchmark,
            cache=cache,
            provider=provider,
        )
    )
    print(f"cache={Path(args.cache).resolve()}")
    print(f"entries={cache.entry_count}")
    print(f"fingerprint={fingerprint}")
    return 0


async def _populate_cache_and_close(
    *,
    benchmark: MemoryRetrievalBenchmark,
    cache: FileEmbeddingCacheProvider,
    provider: _ClosableEmbeddingProvider,
) -> str:
    try:
        return await populate_benchmark_embedding_cache(benchmark, cache)
    finally:
        await provider.aclose()


def _run_experiment(args: Any) -> int:
    if args.allow_draft and args.split != "development":
        raise ValueError("--allow-draft is only valid for development smoke runs")
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
    profiles = _profiles_for_args(args, dataset_hash=benchmark.content_hash)
    db = PostgresDatabase(
        PostgresConfig(dsn=normalize_psycopg_dsn(config.postgres_dsn))
    )
    db.open()
    try:
        report = run_memory_retrieval_experiment(
            benchmark,
            profiles=profiles,
            split=args.split,
            ranking_time=_parse_ranking_time(args.ranking_time),
            db=db,
            embedding_provider=cache,
            embedding_identity=identity,
            embedding_cache_fingerprint=cache.fingerprint,
            artifacts_dir=args.artifacts,
            formal=not args.allow_draft,
            unlock_holdout=args.unlock_holdout,
            experiment_id=args.experiment_id,
            verify_determinism=not args.skip_determinism_check,
            stage=args.stage,
        )
    finally:
        db.close()
    print(f"results={report.results_path.resolve()}")
    print(f"csv={report.csv_path.resolve()}")
    print(f"summary={report.summary_path.resolve()}")
    return 0


def _freeze_shortlist(args: Any) -> int:
    output = freeze_profile_shortlist(
        args.results,
        profile_names=args.profile,
        source_stage=args.source_stage,
        output_path=args.output,
    )
    print(f"shortlist={output.resolve()}")
    return 0


def _rebase_shortlist(args: Any) -> int:
    source_benchmark = load_memory_retrieval_benchmark(args.source_benchmark)
    source_benchmark.require_approved()
    benchmark = load_memory_retrieval_benchmark(args.benchmark)
    benchmark.require_approved()
    output = rebase_finalist_shortlist_for_holdout_qrels(
        args.shortlist,
        source_benchmark=source_benchmark,
        benchmark=benchmark,
        approved_overlay_path=args.approved_overlay,
        output_path=args.output,
    )
    print(f"shortlist={output.resolve()}")
    return 0


def _collect_pool(args: Any) -> int:
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
    profiles = _profiles_for_args(args, dataset_hash=benchmark.content_hash)
    db = PostgresDatabase(
        PostgresConfig(dsn=normalize_psycopg_dsn(config.postgres_dsn))
    )
    db.open()
    try:
        report = collect_memory_retrieval_judging_pool(
            benchmark,
            profiles=profiles,
            split=args.split,
            ranking_time=_parse_ranking_time(args.ranking_time),
            db=db,
            embedding_provider=cache,
            embedding_identity=identity,
            embedding_cache_fingerprint=cache.fingerprint,
            artifacts_dir=args.artifacts,
            experiment_id=args.experiment_id,
            unlock_holdout=args.unlock_holdout,
        )
    finally:
        db.close()
    print(f"pool={report.json_path.resolve()}")
    print(f"review={report.review_path.resolve()}")
    print(f"unknown_pairs={report.unknown_pair_count}")
    return 0


def _profiles_for_args(
    args: Any,
    *,
    dataset_hash: str,
) -> tuple[MemoryRetrievalExperimentProfile, ...]:
    if args.split == "holdout":
        if args.stage != 5:
            raise ValueError("holdout evaluation requires frozen Stage 5 finalists")
        if not args.base_shortlist:
            raise ValueError("holdout evaluation requires --base-shortlist")
        return load_frozen_profile_shortlist(
            args.base_shortlist,
            expected_source_stage=5,
            dataset_hash=dataset_hash,
        )
    base_profiles = _base_profiles_for_stage(args, dataset_hash=dataset_hash)
    return build_stage_profiles(args.stage, base_profiles=base_profiles)


def _base_profiles_for_stage(
    args: Any,
    *,
    dataset_hash: str,
) -> tuple[MemoryRetrievalExperimentProfile, ...]:
    if args.stage >= 2:
        if not args.base_shortlist:
            raise ValueError(f"Stage {args.stage} requires --base-shortlist")
        return load_frozen_profile_shortlist(
            args.base_shortlist,
            expected_source_stage=args.stage - 1,
            dataset_hash=dataset_hash,
        )
    if args.base_shortlist:
        raise ValueError(f"Stage {args.stage} does not accept --base-shortlist")
    return ()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="运行 Amadeus 长期记忆 retrieval 参数实验",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare-cache",
        help="调用正式 embedding provider 并冻结文本向量 cache",
    )
    _add_common_files(prepare)

    run = subparsers.add_parser(
        "run",
        help="使用只读 embedding cache 执行本地 PostgreSQL retrieval sweep",
    )
    _add_common_files(run)
    run.add_argument("--split", choices=("development", "holdout"), required=True)
    run.add_argument("--stage", type=int, choices=range(0, 6), required=True)
    run.add_argument("--ranking-time", required=True)
    run.add_argument(
        "--artifacts",
        default=str(Path("runtime-artifacts") / "memory-retrieval"),
    )
    run.add_argument("--experiment-id")
    run.add_argument("--allow-draft", action="store_true")
    run.add_argument("--unlock-holdout", action="store_true")
    run.add_argument("--skip-determinism-check", action="store_true")
    run.add_argument(
        "--base-shortlist",
        help="Stage 2～4 必需：上一阶段冻结的 profile shortlist JSON",
    )

    freeze = subparsers.add_parser(
        "freeze-shortlist",
        help="从上一阶段结果中冻结一到两个 profile，供下一阶段继承",
    )
    freeze.add_argument("--results", required=True)
    freeze.add_argument("--source-stage", type=int, choices=range(1, 6), required=True)
    freeze.add_argument("--profile", action="append", required=True)
    freeze.add_argument("--output", required=True)

    rebase = subparsers.add_parser(
        "rebase-shortlist",
        help="在只新增 approved holdout qrels 后重签已冻结的 Stage 5 finalists",
    )
    rebase.add_argument("--shortlist", required=True)
    rebase.add_argument("--source-benchmark", required=True)
    rebase.add_argument("--benchmark", required=True)
    rebase.add_argument("--approved-overlay", required=True)
    rebase.add_argument("--output", required=True)

    pool = subparsers.add_parser(
        "collect-pool",
        help="汇总 development top-8 中尚未标注的跨 corpus 记忆",
    )
    _add_common_files(pool)
    pool.add_argument(
        "--split",
        choices=("development", "holdout"),
        default="development",
    )
    pool.add_argument("--stage", type=int, choices=range(0, 6), required=True)
    pool.add_argument("--ranking-time", required=True)
    pool.add_argument(
        "--artifacts",
        default=str(Path("runtime-artifacts") / "memory-retrieval"),
    )
    pool.add_argument("--experiment-id")
    pool.add_argument("--base-shortlist")
    pool.add_argument("--unlock-holdout", action="store_true")
    return parser


def _add_common_files(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--cache", required=True)
    parser.add_argument("--dimensions", type=int, default=1024)


def _required_embedding_model(value: str | None) -> str:
    if value is None or not value.strip():
        raise ValueError("OPENAI_EMBEDDING_MODEL is required")
    return value.strip()


def _embedding_identity(
    *,
    base_url: str | None,
    model: str,
    dimensions: int,
) -> str:
    host = (base_url or "default-openai-endpoint").rstrip("/")
    return f"{host}|{model}|dimensions={dimensions}"


def _parse_ranking_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("--ranking-time must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError("--ranking-time must include a timezone")
    return parsed


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
