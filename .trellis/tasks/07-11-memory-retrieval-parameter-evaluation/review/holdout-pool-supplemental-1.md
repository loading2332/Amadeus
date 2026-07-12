# Holdout judging pool Supplemental-1 审核记录

- 审核状态：`approved`
- 审核日期：`2026-07-12`
- 审核授权：用户已明确批准后续全部 set 审核
- Split：`holdout`
- Source dataset hash：`2748c90799831d4c9eccabb8dc96c02c3cefa793cf530a1c92beec3a136571dd`
- Source pool SHA-256：`2d92bf56e6722db69d3f809133c04943ce2f4d0ec1b17d679f464511ec8519ed`
- Proposal SHA-256：`1b3ff0117c44d2bbca08195f4f76e6a61996351e1623dc5cebfacd4a3aa5e662`
- Approved overlay SHA-256：`aedcfad7c6a21497c77b8d8ac10c4e4d96d9c580a7550ca491fb56fa3d4e8e0d`
- Judgments：`103`
- Grade 分布：`0=100 / 1=3 / 2=0 / 3=0`
- Dangerous：`0`
- 新 dataset hash：`b0566f9a99a94761f4ba40669d70c7d941933464feac8b81830d5047d38499c9`

103 个 unknown query-memory pair 已按既有 `0..3` qrels 与 dangerous rubric 逐项审核。三个 grade 1 分别是同类保险文件背景、同一 memory retrieval 子系统的 review 治理背景，以及通用生产审批背景；它们都不足以直接回答 query。其余 100 条为普通无关项。

包含“密码”的候选只说明密码记录存在或已更新，没有暴露密码值，也没有跨 owner、channel 或 chat scope 元数据；canonical 中对应原始 qrel 同样是 non-dangerous，因此没有仅凭关键词扩大 dangerous 标签。

该 overlay 只新增 holdout qrels，不改变 corpus、query、split、参数 profile 或 development 选择结果。Stage 5 finalists 必须通过 `rebase-shortlist` 在新 dataset hash 上重签，参数本身保持 byte-for-byte 等价。
