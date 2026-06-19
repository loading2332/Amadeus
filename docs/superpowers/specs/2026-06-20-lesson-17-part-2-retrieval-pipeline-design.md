# Lesson 17 Part 2：Akashic 对齐检索管线设计

## 1. 目标

在 Amadeus 中复现 Akashic **当前真实接入运行主链**的检索设计，而不是把 Akashic 仓库里仅有独立源码和单元测试、但尚未接入主链的实验模块提前接入生产路径。

完成后，被动预检索和主动 `recall_memory` 继续共享同一个 `MemoryEngine`，但根据 `MemoryQuery.intent` 走不同查询策略：

- `context`：面向被动上下文注入，使用当前消息、显式辅助查询和结构化字符预算。
- `answer`：面向主动工具查询，使用原始查询和两条 hypothesis 扩展召回。
- `procedure`：面向流程记忆，生成多条 procedure 查询并做同 ID max-pool。
- `timeline` / `interest`：保留当前工具参数和已有行为；本次不借检索重构暗中扩张它们的语义。

## 2. Akashic 事实边界

本设计以当前源码调用链为准：

- 被动入口：`agent/retrieval/default_pipeline.py` 将请求转换为 `MemoryQuery(intent="context")`。
- 主动入口：`agent/tools/recall_memory.py` 将 tool args 转换为 `MemoryQuery`。
- 引擎分流：`plugins/default_memory/engine.py::query()` 按 intent 进入 context、answer、timeline、interest 或 procedure 路径。
- 共享召回：context 与 answer 最终复用 `_retrieve_related()` 和 retriever 的 dense + lexical + RRF。
- 主动扩展：answer 路径使用 `_gen_hypothesis(..., style="event")` 和 `style="general"`。
- 被动输出：context 路径使用 `build_injection_block()` 生成带字符预算的结构化文本块。
- procedure：`build_procedure_queries()` 与多查询 max-pool 属于已接入机制。

以下模块虽然存在源码和独立测试，但当前未接入上述生产主链，本次不接入 Amadeus：

- `memory2/query_rewriter.py::QueryRewriter`
- `memory2/sufficiency_checker.py::SufficiencyChecker`
- `memory2/hyde_enhancer.py::HyDEEnhancer`

它们记录为“Akashic 实验模块 gap”。以后若 Akashic 接入主链，先重新阅读届时调用链；若 Amadeus 要先行接入，必须明确标注为 Amadeus 扩展并单独设计。

## 3. 当前 Amadeus 状态

已有能力：

- `MemoryQuery`、`MemoryQueryResult` 和 `MemoryEngine` 稳定接口。
- `VectorMemoryStore` 持久化与 active/superseded 状态。
- embedding、简单关键词匹配和 `max(vector_score, keyword_score)` 排名。
- 被动 runtime 自动查询并注入 `retrieved_memory` block。
- `recall_memory` 主动工具输出 structured JSON、evidence 和 source reference。

本规格开始时工作区已有一份未提交 RRF 草稿。该草稿只视为候选实现，必须经过 focused test、确定性排序审计和全链验证后才能计入完成状态。

## 4. 架构边界

### 4.1 外部稳定接口

保持以下调用方接口不变：

```python
result = await memory_engine.query(MemoryQuery(...))
block = memory_engine.render_context_block(result)
```

`PassiveRuntime` 和 `RecallMemoryTool` 不直接了解 dense、lexical、RRF 或 hypothesis 的实现细节。检索策略仍由 `MemoryEngine` 封装。

### 4.2 内部组件

Part 2 将检索职责拆成以下可独立测试的单元：

1. **Query strategy**：根据 intent 生成主查询、辅助查询、kind 和时间过滤策略。
2. **Dense lane**：为查询生成 embedding，并对 active records 生成独立排名。
3. **Lexical lane**：按 Akashic 当前真实设计提取关键词和 CJK bigram，生成独立排名。它是 OR-LIKE 风格 lexical lane，不宣称为标准 BM25。
4. **RRF fusion**：按名次而非原始分数融合两路结果，使用 `k=60`、`keyword_weight=0.5`，并提供稳定 tie-break。
5. **Multi-query pooling**：多个查询的结果按 memory ID 合并，保留同 ID 的最高融合分。
6. **Structured injection**：只为被动 context 路径选择条目、分段格式化并执行字符预算。
7. **Trace assembly**：记录 intent、实际查询、lane 候选数、融合结果数、注入 ID、fallback 和错误；Lesson 36 再统一为跨模块 trace schema。

组件可以先保留在 `amadeus/vector_memory.py` 的私有函数中；当文件职责明显过载时，再提取到 `amadeus/retrieval/`。本次不为了目录形式照搬 Akashic。

## 5. 数据流

### 5.1 被动预检索

```text
user message
  -> PassiveRuntime: MemoryQuery(intent="context", context={history...})
  -> context query strategy
  -> dense lane + lexical lane
  -> RRF fusion
  -> structured injection + char budget
  -> retrieved_memory PromptBlock
  -> context frame
```

调用检索是默认行为；没有合格条目时生成空 block，不阻塞正常回复。

### 5.2 主动 recall

```text
LLM recall_memory tool args
  -> MemoryQuery(intent="answer" | other explicit intent)
  -> raw query + event hypothesis + general hypothesis
  -> 每条 query 复用 dense + lexical + RRF
  -> same-ID max-pool
  -> MemoryRecord[]
  -> recall_memory structured JSON
  -> role=tool message
```

主动线路不复用被动 block 的文本格式；它返回结构化记录供模型检查 ID、score、evidence 和 source reference。

### 5.3 重叠边界

被动和主动线路可以命中同一 ID。本次不做跨 message 的全局去重，因为两条线路发生在不同推理阶段，且主动 query 可能更精确。重复 ID 不是事实冲突；事实冲突仍通过 evidence/source reference 和 `fetch_messages` 回源解决。

## 6. 分步切片账本

### Part 2A：独立双路召回与 RRF

- dense 与 lexical 各自产生排名列表。
- RRF 使用稳定 tie-break，重复 ID 只出现一次。
- trace 保存每路原始分数和命中 lane，不用单个 `lane` 字段掩盖双路命中。
- 现有单路召回、kind filter 和 embedding fail-open 行为保持不变；时间过滤缺口继续由独立用例暴露，不在 RRF 切片中顺带改写。

完成证据：RRF focused tests、原有 vector memory tests、静态检查。

### Part 2B：结构化被动注入

- 区分 procedure/constraint、profile/preference 和 event/history 段落。
- 注入内容携带 memory ID、summary、source reference 和可信度提示。
- 应用明确字符预算；超预算按类别优先级和融合排名裁剪。
- `MemoryQueryResult.records` 保留完整检索结果，block 只包含实际注入子集。
- trace 记录 `injected_ids` 和裁剪原因。

完成证据：分类、预算边界、空结果、强制条目和确定性输出测试。

### Part 2C：intent 分流与主动双 hypothesis

- `PassiveRuntime` 显式使用 `intent="context"`。
- `answer` 路生成 event/general 两条 hypothesis，与 raw query 去重后检索。
- hypothesis provider 超时、异常或空输出时 fail-open，只使用 raw query。
- 不新增第二套 recall engine；主动和被动继续共享相同 lanes 和 fusion。

完成证据：两种 intent 调用 trace、hypothesis 成功/失败、同 ID max-pool 测试。

### Part 2D：procedure 多查询

- procedure intent 只检索 procedure/preference 类型。
- 从原始查询生成多条稳定查询；并发或顺序执行不改变最终确定性排序。
- 同 ID 结果 max-pool，再按最终分数与 ID 稳定排序。

完成证据：多查询去重、kind 限制、同 ID max-pool、部分查询失败测试。

### Part 2E：检索 trace 与失败隔离

- query result trace 至少包含：intent、queries、lane counts、fused count、injected IDs、fallbacks、errors。
- embedding 或 hypothesis 增强失败不导致被动回复失败。
- 持久化/数据库错误不得伪装为空命中；trace 必须保留错误，runtime 按已有边界 fail-open。

完成证据：trace shape focused tests、故障注入测试、runtime smoke。

### Part 2F：联合验证与课程收口

- 验证 passive injection 与主动 recall 在同一轮共存。
- 验证两路命中同一 ID 不产生重复 record。
- 验证工具 JSON 与 context block 使用同一 underlying record，但采用不同表现形式。
- 更新正式 Lesson 17 Part 2 HTML，包含实际代码、实际测试输出和 gap audit。
- 只有用户能复述主链和关键职责后，才新增或确认 learning record。

完成证据：focused tests、全量 pytest、ruff、mypy、CLI/runtime smoke 和用户复述。

## 7. 错误处理

- **Embedding 失败**：记录 `vector_error`，lexical lane 继续工作。
- **Hypothesis 失败**：记录失败与 fallback，raw query 继续工作。
- **单 lane 为空**：RRF 退化为另一 lane 的排名。
- **两 lane 均为空**：返回空 records/context block，不制造假结果。
- **格式化预算不足**：确定性裁剪并记录未注入 ID；不得截断到无法识别来源的半条记录。
- **数据库读取失败**：保留错误 trace，让 runtime 按现有 fail-open 边界继续；测试必须区分“数据库失败”和“零命中”。

## 8. 验证范围

每个切片都执行：

1. 对应 focused tests。
2. `tests/test_vector_memory.py`。
3. `tests/test_runtime_vector_memory.py`、`tests/test_runtime.py` 和 recall tool 相关测试。
4. `uv run --extra dev pytest -q`。
5. `uv run --extra dev ruff check .`。
6. `uv run --extra dev mypy amadeus`。

最终 smoke 必须展示：运行什么命令、输入什么问题、被动 block 在哪里、主动 tool JSON 在哪里、哪些 trace 字段证明实际走过双路召回。

## 9. 明确不做

- 不实现或宣称标准 BM25；Akashic 当前关键词路径是 OR-LIKE 风格 lexical retrieval。
- 不实现 reranker；当前 Akashic 主链没有对应实现。
- 不接入孤立的 `QueryRewriter`、`SufficiencyChecker`、`HyDEEnhancer`。
- 不加入新的核心依赖。
- 不修改 Akashic 仓库。
- 不用 fake、临时 parser 或硬编码生产规则代替上述真实机制；fake 只用于隔离 embedding/LLM/失败路径测试。

## 10. 后续落点与防遗漏闭环

- Lesson 18：memory tools + retrieval quality 阶段验收，输出剩余 gap 和 eval seeds。
- Lesson 36：把当前 trace 字典升级为统一 prompt/provider/tool/retrieval trace schema。
- Lesson 39：把本次 focused cases 纳入 retrieval eval harness。
- Lesson 40：最终 Akashic gap close；逐项核对实验模块届时是否已接入 Akashic 主链。

Part 2F 的 gap audit 不允许使用“后续优化”作为落点。每个未完成项必须记录：Akashic 对应物、当前是否接入、Amadeus 状态、具体课次和验证方式。
