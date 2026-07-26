# Prompt Cache 友好的提示词组装契约

> 来源：任务 07-24-prompt-cache-benchmark 的实机 A/B 与 B0/B1 实验（DeepSeek deepseek-v4-flash，2026-07）。
> 实验工具与结果解读见 `docs/prompt-cache-benchmark.md`；原始数据在 `runtime-artifacts/prompt-cache/`。

---

## 核心事实（实机证实，非推测）

1. **供应商缓存按字节前缀匹配，对 system/user 角色边界不敏感。**
   无历史 fixture 的 b0b1 运行（`prompt-cache-20260726T081836Z-081868`）中，同一批材料"放 system 末尾"与"放 user 开头"两种排列的缓存读取率精确相同（93.68%）。把内容在 system/user 之间搬动本身不产生缓存收益；**内容相对于对话历史的位置才是决定因素**。
2. **位于历史之前的半动态内容一旦变化，其后整段历史的缓存全部失效。**
   含 3.5k token 历史的运行（`prompt-cache-20260726T082711Z-174045`）中，长期记忆每 5 请求更新一次：记忆在历史前（B0）时每次更新 miss ≈3,823 token；记忆在历史后（B1）时稳态 miss ≈1,262 token（−67%），平均每请求输入成本 −31.7%。
3. **DeepSeek 的缓存前缀单元需要供应商观察后才落盘。**
   B1 首次记忆变更 miss（5,487）显著高于后续稳态（≈1,262）。凡做缓存实验必须分预热与测量阶段，预热不计入指标。

## 组装契约：Section 路由

`amadeus/prompting/assembler.py` 的 `CONTEXT_FRAME_SECTIONS` 决定 section 进 system prompt 还是历史之后的动态 context frame：

```python
CONTEXT_FRAME_SECTIONS = {
    "self_model",        # 半动态：随自我模型演化
    "long_term_memory",  # 半动态：随记忆抽取/优化更新
    "recent_context",
    "retrieved_memory",
    "active_skills",
    ...
}
```

**规则**：

- system prompt 只留请求之间**字节级稳定**的 section（identity 等）。
- 会在会话生命周期内变化的 section（记忆、自我模型、检索结果、运行时元数据）一律路由到 context frame（历史之后）。
- 新增 section 时先回答："同一会话相邻两次请求之间，这段内容会变吗？" 会变 → `CONTEXT_FRAME_SECTIONS`。

### Wrong vs Correct

```python
# Wrong：把会变的记忆放进 system prompt（历史之前）
# 记忆一更新，其后全部历史 token 重新计费重新处理，对话越长损失越大
system = identity + long_term_memory
messages = [system, *history, user_input]

# Correct：system 只留稳定前缀，半动态内容在历史之后注入
system = identity
messages = [system, *history, frame(self_model, long_term_memory, ...) + user_input]
```

## 验证与实验规范

- 缓存效果**只以供应商 usage 字段为准**（DeepSeek: `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`），缺字段标"不可直接观测"，不得用延迟下降推断命中。
- 复跑实验：`uv run python -m amadeus.evaluation.prompt_cache_cli run --env .env --budget-usd 5 --scenario b0b1 ...`（单价须按 DeepSeek 当期价格显式传入；runner 内置预算截断）。
- 相关测试：`tests/evaluation/test_prompt_cache_benchmark.py`（fake provider，不发真实请求）、`tests/prompting/`（section 路由断言）。
- 结论边界：成本降幅随记忆更新频率与历史长度变化，引用数字时必须带上 K 与历史规模（本次为 K=5、约 3.5k token 历史）。
