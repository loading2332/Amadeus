from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from amadeus.app.bootstrap import load_runtime_config
from amadeus.evaluation.prompt_cache_benchmark import (
    BenchmarkConfig,
    BenchmarkReport,
    TokenPrices,
    run_benchmark,
    write_artifacts,
)
from amadeus.provider import LLMProvider, LLMProviderConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 DeepSeek Prompt Cache 基准（ab 或 b0b1 场景）")
    parser.add_argument("run", nargs="?")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--output-root", default="runtime-artifacts/prompt-cache")
    parser.add_argument("--scenario", choices=("ab", "b0b1"), default="b0b1")
    parser.add_argument("--memory-churn-every", type=_positive_int, default=5)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--budget-usd", type=float, default=5.0)
    parser.add_argument("--hit-input-usd-per-million", type=float, required=True)
    parser.add_argument("--miss-input-usd-per-million", type=float, required=True)
    parser.add_argument("--output-usd-per-million", type=float, required=True)
    return parser


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_runtime_config(env_path=args.env)
    benchmark = BenchmarkConfig(
        model=config.provider.model,
        warmup_requests=args.warmup,
        measurement_requests=args.samples,
        max_tokens=args.max_tokens,
        budget_usd=args.budget_usd,
        scenario=args.scenario,
        memory_churn_every=args.memory_churn_every,
    )
    prices = TokenPrices(
        args.hit_input_usd_per_million,
        args.miss_input_usd_per_million,
        args.output_usd_per_million,
    )
    report = asyncio.run(_run(config.provider, benchmark, prices))
    records, summary, markdown = write_artifacts(report, Path(args.output_root))
    print(f"records={records.resolve()}")
    print(f"summary={summary.resolve()}")
    print(f"markdown={markdown.resolve()}")
    return 0


async def _run(
    provider_config: LLMProviderConfig,
    benchmark: BenchmarkConfig,
    prices: TokenPrices,
) -> BenchmarkReport:
    provider = LLMProvider(provider_config)
    try:
        return await run_benchmark(provider, config=benchmark, prices=prices)
    finally:
        await provider.aclose()


if __name__ == "__main__":
    raise SystemExit(main())
