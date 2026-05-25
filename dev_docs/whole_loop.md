0. 工作流定稿
   明确先做 dossier，再做 eval base，再跑原型。
   状态：已完成，写进 dev_docs/memory_eval_workflow.md。

1. Strategy Dossiers
   给每个 memory 方案写“方案身份证”：
   - 它真实数据流是什么
   - 核心机制是什么
   - 哪些不能省
   - 最小原型怎么做
   - fidelity checklist 是什么
   目标：防止我们脑补一个 “xxx-like”。

2. Eval Schema Design
   定义统一数据格式：
   - MemoryArtifact
   - EvalCase
   - GoldEvidence
   - StrategyResult
   - RunTrace
   目标：PersonaMem / LoCoMo / LongMemEval-V2 / Amadeus golden set 都能转成同一种 eval 输入输出。

3. Dataset Adapters
   给公开数据集写转换器：
   - PersonaMem -> EvalCase
   - LoCoMo -> EvalCase
   - LongMemEval-V2 -> EvalCase
   - Amadeus golden set -> EvalCase
   目标：不同数据集不污染 runner 核心。

4. Strategy Adapter Contract
   定义每个 memory 原型必须实现的接口：
   - ingest_artifacts()
   - retrieve()
   - build_injection()
   - maybe answer_context()
   目标：后续可以插拔不同方案。

5. Prototype Implementations
   实现第一批 5 个最小原型：
   - Akashic-inspired
   - mem0-inspired
   - memU-inspired
   - EverMemOS-inspired
   - Letta-inspired
   还有几个基线：
   - no_memory
   - full_context/oracle
   - raw_chunk_rag

6. Fidelity Tests
   先跑“像不像”测试，不是跑分：
   - Akashic 是否分 stable control plane / dynamic retrieval
   - memU 是否先 summary 后下钻
   - Letta 是否 core 默认注入、archival 按需
   目标：没通过 fidelity，不允许进入 benchmark。

7. Scoring + Trace Runner
   跑每个 eval case，保存：
   - retrieved ids
   - injected context
   - final answer
   - score
   - latency
   - token count
   目标：不只知道分数，还知道失败原因。

8. First Eval Run
   先小规模跑：
   - PersonaMem 子集
   - LoCoMo 子集
   - LongMemEval-V2 small/subset
   - Amadeus golden set
   目标：验证 eval base 可靠，不追求正式榜单。

9. Analysis Report
   输出多维结果：
   - 哪个方案用户画像强
   - 哪个方案项目协作强
   - 哪个方案检索强
   - 哪个方案注入污染少
   - 哪个方案成本/延迟可接受
   - Amadeus 应该迁移哪些设计