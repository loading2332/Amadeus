# Development judging pool AI 审核建议

状态：`draft`，必须由用户批准后才能写回正式 qrels。

- 原 dataset hash：`d12a51ecab44c4fef5a3fb2da01d6f7a898225660e320bc79ccd08ef994050b9`
- 审核轮次：`supplemental-3`
- query-memory pairs：`4`
- 建议等级分布：`{0: 2, 1: 2}`
- 建议 dangerous：`0`
- Proposal SHA-256：`529007fe2f22dd210171f35d5a779be691364d82b0bb5caf605b90ab34482c55`
- Stage 0 pool SHA-256：`a8eaa9cd90d3afd146868f6ff2e841fdc1107feaf0425debe1bbbea5bf756167`
- Stage 1 pool SHA-256：`ff7b157534be7bad2acf89655e3e7bc15d85127fd7b5aa914bfa98cdf0e6430f`

## 1. project_multi_evidence_release_mixed × generic_release_rule

- Query：`发布 ZXQ-4917 前要确认哪两件事？`
- Memory：普通发布应在合并后通知测试群验证主流程。
- 来源 corpus：`project_identifier_lexical`
- Profile ranks：akashic-inspired-reference=#3, amadeus-baseline=#3, window-v15-l16=#3, window-v15-l30=#3, window-v15-l60=#3, window-v16-l16=#3, window-v16-l30=#3, window-v16-l60=#3, window-v32-l16=#3, window-v32-l30=#3, window-v32-l60=#3, window-v64-l16=#3, window-v64-l30=#3, window-v64-l60=#3
- 建议 relevance：`1`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：属于发布流程背景，但描述合并后的通用通知，不是该 query 的两项 readiness 检查。
- [ ] 用户批准

## 2. project_multi_evidence_release_mixed × release_identifier_rule

- Query：`发布 ZXQ-4917 前要确认哪两件事？`
- Memory：发布批次 ZXQ-4917 必须在合并前附上数据库回滚记录。
- 来源 corpus：`project_identifier_lexical`
- Profile ranks：akashic-inspired-reference=#4, amadeus-baseline=#4, window-v15-l16=#4, window-v15-l30=#4, window-v15-l60=#4, window-v16-l16=#4, window-v16-l30=#4, window-v16-l60=#4, window-v32-l16=#4, window-v32-l30=#4, window-v32-l60=#4, window-v64-l16=#4, window-v64-l30=#4, window-v64-l60=#4
- 建议 relevance：`1`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：属于同一批次的合并证据要求，但不是该 query 已指定的两项 release-readiness 检查。
- [ ] 用户批准

## 3. project_release_date_zh × stress_time_boundary_answer

- Query：`0.4.0-beta.3 计划哪天发？`
- Memory：2026 年 7 月 11 日 23:58 提交的是 build-a91c。
- 来源 corpus：`stress_time_boundary`
- Profile ranks：akashic-inspired-reference=#8, amadeus-baseline=#8, window-v15-l16=#8, window-v15-l30=#8, window-v15-l60=#8, window-v16-l16=#8, window-v16-l30=#8, window-v16-l60=#8, window-v32-l16=#8, window-v32-l30=#8, window-v32-l60=#8, window-v64-l16=#8, window-v64-l30=#8, window-v64-l60=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：build-a91c 的提交时间与 0.4.0-beta.3 的计划发布日期无关。
- [ ] 用户批准

## 4. stress_scope_channel_zh × release_identifier_rule

- Query：`这个群的发布口令是什么？`
- Memory：发布批次 ZXQ-4917 必须在合并前附上数据库回滚记录。
- 来源 corpus：`project_identifier_lexical`
- Profile ranks：akashic-inspired-reference=#7, amadeus-baseline=#7, window-v15-l16=#7, window-v15-l30=#7, window-v15-l60=#7, window-v16-l16=#7, window-v16-l30=#7, window-v16-l60=#7, window-v32-l16=#7, window-v32-l30=#7, window-v32-l60=#7, window-v64-l16=#7, window-v64-l30=#7, window-v64-l60=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：同一项目群中的发布证据规则不能回答当前群的发布口令。
- [ ] 用户批准
