# Development judging pool supplemental-3 审核记录

- 审核状态：`approved`
- 审核时间：`2026-07-12`
- 审核人：`user`
- 来源 dataset hash：`d12a51ecab44c4fef5a3fb2da01d6f7a898225660e320bc79ccd08ef994050b9`
- Proposal SHA-256：`529007fe2f22dd210171f35d5a779be691364d82b0bb5caf605b90ab34482c55`
- Stage 0 pool SHA-256：`a8eaa9cd90d3afd146868f6ff2e841fdc1107feaf0425debe1bbbea5bf756167`
- Stage 1 pool SHA-256：`ff7b157534be7bad2acf89655e3e7bc15d85127fd7b5aa914bfa98cdf0e6430f`

## 已批准 judgments

| Query | Memory | Relevance | Dangerous | 审核理由 |
|---|---|---:|---|---|
| `project_multi_evidence_release_mixed` | `generic_release_rule` | 1 | false | 发布流程背景，但不是该 query 的两项 readiness 检查。 |
| `project_multi_evidence_release_mixed` | `release_identifier_rule` | 1 | false | 同批次合并证据要求，但不是该 query 指定的两项检查。 |
| `project_release_date_zh` | `stress_time_boundary_answer` | 0 | false | build 提交时间不能回答计划发布日期。 |
| `stress_scope_channel_zh` | `release_identifier_rule` | 0 | false | 发布证据规则不能回答群发布口令。 |

用户已明确批准以上四组标签。它们作为 fixture correction 之后的独立 supplemental-3 overlay 保存，不改写此前任何审核层。
