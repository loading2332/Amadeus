# 长期记忆检索参数实验实施计划

## 实施原则

- 先证明 runner 能原样复现当前基线，再做任何 sweep。
- 实验代码必须调用真实 PostgreSQL lane 和公共 recall 边界；纯 ranking helper 只能作为单元测试，不能替代产品行为证据。
- 每个 Stage 只改变一个参数族，所有结果保留 baseline 对照。
- holdout 只在 shortlist 冻结后运行一次。
- 本任务允许最终结论是“保留当前基线”。

## 1. 锁定当前行为与参数合同

- [x] 为当前 `request.limit=8`、每 query vector `32`、lexical `30`、weight `1.0`、RRF k `60`、threshold `0.35`、hotness `0.20/14d` 增加 characterization tests，记录默认 top-8、per-query/union counts、lane ranks、RRF contribution 和 hotness signals。
- [x] 新增不可变 `MemoryRetrievalParameters`（或同等 typed profile），实现范围与 finite validation。
- [x] 让 `MemoryRetriever` 的 vector/lexical candidate floor+multiplier、semantic threshold 与 lexical weight 从 profile 读取；统一公式为 `max(floor, request_limit * multiplier)`，并保持最终 K 仍由公开 request 决定。
- [x] 让 `rank_candidate_lanes()` / `rrf_merge()` / hotness helpers 显式消费 RRF k、alpha、half-life、hotness frequency strength、emotional scale 与可注入 ranking time。
- [x] 保持 lexical/RRF reinforcement tie-break 与冲突写入路径使用的旧 `rank_rows()` 行为不变；本任务的 reinforcement strength 只改变 vector hotness frequency。
- [x] 在 trace 中新增参数 profile 与 fingerprint，同时保持现有 trace consumers 兼容。
- [x] 证明默认 profile 与重构前结果逐 id、逐 rank 一致。

审查点：实验参数只有一个真相源；不得同时保留互相覆盖的 module constant、constructor field 和 env value。

## 2. 建立 retrieval benchmark schema

- [x] 在独立 benchmark 模块定义 corpus、memory key、query family、split、产品场景、memory capability、0-3 级 qrels、required keys、abstention、dangerous reasons、strata 和 fixed hypotheses；不把复杂参数标签硬塞进 3-case smoke schema。
- [x] 增加严格解析校验：重复 key、缺失 required key、未知 corpus、空 strata、同 query family 跨 split、非法 grade、dangerous reason 缺失、abstention 仍声明正例均应失败。
- [x] 新增 `tests/evaluation/cases/memory_retrieval_benchmark_v1.yaml`。
- [x] 先生成 `draft` candidate set 与 review sheet，逐 case 展示 query、qrels、required evidence、hard negatives、dangerous/obsolete memories、双维度 strata 和设计理由。
- [x] 用户逐批审核并修正标签；第一批 dev families 用于校准 rubric，校准后回看首批。全部正式 case 通过后才将 dataset 标记为 `approved`、记录内容 hash；formal runner 必须拒绝 draft dataset。
- [x] 生成固定 60 个 families：42 development（21 个人/15 项目/6 压力）与 18 locked holdout（9 个人/6 项目/3 压力），并在 summary 中验证准确数量。
- [x] 覆盖中文、英文、中英混合；vector-only、lexical-only、both；信息提取、跨 session、更新、时间、abstention；稀有标识符、2 字 CJK、长 phrase；普通/危险 hard negatives；memory type/scope/time；hotness pairwise cases。
- [x] 输出 dataset summary，列出 development/holdout 和各 stratum 的 query family 数量。
- [x] 生成 6 个 review batches，每批 10 families；batch 1 全部来自 development 并标记为 rubric calibration，规则稳定后执行一次复审。
- [x] 实现 unknown adjudication：新 profile 的 top-8 若出现未审核 memory，formal comparison 停止并要求新 dataset version，而不是自动记 0。

当前数据进度：60 个 families 与 6 份中文 review sheet 已生成。用户于 2026-07-12 批准全部六批，并使用最终 rubric 完成第一批回看复审；60 个 query 全部标记为 `approved`。正式 `memory_retrieval_benchmark_v1.yaml` 顶层状态为 `approved`，dataset hash 记录在 `review/dataset-freeze.md`。draft 合并文件继续保留顶层 `draft`，用于证明正式 runner 的拒绝门。Gold Set 审核门已完成；正式 sweep 仍需先生成并冻结 DashScope `text-embedding-v4` 1024 维 embedding cache。

2026-07-12 执行记录：正式 DashScope `text-embedding-v4` / 1024 维 cache 已生成到仓库外本地目录，共 323 entries，fingerprint 为 `92d1d4cdb85e1acf31d5561866992fbeaf092da9f0db5ef1a0293c2e0231cbf5`。Stage 0/1 development judging pool 分别发现 274/254 个 unknown pairs，并集为 280、重叠 248；实验用户清理后 PostgreSQL 残留为 0。AI 审核建议已生成，分布为 grade 0/1/2/3 = 230/45/3/2，dangerous 10；proposal 保持 `draft`，等待用户批准后才能写回 qrels 并重新冻结 dataset hash。

用户批准首轮 280 个 pooled qrels 后，已生成可移植 approved overlay；schema 同时纠正了一个 abstention case 的 grade 2 建议为 grade 1。随后用户批准 supplemental-1 的 4 个 grade 0 / non-dangerous judgments，正式 qrels 增至 467，dataset hash 冻结为 `9721b7b6264ab69b7e238c8af7175be10e1cb984729b05b32720c47d1b930d1c`。首轮 280 条 overlay 保持 byte-for-byte 不变，生成器按 base -> primary -> supplemental 的 source hash 链逐层验证。

2026-07-12 稳定性复核发现：旧 `_benchmark_item_id()` 把 `experiment_id` 混入整段 id hash，而生产 ranking 以 id 作最终 tie-break，导致只改实验名称也可能改变 top-8。现已改为“由 corpus/owner/key 生成稳定排序前缀，再追加 experiment ID 的 run 唯一后缀”，真实 PostgreSQL 回归证明两个 experiment ID 的 candidate/final keys 一致。基于新 hash 和稳定 id 重跑 Stage 0/1 completeness，两阶段共同浮现 2 条 supplemental-2 unknown，draft 审核表位于 `review/development-pool-supplemental-2-proposal.md`；完成用户批准前不运行正式 metrics。

用户批准 supplemental-2 两条 grade 0 / non-dangerous judgment 后，正式 qrels 增至 469，dataset hash 冻结为 `4daf138fcd02540f13bf8b70eb593ad90e769a224c0b2466cd5344ceacad8a7b`。Stage 0/1 completeness 均为 0 unknown，正式 metrics 已执行。baseline Recall@8 为 0.9722，但 Stage 0 baseline 和全部 12 个 Stage 1 profile 都因 dangerous hit 失败安全硬门。根因不是 candidate window：6 个 family 缺少 scope metadata，另 1 个旧版 0.3.2 memory 在重复 corpus 中错误保持 active。详细结果与修正提案分别见 `review/stage-0-1-development-results.md`、`review/benchmark-fixture-correction-proposal.md`；用户批准 fixture correction 前不冻结 shortlist。

用户批准全部 fixture correction 后，独立 `fixture-correction-1` overlay 按旧 hash 校验并应用：19 条 memory metadata、6 条 query scope、2 条 qrel/lifecycle 修正；新 dataset hash 为 `d12a51ecab44c4fef5a3fb2da01d6f7a898225660e320bc79ccd08ef994050b9`。focused benchmark/runner tests 为 23 passed。新 hash 的 Stage 0/1 completeness 共同浮现 4 条 supplemental-3 unknown，建议分布为 grade 0 两条、grade 1 两条、全部 non-dangerous；draft 位于 `review/development-pool-supplemental-3-proposal.md`，用户批准前不运行新的正式 metrics。

最终执行记录：Supplemental-3/4/5 均获批准，development dataset hash 冻结为 `2748c90799831d4c9eccabb8dc96c02c3cefa793cf530a1c92beec3a136571dd`，共 499 条 judgments。Stage 0～5 development 全部按依赖顺序完成，三个 Stage 5 finalists 在 holdout 解封前冻结。首次 holdout collect-pool 只产生 103 个 unknown；用户授权审核后形成 `split: holdout` 的 approved overlay，canonical dataset 增至 602 条 judgments，hash 更新为 `b0566f9a99a94761f4ba40669d70c7d941933464feac8b81830d5047d38499c9`。Finalists 通过 `rebase-shortlist` 只重签 dataset hash，最终 completeness 为 0 unknown，正式 holdout 只运行一次。三组 Recall@8 均为 1.0；最终保留生产 baseline，详见 `review/parameter-decision.md`。
- [x] v1 不加载私人数据；optional ignored local overlay 的自动合并语义延后到有脱敏真实样本的新 dataset task，默认测试和 CI 只依赖已提交合成集。

审查点：AI 生成只负责提出案例，不能自我认证 ground truth；split 以 query family 为单位，不能把同义改写拆到 development 与 holdout 两侧。

## 3. 实现本地、无 LangSmith runner

- [x] 新增独立 retrieval experiment runner；复用生产 `PostgresMemoryStore` 与公开 `LongTermMemoryEngine.recall()`，不复用固定 `user_id=1` 且无法冻结 hotness 输入的旧 LangSmith seed 函数。
- [x] 将同一 split 的 corpora seed 到单个隔离实验 user，形成共享 search universe；development 当前有 116 条 eligible memories，并由 `>64` schema 硬门防止候选窗口实验退化。
- [x] 新增 development-only judging-pool collector，汇总跨 corpus unknown top-8，不自动判为 grade 0；人工补标前正式 metrics 继续失败。
- [x] 每次 experiment 分配独立高位 PostgreSQL `user_id`，只清理带本 experiment marker 的 user；禁止调用 `clean_postgres()` 或任何整库 `TRUNCATE`。正式 DB 不可用时直接失败，不按 pytest skip 计成功。
- [x] corpus 只 seed 一次并由所有 profile 只读复用；profile 运行期间禁止 reinforce/write。通过 runner-owned fixture SQL 固定 `updated_at`、reinforcement、emotional weight 和 embedding 状态，并把 benchmark key 映射到真实 id。
- [x] 固定 raw/event/general query plan、支持 DashScope `text-embedding-v4` 的 1024 维只读 embedding cache，并注入固定 ranking time。
- [x] 对每个 profile 通过 `MemoryEngine.recall()` 收集 top-8、trace、lane provenance；用 runner-owned observer 捕获 raw/event/general/lexical 与 pre-RRF union 的 candidate ids/ranks，不把完整候选永久扩大到生产 trace。
- [x] 生成 JSON、CSV、Markdown artifacts，包含环境、干净 commit SHA 或 dirty diff hash、dataset/corpus hash、provider/model、migration/index、profile fingerprint、每 lane effective limit/count/id 和逐 case 结果。
- [x] runner 在无 `LANGSMITH_API_KEY`、无 answer/judge client 时可执行。
- [x] 同 profile 重复运行 top ids 不一致时失败并输出差异。

审查点：固定 provider 可以是测试 fake，但正式参数报告必须明确使用的 embedding provider/model；不得把 fake embedding 的排序结论冒充生产模型结论。

## 4. 实现指标与硬门

- [x] 计算 per-variant candidate recall_any/all、final `Recall@8`、标准固定 cutoff `Precision@8`、returned precision、`MRR@8`、`nDCG@8` 与 `all_required_recalled@8`。
- [x] 计算 strict lexical-only recall、`DangerousHit@8`、no-answer false-positive 和 hotness pairwise ordering accuracy。
- [x] 先在 family 内聚合 variants，再跨 family macro average；按 product scenario、memory capability、language 和显式 strata 报告，并同时保留 family/variant 数。
- [x] 实现 user/status/scope/type/time、provenance、canonical lexical rescue、dangerous-zero-hit 和 hot-unrelated threshold 硬门；失败 profile 不进入 shortlist。
- [x] 为 metric 边界添加单元测试：grade 0-3、unknown、dangerous、多个 required、abstention、返回不足 8、空结果、重复 id、rank 8/9、family variants 权重边界。
- [x] 为 artifact serialization、embedding cache 与 profile fingerprint 添加稳定性测试。

## 5. 执行分阶段 development sweep

- [x] Stage 0：运行 Amadeus baseline 与 Akashic-inspired reference profile，确认 canonical must-hit、per-query/union candidate observer 与指标/trace 完整；Akashic profile 只作参考。
- [x] Stage 1：在固定 request top-8 下比较 per-query vector `15/16/32/64` 和 lexical `16/30/60` effective windows；当前全部 profile 因同一 fixture 缺陷失败安全硬门，尚无合法 shortlist。
- [x] Stage 2：在窗口 shortlist 上比较 lexical weight `0.5/0.75/1.0/1.25/1.5` 与 RRF k `10/30/60/90`。
- [x] Stage 2～4 的 profile builder 必须加载上一阶段冻结 shortlist；shortlist 校验 source stage、dataset hash、完整参数 fingerprint 与自身 hash，禁止静默回退 baseline。
- [x] Stage 3：比较 semantic threshold `0.25/0.30/0.35/0.40/0.45`。
- [x] Stage 4：按用户批准的范围收缩，只验证当前 `0.20/14d` hotness baseline；不宣称替代 hotness 参数已完成搜索。
- [x] Stage 5：只比较生产 baseline 与两个 finalist，避免全组合。
- [x] 保存所有淘汰项及原因，不只保存 winner。

审查点：不得一次运行全笛卡尔积；每个 artifact 必须声明本 Stage 的 changed fields 与 frozen fields。

## 6. 冻结 shortlist 并运行 locked holdout

- [x] 在查看 holdout 前冻结 baseline + 最多 3 个候选 profile、选择理由、Recall practical-equivalence `5.56` 个百分点规则和完整 frozen context。
- [x] 校验独立 holdout split/hash；开发模式默认拒绝加载详细结果，只有显式 unlock 后才对每个 profile 运行一次正式质量评估。
- [x] 将 development 与 holdout 结果并列，标记分层退化和硬门结果。
- [x] 展示逐 family paired difference 和 family-level bootstrap 区间；明确 18 个 holdout families 中每例占 5.56 个百分点，不宣称小幅差异具有统计确定性。
- [x] 报告把 `<5.56pp` 标记为 Recall 相当，把 `>=5.56pp` 标记为方向性改善/退化；安全硬门失败始终优先淘汰，不能被该阈值豁免。
- [x] 形成明确结论：保留当前基线。
- [x] holdout 结果未用于继续本轮调参；下一版建议已记录在参数决策报告。

## 7. 可选默认值发布

- [x] Holdout 未提供替换 baseline 的充分证据，生产默认 profile 保持不变。
- [x] 生产默认值未变；真实 PostgreSQL public recall/store acceptance `24 passed`，证明 baseline 行为未回归。
- [x] canonical memory recall schema/evaluator/runner 回归 `19 passed`，覆盖 lexical-only provenance、scope fallback、source refs 与 context ordering；按本任务边界未调用 LangSmith 正式入口。
- [x] 不更新 `.env.example` / RuntimeConfig，避免暴露无证据的配置面。
- [x] 文档记录当前参数、候选取舍、保留 baseline 的决策和未解决风险。

若 holdout 不支持变更，本步骤以“默认值保持不变 + 决策记录完成”结束，不为了交付代码而强行改参数。

## 8. LangSmith 与公共 benchmark 后续边界

- [x] 本任务首轮 sweep 和 holdout 不调用 LangSmith。
- LongMemEval/PersonaMem adapter、oracle/full-history/no-retrieval baselines 和 baseline-vs-selected answer-level A/B 已确认移入后续 Trellis task，不属于本实施 checklist。
- 后续 LangSmith 数据集必须补齐 version/tag/split/hash；当前 recall sync 的 `prune_stale=False` 不能视为冻结 Gold Set。
- 后续上传前确认 case 已脱敏；真实个人记忆默认不上传。LLM 非确定链路才使用 repetitions，answer-level 结果不覆盖 retrieval qrels 结论。

## 验证命令

具体 CLI 名称在实现 runner 后确定，至少覆盖以下层次：

```powershell
# schema、metrics、profile validation
uv run pytest -q tests/evaluation/test_memory_retrieval_experiment.py

# ranking/retriever 参数兼容
uv run pytest -q tests/memory/test_memory_ranking.py tests/memory/test_memory_retriever.py

# 真实 PostgreSQL 与公开 recall
uv run pytest -q tests/memory/test_memory_retrieval_acceptance.py tests/memory/test_postgres_memory_store.py

# evaluation + memory 广检查
uv run pytest -q tests/evaluation tests/memory tests/db

# 静态与全量检查
uv run ruff check amadeus/evaluation amadeus/memory tests/evaluation tests/memory
uv run mypy amadeus
uv run pytest -q
```

WSL PostgreSQL 命令沿用项目约定：

```powershell
wsl -d Debian --cd /mnt/d/coding/front-end_proj/Amadeus docker compose up -d postgres
```

正式实验命令必须显式指定 benchmark version、split、profile/stage、fixed ranking time 和 artifact directory，不依赖不可见的本机默认状态。

## 2026-07-12 第一阶段检查记录

- `uv run ruff check amadeus tests`：通过。
- `uv run pytest -q`：`592 passed`，仅有一个第三方 Starlette deprecation warning。
- `uv run mypy amadeus tests/evaluation tests/memory tests/db`：132 个 source files 通过。
- 全项目 `uv run mypy amadeus tests`：本次变更错误已清零；仍有 24 个既有错误位于未修改的 `tests/mcp`、`tests/tools` 与 `tests/integration`。
- `python .trellis/scripts/task.py validate ...` 与 `git diff --check`：通过。
- 第一批 10-family draft 使用 fake 1024 维 embedding 完成真实 PostgreSQL Stage 0 smoke；只证明 runner/data path 可执行，不作为参数质量结论。

## 2026-07-12 最终质量门记录

- 正式实验：Stage 0～5 development、holdout judging pool、rebased completeness 与一次正式 holdout 全部在真实 PostgreSQL 上完成；最终实验用户残留为 `0`。
- 本任务 schema/profile/runner/ranking focused tests：`106 passed`。
- 真实 PostgreSQL public recall/store acceptance：`24 passed`。
- Canonical memory recall schema/evaluator/runner 回归：`19 passed`，未调用 LangSmith 正式入口。
- `tests/evaluation tests/memory tests/db`：`203 passed`。
- 全量 `uv run pytest -q`：`608 passed`，仅一个第三方 Starlette/httpx deprecation warning。
- `uv run ruff check amadeus tests` 与四个 task scripts：通过。
- `uv run mypy amadeus tests/evaluation tests/memory tests/db`：`132` 个 source files 通过；四个 task scripts 单独 Mypy 通过。
- `python .trellis/scripts/task.py validate ...` 与 `git diff --check`：通过。
- 一次并行窄测试曾因两个 pytest 进程同时调用共享 `clean_postgres()`，使 lexical fixture 被另一进程清理；精确用例单独通过，原集合改为同进程串行后 `106 passed`。生产代码未因该测试编排竞争被修改，相关约束已写入 backend database spec。

## 风险文件与回滚点

- `amadeus/memory/ranking.py`：把 globals 改为 profile 时最容易改变排序；先锁 baseline characterization。
- `amadeus/memory/ranking.py` 的旧 `rank_rows()` 仍服务 post-response 冲突决策；参数化 shared helper 时禁止无意改变写入/纠错行为。
- `amadeus/memory/retriever.py`：candidate limit 与 public trace；保持 scope fallback 和独立 lane failure。
- `amadeus/app/bootstrap.py`：不要在证据出现前扩大 RuntimeConfig surface。
- 新 benchmark schema：优先独立模块并复用现有 seed primitive，避免扩大 `amadeus/evaluation/cases.py` 后破坏 recall/quality smoke case。
- 新 experiment runner：不能要求 LangSmith，也不能绕过 `MemoryEngine.recall()` 冒充公共行为。
- benchmark YAML：防止 query-family split leakage 和合成数据过度简单。

## 进入实现前审查门

- [x] 用户审阅 `prd.md`、`design.md`、`implement.md` 并确认开始实现。
- [x] 任务通过 `python ./.trellis/scripts/task.py start .trellis/tasks/07-11-memory-retrieval-parameter-evaluation` 进入实现阶段。

## 正式 sweep 前审查门

- [x] 第一批 10 个 development families 已完成 rubric 校准和回看复审；其余批次沿用稳定后的判断规则。
- [x] 60 个 families 已完成人工审核并标记为 `approved`，42/18 split、每批 10 个的数量与 dataset hash 已冻结。
- [x] 当前 `.env` 可调用 DashScope `text-embedding-v4`，1024 维 embedding cache 已生成并冻结；禁止以测试 fake 的质量结果代替正式报告。

## JSONL 说明

当前任务使用 Codex inline workflow，主会话在 Phase 2 通过 `trellis-before-dev` 直接读取 PRD、design、implement 与相关 spec。因此 `implement.jsonl` / `check.jsonl` 保留 task template，不作为启动门。

若后续切换为 sub-agent dispatch workflow，必须先删除 `_example`，并分别写入真实 spec/research context；JSONL 只列 spec/research 文件，不列代码文件。
