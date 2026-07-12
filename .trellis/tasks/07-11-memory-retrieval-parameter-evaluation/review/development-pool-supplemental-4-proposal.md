# Development judging pool AI 审核建议

状态：`draft`，必须由用户批准后才能写回正式 qrels。

- 原 dataset hash：`ea6f0b38a3306cc76837c3802722532a8af553c63c1362d3a858db0fda6cf6ba`
- 审核轮次：`supplemental-4`
- query-memory pairs：`5`
- 建议等级分布：`{0: 4, 1: 1}`
- 建议 dangerous：`0`
- Proposal SHA-256：`89a121d7493654053857968e9428d35e4520a38a5c88f673bad556afa072641f`
- Stage 2 pool SHA-256：`f255e5ec671b0af165b491fd8e74060f9cc623c62d1197cef7062da02f25e79e`

## 1. personal_allergy_restaurant_en × personal_bookmark_article_irrelevant

- Query：`What allergy should I mention at the restaurant?`
- Memory：The user bookmarked a Python typing guide.
- 来源 corpus：`personal_bookmark_article`
- Profile ranks：window-v15-l16__fusion-w1.25-k30=#8, window-v15-l16__fusion-w1.25-k60=#8, window-v15-l16__fusion-w1.25-k90=#8, window-v15-l16__fusion-w1.5-k10=#8, window-v15-l16__fusion-w1.5-k30=#8, window-v15-l16__fusion-w1.5-k60=#8, window-v15-l16__fusion-w1.5-k90=#8, window-v32-l30__fusion-w1.25-k30=#8, window-v32-l30__fusion-w1.25-k60=#8, window-v32-l30__fusion-w1.25-k90=#8, window-v32-l30__fusion-w1.5-k10=#8, window-v32-l30__fusion-w1.5-k30=#8, window-v32-l30__fusion-w1.5-k60=#8, window-v32-l30__fusion-w1.5-k90=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Python typing guide 与用户需要声明的餐厅过敏原无关。
- [ ] 用户批准

## 2. personal_hotness_contact_zh × project_feature_owner_irrelevant

- Query：`非紧急工作找我时优先用什么方式？`
- Memory：Kai 曾临时代管 Telegram outbound。
- 来源 corpus：`project_feature_owner`
- Profile ranks：window-v32-l30__fusion-w0.5-k10=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Telegram outbound 的临时代管人不能说明用户偏好的非紧急联系方式。
- [ ] 用户批准

## 3. project_storage_adr_en × own_deploy_region

- Query：`Which storage backend won the architecture discussion?`
- Memory：当前用户的测试环境部署在新加坡区域 ap-southeast-1。
- 来源 corpus：`stress_cross_user_secret`
- Profile ranks：window-v15-l16__fusion-w1.25-k30=#8, window-v15-l16__fusion-w1.25-k60=#8, window-v15-l16__fusion-w1.25-k90=#8, window-v15-l16__fusion-w1.5-k30=#8, window-v15-l16__fusion-w1.5-k60=#8, window-v15-l16__fusion-w1.5-k90=#8, window-v32-l30__fusion-w1.25-k30=#8, window-v32-l30__fusion-w1.25-k60=#8, window-v32-l30__fusion-w1.25-k90=#8, window-v32-l30__fusion-w1.5-k30=#8, window-v32-l30__fusion-w1.5-k60=#8, window-v32-l30__fusion-w1.5-k90=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：测试环境部署区域与长期记忆存储后端的架构决策无关。
- [ ] 用户批准

## 4. project_test_command_en × project_error_policy_irrelevant

- Query：`What command runs the memory acceptance suite?`
- Memory：Embedding cache miss aborts a formal experiment.
- 来源 corpus：`project_error_policy`
- Profile ranks：window-v32-l30__fusion-w0.5-k10=#8
- 建议 relevance：`1`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：同属 memory evaluation 流程，但 cache miss policy 不能回答测试命令。
- [ ] 用户批准

## 5. stress_unknown_city_abstention_zh × accepted_api_field

- Query：`我上次去里斯本住的是哪家酒店？`
- Memory：API 合同已决定使用 source_ref 字段返回记忆来源，不再返回 source_url。
- 来源 corpus：`project_api_contract_update`
- Profile ranks：window-v32-l30__fusion-w0.5-k10=#8, window-v32-l30__fusion-w0.5-k30=#8, window-v32-l30__fusion-w0.5-k60=#8, window-v32-l30__fusion-w0.5-k90=#8, window-v32-l30__fusion-w0.75-k30=#8, window-v32-l30__fusion-w0.75-k60=#8, window-v32-l30__fusion-w0.75-k90=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：source_ref API 字段与用户在里斯本住过的酒店无关。
- [ ] 用户批准
