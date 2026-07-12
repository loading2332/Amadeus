# 评估并校准长期记忆检索参数

## 目标

在独立 vector lane 与 lexical lane 已经正确建立之后，用可复现的本地实验回答以下问题：当前长期记忆检索的候选窗口、RRF 融合、语义阈值和 hotness 参数是否合适；如果不合适，哪一组配置能在不破坏隔离与 provenance 的前提下改善长期记忆召回质量。

任务的最终产物不是“必须调出一组不同于当前默认值的数字”，而是一份有 holdout 证据的参数决策。若候选没有达到预注册的质量改善门槛，保留基线也是有效结论。

## 第一性原理

1. 检索参数只决定候选数量、过滤门槛和排序强弱；它不能修复不存在的候选通道。独立双 lane 机制已经由前置任务完成，本任务才具备调参前提。
2. “参数更好”必须相对于带相关性标签的查询集合来定义。没有 ground truth，只看几条示例或主观感受，本质上仍是在猜。
3. 公平比较要求除待测参数外的输入保持不变。语料、query rewrite、embedding、时间快照和数据库状态若同时变化，就无法知道指标变化由谁造成。
4. 当前产品阶段明确以召回质量为目标，数据库毫秒级差异不参与参数选择。本任务仍走真实 PostgreSQL 证明公共行为，但不建立 latency benchmark。
5. 调参数据和最终验收数据必须分离。若反复看同一批 case 再改参数，会把参数拟合到题目，而不是拟合到真实问题。
6. retrieval-only 指标先回答“相关记忆有没有被找回、排在第几”；LangSmith/LLM judge 适合后续回答“模型是否正确使用了记忆”。两者不能混为一项实验。

## 已确认事实

- 前置任务 `07-11-memory-dual-lane-retrieval` 已归档并建立：raw/event/general 各自进入 vector lane，raw query 独立进入 lexical lane，再以真实 lane provenance 做 RRF。
- 当前生产基线是：final top-k `8`；每个 vector query 的候选窗口 `4 * max(top_k, request.limit)`，默认 `32`；lexical 窗口 `max(30, 2 * final_limit)`，默认 `30`；lexical RRF weight `1.0`；RRF `k=60`；semantic threshold `0.35`。
- 当前 hotness 基线是：`alpha=0.20`、基础半衰期 `14` 天；reinforcement 进入 frequency 曲线；`emotional_weight` 通过 `14 * (1 + 0.5 * emotional_weight / 10)` 延长有效半衰期。
- hotness 当前只参与 vector lane 的 lane 内排序；lexical lane 主要按 term coverage、reinforcement 和稳定 id 排序。本任务不静默改变这一架构合同。
- 当前 canonical `memory_recall_v1.yaml` 只有 3 个公共行为 case，能够证明机制正确，但不足以支撑参数选择。
- 当前 `memory_recall_runner` 以 LangSmith 为执行入口，并包含可能受 LLM 输出影响的 runtime-turn case；它不适合作为第一轮大量参数组合的本地 runner。
- PostgreSQL 运行于本机 WSL Debian 的 Docker 中；本任务使用真实数据库验证检索正确性，但不测 P50/P95 或查询计划性能。
- 首轮参数实验不需要 LangSmith。只有 retrieval 参数候选收敛后，才考虑用 LangSmith 比较最终答案对记忆的使用质量。
- 当前 `MemoryRecallRequest.limit` 决定单次公开 recall 的最终返回数量；benchmark 固定传入 `8`。`MemoryRetriever.top_k` 不是 final top-k 的唯一真相源，不能直接重命名为 profile 的 `final_top_k`。
- 当前默认 vector window `32` 是 raw/event/general 每条 vector query 各取 32，三个 query 的去重并集最多可明显大于 32；实验 artifact 必须同时记录 per-query 与 union candidate counts。
- hotness 的时间输入是 memory 的 `updated_at`，不是事件的 `happened_at`。正式 fixture 必须显式固定 `updated_at`、reinforcement 和 emotional weight。
- 当前生产 embedding provider 是 DashScope OpenAI-compatible endpoint 上的 `text-embedding-v4`，PostgreSQL schema 使用 `vector(1024)`。正式质量实验固定该 provider/model 与 embedding cache；测试 fake 只能验证 runner，不得用于参数结论。

## 研究依据与适用边界

- Akashic 的公开 `answer` 路径是：raw/event/general 各做 vector top-15，raw query 单独做 keyword top-30，再以 RRF `k=60`、keyword weight `0.5` 融合 top-15，最后返回 top-8；vector threshold 为 `0.35`，hotness 为 `alpha=0.20`、基础半衰期 14 天。
- 在该参数下，keyword-only rank 1 为 `0.5 / 61 = 0.00820`，低于 vector-only rank 15 的 `1 / 75 = 0.01333`。vector 候选填满时，lexical-only memory 无法进入融合 top-15。因此 Akashic 提供架构参考点，不提供最优参数答案。
- Akashic 的 LongMemEval/PersonaMem harness 评估最终回答，没有 retrieval qrels、Recall/MRR/nDCG、lane provenance、P95、dev/holdout 或参数 sweep。
- LongMemEval 证明 indexing、retrieval、reading 应分层评估；PersonaMem 证明“受控合成历史 + 人工策划”可行；LoCoMo 提供 evidence ids 但场景世界较少；Memora 证明过期、删除和冲突旧记忆必须单独惩罚。
- 完整证据和来源见 `research/akashic-retrieval-and-evaluation.md` 与 `research/real-world-memory-evaluation.md`。

## 需求

### R1. 建立可标注、可分层、可冻结的 retrieval benchmark

- 新增独立的长期记忆 retrieval benchmark schema 和版本化 case 文件，不把参数标签硬塞进现有 3-case smoke suite。
- 每条 query 必须以稳定 memory key 声明 0-3 级 qrels：`3=当前有效且直接回答`、`2=当前有效且是必要支持`、`1=相关但不足以回答或不应进入主要上下文`、`0=人工确认无关`；二值 Recall/Precision/MRR 仅把 `grade >= 2` 视为 relevant。
- 未出现在人工 judging pool 中的 memory 是 `unknown`，不得自动当作 `0`。若某个 profile 把 unknown 推入正式 top-8，必须先 adjudicate、生成新 dataset version，再公平重跑全部候选 profile。
- 多证据 query 必须声明 `required_memory_keys`；无正确 evidence 的 query 必须声明 `expected_abstention`，且不进入普通 Recall 分母。
- 过期、已更正、已遗忘、跨 user/project 和冲突旧记忆必须以独立 `dangerous` 与 reason 标签表达，不能只作为普通低 relevance 项被平均掉。
- development 与 locked holdout 必须按 query family 分组切分；同一语义问题的改写不得跨集合，避免信息泄漏。
- 数据集至少覆盖：中文、英文、中英混合；vector-only、lexical-only、双 lane；稀有标识符、2 字 CJK、长 CJK phrase；memory type、时间跨度、reinforcement、emotional weight；近义 hard negatives 和同词不同义 hard negatives。
- 每个关键分层至少包含多个独立 query family。报告必须列出各层样本数，不能只给总体平均值掩盖某一类回归。
- Gold Set v1 由 AI 根据 Amadeus 产品场景生成现实但虚构的 candidate cases，并提供便于人工检查的 query、memory corpus、relevant keys、hard negatives 和分层说明。
- AI 生成的 candidate cases 默认状态为 `draft`，不能因为同时生成了问题和答案就自称 ground truth；用户人工确认相关性标签与难度后，才标记为 `approved` 并冻结 dataset hash。
- Gold Set v1 固定为 60 个 query families：42 个 development、18 个 locked holdout；同一 family 的全部 query variants 必须留在同一 split。
- 60 个 families 按产品场景分配为 30 个个人长期助理、21 个项目/编程助理、9 个跨领域歧义、失效/冲突记忆、中英混合等压力主场景。development 使用 21/15/6，holdout 使用 9/6/3，使两个 split 都保留近似总体分布；普通 hard negatives 仍分布在前两类中。
- 人工审核按每批 10 个 families 进行，共 6 批。第一批 10 个全部来自 development，用于校准 qrels/dangerous/abstention rubric；rubric 稳定后必须回头复审第一批，不能让早晚批次使用不同判断标准。
- 每个 family 同时声明产品场景和 memory capability；capability 至少覆盖信息提取、跨 session、knowledge update、时间推理和 abstention，防止只按语言/lane 分层却漏掉长期记忆本身的能力维度。
- 聚合先在同一 family 的 query variants 内平均，再跨 family 做 macro average，避免改写较多的 family 获得更高统计权重。
- 当前没有真实使用数据不阻塞 v1。后续 dogfooding 中发现的真实召回成功/失败案例，经脱敏后作为新 dataset version 或本地 overlay 加入，不反向修改已经解封的 holdout。
- 可提交的数据只能是合成或已脱敏语料。真实个人记忆若用于补充验证，必须只保存在本地 ignored artifact 中，未经明确授权不得上传 LangSmith 或提交 Git。

### R2. 提供显式、可注入的参数合同

- 将实验参数集中到 typed configuration，而不是每组实验修改源码常量后重新运行。
- 至少覆盖：vector candidate floor/multiplier、lexical candidate floor/multiplier、lexical RRF weight、RRF `k`、semantic threshold、hotness alpha、基础半衰期、emotional half-life scale，以及 reinforcement 对 hotness frequency 的强度参数。
- candidate limit 统一使用可表达绝对 floor 的合同：`max(candidate_floor, request_limit * multiplier)`。Amadeus 默认 vector 为 `floor=32, multiplier=4`；Akashic 参考点为 `floor=15, multiplier=1`。
- `reinforcement_strength` 首轮只改变 hotness frequency 曲线，不改变 lexical coverage 后的 reinforcement tie-break 或其他 RRF tie-break；否则一次实验同时改变多条路径，结果无法归因。
- 生产默认值必须先保持当前基线。只有 holdout 报告支持新配置时，才允许在独立、可审查的改动中更新默认值。
- trace 与实验 artifact 必须记录完整参数 profile 和稳定 fingerprint，保证任何结果可以追溯到实际运行配置。
- final top-k 在首轮实验中固定为 `8`，因为 Recall@8/MRR@8 与公开产品输出合同均依赖它；本任务不通过改变最终返回数量制造指标提升。

### R3. 建立不依赖 LangSmith 的本地实验 runner

- runner 必须走真实 PostgreSQL 候选查询与生产 lane-aware ranking 边界，并能注入固定 embedding provider、固定 hypothesis outputs 和固定 ranking time。
- 同一次 sweep 中，语料、query plan、query rewrite、embedding、数据库 revision/index 和时间快照必须冻结；只有当前阶段声明的参数可以变化。
- runner 必须为每次 experiment/case 使用独立 PostgreSQL user/corpus namespace，并只清理自己拥有的数据；不得复用当前 runner 的固定 `user_id=1` 或调用会 `TRUNCATE` 整库的 test helper。
- runner 必须观测 raw-vector、event-vector、general-vector、lexical 和 pre-RRF union 的 candidate ids/counts；只收集 public top-8 无法定位候选在哪一层丢失。
- runner 不调用 answer LLM，不调用 LLM judge，也不要求 LangSmith API key。
- 每次运行输出机器可读 JSON/CSV 与人类可读 Markdown，至少包含：git commit、dataset hash、embedding provider/model identity、PostgreSQL/version/index 信息、参数 profile、逐 case 排名、分层指标、失败 case 和环境说明。
- 同一 profile 重复运行应产生相同的 ranked ids；不稳定结果必须作为失败暴露，不能取最好一次。

### R4. 计算能够回答产品问题的指标

- candidate 层至少包含 `recall_any`、`recall_all`、各 vector query/lexical lane recall 和 lexical-only outside-vector-window recall，并记录对应 effective limits。
- final 层至少包含 `Recall@8`、标准固定 cutoff 的 `Precision@8`、`MRR@8`、`nDCG@8`、`all_required_recalled@8` 和 strict lexical-only recall；同时按语言、lane、memory type、memory capability 和时间跨度分层。
- abstention case 单独计算 no-answer false-positive rate，不进入 Recall 分母；dangerous/obsolete memory 计算 `DangerousHit@8`。
- hotness 子集必须增加 pairwise ordering accuracy：当两条语义相关度等价但时间、reinforcement 或 emotional weight 不同时，期望优先级是否正确。
- 安全指标必须验证：hot-but-unrelated 记录不能越过 semantic threshold；user/active/status/replacement/scope/type/time 过滤不回归；危险记忆零命中；lane provenance 不被参数 runner 伪造。
- 所有总体指标先在 family 内聚合 variants，再跨 family macro average；逐 stratum 报告必须保留 family 数和原始 case 数。
- 数据库异常、timeout 或 lane error 仍属于可靠性失败并进入硬门；正常成功请求的毫秒耗时不采集、不聚合，也不参与 profile 选择。

### R5. 按依赖顺序实验，避免组合爆炸

- Stage 0：复现当前 Amadeus baseline，并运行独立的 Akashic-inspired reference profile；后者只作参考，不称为“最优基线”。
- Stage 1：固定 RRF、threshold 与 hotness，比较 vector/lexical candidate windows；vector 必须包含精确 `15`，不能用 16 冒充 Akashic 参考点。
- Stage 2：固定 Stage 1 shortlist，比较 lexical weight 与 RRF `k`。
- Stage 3：固定候选窗口与 RRF，比较 semantic threshold。
- Stage 4：只在语义相关性门槛稳定后，比较 hotness alpha、基础半衰期、reinforcement strength 与 emotional half-life scale。
- Stage 5：仅对各阶段排名靠前的少数组合做交叉验证，避免全笛卡尔积；然后冻结最多 3 个候选 profile，在 locked holdout 上各运行一次正式评估。
- holdout 解封后不得继续围绕其失败 case 调参。若证据不足，应新增数据集版本和后续任务，而不是污染当前 holdout。

执行范围修订：用户在 development sweep 中批准 Stage 4 收缩为只验证当前 `0.20/14d` hotness baseline，不做大规模 hotness 参数组合；Stage 5 只比较生产 baseline 与两个 Stage 3 finalist。该修订降低组合爆炸，但也意味着本任务不宣称替代 hotness 参数已被充分搜索。

### R6. 使用已确认的“安全硬门 + Recall 优先 + Precision 约束”规则

- 第一优先级是安全与一致性：user 隔离、active/status、replacement/失效记忆、scope/type/time、provenance 和 `DangerousHit@8=0` 属于零容忍硬门；硬门失败的配置不得用任何平均分抵消。
- 第二优先级是相关记忆进入 final top-8：在通过硬门的配置中，以 Recall@8 为首要质量目标，因为未进入 top-8 的记忆不能被下游 context injection 或 LLM 补救。
- 第三优先级是限制普通不相关噪声：用 Precision@8、MRR@8、nDCG@8、no-answer false-positive 和关键分层最差项约束；不得通过无限扩大候选或降低阈值换取表面 Recall。
- practical-equivalence 规则固定为：holdout family-first Recall@8 的绝对差异小于 `1/18 = 5.56` 个百分点时，v1 视为 Recall 相当；达到或超过 5.56 个百分点时只称为方向性实际改善/退化，不宣称统计确定性。
- 安全硬门优先于 5.56 规则；Recall 相当时依次比较 all-required recall、nDCG、MRR、Precision、no-answer false-positive，再以候选更少、配置更接近基线作为最后 tie-break。候选数量在这里仅表示更小的检索暴露面与更保守的改动，不换算成耗时分数，也不替代已经排除的 P95 指标。证据互有胜负时保留当前基线。
- 选择报告必须同时展示 baseline、入选候选和被淘汰候选的取舍，禁止只报告赢家。
- 若候选只带来测量噪声范围内的改善，或明显牺牲某一关键分层，应保留当前基线。
- 参数默认值变更必须有 public `MemoryEngine.recall()` PostgreSQL acceptance、canonical eval 回归和完整测试证明；kill switch 与 lane failure semantics 保持不变。

### R7. 明确 LangSmith 边界

- 参数探索和 holdout retrieval 选择全部在本地完成，不依赖 LangSmith。
- LongMemEval/PersonaMem adapter、oracle/full-history/no-retrieval answer baselines，以及 LangSmith baseline-vs-selected answer-level A/B 明确拆入后续 Trellis task，不属于当前任务交付。
- LangSmith 不参与第一轮参数搜索，不作为 retrieval ground truth，不自动接收未脱敏记忆。

## 验收标准

- [x] 存在版本化、可校验的 60-family retrieval benchmark，按 42 development / 18 locked holdout 切分，包含 0-3 级 qrels、unknown adjudication、required keys、abstention、dangerous/obsolete labels 和双维度分层清单。
- [x] Gold Set candidate cases 先以 `draft` 形式生成；用户完成逐 case 审核后才标记 `approved`、冻结 hash 并允许用于正式参数选择。
- [x] 6 个 review batches 各含 10 个 families；第一批仅含 development calibration cases，rubric 稳定后完成复审并记录审核状态。
- [x] 参数以 typed profile 注入；无需编辑源码常量即可连续运行多组配置，生产默认值在实验结论前保持当前基线。
- [x] 本地 runner 在无 LangSmith key、无 answer LLM/judge 的条件下，能通过真实 PostgreSQL 与公共 recall 边界完成一组 sweep。
- [x] artifact 可复现：记录干净代码 SHA 或 dirty diff hash、dataset/corpus hash、provider/model、数据库/index、固定时间、参数 fingerprint、per-lane candidate ids/counts、逐 case ranks 和分层质量指标。
- [x] baseline `1.0/32/30/60/8/0.35` 及 hotness `0.20/14d` 被完整测量，而不是只作为源码默认值引用。
- [x] 按 Stage 1～5 完成分阶段实验；没有运行不可解释的全量组合爆炸。
- [x] 报告至少包含 candidate recall_any/all、Recall@8、MRR@8、Precision@8、nDCG@8、all-required recall、strict lexical-only recall、DangerousHit@8、no-answer false-positive、pairwise hotness accuracy 和各关键分层结果。
- [x] locked holdout 只用于最终候选比较；报告保留 baseline 和淘汰项，并给出“更新参数”或“保留基线”的明确结论。
- [x] 每个 profile 按“安全硬门 → Recall@8 → all-required/nDCG/MRR/Precision 分层约束 → candidate size/接近基线”的固定顺序决策，不使用一个会让安全错误被平均分抵消的综合总分。
- [x] holdout Recall@8 的 practical-equivalence 阈值在 unlock 前固定为 5.56 个百分点；报告对小于阈值、达到阈值和安全硬门失败使用不同结论措辞。
- [x] 若更新生产默认值，公开 PostgreSQL acceptance、canonical eval、memory/evaluation tests、mypy、Ruff 和全量 pytest 均通过；若保留基线，也生成完整决策报告。
- [x] 第一轮实验不使用 LangSmith；任何后续 answer-level A/B 都被标记为独立验证且遵守数据脱敏边界。

## 非目标

- 不重新设计 tokenizer，不引入 PostgreSQL FTS、BM25、`pg_bigm` 或专用搜索服务。
- 不回退独立双 lane，不把扩大 vector top-k 当作 lexical lane 的替代品。
- 不改变 query rewrite 的产品机制；实验中只冻结其输出以消除比较噪声。
- 不改写记忆写入、纠错、replacement、consolidation 或 forgetting 生命周期。
- 不用 deep learning workflow、自动超参数优化器或不可解释的单一综合分数。
- 不在没有 holdout 证据时更改生产默认参数。
- 不把 answer-level LLM judge 当作 retrieval 参数搜索器。
- 不在当前任务实现 LongMemEval/PersonaMem adapter、oracle/full-history answer baselines 或 LangSmith answer-level A/B。
- 不测 PostgreSQL、retrieval-core 或 public recall 的 P50/P95，不做 warm-up 循环、固定次数性能采样或 `EXPLAIN (ANALYZE, BUFFERS)` 性能报告。

## 规划状态

- 需求、范围、Gold Set 规模、质量选择规则和非目标均已收敛，没有剩余产品开放问题。
- Akashic 与真实世界研究已写入 `research/`；当前 PRD、design 和 implement 已吸收相关结论。
- 本任务已完成实现与正式实验，处于最终质量检查阶段。Development 选择使用 hash `2748c90799831d4c9eccabb8dc96c02c3cefa793cf530a1c92beec3a136571dd`；Stage 5 finalists 冻结后首次解封 holdout，只收集到 103 个 unknown pair。用户授权审核后形成 holdout-only approved overlay，canonical dataset 增至 602 条 judgments，hash 更新为 `b0566f9a99a94761f4ba40669d70c7d941933464feac8b81830d5047d38499c9`。Finalists 只重签 hash、不改参数，最终 holdout completeness 为 0 unknown，正式 holdout 只运行一次。三组 Recall@8 均为 1.0；综合 development lexical-only 回归、holdout 配对区间与预注册选择规则，结论为保留当前生产 baseline。完整证据见 `review/parameter-decision.md` 与 `review/locked-holdout-paired-analysis.md`。
- 当前使用 Trellis inline workflow，因此 `implement.jsonl` 与 `check.jsonl` 保留模板状态；若后续切换到 sub-agent dispatch，必须在 start 前另行 curate。
