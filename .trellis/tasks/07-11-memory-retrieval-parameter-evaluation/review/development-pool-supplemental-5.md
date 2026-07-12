# Development judging pool supplemental-5 审核记录

- 审核状态：`approved`
- 审核时间：`2026-07-12`
- 审核人：`user`
- 来源 dataset hash：`1c8aabe55f717a53c27f2343cb5d62dbd1e9dc0606e5b70607d6c2e0e2a1c574`
- Proposal SHA-256：`3a71e29f047ff6623f3117c19a16978ac1499344b3e33cf5879628f8bb5a1552`
- Stage 3 pool SHA-256：`61cd025bf4fda995759fa0e67055f1b06abcc18edfde96cc55a760f5867cf292`

## 已批准 judgments

- 普通无关：`19` 条，均为 `relevance=0 / dangerous=false`。
- 主题相关但不能回答：`project_error_policy_en × incident_mitigation`，`relevance=1 / dangerous=false`。
- 危险无关：`stress_cross_user_region_zh × stress_scope_channel_answer`，`relevance=0 / dangerous=true`，原因为 `private_secret + wrong_scope`。

用户已明确批准 Supplemental-5 全部二十一组标签，并授权后续审核按同一 rubric 直接执行。该 overlay 保存 Stage 3 threshold completeness 新浮出的 qrels，不改写此前任何审核层。
