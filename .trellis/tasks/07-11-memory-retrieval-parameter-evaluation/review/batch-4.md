# Gold Set 第 4 批审核表

本批已于 2026-07-12 由用户整体审核通过，所有 family 均为 `approved`。

## 1. personal_home_temperature

- Split：`development`；场景：`personal_assistant`；能力：`cross_session`
- Query：`睡觉时卧室空调设多少度？`
- 直接答案候选：用户睡觉时偏好卧室空调设为 25 度。
- 近邻干扰项：用户工作时书房空调设为 23 度。
- 无关项：用户喜欢温水。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 2. personal_passport_expiry

- Split：`development`；场景：`personal_assistant`；能力：`temporal_reasoning`
- Query：`我的 passport 什么时候过期？`
- 直接答案候选：用户护照于 2031 年 4 月 10 日过期。
- 近邻干扰项：用户旧护照于 2026 年 4 月过期。
- 无关项：用户签证于 2027 年 8 月过期。
- Expected abstention：否；Dangerous related：是
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 3. personal_bookmark_article

- Split：`development`；场景：`personal_assistant`；能力：`information_extraction`
- Query：`Which article did I save about PostgreSQL indexing?`
- 直接答案候选：The saved article is 'GIN and GiST Index Types'.
- 近邻干扰项：The user saved an article about SQLite WAL.
- 无关项：The user bookmarked a Python typing guide.
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 4. personal_family_birthday

- Split：`development`；场景：`personal_assistant`；能力：`temporal_reasoning`
- Query：`姐姐生日是几月几号？`
- 直接答案候选：用户姐姐的生日是 9 月 16 日。
- 近邻干扰项：用户妹妹的生日是 6 月 19 日。
- 无关项：用户姐姐喜欢蓝色。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 5. personal_delivery_address_update

- Split：`development`；场景：`personal_assistant`；能力：`knowledge_update`
- Query：`现在默认收货地址是哪？`
- 直接答案候选：默认收货地址已改为梧桐路 28 号 3 栋 502。
- 近邻干扰项：旧默认地址是银杏路 18 号。
- 无关项：公司地址是科技路 66 号。
- Expected abstention：否；Dangerous related：是
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 6. personal_unknown_wifi

- Split：`development`；场景：`personal_assistant`；能力：`abstention`
- Query：`新公寓 Wi-Fi password 是什么？`
- 直接答案候选：用户的新公寓已经开通宽带。
- 近邻干扰项：旧公寓 Wi-Fi 名为 Home-5G。
- 无关项：用户路由器品牌是 ASUS。
- Expected abstention：是；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 7. project_env_variable

- Split：`development`；场景：`project_assistant`；能力：`information_extraction`
- Query：`DashScope embedding 的 env var 叫什么？`
- 直接答案候选：DashScope embedding 使用 DASHSCOPE_API_KEY。
- 近邻干扰项：OpenAI chat 使用 OPENAI_API_KEY。
- 无关项：数据库使用 AMADEUS_DATABASE_URL。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 8. project_release_date

- Split：`development`；场景：`project_assistant`；能力：`temporal_reasoning`
- Query：`0.4.0-beta.3 计划哪天发？`
- 直接答案候选：0.4.0-beta.3 计划在 2026 年 7 月 24 日发布。
- 近邻干扰项：0.3.2 曾计划在 2026 年 6 月发布。
- 无关项：pgvector 0.8.4 在 2026 年 7 月升级。
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 9. project_error_policy

- Split：`development`；场景：`project_assistant`；能力：`cross_session`
- Query：`How should lexical lane failure degrade?`
- 直接答案候选：A lexical lane failure keeps vector results and records degraded status.
- 近邻干扰项：A vector lane failure keeps lexical results and records degraded status.
- 无关项：Embedding cache miss aborts a formal experiment.
- Expected abstention：否；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 10. project_unknown_pr

- Split：`development`；场景：`project_assistant`；能力：`abstention`
- Query：`PR #842 最后是谁 approve 的？`
- 直接答案候选：PR #824 由 Lin approve。
- 近邻干扰项：Issue #842 由 Nora 关闭。
- 无关项：代码审核要求至少一人批准。
- Expected abstention：是；Dangerous related：否
- [x] Query/场景通过
- [x] qrels 与 required 通过
- [x] Dangerous/abstention 通过

## 批次结论

- [x] 本批全部通过。
- [ ] 需要修改部分 family。
- [ ] rubric 需要调整。
