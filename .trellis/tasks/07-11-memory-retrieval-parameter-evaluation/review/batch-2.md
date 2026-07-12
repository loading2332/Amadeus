# Gold Set 第 2 批审核表

本批已于 2026-07-12 由用户整体审核通过，所有 family 均为 `approved`。

## 1. personal_medicine_instruction

- Query：`甲状腺药现在应该怎么吃？`
- 场景：`personal_assistant`；能力：`knowledge_update`
- Required：`['current_medicine_instruction']`；Expected abstention：`False`
- Judgments：`current_medicine_instruction`=3；`obsolete_medicine_instruction`=1/dangerous；`vitamin_instruction`=0
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 2. personal_airport_pickup

- Query：`接妈妈的 flight number 是多少？`
- 场景：`personal_assistant`；能力：`information_extraction`
- Required：`['pickup_flight_number']`；Expected abstention：`False`
- Judgments：`pickup_flight_number`=3；`similar_flight_number`=0；`airport_transport_preference`=1
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 3. personal_gift_preferences

- Query：`给我伴侣挑礼物时要避开什么？`
- 场景：`personal_assistant`；能力：`cross_session`
- Required：`['partner_gift_dislike']`；Expected abstention：`False`
- Judgments：`partner_gift_dislike`=3；`user_perfume_preference`=1；`partner_food_preference`=1
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 4. personal_unknown_emergency_contact

- Query：`我的紧急联系人电话号码是多少？`
- 场景：`personal_assistant`；能力：`abstention`
- Required：`[]`；Expected abstention：`True`
- Judgments：`office_contact`=0；`family_doctor_name`=0；`emergency_call_preference`=0
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 5. personal_two_character_cjk

- Query：`豆豆几岁了？`
- 场景：`personal_assistant`；能力：`information_extraction`
- Required：`['cat_name_doudou']`；Expected abstention：`False`
- Judgments：`cat_name_doudou`=3；`dog_name_dingding`=0；`red_bean_preference`=0
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 6. project_api_contract_update

- Query：`记忆来源字段现在叫 source_ref 还是 source_url？`
- 场景：`project_assistant`；能力：`knowledge_update`
- Required：`['accepted_api_field']`；Expected abstention：`False`
- Judgments：`accepted_api_field`=3；`obsolete_api_field`=1/dangerous；`unrelated_api_field`=0
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 7. project_incident_root_cause

- Query：`What was the root cause of INC-204?`
- 场景：`project_assistant`；能力：`cross_session`
- Required：`['incident_root_cause']`；Expected abstention：`False`
- Judgments：`incident_root_cause`=3；`incident_mitigation`=2；`different_incident`=0
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 8. project_deploy_rollback

- Query：`build-7f3a9c 什么情况下回滚，命令是什么？`
- 场景：`project_assistant`；能力：`information_extraction`
- Required：`['rollback_trigger', 'rollback_command']`；Expected abstention：`False`
- Judgments：`rollback_trigger`=3；`rollback_command`=3；`similar_build_decoy`=0
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 9. project_test_ownership

- Query：`Who owns memory retrieval evaluation reviews?`
- 场景：`project_assistant`；能力：`cross_session`
- Required：`['memory_eval_owner']`；Expected abstention：`False`
- Judgments：`memory_eval_owner`=3；`runtime_owner`=0；`former_memory_owner`=1/dangerous
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 10. stress_same_term_different_meaning

- Query：`Amadeus production 用哪个 Python version？`
- 场景：`stress`；能力：`information_extraction`
- Required：`['python_runtime_pin']`；Expected abstention：`False`
- Judgments：`python_runtime_pin`=3；`python_course_schedule`=0；`monty_python_preference`=0
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 批次结论

- [x] 本批全部通过。
- [ ] 需要修改部分 family。
- [ ] rubric 需要调整。
