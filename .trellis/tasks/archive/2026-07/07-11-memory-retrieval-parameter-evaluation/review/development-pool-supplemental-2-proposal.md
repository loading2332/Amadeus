# Development judging pool AI 审核建议

状态：`draft`，必须由用户批准后才能写回正式 qrels。

- 原 dataset hash：`9721b7b6264ab69b7e238c8af7175be10e1cb984729b05b32720c47d1b930d1c`
- 审核轮次：`supplemental-2`
- query-memory pairs：`2`
- 建议等级分布：`{0: 2}`
- 建议 dangerous：`0`
- Proposal SHA-256：`e9aef0125c1672665ae92b5c0a3621ed39bb66cc97169cdb288bf9dff5e1898f`
- Stage 0 pool SHA-256：`bd44e5dea577c896f39213b619150ed8307eef5dd0809750f908ede97795fa4b`
- Stage 1 pool SHA-256：`716396898ee3d14890f5499ae44640724f9feb1bc32115fc4eb0449c229c1853`

## 1. project_incident_root_cause_en × personal_bookmark_article_irrelevant

- Query：`What was the root cause of INC-204?`
- Memory：The user bookmarked a Python typing guide.
- 来源 corpus：`personal_bookmark_article`
- Profile ranks：amadeus-baseline=#6, window-v15-l16=#6, window-v15-l30=#6, window-v15-l60=#6, window-v16-l16=#6, window-v16-l30=#6, window-v16-l60=#6, window-v32-l16=#6, window-v32-l30=#6, window-v32-l60=#6, window-v64-l16=#6, window-v64-l30=#6, window-v64-l60=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Python typing guide 与 INC-204 事故根因无关，不能提供根因证据。
- [ ] 用户批准

## 2. project_test_command_en × personal_bookmark_article_irrelevant

- Query：`What command runs the memory acceptance suite?`
- Memory：The user bookmarked a Python typing guide.
- 来源 corpus：`personal_bookmark_article`
- Profile ranks：amadeus-baseline=#8, window-v15-l16=#8, window-v15-l30=#8, window-v15-l60=#8, window-v16-l16=#8, window-v16-l30=#8, window-v16-l60=#8, window-v32-l16=#8, window-v32-l30=#8, window-v32-l60=#8, window-v64-l16=#8, window-v64-l30=#8, window-v64-l60=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Python typing guide 与 memory acceptance 测试命令无关，不能回答运行命令。
- [ ] 用户批准
