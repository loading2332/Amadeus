# Gold Set 第一批审核表

## 这批在审核什么

这 10 个 development families 用于校准判断标准，不会直接进入正式参数结论。用户已于 2026-07-12 初次审核通过，query 状态已改为 `approved`；数据集顶层仍保持 `draft`，因此不能用于正式参数结论。

相关性等级：

- `3`：当前有效，并且可以直接回答问题。
- `2`：当前有效，是完整回答所需的重要支持，但单独不足以回答。
- `1`：主题相关，但不足以回答，或不应进入主要上下文。
- `0`：人工确认无关。

独立安全标签：

- `dangerous=true` 不等于“完全无关”。旧版本、被否决方案、错误 scope、跨用户数据都可能在词面上高度相关，但一旦进入 top-8 就可能诱导错误回答。
- `required_memory_keys` 表示必须同时找回的证据；它不是“最好能找回”。
- `expected_abstention=true` 表示语料中没有答案，此类案例不计算普通 Recall，而计算错误返回率。

审核每个 family 时请确认：

- [x] query 像真实用户会问的话，而不是为了测试而写的提示词。
- [x] `3/2/1/0` 的边界合理。
- [x] dangerous 是否漏标或误标。
- [x] required evidence 是否真的缺一不可。
- [x] hard negative 足够容易混淆，而不是一眼无关。

## 1. 当前饮食限制覆盖旧偏好

Query：`我现在吃饭需要避开什么？`

目标能力：knowledge update；校准“旧信息仍与主题相关，但已经不能用于当前回答”。

| Memory | 摘要 | 建议等级 | Dangerous | 理由 |
|---|---|---:|---:|---|
| `current_gluten_constraint` | 当前避免含麸质食物，优先米饭或无麸质面食 | 3 | 否 | 当前有效且直接回答 |
| `obsolete_pizza_preference` | 以前常点普通小麦饼底披萨 | 1 | 是 | 相关但已被当前限制覆盖 |
| `unrelated_breakfast_habit` | 周末十点后吃早餐 | 0 | 否 | 时间习惯不能回答食物限制 |

Required：`current_gluten_constraint`

- [x] 等级通过
- [x] Dangerous 通过
- [x] Query/场景通过

## 2. 稀有标识符的 lexical-only 召回

Query：`ZXQ-4917 合并前要补什么？`

目标能力：information extraction；目标记忆故意设置 `embedding=NULL`，只能依靠 raw query 的 lexical lane。

| Memory | 摘要 | 建议等级 | Dangerous | 理由 |
|---|---|---:|---:|---|
| `release_identifier_rule` | ZXQ-4917 合并前附数据库回滚记录 | 3 | 否 | 精确命中并直接回答 |
| `similar_identifier_decoy` | ZXQ-4197 已完成资源压缩检查 | 0 | 否 | 数字顺序不同的 hard negative |
| `generic_release_rule` | 普通发布后通知测试群 | 1 | 否 | 发布相关但不是该批次要求 |

Required：`release_identifier_rule`

- [x] 等级通过
- [x] 标识符干扰难度通过
- [x] Query/场景通过

## 3. 默认中文与英文文档例外

Query：`我平时希望你默认怎么回复？`

目标能力：cross-session personalization；重点校准 grade 2 是否真的是完整回答的重要支持。

| Memory | 摘要 | 建议等级 | Dangerous | 理由 |
|---|---|---:|---:|---|
| `current_chinese_reply_preference` | 默认中文，代码标识符保持英文 | 3 | 否 | 直接回答日常默认规则 |
| `english_document_exception` | 海外团队正式设计文档使用英文 | 2 | 否 | 默认规则的重要例外 |
| `concise_style_preference` | 命令输出先结论后细节 | 1 | 否 | 同属回复偏好但与语言无关 |

Required：仅 `current_chinese_reply_preference`。英文例外建议为 2，但当前不要求它必须进入 top-8。

- [x] `english_document_exception=2` 合理
- [x] Required 设置合理
- [x] Query/场景通过

## 4. 已接受 ADR 与被否决方案

Query：`Which storage backend won the architecture discussion?`

目标能力：跨 session 保留架构决定；重点校准“被否决方案”危险性。

| Memory | 摘要 | 建议等级 | Dangerous | 理由 |
|---|---|---:|---:|---|
| `accepted_postgres_decision` | ADR-014 选择 PostgreSQL + pgvector | 3 | 否 | 已接受的直接答案 |
| `rejected_sqlite_proposal` | 早期草案建议继续使用 SQLite | 1 | 是 | 同一决策问题，但作为当前答案会完全答反 |
| `redis_cache_discussion` | Redis 缓存工具发现结果 | 0 | 否 | 解决的是另一条缓存边界 |

Required：`accepted_postgres_decision`

- [x] 等级通过
- [x] 被否决方案 Dangerous 通过
- [x] 英文 Query 通过

## 5. 语料中没有里斯本酒店答案

Query：`我上次去里斯本住的是哪家酒店？`

目标能力：abstention；该 corpus 故意只有旅行、酒店和护照相关的近邻信息，没有里斯本住宿事实。

| Memory | 摘要 | 建议等级 | Dangerous | 理由 |
|---|---|---:|---:|---|
| `osaka_trip_history` | 去过大阪并参观大阪城 | 0 | 否 | 城市不同，没有住宿答案 |
| `shanghai_hotel_preference` | 上海出差酒店位置偏好 | 0 | 否 | 同为酒店主题，但不是历史事实 |
| `passport_renewal` | 四月完成护照换发 | 0 | 否 | 旅行背景相关但无答案 |

Expected abstention：是。Required：空。

- [x] 三条都应判 0
- [x] 该问题确实应该不返回记忆
- [x] Hard negatives 难度通过

## 6. 将“下周二”落到具体预约

Query：`我下周二下午的牙医是几点？`

实验冻结时间：2026-07-12；因此下周二是 2026-07-14。

| Memory | 摘要 | 建议等级 | Dangerous | 理由 |
|---|---|---:|---:|---|
| `upcoming_dentist_appointment` | 7 月 14 日周二下午三点牙科复诊 | 3 | 否 | 日期、事件和时间都匹配 |
| `completed_dentist_visit` | 5 月 19 日完成牙齿清洁 | 1 | 否 | 同类历史事件但不是目标预约 |
| `unrelated_team_meeting` | 周二上午十点项目例会 | 0 | 否 | 同日但事件主体不同 |

Required：`upcoming_dentist_appointment`

- [x] 时间解释通过
- [x] 历史牙科事件等级通过
- [x] Query/场景通过

## 7. 当前发布版本与其他版本号

Query：`Amadeus 下一版现在定成多少了？`

目标能力：knowledge update + identifier/entity disambiguation。

| Memory | 摘要 | 建议等级 | Dangerous | 理由 |
|---|---|---:|---:|---|
| `current_release_version` | 当前准备发布 0.4.0-beta.3 | 3 | 否 | 当前直接答案 |
| `obsolete_release_version` | 之前计划发布 0.3.2 | 1 | 是 | 旧计划，作为当前答案会误导 |
| `dependency_version_decoy` | pgvector 版本 0.8.4 | 0 | 否 | 实体不同，只是同样包含版本号 |

Required：`current_release_version`

- [x] 等级通过
- [x] 旧版本 Dangerous 通过
- [x] 实体干扰难度通过

## 8. 跨用户精确命中也必须过滤

Query：`我的测试环境部署在哪个 region？`

目标能力：user isolation。跨用户项不只是“不相关”，而是候选 SQL 之前就必须挡住的隐私硬门。

| Memory | 摘要 | 建议等级 | Dangerous | 理由 |
|---|---|---:|---:|---|
| `own_deploy_region` | 当前用户测试环境在 ap-southeast-1 | 3 | 否 | 当前用户直接答案 |
| `other_user_exact_secret` | 另一用户生产环境在 eu-central-1 | 0 | 是 | 跨用户私有数据，候选层零容忍 |
| `own_backup_region` | 当前用户备份桶在 ap-northeast-1 | 1 | 否 | 用户正确但实体不是测试环境 |

Required：`own_deploy_region`

- [x] 跨用户项 grade 0 + Dangerous 合理
- [x] 自己的备份区域 grade 1 合理
- [x] Query/场景通过

## 9. Hotness 只在相关候选之间排序

Query：`非紧急工作找我时优先用什么方式？`

目标能力：时间衰减、reinforcement 与 emotional weight 的 pairwise 排序。

| Memory | 摘要 | 建议等级 | Dangerous | 理由 |
|---|---|---:|---:|---|
| `recent_contact_preference` | 最近确认优先 Telegram | 3 | 否 | 当前首选且直接回答 |
| `older_contact_preference` | 较早表示也接受电子邮件 | 2 | 否 | 仍可用，但不应排在首选之前 |
| `emergency_contact_rule` | 生产事故应直接打紧急电话 | 1 | 否 | 沟通渠道相关，但场景条件不匹配 |

Pairwise：`recent_contact_preference` 必须排在 `older_contact_preference` 之前。

- [x] `older_contact_preference=2` 合理
- [x] 紧急电话只判 1 合理
- [x] Pairwise 目标合理

## 10. 两条发布证据必须同时找回

Query：`发布 ZXQ-4917 前要确认哪两件事？`

目标能力：multi-evidence、memory type 与 chat scope 过滤。

| Memory | 摘要 | 建议等级 | Dangerous | 理由 |
|---|---|---:|---:|---|
| `release_database_step` | 迁移 dry-run 并保存输出 | 3 | 否 | 第一条必需证据 |
| `release_branch_step` | release/0.4 通过 smoke tests | 3 | 否 | 第二条必需证据 |
| `wrong_chat_release_note` | 客服群发送维护通知 | 1 | 是 | 标识符相关但 chat scope 错误 |
| `unrelated_local_dev_step` | 本地启动前格式化 | 0 | 否 | 流程相似但不是发布步骤 |

Required：`release_database_step` 与 `release_branch_step`，必须同时进入 top-8。

- [x] 两条 Required 都必要
- [x] Wrong-scope 项 grade 1 + Dangerous 合理
- [x] Query/场景通过

## 批次结论

- [x] 本批全部通过，可按同一 rubric 生成后续 50 families。
- [ ] 需要修改部分案例；请按 family 编号写出修改意见。
- [ ] rubric 本身需要调整；请指出 `3/2/1/0` 或 dangerous/required/abstention 的定义问题。

审核记录：2026-07-12 初次校准通过；同日，在第 2～6 批整体审核通过后，使用最终稳定 rubric 完成回看复审。第一批最终批准，无需调整 qrels、dangerous、required 或 abstention。
