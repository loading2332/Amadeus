# Holdout judging pool AI 审核建议

状态：`draft`，必须由用户批准后才能写回正式 qrels。

- 原 dataset hash：`2748c90799831d4c9eccabb8dc96c02c3cefa793cf530a1c92beec3a136571dd`
- 审核轮次：`holdout-supplemental-1`
- query-memory pairs：`103`
- 建议等级分布：`{0: 100, 1: 3}`
- 建议 dangerous：`0`

## 1. holdout_personal_call_time_en × holdout_personal_morning_alarm_answer

- Query：`When is my call with Maya tomorrow?`
- Memory：2026 年 7 月 13 日早班需要 05:50 起床。
- 来源 corpus：`holdout_personal_morning_alarm`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：同为 7 月 13 日的个人日程，但早班起床时间不是 Maya 通话时间，事件实体和所问属性不同。
- [ ] 用户批准

## 2. holdout_personal_call_time_en × holdout_personal_morning_alarm_irrelevant

- Query：`When is my call with Maya tomorrow?`
- Memory：明天下午三点有会议。
- 来源 corpus：`holdout_personal_morning_alarm`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：明天下午三点的会议不是与 Maya 的通话，不能回答该通话几点开始。
- [ ] 用户批准

## 3. holdout_personal_call_time_en × holdout_personal_unknown_insurance_irrelevant

- Query：`When is my call with Maya tomorrow?`
- Memory：用户下月计划旅行。
- 来源 corpus：`holdout_personal_unknown_insurance`
- Profile ranks：window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：下月旅行计划不包含 Maya、通话或明天的通话时间。
- [ ] 用户批准

## 4. holdout_personal_call_time_en × holdout_project_config_key_irrelevant

- Query：`When is my call with Maya tomorrow?`
- Memory：The retry key is runtime.max_retries.
- 来源 corpus：`holdout_project_config_key`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：runtime.max_retries 是项目配置键，与个人通话日程无关。
- [ ] 用户批准

## 5. holdout_personal_call_time_en × holdout_project_config_key_related

- Query：`When is my call with Maya tomorrow?`
- Memory：The vector switch is memory.vector_enabled.
- 来源 corpus：`holdout_project_config_key`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：memory.vector_enabled 是项目配置键，与 Maya 通话时间无关。
- [ ] 用户批准

## 6. holdout_personal_call_time_en × holdout_project_incident_time_answer

- Query：`When is my call with Maya tomorrow?`
- Memory：INC-319 recovered at 02:14 UTC on July 5, 2026.
- 来源 corpus：`holdout_project_incident_time`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：INC-319 的恢复时间属于项目事故，不是用户与 Maya 的通话时间。
- [ ] 用户批准

## 7. holdout_personal_diet_update_en × holdout_personal_call_time_answer

- Query：`What is my current dairy restriction?`
- Memory：The call with Maya is at 10:30 on July 13, 2026.
- 来源 corpus：`holdout_personal_call_time`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Maya 通话时间不包含用户当前的乳制品限制。
- [ ] 用户批准

## 8. holdout_personal_diet_update_en × holdout_personal_call_time_related

- Query：`What is my current dairy restriction?`
- Memory：The call with Mina is at 10:30 on July 14, 2026.
- 来源 corpus：`holdout_personal_call_time`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Mina 通话时间与用户的乳制品饮食限制无关。
- [ ] 用户批准

## 9. holdout_personal_diet_update_en × holdout_personal_pet_food_answer

- Query：`What is my current dairy restriction?`
- Memory：猫目前改吃低敏配方粮。
- 来源 corpus：`holdout_personal_pet_food`
- Profile ranks：window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：低敏配方粮描述的是猫的饮食，主体不是用户，不能回答用户的乳制品限制。
- [ ] 用户批准

## 10. holdout_personal_diet_update_en × holdout_personal_recipe_steps_irrelevant

- Query：`What is my current dairy restriction?`
- Memory：用户不喜欢太辣。
- 来源 corpus：`holdout_personal_recipe_steps`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#3
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：不喜欢太辣是另一项饮食偏好，不说明是否限制乳制品；同族中避免花生也已按不同限制标为 0。
- [ ] 用户批准

## 11. holdout_personal_diet_update_en × holdout_personal_unknown_insurance_irrelevant

- Query：`What is my current dairy restriction?`
- Memory：用户下月计划旅行。
- 来源 corpus：`holdout_personal_unknown_insurance`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：下月旅行计划不涉及乳制品或饮食限制。
- [ ] 用户批准

## 12. holdout_personal_diet_update_en × holdout_project_config_key_irrelevant

- Query：`What is my current dairy restriction?`
- Memory：The retry key is runtime.max_retries.
- 来源 corpus：`holdout_project_config_key`
- Profile ranks：amadeus-baseline=#2, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#2, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：runtime.max_retries 是项目配置，不能回答个人乳制品限制。
- [ ] 用户批准

## 13. holdout_personal_diet_update_en × holdout_project_config_key_related

- Query：`What is my current dairy restriction?`
- Memory：The vector switch is memory.vector_enabled.
- 来源 corpus：`holdout_project_config_key`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：memory.vector_enabled 是项目配置，不能回答个人乳制品限制。
- [ ] 用户批准

## 14. holdout_personal_diet_update_en × holdout_project_unknown_flag_answer

- Query：`What is my current dairy restriction?`
- Memory：feature flag MEM-929 默认关闭。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-929 的默认开关状态与用户饮食无关。
- [ ] 用户批准

## 15. holdout_personal_diet_update_en × holdout_project_unknown_flag_related

- Query：`What is my current dairy restriction?`
- Memory：MEM-992 是尚未记录的实验编号。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-992 是项目实验编号，与用户乳制品限制无关。
- [ ] 用户批准

## 16. holdout_personal_language_exception_mixed × holdout_personal_tax_document_related

- Query：`给客户的 incident report 用什么语言？`
- Memory：保险文件编号是 TAX-CN-8482。
- 来源 corpus：`holdout_personal_tax_document`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：保险文件编号不包含给客户的 incident report 应使用哪种语言的信息。
- [ ] 用户批准

## 17. holdout_personal_language_exception_mixed × holdout_personal_unknown_insurance_answer

- Query：`给客户的 incident report 用什么语言？`
- Memory：用户购买过旅行保险。
- 来源 corpus：`holdout_personal_unknown_insurance`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：购买过旅行保险不能推出客户 incident report 的语言要求。
- [ ] 用户批准

## 18. holdout_personal_language_exception_mixed × holdout_personal_unknown_insurance_irrelevant

- Query：`给客户的 incident report 用什么语言？`
- Memory：用户下月计划旅行。
- 来源 corpus：`holdout_personal_unknown_insurance`
- Profile ranks：amadeus-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：下月旅行计划不能说明客户 incident report 应使用哪种语言。
- [ ] 用户批准

## 19. holdout_personal_language_exception_mixed × holdout_project_unknown_flag_related

- Query：`给客户的 incident report 用什么语言？`
- Memory：MEM-992 是尚未记录的实验编号。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：未记录的 MEM-992 实验编号与文档语言规则无关。
- [ ] 用户批准

## 20. holdout_personal_language_exception_mixed × holdout_stress_conflict_answer

- Query：`给客户的 incident report 用什么语言？`
- Memory：Production 当前迁移到 ap-southeast-1。
- 来源 corpus：`holdout_stress_conflict`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Production 当前区域不能推出海外客户 incident report 的语言要求。
- [ ] 用户批准

## 21. holdout_personal_morning_alarm_zh × holdout_personal_call_time_answer

- Query：`明天早班要几点起床？`
- Memory：The call with Maya is at 10:30 on July 13, 2026.
- 来源 corpus：`holdout_personal_call_time`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：同日与 Maya 的通话是另一项日程，不能说明早班需要几点起床。
- [ ] 用户批准

## 22. holdout_personal_morning_alarm_zh × holdout_personal_call_time_related

- Query：`明天早班要几点起床？`
- Memory：The call with Mina is at 10:30 on July 14, 2026.
- 来源 corpus：`holdout_personal_call_time`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：与 Mina 的通话属于不同日期和事件，不能回答明天早班起床时间。
- [ ] 用户批准

## 23. holdout_personal_morning_alarm_zh × holdout_personal_unknown_insurance_irrelevant

- Query：`明天早班要几点起床？`
- Memory：用户下月计划旅行。
- 来源 corpus：`holdout_personal_unknown_insurance`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：下月旅行计划不包含明天早班或起床时间。
- [ ] 用户批准

## 24. holdout_personal_morning_alarm_zh × holdout_project_incident_time_answer

- Query：`明天早班要几点起床？`
- Memory：INC-319 recovered at 02:14 UTC on July 5, 2026.
- 来源 corpus：`holdout_project_incident_time`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：项目事故恢复时间不是个人早班起床时间。
- [ ] 用户批准

## 25. holdout_personal_morning_alarm_zh × holdout_project_incident_time_related

- Query：`明天早班要几点起床？`
- Memory：INC-319 started at 01:42 UTC.
- 来源 corpus：`holdout_project_incident_time`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：项目事故开始时间不是个人早班起床时间。
- [ ] 用户批准

## 26. holdout_personal_pet_food_zh × holdout_personal_diet_update_answer

- Query：`现在给猫买哪款粮？`
- Memory：The user currently avoids all dairy products.
- 来源 corpus：`holdout_personal_diet_update`
- Profile ranks：amadeus-baseline=#2, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#2, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#2
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：避免乳制品描述的是用户本人，不是猫当前应购买的猫粮。
- [ ] 用户批准

## 27. holdout_personal_pet_food_zh × holdout_personal_recipe_steps_related

- Query：`现在给猫买哪款粮？`
- Memory：餐厅版汤底需要加花椒。
- 来源 corpus：`holdout_personal_recipe_steps`
- Profile ranks：amadeus-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：餐厅版汤底使用花椒与猫粮选择无关。
- [ ] 用户批准

## 28. holdout_personal_pet_food_zh × holdout_personal_unknown_insurance_irrelevant

- Query：`现在给猫买哪款粮？`
- Memory：用户下月计划旅行。
- 来源 corpus：`holdout_personal_unknown_insurance`
- Profile ranks：amadeus-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：下月旅行计划不包含猫粮信息。
- [ ] 用户批准

## 29. holdout_personal_pet_food_zh × holdout_personal_unknown_locker_related

- Query：`现在给猫买哪款粮？`
- Memory：用户家门密码已更新。
- 来源 corpus：`holdout_personal_unknown_locker`
- Profile ranks：amadeus-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：家门密码已更新与猫粮无关；该记录没有暴露密码值，也没有 secret、owner 或 scope 风险标记。
- [ ] 用户批准

## 30. holdout_personal_pet_food_zh × holdout_project_review_rule_answer

- Query：`现在给猫买哪款粮？`
- Memory：修改 memory ranking 至少需要 memory owner 和一名 runtime reviewer。
- 来源 corpus：`holdout_project_review_rule`
- Profile ranks：amadeus-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：memory ranking 的审核规则与猫粮选择无关。
- [ ] 用户批准

## 31. holdout_personal_pet_food_zh × holdout_project_unknown_flag_answer

- Query：`现在给猫买哪款粮？`
- Memory：feature flag MEM-929 默认关闭。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#3, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#3, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#3
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-929 的默认开关状态与猫粮选择无关。
- [ ] 用户批准

## 32. holdout_personal_pet_food_zh × holdout_project_unknown_flag_related

- Query：`现在给猫买哪款粮？`
- Memory：MEM-992 是尚未记录的实验编号。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-992 实验编号与猫粮选择无关。
- [ ] 用户批准

## 33. holdout_personal_recipe_steps_zh × holdout_personal_pet_food_answer

- Query：`家庭版汤底要加哪两种香料？`
- Memory：猫目前改吃低敏配方粮。
- 来源 corpus：`holdout_personal_pet_food`
- Profile ranks：amadeus-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：猫的低敏配方粮不是家庭版汤底所需香料。
- [ ] 用户批准

## 34. holdout_personal_recipe_steps_zh × holdout_personal_pet_food_irrelevant

- Query：`家庭版汤底要加哪两种香料？`
- Memory：用户喜欢鸡肉沙拉。
- 来源 corpus：`holdout_personal_pet_food`
- Profile ranks：amadeus-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：用户喜欢鸡肉沙拉不包含家庭版汤底的香料步骤。
- [ ] 用户批准

## 35. holdout_personal_recipe_steps_zh × holdout_personal_unknown_locker_related

- Query：`家庭版汤底要加哪两种香料？`
- Memory：用户家门密码已更新。
- 来源 corpus：`holdout_personal_unknown_locker`
- Profile ranks：amadeus-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：家门密码已更新与汤底配方无关；记录未包含真实密码值，因此不构成 private_secret。
- [ ] 用户批准

## 36. holdout_personal_recipe_steps_zh × holdout_project_unknown_flag_related

- Query：`家庭版汤底要加哪两种香料？`
- Memory：MEM-992 是尚未记录的实验编号。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-992 只是项目实验编号，和家庭版汤底所需香料没有共同实体或任务关系。
- [ ] 用户批准

## 37. holdout_personal_tax_document_mixed × holdout_personal_diet_update_answer

- Query：`报税用的 document ID 是什么？`
- Memory：The user currently avoids all dairy products.
- 来源 corpus：`holdout_personal_diet_update`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：当前乳制品限制与报税文件编号无关，不能提供 document ID。
- [ ] 用户批准

## 38. holdout_personal_tax_document_mixed × holdout_personal_diet_update_irrelevant

- Query：`报税用的 document ID 是什么？`
- Memory：The user avoids peanuts.
- 来源 corpus：`holdout_personal_diet_update`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：花生饮食限制与报税文件及其编号无关。
- [ ] 用户批准

## 39. holdout_personal_tax_document_mixed × holdout_personal_language_exception_answer

- Query：`报税用的 document ID 是什么？`
- Memory：给海外客户的 incident report 使用英文。
- 来源 corpus：`holdout_personal_language_exception`
- Profile ranks：amadeus-baseline=#1, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#1, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#1
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：海外客户 incident report 的语言规则属于另一种文档任务，不能回答报税 document ID。
- [ ] 用户批准

## 40. holdout_personal_tax_document_mixed × holdout_personal_language_exception_irrelevant

- Query：`报税用的 document ID 是什么？`
- Memory：代码标识符保持英文。
- 来源 corpus：`holdout_personal_language_exception`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：代码标识符保持英文只是通用格式偏好，未涉及报税文件实体或编号。
- [ ] 用户批准

## 41. holdout_personal_tax_document_mixed × holdout_personal_unknown_locker_irrelevant

- Query：`报税用的 document ID 是什么？`
- Memory：健身房会员号是 GYM-2291。
- 来源 corpus：`holdout_personal_unknown_locker`
- Profile ranks：window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：健身房会员号虽也是标识符，但主体和用途均不是报税文件。
- [ ] 用户批准

## 42. holdout_personal_tax_document_mixed × holdout_project_schema_update_answer

- Query：`报税用的 document ID 是什么？`
- Memory：当前候选并集字段是 candidate_count。
- 来源 corpus：`holdout_project_schema_update`
- Profile ranks：amadeus-baseline=#2, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#2, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#2
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：候选并集字段 candidate_count 是项目 schema 信息，与个人报税 document ID 无关。
- [ ] 用户批准

## 43. holdout_personal_unknown_insurance_zh × holdout_personal_language_exception_answer

- Query：`我的旅行保险保单号是多少？`
- Memory：给海外客户的 incident report 使用英文。
- 来源 corpus：`holdout_personal_language_exception`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：incident report 的语言规则与旅行保险保单及其号码无关。
- [ ] 用户批准

## 44. holdout_personal_unknown_insurance_zh × holdout_personal_tax_document_answer

- Query：`我的旅行保险保单号是多少？`
- Memory：报税文件编号是 TAX-CN-8842。
- 来源 corpus：`holdout_personal_tax_document`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：TAX-CN-8842 明确是报税文件编号，不是旅行保险保单号。
- [ ] 用户批准

## 45. holdout_personal_unknown_insurance_zh × holdout_personal_tax_document_related

- Query：`我的旅行保险保单号是多少？`
- Memory：保险文件编号是 TAX-CN-8482。
- 来源 corpus：`holdout_personal_tax_document`
- Profile ranks：amadeus-baseline=#3, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#3, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#2
- 建议 relevance：`1`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：该记忆给出了一个保险文件编号，和所问保险文档属于同类实体，但没有证明它是旅行保险的保单号。
- [ ] 用户批准

## 46. holdout_personal_unknown_insurance_zh × holdout_personal_unknown_locker_irrelevant

- Query：`我的旅行保险保单号是多少？`
- Memory：健身房会员号是 GYM-2291。
- 来源 corpus：`holdout_personal_unknown_locker`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：健身房会员号与旅行保险保单号属于不同实体和用途。
- [ ] 用户批准

## 47. holdout_personal_unknown_insurance_zh × holdout_personal_unknown_locker_related

- Query：`我的旅行保险保单号是多少？`
- Memory：用户家门密码已更新。
- 来源 corpus：`holdout_personal_unknown_locker`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：家门密码更新与旅行保险保单及其号码无关，且记忆没有暴露密码值。
- [ ] 用户批准

## 48. holdout_personal_unknown_locker_zh × holdout_personal_pet_food_irrelevant

- Query：`健身房储物柜密码是多少？`
- Memory：用户喜欢鸡肉沙拉。
- 来源 corpus：`holdout_personal_pet_food`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：鸡肉沙拉偏好与健身房储物柜密码无关。
- [ ] 用户批准

## 49. holdout_personal_unknown_locker_zh × holdout_personal_unknown_insurance_answer

- Query：`健身房储物柜密码是多少？`
- Memory：用户购买过旅行保险。
- 来源 corpus：`holdout_personal_unknown_insurance`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：购买过旅行保险与健身房储物柜或其密码无关。
- [ ] 用户批准

## 50. holdout_personal_unknown_locker_zh × holdout_personal_unknown_insurance_irrelevant

- Query：`健身房储物柜密码是多少？`
- Memory：用户下月计划旅行。
- 来源 corpus：`holdout_personal_unknown_insurance`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：下月旅行计划与健身房储物柜密码无关。
- [ ] 用户批准

## 51. holdout_personal_unknown_locker_zh × holdout_project_unknown_flag_related

- Query：`健身房储物柜密码是多少？`
- Memory：MEM-992 是尚未记录的实验编号。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-992 实验编号与个人健身房储物柜密码无关。
- [ ] 用户批准

## 52. holdout_personal_unknown_locker_zh × holdout_stress_cross_user_answer

- Query：`健身房储物柜密码是多少？`
- Memory：另一个用户的数据库密码记录存在但不可访问。
- 来源 corpus：`holdout_stress_cross_user`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：另一用户数据库密码记录的存在与当前用户的健身房储物柜密码不是同一主体或秘密；文本未暴露密码值。
- [ ] 用户批准

## 53. holdout_project_config_key_mixed × holdout_personal_language_exception_related

- Query：`memory lexical kill switch 的 config key？`
- Memory：日常解释默认使用中文。
- 来源 corpus：`holdout_personal_language_exception`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：默认中文的回复偏好与 lexical kill switch 的配置键无关。
- [ ] 用户批准

## 54. holdout_project_config_key_mixed × holdout_project_review_rule_answer

- Query：`memory lexical kill switch 的 config key？`
- Memory：修改 memory ranking 至少需要 memory owner 和一名 runtime reviewer。
- 来源 corpus：`holdout_project_review_rule`
- Profile ranks：amadeus-baseline=#3, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#3, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#3
- 建议 relevance：`1`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：memory ranking 的 review 规则属于修改同一检索子系统时的治理背景，但没有给出 lexical kill switch 的 config key。
- [ ] 用户批准

## 55. holdout_project_config_key_mixed × holdout_project_unknown_flag_answer

- Query：`memory lexical kill switch 的 config key？`
- Memory：feature flag MEM-929 默认关闭。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-929 是另一个 feature flag，且记忆只给默认值，没有给出 lexical kill switch 的配置键。
- [ ] 用户批准

## 56. holdout_project_config_key_mixed × holdout_project_unknown_flag_related

- Query：`memory lexical kill switch 的 config key？`
- Memory：MEM-992 是尚未记录的实验编号。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-992 是未记录的实验编号，不是 lexical kill switch 的配置键。
- [ ] 用户批准

## 57. holdout_project_config_key_mixed × holdout_stress_cross_user_answer

- Query：`memory lexical kill switch 的 config key？`
- Memory：另一个用户的数据库密码记录存在但不可访问。
- 来源 corpus：`holdout_stress_cross_user`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：另一用户数据库密码记录与 memory lexical 配置键无关，且文本没有暴露密码值。
- [ ] 用户批准

## 58. holdout_project_incident_time_en × holdout_personal_call_time_answer

- Query：`When did INC-319 recover?`
- Memory：The call with Maya is at 10:30 on July 13, 2026.
- 来源 corpus：`holdout_personal_call_time`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Maya 通话时间与 INC-319 的恢复事件无关，日期和主体都不匹配。
- [ ] 用户批准

## 59. holdout_project_incident_time_en × holdout_personal_call_time_related

- Query：`When did INC-319 recover?`
- Memory：The call with Mina is at 10:30 on July 14, 2026.
- 来源 corpus：`holdout_personal_call_time`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Mina 通话时间与 INC-319 的恢复事件无关，日期和主体都不匹配。
- [ ] 用户批准

## 60. holdout_project_incident_time_en × holdout_personal_morning_alarm_answer

- Query：`When did INC-319 recover?`
- Memory：2026 年 7 月 13 日早班需要 05:50 起床。
- 来源 corpus：`holdout_personal_morning_alarm`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：个人早班起床时间与 INC-319 的恢复时间属于不同事件。
- [ ] 用户批准

## 61. holdout_project_incident_time_en × holdout_project_schema_update_answer

- Query：`When did INC-319 recover?`
- Memory：当前候选并集字段是 candidate_count。
- 来源 corpus：`holdout_project_schema_update`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：candidate_count 字段与 INC-319 事故及其恢复时间无关。
- [ ] 用户批准

## 62. holdout_project_incident_time_en × holdout_project_unknown_flag_related

- Query：`When did INC-319 recover?`
- Memory：MEM-992 是尚未记录的实验编号。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-992 实验编号与 INC-319 事故恢复时间无关。
- [ ] 用户批准

## 63. holdout_project_queue_choice_en × holdout_project_config_key_irrelevant

- Query：`Which queue backend did the worker design choose?`
- Memory：The retry key is runtime.max_retries.
- 来源 corpus：`holdout_project_config_key`
- Profile ranks：amadeus-baseline=#3, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#3, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#3
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：runtime.max_retries 是重试配置键，没有说明 worker 选择了哪种队列后端。
- [ ] 用户批准

## 64. holdout_project_queue_choice_en × holdout_project_config_key_related

- Query：`Which queue backend did the worker design choose?`
- Memory：The vector switch is memory.vector_enabled.
- 来源 corpus：`holdout_project_config_key`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：memory.vector_enabled 属于向量检索开关，与 worker 的队列后端决策不是同一实体或任务。
- [ ] 用户批准

## 65. holdout_project_queue_choice_en × holdout_project_review_rule_answer

- Query：`Which queue backend did the worker design choose?`
- Memory：修改 memory ranking 至少需要 memory owner 和一名 runtime reviewer。
- 来源 corpus：`holdout_project_review_rule`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：memory ranking 的 review 规则与 worker 队列后端的架构选择无关。
- [ ] 用户批准

## 66. holdout_project_queue_choice_en × holdout_project_schema_update_answer

- Query：`Which queue backend did the worker design choose?`
- Memory：当前候选并集字段是 candidate_count。
- 来源 corpus：`holdout_project_schema_update`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：candidate_count schema 字段与 worker 选择的队列后端无关。
- [ ] 用户批准

## 67. holdout_project_queue_choice_en × holdout_project_unknown_flag_answer

- Query：`Which queue backend did the worker design choose?`
- Memory：feature flag MEM-929 默认关闭。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-929 feature flag 的默认值与 worker 队列后端选择无关。
- [ ] 用户批准

## 68. holdout_project_queue_choice_en × holdout_stress_conflict_answer

- Query：`Which queue backend did the worker design choose?`
- Memory：Production 当前迁移到 ap-southeast-1。
- 来源 corpus：`holdout_stress_conflict`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Production region 与 worker 队列后端是两个独立的架构属性。
- [ ] 用户批准

## 69. holdout_project_queue_choice_en × holdout_stress_conflict_irrelevant

- Query：`Which queue backend did the worker design choose?`
- Memory：Backup region 是 ap-northeast-1。
- 来源 corpus：`holdout_stress_conflict`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Backup region 与 worker 队列后端选择无关。
- [ ] 用户批准

## 70. holdout_project_review_rule_zh × holdout_project_config_key_answer

- Query：`改 memory ranking 至少要谁 review？`
- Memory：The lexical kill switch is memory.lexical_enabled.
- 来源 corpus：`holdout_project_config_key`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：lexical kill switch 的配置键属于检索配置，不包含修改 memory ranking 所需的 reviewer 身份或审核规则。
- [ ] 用户批准

## 71. holdout_project_review_rule_zh × holdout_project_config_key_related

- Query：`改 memory ranking 至少要谁 review？`
- Memory：The vector switch is memory.vector_enabled.
- 来源 corpus：`holdout_project_config_key`
- Profile ranks：amadeus-baseline=#3, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#3, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#3
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：vector switch 的配置键不包含修改 memory ranking 所需的 reviewer 身份或审核规则。
- [ ] 用户批准

## 72. holdout_project_review_rule_zh × holdout_project_schema_update_answer

- Query：`改 memory ranking 至少要谁 review？`
- Memory：当前候选并集字段是 candidate_count。
- 来源 corpus：`holdout_project_schema_update`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：candidate_count 是 trace schema 字段，不能说明修改 memory ranking 至少需要谁 review。
- [ ] 用户批准

## 73. holdout_project_review_rule_zh × holdout_project_unknown_flag_answer

- Query：`改 memory ranking 至少要谁 review？`
- Memory：feature flag MEM-929 默认关闭。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-929 的默认值与 memory ranking 的 reviewer 要求是不同属性。
- [ ] 用户批准

## 74. holdout_project_review_rule_zh × holdout_project_unknown_flag_irrelevant

- Query：`改 memory ranking 至少要谁 review？`
- Memory：所有生产 flag 需要审批。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`1`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：生产 flag 需要审批属于变更治理背景，但没有说明修改 memory ranking 具体需要 memory owner 和 runtime reviewer。
- [ ] 用户批准

## 75. holdout_project_review_rule_zh × holdout_project_unknown_flag_related

- Query：`改 memory ranking 至少要谁 review？`
- Memory：MEM-992 是尚未记录的实验编号。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-992 是未记录实验编号这一事实没有提供任何 reviewer 或审批角色信息。
- [ ] 用户批准

## 76. holdout_project_schema_update_zh × holdout_project_review_rule_answer

- Query：`trace 里的候选并集字段现在叫什么？`
- Memory：修改 memory ranking 至少需要 memory owner 和一名 runtime reviewer。
- 来源 corpus：`holdout_project_review_rule`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：memory ranking 的审核角色不能说明 trace 中候选并集字段的名称。
- [ ] 用户批准

## 77. holdout_project_schema_update_zh × holdout_project_review_rule_irrelevant

- Query：`trace 里的候选并集字段现在叫什么？`
- Memory：旧规则只要求任意一名 reviewer。
- 来源 corpus：`holdout_project_review_rule`
- Profile ranks：amadeus-baseline=#3, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#3, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#3
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：旧 reviewer 规则与 trace 候选并集字段名称无关；该 memory 也没有 superseded 状态。
- [ ] 用户批准

## 78. holdout_project_schema_update_zh × holdout_project_unknown_flag_answer

- Query：`trace 里的候选并集字段现在叫什么？`
- Memory：feature flag MEM-929 默认关闭。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-929 的默认值不能说明 trace 候选并集字段当前叫什么。
- [ ] 用户批准

## 79. holdout_project_schema_update_zh × holdout_project_unknown_flag_related

- Query：`trace 里的候选并集字段现在叫什么？`
- Memory：MEM-992 是尚未记录的实验编号。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-992 的实验编号信息与 trace 候选并集字段无关。
- [ ] 用户批准

## 80. holdout_project_schema_update_zh × holdout_stress_conflict_answer

- Query：`trace 里的候选并集字段现在叫什么？`
- Memory：Production 当前迁移到 ap-southeast-1。
- 来源 corpus：`holdout_stress_conflict`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Production region 与 trace schema 字段名称属于不同实体和属性。
- [ ] 用户批准

## 81. holdout_project_schema_update_zh × holdout_stress_cross_user_answer

- Query：`trace 里的候选并集字段现在叫什么？`
- Memory：另一个用户的数据库密码记录存在但不可访问。
- 来源 corpus：`holdout_stress_cross_user`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：另一个用户的密码记录不可访问这一事实不包含 trace 字段信息，也没有暴露密码值。
- [ ] 用户批准

## 82. holdout_project_unknown_flag_mixed × holdout_personal_language_exception_related

- Query：`feature flag MEM-992 默认值是什么？`
- Memory：日常解释默认使用中文。
- 来源 corpus：`holdout_personal_language_exception`
- Profile ranks：amadeus-baseline=#3, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#3, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#3
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：日常解释语言偏好与 MEM-992 feature flag 的默认值无关。
- [ ] 用户批准

## 83. holdout_project_unknown_flag_mixed × holdout_project_config_key_answer

- Query：`feature flag MEM-992 默认值是什么？`
- Memory：The lexical kill switch is memory.lexical_enabled.
- 来源 corpus：`holdout_project_config_key`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：lexical kill switch 是另一个配置项，不能证明 MEM-992 的默认值。
- [ ] 用户批准

## 84. holdout_project_unknown_flag_mixed × holdout_project_config_key_related

- Query：`feature flag MEM-992 默认值是什么？`
- Memory：The vector switch is memory.vector_enabled.
- 来源 corpus：`holdout_project_config_key`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：vector switch 是另一个配置项，不能证明 MEM-992 的默认值。
- [ ] 用户批准

## 85. holdout_project_unknown_flag_mixed × holdout_project_review_rule_answer

- Query：`feature flag MEM-992 默认值是什么？`
- Memory：修改 memory ranking 至少需要 memory owner 和一名 runtime reviewer。
- 来源 corpus：`holdout_project_review_rule`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：memory ranking 的 reviewer 规则不包含 MEM-992 的默认值。
- [ ] 用户批准

## 86. holdout_project_unknown_flag_mixed × holdout_stress_conflict_irrelevant

- Query：`feature flag MEM-992 默认值是什么？`
- Memory：Backup region 是 ap-northeast-1。
- 来源 corpus：`holdout_stress_conflict`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Backup region 与 MEM-992 feature flag 的默认值无关。
- [ ] 用户批准

## 87. holdout_stress_conflict_mixed × holdout_personal_language_exception_irrelevant

- Query：`production region 现在到底是哪？`
- Memory：代码标识符保持英文。
- 来源 corpus：`holdout_personal_language_exception`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：代码标识符保持英文的规则不能说明 Production 当前 region。
- [ ] 用户批准

## 88. holdout_stress_conflict_mixed × holdout_project_unknown_flag_answer

- Query：`production region 现在到底是哪？`
- Memory：feature flag MEM-929 默认关闭。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-929 的默认值与 Production 部署 region 无关。
- [ ] 用户批准

## 89. holdout_stress_conflict_mixed × holdout_project_unknown_flag_irrelevant

- Query：`production region 现在到底是哪？`
- Memory：所有生产 flag 需要审批。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#3, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#3, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#3
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：生产 flag 的审批规则不能说明 Production 部署在哪个 region。
- [ ] 用户批准

## 90. holdout_stress_conflict_mixed × holdout_project_unknown_flag_related

- Query：`production region 现在到底是哪？`
- Memory：MEM-992 是尚未记录的实验编号。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-992 的实验编号信息不能说明 Production 当前 region。
- [ ] 用户批准

## 91. holdout_stress_conflict_mixed × holdout_stress_cross_user_answer

- Query：`production region 现在到底是哪？`
- Memory：另一个用户的数据库密码记录存在但不可访问。
- 来源 corpus：`holdout_stress_cross_user`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：另一个用户的数据库密码记录不可访问这一事实不包含 Production region，也没有暴露密码值。
- [ ] 用户批准

## 92. holdout_stress_conflict_mixed × holdout_stress_cross_user_irrelevant

- Query：`production region 现在到底是哪？`
- Memory：数据库运行在 WSL Docker。
- 来源 corpus：`holdout_stress_cross_user`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：WSL Docker 描述的是数据库运行载体，不是云 region，且没有说明它就是问题所指的 Production 环境。
- [ ] 用户批准

## 93. holdout_stress_cross_user_zh × holdout_personal_unknown_insurance_irrelevant

- Query：`我的生产数据库密码是什么？`
- Memory：用户下月计划旅行。
- 来源 corpus：`holdout_personal_unknown_insurance`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：下月旅行计划与生产数据库密码无关。
- [ ] 用户批准

## 94. holdout_stress_cross_user_zh × holdout_personal_unknown_locker_related

- Query：`我的生产数据库密码是什么？`
- Memory：用户家门密码已更新。
- 来源 corpus：`holdout_personal_unknown_locker`
- Profile ranks：amadeus-baseline=#2, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#2, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#2
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：家门密码与生产数据库密码是不同凭据；该记忆也只说明已更新，没有暴露密码值。
- [ ] 用户批准

## 95. holdout_stress_cross_user_zh × holdout_project_unknown_flag_answer

- Query：`我的生产数据库密码是什么？`
- Memory：feature flag MEM-929 默认关闭。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：MEM-929 的默认值不能回答生产数据库密码。
- [ ] 用户批准

## 96. holdout_stress_cross_user_zh × holdout_project_unknown_flag_irrelevant

- Query：`我的生产数据库密码是什么？`
- Memory：所有生产 flag 需要审批。
- 来源 corpus：`holdout_project_unknown_flag`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：生产 flag 的审批规则不包含生产数据库密码。
- [ ] 用户批准

## 97. holdout_stress_cross_user_zh × holdout_stress_conflict_answer

- Query：`我的生产数据库密码是什么？`
- Memory：Production 当前迁移到 ap-southeast-1。
- 来源 corpus：`holdout_stress_conflict`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Production region 是部署属性，不能提供生产数据库密码。
- [ ] 用户批准

## 98. holdout_stress_cross_user_zh × holdout_stress_conflict_irrelevant

- Query：`我的生产数据库密码是什么？`
- Memory：Backup region 是 ap-northeast-1。
- 来源 corpus：`holdout_stress_conflict`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Backup region 与生产数据库密码属于不同实体和属性。
- [ ] 用户批准

## 99. holdout_stress_homonym_zh × holdout_personal_call_time_irrelevant

- Query：`苹果账号绑定的是哪个邮箱？`
- Memory：Maya sent an email yesterday.
- 来源 corpus：`holdout_personal_call_time`
- Profile ranks：amadeus-baseline=#8, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Maya 曾发送邮件是通信事件，不能说明 Apple 账号绑定的邮箱地址。
- [ ] 用户批准

## 100. holdout_stress_homonym_zh × holdout_personal_unknown_locker_irrelevant

- Query：`苹果账号绑定的是哪个邮箱？`
- Memory：健身房会员号是 GYM-2291。
- 来源 corpus：`holdout_personal_unknown_locker`
- Profile ranks：amadeus-baseline=#4, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#3, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#3
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：健身房会员号与 Apple 账号绑定邮箱无关。
- [ ] 用户批准

## 101. holdout_stress_homonym_zh × holdout_personal_unknown_locker_related

- Query：`苹果账号绑定的是哪个邮箱？`
- Memory：用户家门密码已更新。
- 来源 corpus：`holdout_personal_unknown_locker`
- Profile ranks：amadeus-baseline=#5, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：家门密码更新与 Apple 账号及其绑定邮箱是不同凭据和属性，也没有暴露密码值。
- [ ] 用户批准

## 102. holdout_stress_homonym_zh × holdout_stress_conflict_answer

- Query：`苹果账号绑定的是哪个邮箱？`
- Memory：Production 当前迁移到 ap-southeast-1。
- 来源 corpus：`holdout_stress_conflict`
- Profile ranks：amadeus-baseline=#6, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Production region 与 Apple 账号绑定邮箱无关。
- [ ] 用户批准

## 103. holdout_stress_homonym_zh × holdout_stress_cross_user_answer

- Query：`苹果账号绑定的是哪个邮箱？`
- Memory：另一个用户的数据库密码记录存在但不可访问。
- 来源 corpus：`holdout_stress_cross_user`
- Profile ranks：amadeus-baseline=#7, window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：另一个用户的数据库密码记录不可访问这一事实与 Apple 账号邮箱无关，也没有暴露密码值。
- [ ] 用户批准
