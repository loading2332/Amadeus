# 真实世界长期记忆检索与评测研究

## 研究问题

本研究不寻找一个可以直接抄进 Amadeus 的“行业最佳参数”。它回答：

1. 公开 benchmark 如何定义长期记忆能力；
2. 真实检索系统如何处理 vector、lexical、候选窗口与融合参数；
3. 没有真实用户日志时，Gold Set 怎样建立才可信；
4. 本任务应该做到 retrieval 参数实验，还是同时承担端到端回答 benchmark。

研究日期：2026-07-11。

产品范围决定：研究记录保留了公共 benchmark 和工业系统对 latency 的关注，但用户已明确当前 Amadeus 参数任务不测 P50/P95。性能材料仅作为背景，不进入 PRD、实现或参数选择规则。

## 结论摘要

真实世界没有一个能直接给出 Amadeus `top-k/weight/RRF k/threshold/hotness` 最优值的公共 benchmark。现有实践分成两类：

- LongMemEval、PersonaMem、LoCoMo、Memora 等评估长期记忆产品能力，主要关注最终回答、时间更新、跨 session 推理和拒答；
- TREC/BEIR 风格 IR 评测关注 query 到 evidence 的相关性，用 Recall、Precision、MRR、nDCG 等确定性指标评价检索。

参数选择必须优先采用第二类方法，因为它能把“没检索到”与“检索到了但 LLM 没用好”分开。公共长期记忆 benchmark 适合作为后续端到端外部有效性验证，不适合直接参与第一轮参数搜索。

“AI 生成现实但虚构的候选案例，再由用户人工审核、冻结 dataset hash”是可行且符合公开 benchmark 的建集路径；但 AI 生成后未经人工判断的标签只能叫 `draft`，不能叫 Gold Set。

## 证据分级

### A 级：同行评审论文、官方 benchmark 数据与代码

- LongMemEval，ICLR 2025；
- LoCoMo，ACL 2024；
- PersonaMem，COLM 2025；
- LongMemEval-V2 官方 benchmark；
- Memora，ACL Findings 2026；
- TREC、BEIR、原始 RRF 论文。

### B 级：官方产品文档和开源仓库

- pgvector、Elasticsearch、Azure AI Search；
- LangSmith 官方 evaluation 文档；
- Mem0、Zep、Letta 的公开代码与 issue。

### C 级：厂商博客和社区讨论

这类材料只用于发现复现风险和实践痛点，不把厂商自报分数当作中立结论。

## 1. 第一性原理：长期记忆评测实际有三道门

一个问题最终答对，至少依赖三步：

```text
索引 / 写入门
历史内容是否被正确提炼、更新、失效和存储
        ↓
检索门
当前 query 是否找回正确、仍有效的 evidence
        ↓
阅读 / 生成门
LLM 是否理解 evidence，并生成正确、不引用旧事实的回答
```

若三步一起测，最终答案错误时无法判断：

- memory 根本没写进去；
- memory 写进去了但没召回；
- memory 已召回但 reader 用错了；
- 旧 memory 没失效，污染了回答。

因此当前参数任务要固定索引与 reader 之外的变量，先隔离“检索门”。这也是 LongMemEval 明确区分 indexing、retrieval、reading 的原因。

## 2. 公共长期记忆 benchmark 怎么做

| Benchmark | 主要规模与能力 | Gold / 指标 | 对 Amadeus 的用途与局限 |
|---|---|---|---|
| LongMemEval | 500 个高质量问题；信息提取、跨 session、时间、knowledge update、abstention | `answer`、turn 级 `has_answer`、session 级 `answer_session_ids`；检索使用 Recall/nDCG，回答另行评分 | 最接近 Amadeus 长期助理；证明 retrieval 与 reading 应分层。公开集无 blind holdout，2025 年还发布 cleaned 版，必须锁版本/hash |
| LongMemEval-V2 | 451 个手工问题；最长 500 条 web/enterprise trajectory、最高 115M tokens；5 类 agent experience memory | 同时评估 answer accuracy 与 query latency，以 accuracy-latency frontier 比较 | 证明质量和延迟要看 Pareto/frontier；多模态 web-agent 规模超出当前 MVP，不应直接塞进首版任务 |
| PersonaMem | 180+ synthetic histories；每个最多 60 sessions；15 个现实 personalization task；7 类 in-situ query | 当前 persona 状态对应的选项 accuracy | 证明“受控生成 + 现实任务 + 动态偏好 + 人工策划”可行；偏 answer-level，不能单独选 retrieval 参数 |
| LoCoMo | 10 段长对话、272 sessions、5,882 turns、1,986 QA；single-hop、multi-hop、temporal、open-domain、adversarial | answer、category、evidence dialog ids；QA 与 evidence recall | 有 evidence 标签，适合参考场景；只来自 10 个对话世界，缺少 knowledge-update，不能作为唯一 Gold Set |
| Memora | 模拟数周到数月的个性化交互，重点测试 memory mutation、删除和更新 | 分开标注应出现的有效事实与不应出现的 obsolete/deleted 事实；FAMA 惩罚复用失效记忆 | 直接支持 Amadeus 把 obsolete/dangerous 记忆设为独立安全门，而不是只优化普通相关性 |
| LMEB | 22 个数据集、193 个 long-horizon memory embedding retrieval task，覆盖 episodic/dialogue/semantic/procedural | 主要比较 embedding retrieval | 适合以后选择 embedding model；当前任务冻结 embedding，不应把“换模型”和“调融合参数”混在一次实验里 |

### 2.1 LongMemEval 给出的关键方法

LongMemEval 的 evidence 标签使它能单独计算 retrieval recall/nDCG，再用 oracle evidence 测 reader。论文还报告：即使 evidence 完美，reading strategy 不佳仍可带来约 10 个点的回答差距。

这说明：

```text
retrieval 指标提高
不自动等于
最终回答一定提高
```

但反过来，若 relevant memory 根本没有进入 top-8，reader 一定无法使用它。所以当前任务先以 Recall@8 为第一质量目标，随后再做 answer-level A/B，依赖顺序是正确的。

### 2.2 公开数据集也不是永恒真值

LongMemEval 在 2025 年因干扰 history 影响答案正确性发布 cleaned 版本。LoCoMo 的少量 conversation worlds、含图问题和歧义问题也受到公开质疑。

因此所有实验必须记录：

- dataset 版本与内容 hash；
- corpus hash；
- code SHA；
- embedding/index 版本；
- reader/judge/prompt 版本；
- 并发和 latency 口径。

只写“我们跑了 LoCoMo”不具备可复现性。

## 3. 工业 hybrid retrieval 如何处理参数

### 3.1 pgvector 官方建议

pgvector 官方 README 明确建议将 vector search 与 PostgreSQL full-text search 组合，再用 RRF 或 cross-encoder 融合。

这证明 `PostgreSQL + pgvector + 独立 lexical candidate + fusion` 是正常的工程路线。但 pgvector 不替应用决定 tokenizer、候选窗口或 RRF 权重，这些仍由领域数据决定。

来源：[pgvector Hybrid Search](https://github.com/pgvector/pgvector#hybrid-search)

### 3.2 Elasticsearch

Elasticsearch 的 RRF API 暴露：

- `rank_constant`：默认 60；越大时，lane 内较低排名的结果影响越大；
- `rank_window_size`：控制每个独立结果集进入 RRF 的候选数；扩大通常改善相关性，但增加性能成本。

这与 Amadeus 的实验变量一一对应：

- `RRF k` 不是隐藏常量；
- vector/lexical candidate window 既影响质量，也影响延迟；
- final size 与 fusion window 是两个不同概念。

来源：[Elasticsearch Reciprocal Rank Fusion](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/rrf.html)

### 3.3 Azure AI Search

Azure hybrid search 并行执行 text 与一个或多个 vector query，再以 RRF 融合。它显式提供 vector `k` 和 query weight，并说明 vector KNN 在语料足够时总会返回 `k` 条，即使尾部相似度很差。

对 Amadeus 的启示：

- 扩大 vector top-k 会扩大召回机会，也会引入低相关候选；
- semantic threshold 与 Precision 约束不能缺失；
- 多条 vector rewrite 会产生多个排名列表，必须固定 query rewrite 才能公平比较融合参数。

来源：[Azure Hybrid Search RRF](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)

### 3.4 `k=60` 的来源不是自然常数

原始 RRF 论文在 pilot investigation 中选择 `k=60`，随后固定用于验证。后续 hybrid retrieval 研究发现 RRF 对参数可能敏感，并不存在“所有语料都应使用 60”的证明。

来源：

- [原始 RRF 论文](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)
- [An Analysis of Fusion Functions for Hybrid Retrieval](https://arxiv.org/abs/2210.11934)

因此 Amadeus 应把 60 当 baseline，而不是答案。

## 4. 厂商 benchmark 为什么不能直接横比

### 4.1 Mem0 的可复现性案例

Mem0 论文结果使用 SaaS `MemoryClient`，不是 OSS `Memory`。官方在 issue 中确认：

- SaaS 与 OSS 使用不同 pipeline；
- 论文后算法又发生变化；
- 当前平台结果也不一定能复现论文数字。

同一 issue 还出现 paper 与 evaluation script 的 batch/top-k 配置不一致问题。

来源：[mem0ai/mem0#2800](https://github.com/mem0ai/mem0/issues/2800)

这不是为了否定 Mem0，而是说明一条实验原则：没有完整配置、版本和执行路径，单个分数无法审计。

### 4.2 LoCoMo 厂商复测协议不一致

Mem0、Letta、Zep 的公开 LoCoMo 结果存在这些差异：

- 有的删除 adversarial 类别；
- 有的从 token-F1 改成 LLM judge；
- 有的比较 SaaS，有的比较 OSS；
- 有的串行调用竞品，有的并行；
- reader/judge 模型和 prompt 不一致；
- latency 有的只算 search，有的包含完整 answer pipeline。

所以这些分数适合发现方案和风险，不适合作为 Amadeus 的参数真值。

## 5. Gold Set 从第一性原理怎么建立

### 5.1 Gold Set 的核心是 qrels

对 retrieval 而言，Gold Set 不是只有“标准答案文本”，而是：

```text
query
-> memory id
-> relevance judgment
```

这类映射在信息检索领域称为 qrels。

建议使用四级相关性：

| Grade | 含义 |
|---|---|
| 3 | 当前有效，且直接回答 query |
| 2 | 当前有效，是完整回答所必需的支持证据 |
| 1 | 主题相关，但不足以回答或不应进入主要上下文 |
| 0 | 人工确认无关 |

二值 Recall/Precision 中，`grade >= 2` 才算 relevant。Grade 1 可以影响 nDCG 的 graded relevance，但不能把“有点相关”当成成功召回。

### 5.2 `dangerous` 必须独立于 relevance

过期版本、已更正事实、已遗忘内容、错误 user/project 和冲突旧记忆，不能简单标成普通 `0`。

原因是：

- 普通无关记忆进入 top-8 是噪声；
- 旧事实进入 top-8 可能直接造成错误决定；
- 两者产品风险不同，不能在平均 Precision 中互相抵消。

因此增加独立标签：

```text
dangerous_negative_ids
obsolete_evidence_ids
```

并以 `DangerousHit@8 = 0` 作为硬门。

### 5.3 未审核不是无关

当新参数把一条之前没有进入 judging pool 的 memory 推到 top-8 时，它的状态是 `unknown`，不是自动 grade 0。

正确流程是：

```text
进入新 top-N 的 unknown memory
-> 人工 adjudication
-> 产生新的 dataset version/hash
-> 所有待比较 profile 在新版本上重跑
```

否则旧配置见过的结果都被认真标注，新配置发现的新结果却被自动判错，会产生系统性偏差。

### 5.4 多证据和拒答需要额外字段

多个 memory 必须同时召回时，普通 qrels 只能表达“每条各自相关”，不能表达合取条件。因此增加：

```text
required_memory_ids
all_required_recalled@8
```

无正确 evidence 的 query 不应硬算 Recall；应单独标记：

```text
unanswerable: true
```

并计算 no-answer false-positive rate。LongMemEval 也会把 abstention case 从普通 retrieval Recall 中排除，因为它们没有 answer location。

## 6. 没有真实使用数据，AI 生成后人工审核是否可行

可行，但有严格边界。

LongMemEval、LoCoMo、PersonaMem 都包含受控生成或合成 history，再进行人工策划、修订或 evidence 标注。它们不是直接把真实用户日志原样公开。

Amadeus v1 应采用：

```text
AI 生成现实但虚构的 query family、corpus 和候选标签
-> 状态为 draft
-> 用户逐条审核 query、qrels、hard negatives、dangerous labels
-> 修正歧义和过度简单案例
-> 标记 approved
-> 冻结 dataset hash
-> 才允许正式参数选择
```

AI 可以降低案例编写成本，但不能同时当出题人、答题人和最终裁判。

## 7. 指标应该分层，而不是压成一个总分

### 7.1 Candidate layer

回答“相关 memory 是否有机会参与融合”：

- `recall_any@candidate_k`：至少找回一条 relevant evidence 的 family 比例；
- `recall_all@candidate_k`：所有 required evidence 都进入候选并集的 family 比例；
- vector/lexical 各 lane recall；
- lexical-only outside-vector-window recall。

### 7.2 Final top-8 layer

回答“最终注入上下文的质量”：

- `Recall@8`：需要的 evidence 找回多少；
- `Precision@8`：top-8 中 relevant 的比例；
- `MRR@8`：第一条 relevant memory 是否靠前；
- `nDCG@8`：同时考虑 0-3 级相关性和排名；
- `all_required_recalled@8`：多证据是否找全。

MRR 不能单独作为主指标，因为它只关心第一条 relevant；对于需要多条 evidence 的 query，第一条命中不代表问题可回答。

### 7.3 安全层

- `DangerousHit@8 = 0`；
- user/status/replacement/scope/type/time 硬门全部通过；
- no-answer false-positive rate；
- lane provenance 与独立失败降级不回归；
- hot-but-unrelated 不得越过 semantic threshold。

### 7.4 当前任务不做性能评分

真实世界方案常报告 SQL、retrieval core 或完整请求 latency，但这是研究事实，不是当前 Amadeus task 的交付要求。当前任务只保留 candidate counts 作为检索机制诊断；正常成功请求的毫秒耗时不采集，数据库 error/timeout 仍按可靠性失败处理。

### 7.5 Answer layer，后续独立验证

- answer correctness；
- abstention correctness；
- obsolete memory misuse；
- source grounding；
- token cost 与完整端到端 latency。

这一层才需要 answer LLM、可能的 LLM judge 和 LangSmith traces。

## 8. Dev / holdout 如何避免自我欺骗

### 8.1 按 query family 切分

同一个事实的多种问法共享答案和 corpus，不能把 paraphrase 随机拆到 dev 与 holdout。否则 dev 已经泄露了 holdout 的语义结构。

`family_id` 是最小切分单元：一个 family 的所有 variant 必须全部进入同一个 split。

### 8.2 先 family 内平均，再跨 family macro average

若一个 family 有 5 个改写，另一个只有 1 个，直接按 query 平均会让前者权重变成后者的 5 倍。

正确做法：

```text
先计算每个 family 内 variants 的平均
-> 再对所有 family 做 macro average
```

### 8.3 60 families 是方向性 MVP，不是统计终局

当前建议的 60 families、42 dev、18 holdout 可以支持首版方向性实验和明显回归检测。但 18 个 holdout family 中，每错一例会改变 `1/18 = 5.56` 个百分点。

因此它不能证明 1-2 个百分点的小幅提升具有统计确定性。正式报告应：

- 展示逐 family paired difference；
- 报告 family-level bootstrap 区间；
- 把结论限定为“首版 evidence-backed choice”；
- 后续用 dogfooding 真实失败扩充新版本。

## 9. 推荐基线与参数实验顺序

### 9.1 必须同时报告的 retrieval baselines

- vector-only；
- lexical-only；
- 当前 Amadeus hybrid baseline；
- Akashic-like 参数 profile；
- 入选的 Amadeus candidate profile。

这样才能判断提升来自哪个 lane，而不是只比较两个不透明总分。

端到端后续任务再加入：

- oracle evidence；
- full history；
- no retrieval；
- baseline vs selected hybrid。

### 9.2 参数顺序

```text
Stage 0：复现 baseline
Stage 1：candidate windows，包括 vector 15/16/32/64
Stage 2：lexical weight 与 RRF k
Stage 3：semantic threshold
Stage 4：hotness / reinforcement / time decay / emotional scale
Stage 5：只对 shortlist 做少量交叉组合
```

先调候选窗口，因为候选外的 memory 不可能被后续排序救回；最后调 hotness，因为只有语义门和基础相关性稳定后，才能判断时间与强化信号是否真的改善排序。

本任务不使用 learning-to-rank、自动超参数优化或 deep learning workflow。

## 10. LangSmith 什么时候用

LangSmith 官方把 evaluation 分成：

- offline evaluation：在有 reference output 的 curated dataset 上做 benchmark/regression；
- online evaluation：在没有 ground truth 的生产 traces 上监控异常，并把真实失败回灌离线集。

对 Amadeus：

### 当前 retrieval 参数任务

- 不需要 LangSmith；
- qrels 指标是确定性计算；
- runner 要走真实 PostgreSQL，但不调用 answer LLM 或 judge；
- query rewrite 若被固定，`num_repetitions=1` 即可。

### 参数冻结后的端到端任务

- 在同一脱敏 dataset version 上比较 baseline 与 selected profile；
- 记录完整 traces，判断模型是否正确使用 memory；
- LLM 非确定链路可重复 3-5 次；
- 真实记忆默认不上传，除非另行脱敏和授权。

来源：[LangSmith Evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts)

## 11. 对当前 Trellis task 的建议

### 已确认的当前任务交付

- Amadeus 专属、人工审核的 retrieval Gold Set；
- qrels、dangerous/obsolete、多证据和 abstention schema；
- typed parameter profile；
- 真实 PostgreSQL local runner；
- candidate/final/safety 分层指标；
- dev sweep、sealed holdout 和参数决策报告。

### 已确认拆成后续任务

- LongMemEval / PersonaMem adapter；
- oracle/full-history/no-retrieval answer baselines；
- baseline vs selected 的 LangSmith answer-level A/B；
- production online eval 与真实失败回灌。

拆分理由不是减少质量，而是保护因果关系。公共 benchmark 同时包含 ingest、consolidation、retrieval 和 reading；若它与当前参数 sweep 混在一起，失败原因会再次变得不可辨认，任务范围和外部模型成本也会显著扩大。用户已于 2026-07-11 确认按此边界拆分。

## 主要来源

- [LongMemEval 官方仓库](https://github.com/xiaowu0162/LongMemEval)
- [LongMemEval ICLR 2025 论文](https://proceedings.iclr.cc/paper_files/paper/2025/file/d813d324dbf0598bbdc9c8e79740ed01-Paper-Conference.pdf)
- [LongMemEval-V2 官方仓库](https://github.com/xiaowu0162/LongMemEval-V2)
- [PersonaMem 官方仓库](https://github.com/bowen-upenn/PersonaMem)
- [LoCoMo 官方仓库](https://github.com/snap-research/locomo)
- [Memora ACL 2026 论文](https://aclanthology.org/2026.findings-acl.1337/)
- [LMEB 官方仓库](https://github.com/KaLM-Embedding/LMEB)
- [BEIR](https://github.com/beir-cellar/beir)
- [NIST trec_eval](https://github.com/usnistgov/trec_eval)
- [原始 RRF 论文](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)
- [RRF 参数分析](https://arxiv.org/abs/2210.11934)
- [pgvector Hybrid Search](https://github.com/pgvector/pgvector#hybrid-search)
- [Elasticsearch RRF](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/rrf.html)
- [Azure Hybrid Search RRF](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)
- [LangSmith Evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts)
- [Mem0 复现 issue](https://github.com/mem0ai/mem0/issues/2800)
