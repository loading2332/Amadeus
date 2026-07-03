# Amadeus Domain Context

## Memory Terms

- `profile`: 用户稳定身份或客观状态，例如公司、角色、长期项目状态。只能由用户消息提供证据。
- `preference`: 用户希望 Amadeus 如何回答、解释、推荐或服务，例如默认语言、解释风格。
- `procedure`: 用户要求 Amadeus 未来执行任务时遵守的规则，例如修改代码前先写测试。
- `fact`: 与用户或项目有关的长期事实，但不直接属于身份、偏好或执行规则。
- `candidate`: post-response 抽取阶段产生的待写入记忆候选，必须带类型、summary 和可回源证据。
- `decision`: 写入候选进入 store 前的判定结果，包括 `create`、`skip`、`replace`。
- `replacement`: 新记忆 supersede 旧记忆的生命周期边，记录在 `memory_replacements`。
- `invalidation`: 用户明确否定、更正或遗忘旧记忆时，让旧 active item 退出召回和上下文注入。
- `source_ref`: 指向原始 session message id 的可解析引用，供 `fetch_messages` 回源验证。
