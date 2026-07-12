# 长期记忆检索参数实验技术设计

## 能力定位

- 产品能力：在长期运行中稳定找回真正相关的记忆，同时控制普通噪声和危险旧记忆。
- 公共证明：相同 benchmark case 在不同参数 profile 下通过 `MemoryEngine.recall()` 产生可比较的 top-8、lane provenance 和 trace。
- 前置架构：归档任务 `07-11-memory-dual-lane-retrieval` 提供独立 vector/lexical 候选、RRF、hotness 和 PostgreSQL acceptance。
- 本任务扩展：参数注入合同、本地 retrieval benchmark runner、分层 metrics 和 holdout 决策报告。

## 为什么先做本地 retrieval 实验

一个回答是否正确，至少经过两道门：

```text
检索门：相关记忆是否进入 top-8、排在什么位置
    ↓
生成门：LLM 是否读取、理解并正确使用这些记忆
```

LangSmith 擅长记录完整运行和评估第二道门，但第一轮要比较大量参数。若每次同时运行 query rewrite LLM、answer LLM 和 judge，参数差异会与模型随机性、网络延迟和 judge 误差混在一起。因此当前任务只用本地 runner 隔离检索门；baseline 与最终候选的 answer-level 验证进入后续 Trellis task。

## 参数合同

引入不可变配置对象，名字以实际代码风格为准，职责等价于：

```python
@dataclass(frozen=True)
class MemoryRetrievalParameters:
    vector_candidate_floor: int = 32
    vector_candidate_multiplier: int = 4
    lexical_candidate_floor: int = 30
    lexical_candidate_multiplier: int = 2
    lexical_rrf_weight: float = 1.0
    rrf_k: int = 60
    semantic_threshold: float = 0.35
    hotness_alpha: float = 0.20
    hotness_half_life_days: float = 14.0
    reinforcement_strength: float = 1.0
    emotional_half_life_scale: float = 0.5
```

约束：

- 所有值在构造时验证 finite、范围和正数要求。
- 最终返回数仍由 `MemoryRecallRequest.limit` 决定，不放入参数 profile；benchmark 显式固定 `request.limit=8`。
- profile 根据调用方的 request limit 解析 effective SQL limits：vector 为 `max(vector_floor, request_limit * vector_multiplier)`，lexical 为 `max(lexical_floor, request_limit * lexical_multiplier)`；这分别精确复现当前 Amadeus `max(32, limit*4)` 和 Akashic 参考 `max(15, limit*1)`。
- vector effective limit 对 raw/event/general 每条 query 分别生效，不是三条 query 合计共享一个 limit。trace 与 artifact 同时记录每条 query 的候选数和去重 union。
- `MemoryRetriever` 接收一个 profile；生产 bootstrap 构造默认 profile，实验 runner 显式注入 profile。
- `rank_candidate_lanes()`、`rrf_merge()`、`hotness_fused_score()` 与 `hotness_signal_for_row()` 不再偷偷读取实验相关 module globals，而是从 profile 或显式参数获得数值。
- `reinforcement_strength` 只进入 `sigmoid(strength * log1p(reinforcement))` 的 hotness frequency；`strength=0` 时不同 reinforcement 不再改变 frequency 排序。lexical coverage 后的 reinforcement tie-break 保持生产合同，不与本参数联动。
- 为保持兼容，可以先保留旧 constructor fields 作为薄适配，但只能有一个最终真相源。
- trace 记录 profile 字段与基于 canonical JSON 计算的 fingerprint。
- 首轮 request limit `8` 固定，不进入 sweep。

这里的参数对象不是为了把所有数字都变成环境变量。实验需要可注入，生产只需要暴露确有运维价值的少数配置；最终是否进入 `RuntimeConfig` 由实验结论决定。

## Benchmark 数据模型

### 场景分布

- 30/60 个人长期助理：语言/格式偏好、profile、习惯、关系、计划和过去事件，重点覆盖中文口语、省略和语义改写。
- 21/60 项目与编程助理：架构决定、当前优先级、procedure、constraint、文件名、版本号和稀有标识符。
- 9/60 以压力行为为主：跨领域歧义、近义/同词 hard negatives、失效或冲突记忆、中英混合、2 字 CJK 和时间边界。

该比例按 query family 计算，不按 seed memory 行数计算；否则一个包含大量 decoys 的压力 corpus 会虚假地主导分布。每个主要场景内部仍应包含普通 hard negatives，不能把前 85% 都设计成无干扰的简单题。

### 规模、切分与审核

- v1 固定 60 个 query families；每个 family 可包含 2-3 个 query variants，但统计权重仍为一个 family。
- development 固定 42 families：21 个人、15 项目、6 压力，用于 rubric calibration 和参数 sweep。
- locked holdout 固定 18 families：9 个人、6 项目、3 压力，只在 shortlist 与选择规则冻结后显式 unlock。
- memory capability 是与产品场景正交的第二个维度；五类能力必须在 development 和 holdout 中都有多个 family，不能只靠总体 30/21/9 分布推断覆盖。
- 共 6 个人工审核批次，每批 10 families。batch 1 全部来自 development，用于校准 0-3 qrels、dangerous reason、required evidence 和 abstention；校准完成后重新审核 batch 1。
- query variants 随 `family_id` 整组切分；禁止把同一事实的中文、英文或改写版本拆到 development 与 holdout。

建议新增独立文件：

```text
tests/evaluation/cases/memory_retrieval_benchmark_v1.yaml
```

每个 suite 包含：

```yaml
version: memory-retrieval-v1
review_status: draft
corpora:
  - id: updated_food_preference
    memories:
      - key: current_preference
        summary: 用户目前需要无麸质餐食建议。
        memory_type: preference
        happened_at: "2026-07-01T08:00:00+08:00"
        updated_at: "2026-07-01T08:00:00+08:00"
        reinforcement: 3
        emotional_weight: 2
      - key: superseded_preference
        summary: 用户以前经常选择普通披萨。
        memory_type: preference
        happened_at: "2025-08-01T08:00:00+08:00"
        updated_at: "2025-08-01T08:00:00+08:00"
        reinforcement: 5
        emotional_weight: 2
queries:
  - id: recommend_dinner_now
    family_id: updated_food_preference_zh
    corpus_id: updated_food_preference
    split: development
    product_scenario: personal_assistant
    memory_capability: knowledge_update
    strata: [zh, both-lanes, preference, knowledge-update]
    expected_abstention: false
    raw_query: 晚餐给我推荐什么？
    fixed_hypotheses:
      event: 用户更新过饮食限制。
      general: 用户当前的饮食偏好。
    required_memory_keys: [current_preference]
    judgments:
      - memory_key: current_preference
        relevance: 3
        dangerous: false
        rationale: 当前有效且直接约束推荐。
      - memory_key: superseded_preference
        relevance: 1
        dangerous: true
        danger_reasons: [superseded]
        rationale: 主题相关，但已被新的饮食限制覆盖。
```

设计原则：

- benchmark 用稳定 `key` 表示标签，不依赖 PostgreSQL 运行时生成 id。
- 生成器首先输出 `review_status: draft` 和人类可读 review sheet；只有用户检查 query、0-3 级 qrels、required keys、hard negatives、dangerous reasons 与期望优先级后，才能改为 `approved`。正式 runner 拒绝用 draft dataset 生成参数结论。
- runner 在 seed 时把 key 写入受控 `extra`，再把返回结果映射回 key。
- `corpus_id` 负责组织一个 family 的核心答案与 hard negatives，不再表示该 query 唯一可见的数据库。正式 development run 把 development split 引用的全部 corpora 写入同一个实验 user，形成共享 search universe；holdout 使用独立 universe，禁止把 holdout memories 混入 development。
- v1 development shared universe 的 active experiment-owned memories 必须多于最大候选窗口 `64`；否则 top-15/top-32/top-64 会退化成相同结果，schema validation 直接拒绝。
- 共享 universe 中跨 corpus 进入 top-8、但尚无 qrel 的 memory 保持 `unknown`。`collect-pool` 汇总 `(query, memory)` 对及各 profile rank，人工 adjudication 后发布新 dataset hash；正式 metrics 仍拒绝 unknown，绝不自动按 grade 0 计算。
- `strata` 是显式维度，不从自然语言临时猜测。
- qrels 使用 0-3 级 relevance，`grade >= 2` 才进入二值 relevant 集合；nDCG@8 使用完整等级。未审核 memory 为 unknown，不自动当作 0。
- `dangerous` 与 relevance 分离：失效/冲突记录即使词面直接匹配，也不成为正例，并由 `DangerousHit@8` 单独形成安全硬门。
- 多证据 query 用 `required_memory_keys` 表达合取条件；`expected_abstention=true` 的 query 没有 positive qrels，单独计算 false-positive。
- query family 是 split 的最小单元；同义改写与共享答案的 query 必须留在同一 split。
- 每个 family 同时有 `product_scenario` 和 `memory_capability`；前者体现 Amadeus 使用比例，后者覆盖信息提取、跨 session、更新、时间与 abstention。
- canonical fixture v1 使用 AI 生成、用户审核后的现实虚构数据。v1 不实现私人 overlay 的自动合并；未来有脱敏真实样本时，以新 dataset task 定义 ignored local overlay 的校验与 lineage，当前缺少真实样本不阻塞 v1。

## 固定变量与可变变量

每次 sweep 开始时冻结：

- benchmark version 与内容 hash；
- corpus 内容 hash 与 judging pool version；
- PostgreSQL migration head、extension/index 和 seed corpus；
- embedding provider/model 固定为当前生产使用的 DashScope OpenAI-compatible `text-embedding-v4`，维度 1024；同一文本的 embedding 在本轮内缓存；
- raw/event/general query texts；
- ranking `now`；
- request limit `8`；
- PostgreSQL、pgvector 与 pg_trgm 版本。

代码状态必须可重建：干净 worktree 记录 commit SHA；dirty worktree 额外记录 diff hash，不能只记录一个无法代表实际运行代码的旧 commit。

每个 Stage 只允许改变声明的字段。runner 在 artifact 中同时记录 frozen context 和 changed fields，发现未声明差异时拒绝把结果合并为同一实验。

## 数据流

```text
versioned benchmark + optional local redacted overlay
-> validate qrels / split leakage / required keys / dangerous labels
-> allocate experiment-owned PostgreSQL user/corpus namespace
-> seed all corpora in the selected split into one isolated search universe
-> freeze query rewrites, embeddings and ranking time
-> for each parameter profile
   -> public MemoryEngine.recall()
   -> raw/event/general vector SQL + lexical SQL + lane-aware ranking
   -> collect per-lane/pre-RRF candidate ids, top-8 and trace
-> adjudicate unknown top results before formal comparison
-> compute per-variant, per-family and per-stratum metrics
-> write JSON + CSV + Markdown artifacts
-> development shortlist
-> explicitly unlocked holdout comparison
-> parameter decision / optional default update
```

runner 不复用当前 eval 的固定 `user_id=1`，也不调用测试 helper 的整库 `TRUNCATE`。每次 run 分配独立 user id，只删除该 run 所拥有的 memory/replacement 数据，使串行失败重试和未来并发执行都不会互相污染。

## 指标定义

对 query `q`，令 `R_q` 为 `grade >= 2` 的安全相关集合，`P_q@8` 为返回前 8 条：

- `Recall@8 = |R_q ∩ P_q@8| / |R_q|`：应该找回的记忆中，找回了多少。
- `Precision@8 = |R_q ∩ P_q@8| / 8`：使用标准固定 cutoff；不足 8 条视为未命中。另输出 `returned_precision@8` 作为“已返回内容的纯度”诊断，不能与标准 P@8 混名。
- `MRR@8 = 1 / first_relevant_rank`：第一个相关记忆越靠前越好；前 8 条没有相关项时为 0。
- `nDCG@8`：使用 0-3 级 relevance，同时奖励高相关结果靠前；危险项不产生 gain，并另由安全指标处理。
- `candidate recall_any`：实际候选并集中至少出现一条 relevant evidence；按 raw/event/general/lexical 和 union 分别报告。
- `candidate recall_all`：所有 `required_memory_keys` 都进入候选并集。
- `all_required_recalled@8`：所有 required evidence 都进入 final top-8。
- `strict lexical-only recall`：标注为 lexical-only 的 relevant targets 中，实际进入 top-8 且 signals 只含 lexical 的比例。
- `DangerousHit@8`：top-8 是否包含任一 dangerous memory；正式候选要求为 0。
- `no-answer false-positive rate`：`expected_abstention=true` 时仍返回任意候选/注入内容的比例；不把这些 case 塞进 Recall 分母。
- `pairwise hotness accuracy`：预先标注的等语义候选对中，期望优先项实际排在另一项之前的比例。

聚合先对同一 family 内的 query variants 平均，再跨 family 做 macro average；否则改写多的 family 会被重复加权。逐 stratum 同时输出 family 数、variant 数和原始结果，不能只输出总体均值。

## 分阶段参数空间

下面是首轮候选点，不是预先认定的最优值：

| Stage | 参数 | 初始候选 |
|---|---|---|
| 0 | references | Amadeus baseline：vector `32/query`、lexical `30`、weight `1.0`；Akashic-inspired：vector `15/query`、lexical `30`、weight `0.5`；两者 RRF k `60`、threshold `0.35`、alpha `0.20`、half-life `14d` |
| 1 | candidate windows | 默认 request top-8 下 vector `15/16/32/64 per query`；lexical `16/30/60`；同时报告 raw/event/general 和 union counts |
| 2 | fusion | lexical weight `0.5/0.75/1.0/1.25/1.5`；RRF k `10/30/60/90` |
| 3 | semantic gate | threshold `0.25/0.30/0.35/0.40/0.45` |
| 4 | hotness | alpha `0/0.10/0.20/0.30`；half-life `7/14/30/60d`；reinforcement strength `0/0.5/1/2`；emotional scale `0/0.5/1` |
| 5 | interaction check | 每阶段最多保留 2 个点，只运行少量交叉组合 |

Stage 4 原设计不做 `4 * 4 * 4 * 3` 的全组合，而是在 pairwise subset 上逐族筛选。执行期间用户进一步批准收缩为只验证当前 `0.20/14d` hotness baseline；因此 Stage 4 不生成替代 hotness profile，Stage 5 只比较生产 baseline 与两个语义 finalist。参数边界和替代 hotness 组合留到有更多 pairwise family 的新 dataset version，不能把“baseline 通过”写成“baseline 已证明最优”。

Stage 2～4 不允许从默认 baseline 重新开始。每个阶段先从上一阶段 JSON artifact 中显式冻结最多两个 profile；shortlist 保存 source stage、dataset hash、完整参数、profile fingerprint 和自身 hash。下一阶段加载时逐项验证，然后只替换本阶段声明的字段。缺少 shortlist、stage 不连续、dataset hash 漂移或 fingerprint 不一致都必须拒绝运行。

## 选择规则

先执行硬门：

- user/active/status/replacement/scope/type/time 隔离全过，且过滤前候选也不得泄漏；
- canonical lexical rescue must-hit 全过；聚合 lexical-only recall 作为质量指标，不要求所有合成 lexical case 机械地达到 100%；
- `DangerousHit@8=0`；
- provenance 与 lane status 正确；
- hot-but-unrelated 不越过 semantic threshold；
- 重复运行 ranked ids 稳定。

通过硬门后按以下顺序判断：

1. 优先比较 development/holdout family-first Recall@8；holdout 绝对差异 `< 5.56` 个百分点时视为 Recall 相当，`>= 5.56` 时只称方向性实际改善/退化。
2. Recall 相当时依次比较 all-required recall、最差关键 stratum、nDCG@8、MRR@8、Precision@8、no-answer false-positive 和 hotness pairwise accuracy。
3. 上述质量指标仍无清晰赢家时，选择候选更少、配置更接近基线的 profile；这只是减少检索暴露面与改动幅度的保守 tie-break，不作为 latency 代理指标。
4. holdout 以独立 split/hash 保存，开发 runner 默认拒绝加载详细结果；只有 shortlist 与 practical-equivalence 规则冻结后才允许显式 unlock；解封后不再调参。

本任务不把正常成功请求的毫秒耗时加入指标或选择规则；数据库 error、timeout 和 lane failure 仍按可靠性硬门处理。

首版固定 18 个 holdout families，每例占 5.56 个百分点，只能识别明显变化。报告必须展示逐 family paired difference 和 bootstrap 区间，不能宣称 1-2 个百分点的小幅提升具有统计确定性。

## LangSmith 边界

本地 artifact 是当前任务参数选择的权威来源。参数冻结后的后续 Trellis task 才执行 LangSmith：

```text
baseline retrieval profile + 相同 answer cases
vs
selected retrieval profile + 相同 answer cases
```

这一步验证“更好的 retrieval 是否真的改善回答”，不反向参与当前 holdout 调参。任何包含真实个人记忆的数据，在上传前必须另行获得授权并脱敏。

## 兼容、发布与回滚

- 参数对象默认值完全复现当前行为，先用 characterization tests 证明迁移前后 top-8/trace 一致。
- benchmark runner 与 artifacts 不进入生产请求路径。
- 若证据支持新默认值，参数改动单独提交，并在 trace 中可见；旧值保留为可快速回退 profile。
- lexical kill switch、独立 lane 失败降级、scope fallback 与 context 顺序不变。
- 若实验发现需要改变 tokenizer、lane 结构或 hotness 作用位置，停止参数外推并创建新的架构任务。

## 主要风险

- 数据集过小导致过拟合：使用 query-family split、分层报告和 locked holdout。
- embedding/query rewrite 波动污染比较：一轮 sweep 内冻结并缓存，模型变化另开实验版本。
- 正式 provider 的网络调用、模型版本或供应商服务可能漂移：运行前记录 provider/model/base host 与向量维度，冻结本轮 embedding artifact；后续重跑优先复用同一缓存。
- 时间衰减随运行时间漂移：注入单一 ranking time。
- synthetic data 与真实使用有差距：canonical 合成集保证可提交与可复现，本地脱敏 overlay 用于外部有效性复核。
- 参数化重构本身改变行为：先做 baseline characterization，再实现 sweep。
- 当前 `run_memory_recall_case()` 可复用部分公共执行逻辑，但它只隔离临时 workspace，不隔离 PostgreSQL；新 runner 必须拥有独立的 database namespace/lifecycle。
- 当前 eval seed 不能直接固定 `updated_at` 和完整 hotness 输入；需要受控 seed seam，不能依赖运行当下时间或事后整库修改。
- 当前 LangSmith sync 没有本任务需要的 dataset version/tag/split/hash 合同，且 recall sync 不清理 stale examples；若后续接入，必须另行补齐，不能把现状当作已冻结数据集。

## 任务拆分决策

当前 vertical slice 已确认限定为：参数合同、Amadeus retrieval benchmark、本地 runner、development sweep、locked holdout 与参数决策。它们共用同一组 frozen inputs 与 artifact lineage，保留在一个 Trellis task 中。

LongMemEval/PersonaMem adapter、oracle/full-history/no-retrieval answer baselines 和 LangSmith answer-level A/B 创建后续 task。公共 benchmark 同时测 ingest、consolidation、retrieval 与 reading，若塞入当前参数任务，会污染参数因果并显著扩大外部模型成本。

当前任务的 typed profile、benchmark/metrics、共享 split search universe、本地 PostgreSQL runner、candidate observer、只读 embedding cache、judging-pool collector、stage shortlist 继承、holdout-only qrels rebase 与 artifacts 均已实现。Development 在 hash `2748c90799831d4c9eccabb8dc96c02c3cefa793cf530a1c92beec3a136571dd` 上冻结三组 Stage 5 finalists；generator 在应用 holdout overlay 前输出并校验同 hash selection snapshot。首次 holdout pool 的 103 个 unknown 经批准后只新增 qrels，dataset hash 更新为 `b0566f9a99a94761f4ba40669d70c7d941933464feac8b81830d5047d38499c9`。Rebase 逐项证明 corpus/query/旧 qrels 不变且新增项恰好等于 approved overlay；重签后的 holdout completeness 为 0 unknown，正式 holdout 只运行一次。最终选择保留生产 baseline；具体阶段取舍、逐 family 差值和 bootstrap 区间见 `review/parameter-decision.md` 与 `review/locked-holdout-paired-analysis.md`。
