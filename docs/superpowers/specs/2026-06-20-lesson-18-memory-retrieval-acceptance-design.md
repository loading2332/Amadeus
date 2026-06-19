# Lesson 18：Memory / Retrieval 阶段验收设计

## 1. 目标

Lesson 18 不预设新功能，而是验证 Lesson 14-17 已完成的 memory tools 与 retrieval quality 是否真的组成一条可用主链。只有验收暴露出可复现的真实缺口，才进入 Part 2 修复；不得为了让课程显得“有实现”而新增临时模块。

## 2. 当前阶段地图

已实现：

- 被动预检索进入 `retrieved_memory` context-frame section。
- 主动 `recall_memory` 返回 structured JSON、memory ID、evidence 和 source reference。
- `search_messages` 负责关键词候选定位，`fetch_messages` 负责回看原始消息。
- `forget_memory` 通过 memory ID 失效旧条目。
- dense / lexical 排名、确定性 RRF、answer hypotheses、procedure multi-query、结构化注入和基础 retrieval trace。
- ToolExecutor 原生支持 async tool，主动 recall 不再经过同步桥接。

尚未验收：

- 被动注入与主动 recall 在同一真实 tool loop 中的职责是否清楚。
- recall evidence、search source_ref、fetch 输入三者是否可以稳定衔接。
- 摘要、候选预览和原始消息的证据等级是否在 prompt、工具描述和测试中一致。
- 纠错路径是否能从注入 ID 或 recall ID 回源，再 forget，而不会误删 message ID。
- retrieval trace 是否足够生成 Lesson 39 的 eval seeds。

## 3. 方案选择

采用已确认的“验收优先”方案：

1. Part 1 只读 Akashic 真实主链、工具描述和测试，形成验收矩阵。
2. 在 Amadeus 上复跑对应 focused tests 和联合 smoke。
3. 结果通过则记录证据，不修改生产代码。
4. 结果失败则把最小复现、Akashic 对应物和改动边界写入 Part 2 设计，再实施修复。

未采用：

- 实现优先：会在没有失败证据时继续扩大 retrieval 范围。
- 文档优先：只整理已有结论，无法证明工具链真实可用。

## 4. Part 1：Akashic 源码课范围

按真实调用链阅读：

```text
被动入口
  -> retrieval pipeline
  -> retrieved memory context block
  -> prompt/context frame

主动入口
  -> recall_memory
  -> structured memory records
  -> evidence/source_ref
  -> fetch_messages
  -> original session messages
```

重点文件与测试：

- `agent/retrieval/default_pipeline.py`
- `plugins/default_memory/engine.py`
- `agent/tools/recall_memory.py`
- `agent/tools/message_lookup.py`
- `agent/tools/forget_memory.py`
- `agent/prompting/assembler.py`
- `tests/test_recall_memory_tool.py`
- `tests/test_message_lookup_tool.py`
- `tests/test_forget_memory_tool.py`
- `tests/test_citation_plugin.py`
- `tests/test_memory2_retrieval_baseline.py`

必须讲清：

- retrieval summary 是候选上下文，不是最终原文证据。
- `source_ref` / `evidence` 是定位合同，不等于消息正文。
- `fetch_messages` 才把定位合同解析成可引用原文。
- forget 接收 memory ID，不接收 message ID。
- 被动与主动检索允许命中同一条记忆，但两者服务于不同推理阶段。

## 5. Amadeus 验收矩阵

| 场景 | 输入 | 必须观察的输出 | 失败意味着什么 |
|---|---|---|---|
| 被动注入 | 与历史记忆相关的当前消息 | context frame 中出现结构化 retrieved memory | runtime / context routing 断链 |
| 主动 recall | LLM 发出 recall tool call | role=tool JSON 包含唯一 memory IDs | async tool / engine / schema 断链 |
| recall → fetch | recall 返回 evidence/source_ref | fetch 返回对应原始 message | resolver 或 ID 合同不一致 |
| search → fetch | recall 不足，关键词搜索 | search source_ref 可被 fetch 消费 | lookup 两工具合同不一致 |
| correction → forget | 用户纠正已注入条目 | 先回源，再按 memory ID supersede | 证据顺序或删除边界错误 |
| retrieval fallback | embedding / hypothesis 失败 | lexical/raw query 仍返回，trace 记录 fallback | fail-open 失效 |
| context budget | 结果超过预算 | 只丢完整条目，不产生半条 source_ref | injection budget 错误 |

## 6. 验证策略

验收顺序：

1. 运行 memory/retrieval focused tests。
2. 运行 passive + active 同轮 tool-loop 测试。
3. 为 recall → fetch 与 search → fetch 增加或复用联合测试；测试 double 只隔离 LLM/embedding，不替代生产合同。
4. 运行全量 pytest、ruff、mypy。
5. 输出逐项证据表：命令、观察字段、通过条件、实际结果。

Part 1 不因为缺少 UI 而虚构点击验证；当前真实接口是 Python runtime、CLI 与测试 payload。

## 7. Eval seeds

至少沉淀以下可复跑 seed：

- 语义相近但无精确关键词：dense lane 应召回。
- 精确 ID / 技术名：lexical lane 应召回。
- 双路中等排名：RRF 后高于单路高排名。
- recall 摘要不足：必须能沿 evidence/source_ref fetch 原文。
- 两条互相矛盾记忆：不能直接把最高 score 当真相，必须回源。
- embedding 或 hypothesis 失败：fallback 有结果且 trace 可解释。
- 被动 block 与主动 JSON 同轮包含相同 memory ID：各自内部无重复，不做跨 message 去重。

这些 seed 在 Lesson 18 记录为具体案例，Lesson 39 再进入统一 retrieval eval harness。

## 8. Part 2 触发条件

只有以下情况进入修复：

- focused test 或联合 smoke 可重复失败；
- Akashic 有明确对应实现或边界；
- 能写出最小失败用例；
- 修复不需要无关重构或新核心依赖。

如果全部验收通过，Lesson 18 Part 2 只做 Amadeus 代码精读、gap audit 和简历表达，不制造代码改动。

## 9. 教学产物

- 新建 `lessons/0013-lesson-18-memory-retrieval-acceptance-part-1.html`。
- Part 1 包含 Akashic 源码课、验收矩阵、验证命令、必须复述问题和 gap audit。
- Part 2 是否新建取决于 Part 1 的真实验收结果。
- 只有用户能复述联合链路和证据等级后，才新增 Lesson 18 learning record。

## 10. 明确不做

- 不接入 Akashic 尚未接入生产主链的 QueryRewriter、SufficiencyChecker、HyDEEnhancer。
- 不把标准 BM25、reranker 或数据库级 vector index 冒充当前 Akashic 对齐要求。
- 不因验收课而改写完整 memory architecture。
- 不把单元测试通过等同于联合链路验收。
