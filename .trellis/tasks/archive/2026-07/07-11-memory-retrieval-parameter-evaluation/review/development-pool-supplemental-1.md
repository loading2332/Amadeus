# Development judging pool supplemental-1 审核记录

- 审核状态：`approved`
- 审核时间：`2026-07-12`
- 审核人：`user`
- 来源 dataset hash：`2558260d47c55c3a1c740f19abe8bcf4b013657e226ee427e9b978e356f12d3a`
- 来源 embedding cache fingerprint：`92d1d4cdb85e1acf31d5561866992fbeaf092da9f0db5ef1a0293c2e0231cbf5`
- 固定 ranking time：`2026-07-12T04:00:00+00:00`
- Proposal SHA-256：`4be03e144a1cec19daee508163807dc7a6c108b105c4c9553a3ddbbcebdb97e0`

来源 judging pool：

- `memory-retrieval-v1-pool-verification-stage-0-judging-pool.json`：`12fcb88eaa775bc36c3a7dfb10095924b598573f6e1fe71c80be0ea80e11ccef`
- `memory-retrieval-v1-pool-verification-stage-1-judging-pool.json`：`2a57512f578abc72eed5ffd5f5c76ffa976edb502c8ace5bdf2ed19c2d0d3463`

## 已批准 judgments

| Query | Memory | 浮现位置 | Relevance | Dangerous | 审核理由 |
|---|---|---:|---:|---|---|
| `project_incident_root_cause_en` | `personal_allergy_restaurant_related` | Stage 0 baseline #7 | 0 | false | INC-204 根因问题与用户辣度偏好无关，不能提供事故根因证据。 |
| `personal_allergy_restaurant_en` | `project_env_variable_irrelevant` | Stage 1 #7/#8 | 0 | false | 数据库环境变量与用户餐厅过敏原无关，不能回答需声明的 allergy。 |
| `project_storage_adr_en` | `personal_bookmark_article_irrelevant` | Stage 1 #8 | 0 | false | Python typing guide 与存储后端架构决策无关，不能证明哪个后端获选。 |
| `project_test_command_en` | `personal_allergy_restaurant_answer` | Stage 1 #7 | 0 | false | 花生过敏与 memory acceptance 测试命令无关，不能回答运行命令。 |

用户已明确批准以上四组标签。它们作为独立 supplemental overlay 保存，不改写首轮 280 条审核历史；正式数据集必须按 `base -> primary 280 -> supplemental-1 4` 的 source hash 链重新生成。
