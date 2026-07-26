# Amadeus Domain Context

## Prompt Cache Terms

- `提示词缓存（Prompt Cache）`: 模型供应商复用已处理过的、与当前请求相同的提示词前缀所产生的中间计算结果；它不是 Amadeus 本地的响应缓存，也不复用模型最终生成的文本。
- `缓存读取 token（cached tokens）`: 本次请求从供应商缓存复用的输入 token 数；这是确认一次缓存读取的直接观测量。
- `缓存写入 token（cache write tokens）`: 本次请求为后续复用而写入供应商缓存的输入 token 数；写入可能有独立计费，不能被当成缓存读取。
- `缓存命中率（cache-read ratio）`: 在一次请求或一组请求中，缓存读取 token 占总输入 token 的比例。该术语只在供应商返回对应用量字段时使用；延迟下降只是代理证据。
- `稳定前缀（stable prefix）`: 在预期复用的请求之间字节级等价、位于动态内容之前的提示词部分；只有足够长且仍在供应商存活期内的稳定前缀才可能产生缓存读取。
- `缓存前缀单元（cache prefix unit）`: DeepSeek 已落盘、可作为整体被后续请求完整匹配的前缀。稳定文本本身不等于可读缓存：只有已生成的完整单元才能被命中。

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
