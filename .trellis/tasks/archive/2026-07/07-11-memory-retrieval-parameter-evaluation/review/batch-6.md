# Gold Set 第 6 批审核表

本批已于 2026-07-12 由用户整体审核通过，所有 family 均为 `approved`。

## 1. holdout_personal_language_exception

- Split：`holdout`；场景：`personal_assistant`；能力：`cross_session`
- Query：`给客户的 incident report 用什么语言？`
- 直接答案候选：给海外客户的 incident report 使用英文。
- 近邻干扰项：日常解释默认使用中文。
- 无关项：代码标识符保持英文。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 2. holdout_personal_recipe_steps

- Split：`holdout`；场景：`personal_assistant`；能力：`information_extraction`
- Query：`家庭版汤底要加哪两种香料？`
- 直接答案候选：家庭版汤底需要加八角。
- 近邻干扰项：餐厅版汤底需要加花椒。
- 无关项：用户不喜欢太辣。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 3. holdout_personal_morning_alarm

- Split：`holdout`；场景：`personal_assistant`；能力：`temporal_reasoning`
- Query：`明天早班要几点起床？`
- 直接答案候选：2026 年 7 月 13 日早班需要 05:50 起床。
- 近邻干扰项：平时工作日起床时间是 07:20。
- 无关项：明天下午三点有会议。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 4. holdout_personal_diet_update

- Split：`holdout`；场景：`personal_assistant`；能力：`knowledge_update`
- Query：`What is my current dairy restriction?`
- 直接答案候选：The user currently avoids all dairy products.
- 近邻干扰项：The user previously allowed small amounts of cheese.
- 无关项：The user avoids peanuts.
- Expected abstention：否；Dangerous related：是
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 5. holdout_personal_unknown_locker

- Split：`holdout`；场景：`personal_assistant`；能力：`abstention`
- Query：`健身房储物柜密码是多少？`
- 直接答案候选：用户常去星河健身房。
- 近邻干扰项：用户家门密码已更新。
- 无关项：健身房会员号是 GYM-2291。
- Expected abstention：是；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 6. holdout_project_incident_time

- Split：`holdout`；场景：`project_assistant`；能力：`temporal_reasoning`
- Query：`When did INC-319 recover?`
- 直接答案候选：INC-319 recovered at 02:14 UTC on July 5, 2026.
- 近邻干扰项：INC-319 started at 01:42 UTC.
- 无关项：INC-391 recovered at 02:14 UTC.
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 7. holdout_project_review_rule

- Split：`holdout`；场景：`project_assistant`；能力：`cross_session`
- Query：`改 memory ranking 至少要谁 review？`
- 直接答案候选：修改 memory ranking 至少需要 memory owner 和一名 runtime reviewer。
- 近邻干扰项：修改前端样式只需 frontend owner。
- 无关项：旧规则只要求任意一名 reviewer。
- Expected abstention：否；Dangerous related：是
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 8. holdout_project_unknown_flag

- Split：`holdout`；场景：`project_assistant`；能力：`abstention`
- Query：`feature flag MEM-992 默认值是什么？`
- 直接答案候选：feature flag MEM-929 默认关闭。
- 近邻干扰项：MEM-992 是尚未记录的实验编号。
- 无关项：所有生产 flag 需要审批。
- Expected abstention：是；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 9. holdout_stress_homonym

- Split：`holdout`；场景：`stress`；能力：`information_extraction`
- Query：`苹果账号绑定的是哪个邮箱？`
- 直接答案候选：用户的 Apple 账号绑定邮箱是 user@example.test。
- 近邻干扰项：用户喜欢吃青苹果。
- 无关项：公司邮箱使用 Outlook。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 10. holdout_stress_conflict

- Split：`holdout`；场景：`stress`；能力：`knowledge_update`
- Query：`production region 现在到底是哪？`
- 直接答案候选：Production 当前迁移到 ap-southeast-1。
- 近邻干扰项：Production 过去位于 us-west-2。
- 无关项：Backup region 是 ap-northeast-1。
- Expected abstention：否；Dangerous related：是
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 批次结论

- [x] 本批全部通过。
- [ ] 需要修改部分 family。
- [ ] rubric 需要调整。
