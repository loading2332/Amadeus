# Gold Set fixture 修正提案

状态：`approved`。用户于 2026-07-12 批准全部 scope 与 qrel/lifecycle 修正；正式变更记录在独立 `fixture-correction-1` overlay。

## 为什么必须先修 fixture

检索参数只能改变候选数量和排序，不能猜出一条记忆属于哪个 chat，也不能把数据库中仍为 `active` 的旧事实自动当成 `superseded`。当前 7 个安全失败中有 6 个缺少 scope 元数据，另 1 个生命周期状态矛盾，因此继续 Stage 2 会把测试数据错误误判成参数错误。

## 提议的 scope 修正

以下修正只补齐已经由场景和 `wrong_scope/private_secret` 标签表达的边界，不改变 query 文本或 memory 文本：

| Family | Query/current memory scope | 特殊干扰项 scope |
|---|---|---|
| `project_identifier_lexical` | `telegram/project-amadeus` | `wrong_chat_release_note` 保持 `telegram/customer-support` |
| `personal_airport_pickup` | `telegram/personal-travel` | 项目群口令保持项目 scope |
| `project_deploy_rollback` | `telegram/project-ops` | 项目群口令使用不同 chat scope |
| `stress_scope_channel` | `telegram/project-amadeus` | `stress_scope_channel_related` 使用 `telegram/private-other` |
| `personal_unknown_wifi` | `telegram/personal-home` | 项目群口令使用不同 chat scope |
| `stress_forgotten_secret` | `telegram/personal-security` | 项目群口令使用不同 chat scope |

## 提议的 qrel/lifecycle 修正

1. `stress_scope_channel_zh × stress_scope_channel_related`
   - 保持 `relevance=1`
   - `dangerous: false -> true`
   - `danger_reasons: [private_secret, wrong_scope]`
   - 原因：这是另一个私有群的发布口令，对“这个群”问题属于敏感的错误 scope。

2. `project_release_date_related`
   - memory status：`active -> superseded`
   - 在 `project_release_date_zh` 中保持 `relevance=1`
   - `dangerous: false -> true`
   - `danger_reasons: [superseded, obsolete_version]`
   - 原因：它描述 0.3.2 的旧计划；当前 0.4.0-beta.3 计划已经取代它。同一 Gold Set 中另一条 0.3.2 记忆已经使用相同生命周期语义。

## 批准后的验证顺序

```text
生成独立 fixture-correction overlay
-> 按旧 final hash 校验 source lineage
-> 冻结新 dataset hash
-> Stage 0/1 collect-pool 必须 unknown=0
-> 重跑正式 Stage 0/1
-> 只有安全硬门通过的 profile 才能进入 shortlist
```

- [x] 用户批准全部 scope 修正。
- [x] 用户批准两项 qrel/lifecycle 修正。
