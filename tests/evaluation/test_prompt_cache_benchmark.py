import asyncio

import pytest
from amadeus.evaluation.prompt_cache_benchmark import (
    BenchmarkConfig,
    TokenPrices,
    build_benchmark_messages,
    run_benchmark,
    write_artifacts,
)
from amadeus.evaluation.prompt_cache_cli import build_parser
from amadeus.provider import LLMResponse


def test_ab_changes_only_fixture_order_and_keeps_dynamic_content() -> None:
    a = build_benchmark_messages("A", request_id="id-1", question="问题")
    b = build_benchmark_messages("B", request_id="id-1", question="问题")
    assert a[0]["role"] == "user"
    assert b[0]["role"] == "system"
    assert "request_id: id-1" in str(a)
    assert "request_id: id-1" in str(b)
    assert str(a).index("request_id") < str(a).index("固定 Agent 上下文")
    assert str(b).index("固定 Agent 上下文") < str(b).index("request_id")


def test_runner_calculates_observable_ab_metrics() -> None:
    report = asyncio.run(
        run_benchmark(
            _FakeProvider(),
            config=BenchmarkConfig(
                model="deepseek-chat", warmup_requests=1, measurement_requests=2
            ),
            prices=TokenPrices(1, 10, 20),
        )
    )
    summary = report.summary()
    assert summary["groups"]["A"]["token_cache_read_ratio"] == 0
    assert summary["groups"]["B"]["token_cache_read_ratio"] == 0.8
    assert summary["ab"]["token_cache_read_ratio_absolute_lift"] == 0.8


def test_runner_records_provider_failure_without_leaking_error_text() -> None:
    report = asyncio.run(
        run_benchmark(
            _FailingProvider(),
            config=BenchmarkConfig(model="deepseek-chat", measurement_requests=1),
            prices=TokenPrices(1, 10, 20),
        )
    )
    assert report.budget_truncated is False
    assert report.stopped_on_provider_error is True
    assert report.observations[0].error_code == "RuntimeError"


class _FakeProvider:
    async def chat(self, messages, *, model=None, max_tokens=None, **request_options):
        hit = 80 if messages[0]["role"] == "system" else 0
        return LLMResponse(content="ok", model=model, usage={"prompt_cache_hit_tokens": hit, "prompt_cache_miss_tokens": 100 - hit, "completion_tokens": 5})


class _FailingProvider:
    async def chat(self, messages, *, model=None, max_tokens=None, **request_options):
        raise RuntimeError("do not expose this provider detail")


def test_b0_b1_use_same_token_material_and_differ_only_in_arrangement() -> None:
    b0 = build_benchmark_messages("B0", request_id="id-1", question="问题", memory_version=2)
    b1 = build_benchmark_messages("B1", request_id="id-1", question="问题", memory_version=2)
    # 材料集合一致：全部消息内容的字符多重集完全相同，仅记忆材料的排列位置不同。
    assert sorted("\n\n".join(m["content"] for m in b0)) == sorted("\n\n".join(m["content"] for m in b1))
    assert [m["role"] for m in b0] == [m["role"] for m in b1]
    assert b0[0]["role"] == "system" and b0[-1]["role"] == "user"
    assert b0[0]["content"] != b1[0]["content"]
    # B0 的记忆材料在 system（历史之前）；B1 的记忆材料在末条 user 消息（历史之后）。
    assert "# 长期记忆" in b0[0]["content"] and "# 自我模型" in b0[0]["content"]
    assert "# 长期记忆" not in b0[-1]["content"]
    assert "# 长期记忆" not in b1[0]["content"] and "# 自我模型" not in b1[0]["content"]
    assert "# 长期记忆" in b1[-1]["content"] and "# 自我模型" in b1[-1]["content"]
    assert "request_id: id-1" in b0[-1]["content"] and "request_id: id-1" in b1[-1]["content"]


def test_b0_b1_share_identical_deterministic_history() -> None:
    b0 = build_benchmark_messages("B0", request_id="id-1", question="问题")
    b1 = build_benchmark_messages("B1", request_id="id-1", question="问题")
    history_b0 = b0[1:-1]
    history_b1 = b1[1:-1]
    # 两组历史逐字节一致，且再次构造得到相同字节（run 内确定性）。
    assert history_b0 == history_b1
    assert history_b0 == build_benchmark_messages("B0", request_id="id-2", question="另一问题")[1:-1]
    # 历史为 user/assistant 交替、12–16 轮、合计数千 token 规模的中文内容。
    assert [m["role"] for m in history_b0] == ["user", "assistant"] * (len(history_b0) // 2)
    assert 12 <= len(history_b0) // 2 <= 16
    assert sum(len(m["content"]) for m in history_b0) >= 4500
    # 历史不包含记忆材料，记忆位置差异只由 system/末条 user 决定。
    assert all("# 长期记忆" not in m["content"] for m in history_b0)


def test_memory_fixture_changes_only_memory_part_across_versions() -> None:
    v0 = build_benchmark_messages("B1", request_id="id-1", question="问题", memory_version=0)
    v1 = build_benchmark_messages("B1", request_id="id-1", question="问题", memory_version=1)
    # 版本推进只改写末条 user 消息中的记忆段：system 与历史保持字节级稳定。
    assert v0[:-1] == v1[:-1]
    assert "长期记忆（版本 0）" in v0[-1]["content"]
    assert "长期记忆（版本 1）" in v1[-1]["content"]


def test_b0b1_runner_shares_memory_version_schedule_and_records_versions() -> None:
    provider = _RecordingProvider()
    report = asyncio.run(
        run_benchmark(
            provider,
            config=BenchmarkConfig(
                model="deepseek-chat",
                warmup_requests=1,
                measurement_requests=5,
                scenario="b0b1",
                memory_churn_every=2,
            ),
            prices=TokenPrices(1, 10, 20),
        )
    )
    for variant in ("B0", "B1"):
        warmups = [o for o in report.observations if o.variant == variant and o.phase == "warmup"]
        measures = [o for o in report.observations if o.variant == variant and o.phase == "measurement"]
        assert [o.memory_version for o in warmups] == [0]
        assert [o.memory_version for o in measures] == [0, 0, 1, 1, 2]
    # 两组请求正文中的记忆版本序列一致，即共享同一变更时点与内容序列。
    assert provider.memory_versions["B0"] == provider.memory_versions["B1"] == [0, 0, 0, 1, 1, 2]


def test_ab_runner_leaves_memory_version_unset() -> None:
    report = asyncio.run(
        run_benchmark(
            _FakeProvider(),
            config=BenchmarkConfig(model="deepseek-chat", warmup_requests=0, measurement_requests=1),
            prices=TokenPrices(1, 10, 20),
        )
    )
    assert all(o.memory_version is None for o in report.observations)


def test_b0b1_summary_reports_b1_vs_b0_lift_and_input_cost_reduction() -> None:
    report = asyncio.run(
        run_benchmark(
            _MemoryAwareProvider(),
            config=BenchmarkConfig(
                model="deepseek-chat",
                warmup_requests=1,
                measurement_requests=2,
                scenario="b0b1",
            ),
            prices=TokenPrices(1, 10, 20),
        )
    )
    summary = report.summary()
    assert summary["scenario"] == "b0b1"
    assert summary["memory_churn_every"] == 5
    assert set(summary["groups"]) == {"B0", "B1"}
    assert summary["groups"]["B0"]["token_cache_read_ratio"] == 0.4
    assert summary["groups"]["B1"]["token_cache_read_ratio"] == 0.9
    lift = summary["b1_vs_b0"]
    assert lift["token_cache_read_ratio_absolute_lift"] == pytest.approx(0.5)
    assert lift["token_cache_read_ratio_relative_lift"] == pytest.approx(1.25)
    assert lift["b0_avg_input_cost_usd_per_request"] == pytest.approx(640 / 1_000_000)
    assert lift["b1_avg_input_cost_usd_per_request"] == pytest.approx(190 / 1_000_000)
    assert lift["avg_input_cost_reduction_ratio"] == pytest.approx(450 / 640)


def test_markdown_report_keeps_small_usd_costs_distinguishable(tmp_path) -> None:
    report = asyncio.run(
        run_benchmark(
            _MemoryAwareProvider(),
            config=BenchmarkConfig(
                model="deepseek-chat",
                warmup_requests=0,
                measurement_requests=2,
                scenario="b0b1",
            ),
            prices=TokenPrices(1, 10, 20),
        )
    )
    _, _, markdown_path = write_artifacts(report, tmp_path)
    markdown = markdown_path.read_text(encoding="utf-8")
    # B0=640e-6、B1=190e-6：报告不得把两个不同量级的小额成本抹成同一数字。
    assert "- B0 平均每请求输入成本 (USD): 0.0006400" in markdown
    assert "- B1 平均每请求输入成本 (USD): 0.0001900" in markdown


def test_config_rejects_invalid_scenario_and_churn() -> None:
    with pytest.raises(ValueError):
        BenchmarkConfig(model="deepseek-chat", scenario="b2")
    with pytest.raises(ValueError):
        BenchmarkConfig(model="deepseek-chat", memory_churn_every=0)


def test_cli_parser_exposes_scenario_and_memory_churn() -> None:
    prices = [
        "--hit-input-usd-per-million", "0.07",
        "--miss-input-usd-per-million", "0.56",
        "--output-usd-per-million", "1.68",
    ]
    defaults = build_parser().parse_args(["run", *prices])
    assert defaults.scenario == "b0b1"
    assert defaults.memory_churn_every == 5
    explicit = build_parser().parse_args(
        ["run", "--scenario", "ab", "--memory-churn-every", "3", *prices]
    )
    assert explicit.scenario == "ab"
    assert explicit.memory_churn_every == 3
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--memory-churn-every", "0", *prices])


class _RecordingProvider:
    """记录每次请求正文中的记忆版本号，不发真实网络请求。"""

    def __init__(self) -> None:
        self.memory_versions: dict[str, list[int]] = {"B0": [], "B1": []}

    async def chat(self, messages, *, model=None, max_tokens=None, **request_options):
        joined = "\n\n".join(m["content"] for m in messages)
        variant = "B0" if "# 长期记忆" in messages[0]["content"] else "B1"
        marker = "长期记忆（版本 "
        version = int(joined.split(marker, 1)[1].split("）", 1)[0])
        self.memory_versions[variant].append(version)
        return LLMResponse(content="ok", model=model, usage={"prompt_cache_hit_tokens": 50, "prompt_cache_miss_tokens": 50, "completion_tokens": 5})


class _MemoryAwareProvider:
    """B0（记忆在 system）返回低命中，B1（记忆在 user）返回高命中。"""

    async def chat(self, messages, *, model=None, max_tokens=None, **request_options):
        memory_in_system = "# 长期记忆" in messages[0]["content"]
        hit, miss = (40, 60) if memory_in_system else (90, 10)
        return LLMResponse(content="ok", model=model, usage={"prompt_cache_hit_tokens": hit, "prompt_cache_miss_tokens": miss, "completion_tokens": 5})
