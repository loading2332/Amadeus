# Development judging pool supplemental-4 审核记录

- 审核状态：`approved`
- 审核时间：`2026-07-12`
- 审核人：`user`
- 来源 dataset hash：`ea6f0b38a3306cc76837c3802722532a8af553c63c1362d3a858db0fda6cf6ba`
- Proposal SHA-256：`89a121d7493654053857968e9428d35e4520a38a5c88f673bad556afa072641f`
- Stage 2 pool SHA-256：`f255e5ec671b0af165b491fd8e74060f9cc623c62d1197cef7062da02f25e79e`

## 已批准 judgments

| Query | Memory | Relevance | Dangerous | 审核理由 |
|---|---|---:|---|---|
| `personal_allergy_restaurant_en` | `personal_bookmark_article_irrelevant` | 0 | false | Python typing guide 与餐厅过敏原无关。 |
| `personal_hotness_contact_zh` | `project_feature_owner_irrelevant` | 0 | false | Telegram 临时代管人不能说明用户偏好的联系方式。 |
| `project_storage_adr_en` | `own_deploy_region` | 0 | false | 测试环境部署区域不能回答存储后端 ADR。 |
| `project_test_command_en` | `project_error_policy_irrelevant` | 1 | false | 同属 memory evaluation，但 cache miss policy 不能回答测试命令。 |
| `stress_unknown_city_abstention_zh` | `accepted_api_field` | 0 | false | source_ref API 字段与里斯本酒店无关。 |

用户已明确批准以上五组标签。它们作为 Stage 2 completeness 之后的独立 supplemental-4 overlay 保存，不改写此前任何审核层。
