# DeepSeek Prompt Cache A/B 基准

本工具测量的是 DeepSeek 实际返回的缓存读取 token，而不是根据“提示词看起来相似”猜测缓存是否命中。

## 先理解指标

DeepSeek 在 `usage` 中返回：

- `prompt_cache_hit_tokens`：本次从缓存读取的输入 token。
- `prompt_cache_miss_tokens`：本次重新计算的输入 token。

主指标为：

```text
Token 缓存读取率 = hit_tokens / (hit_tokens + miss_tokens)
```

这比“有多少请求命中”更有信息量：一个请求可能只复用一部分前缀。

## A/B 分别是什么

- A 是反事实基线：每轮变化的 request ID、检索记忆和用户问题放在开头，后面才放固定 Agent 上下文。它让公共内容不再是请求前缀。
- B 是生产代表：固定 Agent 上下文在前，动态内容在后；这对应 Amadeus 的 system → history → context frame → current user message 信封顺序。

两组的文本材料、模型、参数、问题集、预热数和测量数一致，只改变排列。A 只存在于 benchmark fixture，不会修改生产提示词或 `MessageEnvelopeBuilder`。

## B0/B1 分别是什么

A/B 证明"稳定前缀在前"的因果作用之后，B0/B1（`--scenario b0b1`，默认场景）量化一个具体生产优化的真实增益：把 `self_model` 与 `long_term_memory` 从 system prompt 移入历史之后的动态 context frame（`assembler.py` 中 `CONTEXT_FRAME_SECTIONS` 的改动）。

- B0（优化前）：`system(identity + self_model + 长期记忆)` → 15 轮固定历史 → `user(动态 frame)`。
- B1（优化后）：`system(仅 identity)` → 15 轮固定历史 → `user(self_model + 长期记忆 + 动态 frame)`。

关键负载是记忆变更：每 `--memory-churn-every` 次测量请求（默认 5）按相同计划替换一次长期记忆内容，模拟 Amadeus 记忆抽取/优化的写入。B0 中记忆位于历史之前，记忆一变，**其后整段历史的缓存全部失效**；B1 中记忆位于历史之后，只有末尾小段失效。

两个已被实机数据证实的前提：

1. DeepSeek 缓存按字节前缀匹配、对 system/user 角色边界不敏感——无历史 fixture 的运行（`prompt-cache-20260726T081836Z-081868`）中 B0/B1 读取率完全相同（93.68%），因为此时两种排列字节等价。历史是本对照的必要元素。
2. 历史边界处的缓存前缀单元需要供应商观察后才落盘——B1 首次记忆变更的 miss（5,487 token）高于后续稳态（约 1,262 token）。

## 最近一次 B0/B1 结果（2026-07-26）

运行 `prompt-cache-20260726T082711Z-174045`（deepseek-v4-flash，K=5，历史约 3.5k token，每组 3 预热 + 30 测量）：

| 指标 | B0（优化前） | B1（优化后） | 变化 |
|---|---:|---:|---:|
| Token 缓存读取率 | 91.33% | 94.73% | +3.40pp |
| 每次记忆变更的稳态 miss token | ≈3,823 | ≈1,262 | −67% |
| 平均每请求输入成本（示例价格） | $0.000124 | $0.0000846 | **−31.7%** |

稳态请求（记忆未变时）两组都只 miss 约 110–115 token 的动态内容，差异全部来自记忆变更时点。

结论边界（不要过度外推）：

- 成本降幅依赖记忆变更频率 K 与历史长度：K 越小（记忆更新越频繁）、历史越长，B1 优势越大；本数字只对 K=5、约 3.5k token 历史、该 fixture 规模成立。
- 总耗时中位数两组差异在噪声范围内（2,987ms vs 3,152ms），本实验不主张延迟改善。
- 价格用的是运行时传入的示例单价，换算比例会随 DeepSeek 定价变化。

## 运行前检查

`.env` 必须指向真正兼容 Chat Completions 的 DeepSeek API：

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
```

不要在命令行或报告中打印 `OPENAI_API_KEY`。模型与价格会变化，运行前请从 [DeepSeek 官方价格页](https://api-docs.deepseek.com/quick_start/pricing) 查当前价格。

## 运行

以下价格是一次示例参数，不是硬编码的通用事实：

```powershell
uv run python -m amadeus.evaluation.prompt_cache_cli run `
  --env .env `
  --budget-usd 5 `
  --scenario b0b1 `
  --memory-churn-every 5 `
  --hit-input-usd-per-million 0.0028 `
  --miss-input-usd-per-million 0.14 `
  --output-usd-per-million 0.28
```

`--scenario ab` 可复跑第一轮 A/B 对照。默认每组先预热 3 次、再串行测量 30 次。预热不参与主指标，因为 DeepSeek 需要先构建可复用的缓存前缀单元。

结果写入 `runtime-artifacts/prompt-cache/<run-id>/`：

- `records.jsonl`：每次请求的脱敏观测记录。
- `summary.json`：机器可读汇总。
- `summary.md`：供人阅读的结果表。

若响应没有 DeepSeek 的 hit/miss 字段，或端点调用失败，报告会标记为不可直接观测；不会把延迟变化误报为缓存命中。
