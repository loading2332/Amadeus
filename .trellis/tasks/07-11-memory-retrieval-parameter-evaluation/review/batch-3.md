# Gold Set 第 3 批审核表

本批已于 2026-07-12 由用户整体审核通过，所有 family 均为 `approved`。

## 1. personal_coffee_update

- Split：`development`；场景：`personal_assistant`；能力：`knowledge_update`
- Query：`我现在喝咖啡要选哪种？`
- 直接答案候选：用户目前只喝低因咖啡。
- 近邻干扰项：用户以前每天喝双份浓缩咖啡。
- 无关项：用户喜欢茉莉花茶。
- Expected abstention：否；Dangerous related：是
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 2. personal_train_seat

- Split：`development`；场景：`personal_assistant`；能力：`information_extraction`
- Query：`G128 booking 的座位在哪？`
- 直接答案候选：G128 订单的座位是 06 车 12A。
- 近邻干扰项：G182 订单的座位是 08 车 12A。
- 无关项：用户高铁出行偏好靠窗。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 3. personal_weekly_class

- Split：`development`；场景：`personal_assistant`；能力：`temporal_reasoning`
- Query：`这周六的游泳课几点？`
- 直接答案候选：2026 年 7 月 18 日周六游泳课是上午九点。
- 近邻干扰项：上周六游泳课是上午十点。
- 无关项：周六下午有钢琴课。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 4. personal_allergy_restaurant

- Split：`development`；场景：`personal_assistant`；能力：`cross_session`
- Query：`What allergy should I mention at the restaurant?`
- 直接答案候选：The user has a severe peanut allergy.
- 近邻干扰项：The user dislikes very spicy food.
- 无关项：The user prefers window seats.
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 5. personal_unknown_parking

- Split：`development`；场景：`personal_assistant`；能力：`abstention`
- Query：`我把车停在地下几层了？`
- 直接答案候选：用户常去的商场有地下停车场。
- 近邻干扰项：用户的汽车是白色。
- 无关项：用户今天下午去过商场。
- Expected abstention：是；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 6. personal_shared_shopping

- Split：`development`；场景：`personal_assistant`；能力：`information_extraction`
- Query：`周末采购还缺哪两样？`
- 直接答案候选：周末采购还缺燕麦奶。
- 近邻干扰项：采购清单中的鸡蛋已经买到。
- 无关项：下周需要购买打印纸。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 7. project_migration_decision

- Split：`development`；场景：`project_assistant`；能力：`knowledge_update`
- Query：`memory schema migration 最后选 online 还是 downtime？`
- 直接答案候选：最终决定使用 online migration。
- 近邻干扰项：早期方案要求两小时 downtime。
- 无关项：前端迁移使用 codemod。
- Expected abstention：否；Dangerous related：是
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 8. project_test_command

- Split：`development`；场景：`project_assistant`；能力：`information_extraction`
- Query：`What command runs the memory acceptance suite?`
- 直接答案候选：Run uv run pytest tests/memory/test_memory_retrieval_acceptance.py.
- 近邻干扰项：Run uv run pytest tests/runtime for runtime tests.
- 无关项：Run uv run ruff check for lint.
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 9. project_feature_owner

- Split：`development`；场景：`project_assistant`；能力：`cross_session`
- Query：`Telegram outbound 这块现在谁负责？`
- 直接答案候选：Telegram outbound 当前由 Nora 负责。
- 近邻干扰项：Memory evaluation 当前由 Lin 负责。
- 无关项：Kai 曾临时代管 Telegram outbound。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 10. stress_scope_channel

- Split：`development`；场景：`stress`；能力：`information_extraction`
- Query：`这个群的发布口令是什么？`
- 直接答案候选：当前项目群的发布口令是 ORBIT-27。
- 近邻干扰项：另一个私有群的发布口令是 ORBIT-72。
- 无关项：当前群的值班人是 Nora。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 批次结论

- [x] 本批全部通过。
- [ ] 需要修改部分 family。
- [ ] rubric 需要调整。
