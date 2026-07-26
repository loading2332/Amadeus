# Prompt Cache A/B 基准设计

## 目标边界

本设计为 Amadeus 增加独立的 DeepSeek Prompt Cache 基准工具。它调用真实 Chat Completions 兼容 API，读取 DeepSeek 返回的 `usage.prompt_cache_hit_tokens` 与 `usage.prompt_cache_miss_tokens`，以可复现 A/B 对照验证“动态内容的位置”对缓存读取、耗时与成本的影响。

生产运行时不改变：`MessageEnvelopeBuilder` 继续使用既有“system → history → context frame → current user message”顺序。A 的动态前缀仅存在于 benchmark fixture。

## 第一性原理与实验变量

模型处理输入时，只有已构建且完整匹配的前缀单元可被 DeepSeek 复用。若请求的首个 token 每次不同，后续相同文本无法成为共同开头；若大型不变内容从开头起一致，则它有机会被写入并在后续读取。

| 项目 | A：动态前缀基线 | B：稳定前缀生产代表 |
|---|---|---|
| 消息顺序 | 动态 fixture → 固定 Agent 上下文 | 固定 Agent 上下文 → 动态 fixture |
| 目的 | 构造低前缀复用参照 | 复刻生产信封、测真实收益 |
| 预期 | 缓存读取率较低，但不保证为零 | 缓存读取率较高，但不保证命中 |

固定 Agent 上下文由不含敏感数据的 fixture 构造，包含系统职责、模拟工具 schema、模拟长期说明和示例；动态 fixture 包含唯一请求 ID、模拟检索记忆以及固定问题集中的一项。两组使用完全相同的 token 材料集合，只改变材料排列。

## 模块与数据流

新增 `amadeus.evaluation.prompt_cache_benchmark`，职责如下：

1. 生成 A/B 请求与预热请求；请求传给现有 `LLMProvider` 或等价的 OpenAI 兼容 client。
2. 对每个响应记录组别、阶段、请求序号、单调时钟总耗时、模型、原始 usage 的必要字段及估算成本。
3. 以 DeepSeek 字段计算 token 缓存读取率、二元请求命中率、总成本、中位数与 P95 总耗时。
4. 将原始 JSONL 与汇总 JSON/Markdown 写入 `runtime-artifacts/prompt-cache/<run-id>/`；不写入请求正文、API key 或完整模型输出。

新增 `amadeus.evaluation.prompt_cache_cli`，提供 `python -m ...` 单命令入口。它经 `load_runtime_config` 获取现有 `.env` 中的 DeepSeek 兼容配置；模型、样本数、预热数、输出目录、预算和 token 单价均可由命令行覆盖。

## 指标与统计

主指标：

`token_cache_read_ratio = sum(hit_tokens) / sum(hit_tokens + miss_tokens)`

辅助指标：

- `request_hit_rate = count(hit_tokens > 0) / completed_requests`
- A/B 绝对提升 `ratio_B - ratio_A` 与相对提升（仅当 A 非零时）
- 总耗时的中位数与 P95；流式首 token 延迟不纳入第一版，以避免把 streaming usage 兼容性混入缓存因果判断
- 以 `hit_tokens * hit_price + miss_tokens * miss_price + output_tokens * output_price` 得到的估算成本

若响应缺失 DeepSeek 的两个字段，该请求与所在组标记为“不可直接观测”，不从其他延迟数据推断命中率。

## 运行控制与失败边界

- 每组先串行预热 3 次，预热原始记录保留但不进入主指标。
- 每组最多串行测量 30 次，随机化问题顺序但保持 A/B 相同题目多重集。
- 预算按已完成请求的实际返回 token 累加；下一请求前若预算不足则停止，并标记 `budget_truncated`。
- API 异常记录为失败并停止该组，不能用缺失 usage 填零。
- 结果只适用于本次 API endpoint、模型、时间、fixture 和请求节奏，不外推为 DeepSeek 的全局命中率。

## 第二轮：B0/B1 记忆变更对照

第一轮证明因果后，第二轮量化生产优化候选的真实增益。优化候选是 `PromptAssembler` 的 section 路由调整：`self_model` 与 `long_term_memory` 从 system prompt 移入动态 context frame，使 system 前缀只剩字节级稳定的 identity 材料。

| 项目 | B0：优化前生产结构 | B1：优化后生产结构 |
|---|---|---|
| 消息序列 | system(identity + self_model + long_term_memory) → 多轮历史 → user(动态 frame) | system(仅 identity) → 多轮历史 → user(self_model + long_term_memory + 动态 frame) |
| 记忆更新的后果 | 从记忆位置起破坏前缀，**其后整段历史全部 miss** | 仅末尾记忆+frame 段 miss，identity+历史长前缀持续命中 |

两组必须包含相同的固定多轮对话历史 fixture（约十几轮、数千 token），位于 system 与当前输入之间。历史是本对照的关键混杂控制：无历史时 B0/B1 字节序列几乎相同（仅 system/user 角色边界不同），DeepSeek 按字节前缀匹配、对角色边界不敏感，两组结果必然一致——2026-07-26 首次 b0b1 运行（`prompt-cache-20260726T081836Z-081868`，两组读取率同为 93.68%）实证了这一点，该运行保留作为"角色边界不影响缓存"的证据。

关键负载：每 K 次测量请求（默认 K=5）按预定序列替换一次 `long_term_memory` fixture 内容；两组共享同一变更时点与内容序列。历史在整个 run 内保持固定（受控变量：只测记忆位置的影响，不混入历史增长）。除排列与 K 计划外，模型、参数、问题多重集、预热与串行节奏与第一轮一致。

实现方式：benchmark 引入 scenario 概念——`ab`（第一轮，保留可复跑）与 `b0b1`（第二轮）。`Variant` 扩展为 `A/B/B0/B1`；消息构造函数按 scenario+variant 生成排列，fixture 忠实复刻两种生产结构但不调用生产装配器。CLI 增加 `--scenario` 与 `--memory-churn-every` 参数。

汇总在原有分组统计之上输出 `b1_vs_b0`：token 缓存读取率绝对/相对提升、可观测请求的平均每请求输入成本及降幅。记录中每个观测保留其记忆版本号，便于核对变更时点后的首请求 miss 模式。

## 验证策略

- 单元测试验证 A/B 仅改变顺序、每个动态 ID 唯一、指标计算、缺字段降级与预算停止。
- 第二轮单元测试验证：B0/B1 仅在排列上不同、两组记忆变更序列一致、B0 的记忆内容进入 system prompt 而 B1 进入 frame、`b1_vs_b0` 汇总计算正确；全部不调用真实 API。
- 真实 smoke 使用当前 `.env`、默认 5 美元上限；成功条件是生成包含 DeepSeek hit/miss 字段的原始记录和报告，而非预设某个命中率阈值。
