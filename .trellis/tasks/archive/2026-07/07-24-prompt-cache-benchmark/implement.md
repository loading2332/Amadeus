# Prompt Cache A/B 基准实施计划

## 实施步骤

1. 新建基准数据模型与纯函数：请求 fixture、DeepSeek usage 解析、成本计算、统计汇总和 JSONL/Markdown 报告。
2. 新建异步 runner：按 A/B 串行执行预热和测量，调用 OpenAI 兼容客户端，使用单调时钟记录耗时并实施预算中止。
3. 新建命令行入口：加载现有运行时配置，暴露模型、样本数、预热数、预算、单价和 artifact 输出目录。
4. 为纯函数和 runner 的 fake client 路径编写单元测试；验证不发真实网络请求。
5. 运行 focused pytest、ruff 与 mypy；通过后以默认 5 美元限制执行真实 DeepSeek smoke，并检查 artifact 中的 usage 字段与汇总结论。

## 第二轮（B0/B1）实施步骤

6. 扩展 benchmark：新增 scenario 概念（`ab`/`b0b1`）与 `B0`/`B1` variant；实现记忆变更序列 fixture（默认每 5 次测量请求更新一次 `long_term_memory` 内容，两组共享同一序列），观测记录增加记忆版本号字段。
7. 消息构造：B0 = system(identity+self_model+long_term_memory) → user(动态 frame+问题)；B1 = system(identity) → user(self_model+long_term_memory+动态 frame+问题)。两组 token 材料集合一致，仅排列不同。
8. 汇总扩展：`b0b1` scenario 输出 `b1_vs_b0`（缓存读取率绝对/相对提升、平均每请求输入成本与降幅）；Markdown 报告同步展示。
9. CLI 增加 `--scenario`（默认 `b0b1`）与 `--memory-churn-every`（默认 5）参数，向后兼容 `ab`。
10. 补第二轮单元测试（排列差异、变更序列一致性、版本号记录、`b1_vs_b0` 计算），跑 focused pytest / ruff / mypy 与全量 prompting 测试（覆盖 `assembler.py` 改动）。
11. 以 5 美元预算跑真实 `b0b1` 实验，把结果回写 prd“首次运行证据”节与 `docs/prompt-cache-benchmark.md`，勾选验收标准。

## 验证命令

```powershell
uv run pytest tests/evaluation/test_prompt_cache_benchmark.py tests/prompting/
uv run ruff check amadeus/evaluation/prompt_cache_benchmark.py amadeus/evaluation/prompt_cache_cli.py tests/evaluation/test_prompt_cache_benchmark.py
uv run mypy amadeus/evaluation/prompt_cache_benchmark.py amadeus/evaluation/prompt_cache_cli.py
uv run python -m amadeus.evaluation.prompt_cache_cli run --env .env --budget-usd 5 --scenario b0b1
```

## 风险与回滚

- DeepSeek 兼容端点可能不返回缓存字段：保留原始 usage，报告不可直接观测；不伪造结果。
- 真实 API 调用会产生费用：预算守卫在 runner 内部实现，默认上限 5 美元。
- 基准 fixture 仅用于实验，不修改 `MessageEnvelopeBuilder` 或生产提示词；回滚仅删除新增基准模块与测试。
