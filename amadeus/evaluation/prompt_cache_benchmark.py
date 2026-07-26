from __future__ import annotations

import json
import math
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from amadeus.context import Message
from amadeus.provider import LLMResponse

Scenario = Literal["ab", "b0b1"]
Variant = Literal["A", "B", "B0", "B1"]
Phase = Literal["warmup", "measurement"]

SCENARIO_VARIANTS: dict[Scenario, tuple[Variant, ...]] = {
    "ab": ("A", "B"),
    "b0b1": ("B0", "B1"),
}


@dataclass(frozen=True)
class TokenPrices:
    hit_input_usd_per_million: float
    miss_input_usd_per_million: float
    output_usd_per_million: float

    def __post_init__(self) -> None:
        if min(asdict(self).values()) < 0:
            raise ValueError("token prices must not be negative")


@dataclass(frozen=True)
class BenchmarkConfig:
    model: str
    warmup_requests: int = 3
    measurement_requests: int = 30
    max_tokens: int = 64
    budget_usd: float = 5.0
    scenario: Scenario = "ab"
    memory_churn_every: int = 5

    def __post_init__(self) -> None:
        if self.warmup_requests < 0 or self.measurement_requests <= 0:
            raise ValueError("request counts must be non-negative and measurement positive")
        if self.max_tokens <= 0 or self.budget_usd <= 0:
            raise ValueError("max_tokens and budget_usd must be positive")
        if self.scenario not in SCENARIO_VARIANTS:
            raise ValueError("scenario must be one of: " + ", ".join(SCENARIO_VARIANTS))
        if self.memory_churn_every <= 0:
            raise ValueError("memory_churn_every must be positive")


@dataclass(frozen=True)
class BenchmarkObservation:
    variant: Variant
    phase: Phase
    sequence: int
    request_id: str
    started_at: str
    total_latency_ms: float
    prompt_cache_hit_tokens: int | None
    prompt_cache_miss_tokens: int | None
    completion_tokens: int | None
    estimated_cost_usd: float | None
    estimated_input_cost_usd: float | None
    model: str | None
    memory_version: int | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class BenchmarkReport:
    run_id: str
    config: BenchmarkConfig
    budget_truncated: bool
    stopped_on_provider_error: bool
    observations: tuple[BenchmarkObservation, ...]

    def summary(self) -> dict[str, Any]:
        variants = SCENARIO_VARIANTS[self.config.scenario]
        groups = {variant: _group_summary(self.observations, variant) for variant in variants}
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "model": self.config.model,
            "scenario": self.config.scenario,
            "budget_usd": self.config.budget_usd,
            "budget_truncated": self.budget_truncated,
            "stopped_on_provider_error": self.stopped_on_provider_error,
            "groups": groups,
        }
        if self.config.scenario == "ab":
            payload["ab"] = _ratio_lift(groups["A"], groups["B"])
        else:
            payload["memory_churn_every"] = self.config.memory_churn_every
            payload["b1_vs_b0"] = _b1_vs_b0(groups["B0"], groups["B1"])
        return payload


class ChatProvider(Protocol):
    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        **request_options: Any,
    ) -> LLMResponse: ...


def build_benchmark_messages(
    variant: Variant,
    *,
    request_id: str,
    question: str,
    memory_version: int = 0,
) -> list[Message]:
    """生成仅供基准使用的脱敏请求排列，不触碰生产消息装配。

    A/B 只重排静态上下文与动态内容。B0/B1 使用完全相同的 token 材料集合
    （identity 静态上下文、固定多轮历史、self_model、long_term_memory、动态 frame），
    仅改变记忆材料位于 system（历史之前）还是末条 user 消息（历史之后）。
    历史是对照的关键：DeepSeek 缓存按字节前缀匹配、对角色边界不敏感，
    无历史时两种排列字节等价，记忆变更的失效范围差异测不出来。
    """
    static = _static_agent_context()
    dynamic = _dynamic_context(request_id, question)
    if variant == "A":
        return [{"role": "user", "content": f"{dynamic}\n\n{static}"}]
    if variant == "B":
        return [{"role": "system", "content": static}, {"role": "user", "content": dynamic}]
    history = _conversation_history_fixture()
    memory_block = f"{_self_model_fixture()}\n\n{_long_term_memory_fixture(memory_version)}"
    if variant == "B0":
        return [
            {"role": "system", "content": f"{static}\n\n{memory_block}"},
            *history,
            {"role": "user", "content": dynamic},
        ]
    return [
        {"role": "system", "content": static},
        *history,
        {"role": "user", "content": f"{memory_block}\n\n{dynamic}"},
    ]


async def run_benchmark(
    provider: ChatProvider,
    *,
    config: BenchmarkConfig,
    prices: TokenPrices,
) -> BenchmarkReport:
    observations: list[BenchmarkObservation] = []
    total_cost = 0.0
    truncated = False
    provider_failed = False
    variants = SCENARIO_VARIANTS[config.scenario]
    phases: tuple[tuple[Phase, int], ...] = (
        ("warmup", config.warmup_requests),
        ("measurement", config.measurement_requests),
    )
    for variant in variants:
        for phase, count in phases:
            for sequence in range(count):
                if total_cost >= config.budget_usd:
                    truncated = True
                    break
                request_id = f"benchmark-{variant.lower()}-{phase}-{sequence}-{secrets.token_hex(6)}"
                question = _QUESTIONS[sequence % len(_QUESTIONS)]
                memory_version = _memory_version_for(config, phase, sequence)
                try:
                    observation = await _run_one(
                        provider,
                        variant=variant,
                        phase=phase,
                        sequence=sequence,
                        request_id=request_id,
                        question=question,
                        memory_version=memory_version,
                        config=config,
                        prices=prices,
                    )
                except Exception as error:
                    observations.append(
                        _failed_observation(
                            variant=variant,
                            phase=phase,
                            sequence=sequence,
                            request_id=request_id,
                            memory_version=memory_version,
                            error=error,
                        )
                    )
                    provider_failed = True
                    break
                observations.append(observation)
                if observation.estimated_cost_usd is not None:
                    total_cost += observation.estimated_cost_usd
            if truncated or provider_failed:
                break
        if truncated or provider_failed:
            break
    return BenchmarkReport(
        run_id=_new_run_id(),
        config=config,
        budget_truncated=truncated,
        stopped_on_provider_error=provider_failed,
        observations=tuple(observations),
    )


def _memory_version_for(config: BenchmarkConfig, phase: Phase, sequence: int) -> int | None:
    """b0b1 场景下的记忆版本计划：预热固定用版本 0，测量每 K 次推进一个版本。

    两组共享同一确定性计划，因此 B0/B1 的变更时点与内容序列完全一致；
    ab 场景不引入记忆变更，返回 None。
    """
    if config.scenario != "b0b1":
        return None
    if phase == "warmup":
        return 0
    return sequence // config.memory_churn_every


def _failed_observation(
    *,
    variant: Variant,
    phase: Phase,
    sequence: int,
    request_id: str,
    memory_version: int | None,
    error: Exception,
) -> BenchmarkObservation:
    return BenchmarkObservation(
        variant=variant,
        phase=phase,
        sequence=sequence,
        request_id=request_id,
        started_at=datetime.now(UTC).isoformat(),
        total_latency_ms=0,
        prompt_cache_hit_tokens=None,
        prompt_cache_miss_tokens=None,
        completion_tokens=None,
        estimated_cost_usd=None,
        estimated_input_cost_usd=None,
        model=None,
        memory_version=memory_version,
        error_code=type(error).__name__,
    )


async def _run_one(
    provider: ChatProvider,
    *,
    variant: Variant,
    phase: Phase,
    sequence: int,
    request_id: str,
    question: str,
    memory_version: int | None,
    config: BenchmarkConfig,
    prices: TokenPrices,
) -> BenchmarkObservation:
    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    response = await provider.chat(
        build_benchmark_messages(
            variant,
            request_id=request_id,
            question=question,
            memory_version=memory_version or 0,
        ),
        model=config.model,
        max_tokens=config.max_tokens,
        temperature=0,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    usage = response.usage or {}
    hit = _optional_nonnegative_int(usage.get("prompt_cache_hit_tokens"))
    miss = _optional_nonnegative_int(usage.get("prompt_cache_miss_tokens"))
    completion = _optional_nonnegative_int(usage.get("completion_tokens"))
    cost = _estimate_cost(hit, miss, completion, prices)
    input_cost = _estimate_input_cost(hit, miss, prices)
    return BenchmarkObservation(
        variant=variant,
        phase=phase,
        sequence=sequence,
        request_id=request_id,
        started_at=started_at,
        total_latency_ms=latency_ms,
        prompt_cache_hit_tokens=hit,
        prompt_cache_miss_tokens=miss,
        completion_tokens=completion,
        estimated_cost_usd=cost,
        estimated_input_cost_usd=input_cost,
        model=response.model,
        memory_version=memory_version,
    )


def write_artifacts(report: BenchmarkReport, output_root: Path) -> tuple[Path, Path, Path]:
    run_dir = output_root / report.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    records = run_dir / "records.jsonl"
    with records.open("w", encoding="utf-8") as handle:
        for observation in report.observations:
            handle.write(json.dumps(asdict(observation), ensure_ascii=False) + "\n")
    summary = report.summary()
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = run_dir / "summary.md"
    markdown_path.write_text(_render_markdown(summary), encoding="utf-8")
    return records, summary_path, markdown_path


def _group_summary(observations: tuple[BenchmarkObservation, ...], variant: Variant) -> dict[str, Any]:
    selected = [item for item in observations if item.variant == variant and item.phase == "measurement"]
    observable = [item for item in selected if item.prompt_cache_hit_tokens is not None and item.prompt_cache_miss_tokens is not None]
    hit_tokens = sum(item.prompt_cache_hit_tokens or 0 for item in observable)
    miss_tokens = sum(item.prompt_cache_miss_tokens or 0 for item in observable)
    denominator = hit_tokens + miss_tokens
    latencies = [item.total_latency_ms for item in selected]
    input_costs = [item.estimated_input_cost_usd for item in observable if item.estimated_input_cost_usd is not None]
    return {
        "measurement_requests": len(selected),
        "directly_observable_requests": len(observable),
        "token_cache_read_ratio": None if denominator == 0 else hit_tokens / denominator,
        "request_hit_rate": None if not observable else sum((item.prompt_cache_hit_tokens or 0) > 0 for item in observable) / len(observable),
        "prompt_cache_hit_tokens": hit_tokens,
        "prompt_cache_miss_tokens": miss_tokens,
        "estimated_cost_usd": sum(item.estimated_cost_usd or 0 for item in selected),
        "avg_input_cost_usd_per_observable_request": None if not input_costs else sum(input_costs) / len(input_costs),
        "median_total_latency_ms": _percentile(latencies, 50),
        "p95_total_latency_ms": _percentile(latencies, 95),
    }


def _ratio_lift(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """候选组相对基线组的 token 缓存读取率提升；基线不可观测或为零时相对值为 None。"""
    baseline_ratio = baseline["token_cache_read_ratio"]
    candidate_ratio = candidate["token_cache_read_ratio"]
    absolute = None if baseline_ratio is None or candidate_ratio is None else candidate_ratio - baseline_ratio
    relative = None if absolute is None or baseline_ratio == 0 else absolute / baseline_ratio
    return {
        "token_cache_read_ratio_absolute_lift": absolute,
        "token_cache_read_ratio_relative_lift": relative,
    }


def _b1_vs_b0(b0: dict[str, Any], b1: dict[str, Any]) -> dict[str, Any]:
    """B1 相对 B0 的缓存读取率提升与可观测请求的平均每请求输入成本降幅。"""
    b0_cost = b0["avg_input_cost_usd_per_observable_request"]
    b1_cost = b1["avg_input_cost_usd_per_observable_request"]
    reduction = None
    if b0_cost is not None and b1_cost is not None and b0_cost > 0:
        reduction = (b0_cost - b1_cost) / b0_cost
    return {
        **_ratio_lift(b0, b1),
        "b0_avg_input_cost_usd_per_request": b0_cost,
        "b1_avg_input_cost_usd_per_request": b1_cost,
        "avg_input_cost_reduction_ratio": reduction,
    }


def _estimate_cost(hit: int | None, miss: int | None, completion: int | None, prices: TokenPrices) -> float | None:
    if hit is None or miss is None or completion is None:
        return None
    return (hit * prices.hit_input_usd_per_million + miss * prices.miss_input_usd_per_million + completion * prices.output_usd_per_million) / 1_000_000


def _estimate_input_cost(hit: int | None, miss: int | None, prices: TokenPrices) -> float | None:
    if hit is None or miss is None:
        return None
    return (hit * prices.hit_input_usd_per_million + miss * prices.miss_input_usd_per_million) / 1_000_000


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        result = int(value)
    except ValueError:
        return None
    return result if result >= 0 else None


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] if lower == upper else ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _static_agent_context() -> str:
    policy = """你是 Amadeus 的可靠代理。区分事实、推测和用户偏好；对每个结论说明依据；不得编造工具结果。\n工具契约：每次调用前说明目的，工具结果仅作为候选证据，遇到冲突时优先请求澄清。\n记忆契约：长期记忆只能来自可回源的用户事实；检索内容不是用户的新陈述。"""
    examples = "\n".join(f"示例 {index}: 先提炼约束，再给出可验证的下一步。" for index in range(1, 181))
    return f"# 固定 Agent 上下文\n\n{policy}\n\n# 固定示例\n\n{examples}"


def _dynamic_context(request_id: str, question: str) -> str:
    return f"# 本轮上下文\nrequest_id: {request_id}\n检索记忆: 用户偏好中文、强调可验证结论。\n\n用户问题: {question}\n\n请用两句话回答。"


def _self_model_fixture() -> str:
    """脱敏 self_model fixture：规模需可观测，否则 B0/B1 排列差异测不出来。"""
    traits = "\n".join(
        f"特质 {index}: 保持谨慎、可验证、以用户目标为先，冲突时先澄清再行动。"
        for index in range(1, 21)
    )
    return f"# 自我模型\n\n{traits}"


def _long_term_memory_fixture(version: int) -> str:
    """确定性长期记忆 fixture：同一版本内容字节级一致，版本推进即整体改写。"""
    entries = "\n".join(
        f"记忆 {index}(v{version}): 用户在第 {version} 轮整理后偏好方案 {(version + index) % 7}，"
        "要求结论附带可回源依据。"
        for index in range(1, 41)
    )
    return f"# 长期记忆（版本 {version}）\n\n{entries}"


_HISTORY_TOPICS = (
    "检索记忆的去重策略",
    "工具调用的失败重试边界",
    "长期记忆的回源验证",
    "上下文窗口的裁剪顺序",
    "对话摘要的信息损失",
    "提示词分层的职责划分",
    "流式输出的中断恢复",
    "多轮澄清的终止条件",
    "工具结果与用户原文的冲突处理",
    "记忆写入的最小证据标准",
    "会话状态的持久化时机",
    "错误信息的脱敏展示",
    "并发请求的顺序保证",
    "缓存失效后的降级路径",
    "评估指标的可复现实验设计",
)


def _conversation_history_fixture() -> list[Message]:
    """确定性多轮历史 fixture：整个 run 内容固定，B0/B1 逐字节共享。

    15 轮 user/assistant 交替、合计数千 token。历史必须足够长：
    记忆变更时，B0 从记忆位置起使其后整段历史失效，而 B1 的
    identity+历史长前缀保持稳定——没有这段中间历史，两种排列的
    字节序列几乎相同，差异无法观测。
    """
    messages: list[Message] = []
    for index, topic in enumerate(_HISTORY_TOPICS, start=1):
        points = "".join(
            f"第{point}点，先明确输入契约与失败边界，再列出可回源的依据，"
            "最后给出可复查的验证命令与预期输出；"
            for point in range(1, 7)
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    f"历史问题 {index}：围绕「{topic}」，请说明适用边界、"
                    "失败模式与可验证的检查步骤，并指出哪些结论需要额外证据。"
                ),
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": (
                    f"历史回答 {index}：关于「{topic}」，{points}"
                    "以上结论仅在当前配置下成立，跨环境推广前必须重新验证。"
                ),
            }
        )
    return messages


def _render_markdown(summary: dict[str, Any]) -> str:
    groups = summary["groups"]
    lines = [
        "# DeepSeek Prompt Cache 基准结果", "", f"- run_id: `{summary['run_id']}`", f"- model: `{summary['model']}`", f"- scenario: `{summary['scenario']}`", f"- 预算截断: `{summary['budget_truncated']}`", f"- 因供应商错误停止: `{summary['stopped_on_provider_error']}`",
    ]
    if "memory_churn_every" in summary:
        lines.append(f"- 记忆变更频率 K: `{summary['memory_churn_every']}`（每 K 次测量请求推进一个记忆版本）")
    lines += [
        "", "| 组别 | 可观测请求 | Token 缓存读取率 | 请求命中率 | 中位总耗时 (ms) | P95 (ms) |", "|---|---:|---:|---:|---:|---:|", *_markdown_rows(groups), "", "缓存读取率基于 DeepSeek 返回的 prompt_cache_hit_tokens / (hit + miss)；缺少字段不推断命中。", "",
    ]
    if "b1_vs_b0" in summary:
        lift = summary["b1_vs_b0"]
        lines += [
            "## B1 相对 B0", "", f"- Token 缓存读取率绝对提升: {_format(lift['token_cache_read_ratio_absolute_lift'])}", f"- Token 缓存读取率相对提升: {_format(lift['token_cache_read_ratio_relative_lift'])}", f"- B0 平均每请求输入成本 (USD): {_format_usd(lift['b0_avg_input_cost_usd_per_request'])}", f"- B1 平均每请求输入成本 (USD): {_format_usd(lift['b1_avg_input_cost_usd_per_request'])}", f"- 平均每请求输入成本降幅: {_format(lift['avg_input_cost_reduction_ratio'])}", "", "结论仅对本次记忆变更频率 K 成立；`-` 表示不可直接观测。", "",
        ]
    return "\n".join(lines)


def _markdown_rows(groups: dict[str, Any]) -> list[str]:
    return [f"| {variant} | {group['directly_observable_requests']} | {_format(group['token_cache_read_ratio'])} | {_format(group['request_hit_rate'])} | {_format(group['median_total_latency_ms'])} | {_format(group['p95_total_latency_ms'])} |" for variant, group in groups.items()]


def _format(value: float | int | None) -> str:
    return "-" if value is None else f"{float(value):.4f}"


def _format_usd(value: float | int | None) -> str:
    """成本量级远小于 1 USD，用 .4f 会把 B0/B1 的差异抹成同一数字，须保留更多有效位。"""
    return "-" if value is None else f"{float(value):.7f}"


def _new_run_id() -> str:
    return f"prompt-cache-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


_QUESTIONS = ("请总结当前计划的主要风险。", "请列出下一步可验证的行动。", "请说明该设计的失败边界。")
