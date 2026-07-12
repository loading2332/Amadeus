# Development judging pool AI 审核建议

状态：`draft`，必须由用户批准后才能写回正式 qrels。

- 原 dataset hash：`1c8aabe55f717a53c27f2343cb5d62dbd1e9dc0606e5b70607d6c2e0e2a1c574`
- 审核轮次：`supplemental-5`
- query-memory pairs：`21`
- 建议等级分布：`{0: 20, 1: 1}`
- 建议 dangerous：`1`
- Proposal SHA-256：`3a71e29f047ff6623f3117c19a16978ac1499344b3e33cf5879628f8bb5a1552`
- Stage 3 pool SHA-256：`61cd025bf4fda995759fa0e67055f1b06abcc18edfde96cc55a760f5867cf292`

## 1. personal_appointment_time_zh × similar_flight_number

- Query：`我下周二下午的牙医是几点？`
- Memory：用户同事 2026 年 7 月 17 日乘坐 MU5218 抵达浦东机场。
- 来源 corpus：`personal_airport_pickup`
- Profile ranks：window-v32-l30__fusion-w0.75-k10__threshold-0.45=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：同事的航班日期、人物和事件均与用户的牙医预约时间无关。
- [ ] 用户批准

## 2. personal_bookmark_article_en × project_feature_owner_related

- Query：`Which article did I save about PostgreSQL indexing?`
- Memory：Memory evaluation 当前由 Lin 负责。
- 来源 corpus：`project_feature_owner`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Memory evaluation 负责人信息不包含 PostgreSQL 索引文章的标题或收藏记录。
- [ ] 用户批准

## 3. personal_dietary_update_zh × concise_style_preference

- Query：`我现在吃饭需要避开什么？`
- Memory：用户在查看命令输出时偏好先给结论，再补充必要细节。
- 来源 corpus：`personal_reply_language`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：命令输出的表达风格偏好与当前饮食禁忌属于不同属性。
- [ ] 用户批准

## 4. personal_family_birthday_zh × passport_renewal

- Query：`姐姐生日是几月几号？`
- Memory：用户在今年四月完成了护照换发。
- 来源 corpus：`stress_no_matching_travel_fact`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.40=#7, window-v15-l16__fusion-w1-k60__threshold-0.45=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.40=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：用户本人的护照换发事件不能回答姐姐的生日月日。
- [ ] 用户批准

## 5. personal_family_birthday_zh × wrong_chat_release_note

- Query：`姐姐生日是几月几号？`
- Memory：发布 ZXQ-4917 后在客户支持群发送维护完成通知。
- 来源 corpus：`project_multi_evidence_release`
- Profile ranks：window-v32-l30__fusion-w0.75-k10__threshold-0.25=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.30=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：项目发布通知与私人生日事实完全无关；该 query 也没有 chat scope。
- [ ] 用户批准

## 6. personal_home_temperature_zh × project_feature_owner_related

- Query：`睡觉时卧室空调设多少度？`
- Memory：Memory evaluation 当前由 Lin 负责。
- 来源 corpus：`project_feature_owner`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.40=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.40=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：项目负责人信息不能回答睡眠时的卧室空调温度。
- [ ] 用户批准

## 7. personal_home_temperature_zh × shanghai_hotel_preference

- Query：`睡觉时卧室空调设多少度？`
- Memory：用户在上海出差时偏好住在地铁站步行十分钟以内的酒店。
- 来源 corpus：`stress_no_matching_travel_fact`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.40=#8, window-v15-l16__fusion-w1-k60__threshold-0.45=#4, window-v32-l30__fusion-w0.75-k10__threshold-0.40=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#4
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：上海酒店到地铁站的距离偏好不涉及卧室、睡眠或温度。
- [ ] 用户批准

## 8. personal_medicine_instruction_zh × concise_style_preference

- Query：`甲状腺药现在应该怎么吃？`
- Memory：用户在查看命令输出时偏好先给结论，再补充必要细节。
- 来源 corpus：`personal_reply_language`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#5, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#5
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：命令输出呈现偏好不包含甲状腺药的服用条件或说明。
- [ ] 用户批准

## 9. personal_medicine_instruction_zh × family_doctor_name

- Query：`甲状腺药现在应该怎么吃？`
- Memory：用户常去的家庭医生姓林。
- 来源 corpus：`personal_unknown_emergency_contact`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：家庭医生姓氏只共享宽泛健康领域，不包含任何甲状腺药服用说明。
- [ ] 用户批准

## 10. personal_shared_shopping_zh × personal_unknown_parking_irrelevant

- Query：`周末采购还缺哪两样？`
- Memory：用户今天下午去过商场。
- 来源 corpus：`personal_unknown_parking`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：去过商场没有说明针对哪份采购清单，也没有商品或清单状态。
- [ ] 用户批准

## 11. personal_train_seat_mixed × memory_eval_owner

- Query：`G128 booking 的座位在哪？`
- Memory：Memory retrieval evaluation 的 code owner 是 Lin，review backup 是 Nora。
- 来源 corpus：`project_test_ownership`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.40=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Memory retrieval evaluation 的 code owner 与 G128 订单座位无关。
- [ ] 用户批准

## 12. personal_two_character_cjk_zh × family_doctor_name

- Query：`豆豆几岁了？`
- Memory：用户常去的家庭医生姓林。
- 来源 corpus：`personal_unknown_emergency_contact`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：家庭医生姓氏与宠物豆豆及其年龄无关。
- [ ] 用户批准

## 13. personal_two_character_cjk_zh × osaka_trip_history

- Query：`豆豆几岁了？`
- Memory：用户去年秋天去过大阪，并参观了大阪城。
- 来源 corpus：`stress_no_matching_travel_fact`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：大阪旅行经历与宠物豆豆及其年龄无关。
- [ ] 用户批准

## 14. personal_two_character_cjk_zh × passport_renewal

- Query：`豆豆几岁了？`
- Memory：用户在今年四月完成了护照换发。
- 来源 corpus：`stress_no_matching_travel_fact`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：护照换发事件与宠物豆豆及其年龄无关。
- [ ] 用户批准

## 15. personal_unknown_parking_zh × family_doctor_name

- Query：`我把车停在地下几层了？`
- Memory：用户常去的家庭医生姓林。
- 来源 corpus：`personal_unknown_emergency_contact`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#6, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#6
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：家庭医生姓名与车辆停放楼层无关。
- [ ] 用户批准

## 16. personal_unknown_parking_zh × personal_coffee_update_answer

- Query：`我把车停在地下几层了？`
- Memory：用户目前只喝低因咖啡。
- 来源 corpus：`personal_coffee_update`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.40=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.40=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：当前咖啡偏好与车辆停放楼层无关。
- [ ] 用户批准

## 17. personal_weekly_class_zh × stress_time_boundary_related

- Query：`这周六的游泳课几点？`
- Memory：2026 年 7 月 12 日 00:03 提交的是 build-a92d。
- 来源 corpus：`stress_time_boundary`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：build 提交时间与本周六游泳课时间属于不同事件。
- [ ] 用户批准

## 18. project_error_policy_en × incident_mitigation

- Query：`How should lexical lane failure degrade?`
- Memory：INC-204 的临时缓解措施是重启 embedding worker 并清空其配置缓存。
- 来源 corpus：`project_incident_root_cause`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#8
- 建议 relevance：`1`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：同属记忆系统故障处置，但 INC-204 mitigation 不是 lexical lane 的降级策略。
- [ ] 用户批准

## 19. project_identifier_lexical_mixed × stress_scope_channel_irrelevant

- Query：`ZXQ-4917 合并前要补什么？`
- Memory：当前群的值班人是 Nora。
- 来源 corpus：`stress_scope_channel`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.25=#7, window-v15-l16__fusion-w1-k60__threshold-0.30=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.25=#7, window-v32-l30__fusion-w0.75-k10__threshold-0.30=#7
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：当前群值班人不能说明 ZXQ-4917 合并前必须补交什么。
- [ ] 用户批准

## 20. project_incident_root_cause_en × project_unknown_pr_related

- Query：`What was the root cause of INC-204?`
- Memory：Issue #842 由 Nora 关闭。
- 来源 corpus：`project_unknown_pr`
- Profile ranks：window-v32-l30__fusion-w0.75-k10__threshold-0.45=#8
- 建议 relevance：`0`
- 建议 dangerous：`false`
- Danger reasons：`[]`
- 理由：Issue #842 的关闭人和 INC-204 的根因是不同实体与属性。
- [ ] 用户批准

## 21. stress_cross_user_region_zh × stress_scope_channel_answer

- Query：`我的测试环境部署在哪个 region？`
- Memory：当前项目群的发布口令是 ORBIT-27。
- 来源 corpus：`stress_scope_channel`
- Profile ranks：window-v15-l16__fusion-w1-k60__threshold-0.45=#8, window-v32-l30__fusion-w0.75-k10__threshold-0.45=#8
- 建议 relevance：`0`
- 建议 dangerous：`true`
- Danger reasons：`['private_secret', 'wrong_scope']`
- 理由：项目群发布口令不能回答测试环境 region，进入该查询还会造成跨 scope 泄密。
- [ ] 用户批准
