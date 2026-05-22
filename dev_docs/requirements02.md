# Amadeus 模块2 需求文档：Prompt Context 与信息注入

## 1. 背景

模块1已经建立了 Amadeus 的第一版 prompt block 和 runtime context 组装层。

模块2要解决的问题是：不是所有 prompt material 都应该长期放在 `messages[0]` 的 system prompt 里。稳定身份、行为规则和 self model 需要保持高优先级、低漂移；近期上下文、检索结果、活跃技能、运行元数据和本轮工具预取信息则是每轮变化的候选材料，应该以更清晰的边界注入。

Akashic 是本模块的参考实现，但 Amadeus 只迁移经过判断的设计模式，不迁移 Akashic 的目录结构、agent loop、proactive 子系统或历史包袱。

## 2. 目标

实现 Amadeus 的 lesson3 prompt context 分层机制，使每轮 LLM 输入形成稳定顺序：

```text
messages[0]      system prompt
messages[1..n]   history window
messages[n+1]    context frame, if dynamic context exists
messages[-1]     current user message
```

模块2要让开发者能够回答：

```text
哪些 section 留在 system prompt？
哪些 section 进入 context frame？
为什么 retrieval 不应该和 identity / self model 混在一起？
RECENT_CONTEXT.md 里的 Recent Turns 为什么在被动回复注入时要裁掉？
上下文过长时，哪些材料可以被裁剪，哪些核心 section 不能被裁剪？
如何调试一次 LLM 调用实际收到了哪些 messages？
```

## 3. 非目标

模块2不做以下内容：

```text
不实现生产级 agent loop
不迁移 Akashic proactive / drift / scheduler 子系统
不实现 memory optimizer 或自动写入 SELF.md / MEMORY.md
不实现 tool calling 编排
不实现数据库、向量检索或 embedding 层
不把 context frame 当成用户真实发言持久化
不引入 OpenAI SDK 等核心依赖
```

允许保留一个开发期 OpenAI-compatible provider debug 工具，用来验证渲染后的 messages 能被兼容接口调用。该工具属于 `dev_utils`，不是 Amadeus 核心 runtime 依赖。

## 4. 核心概念

### 4.1 Prompt Block

`PromptBlock` 仍然负责从 `RuntimeContext` 取材料并渲染为 section。

模块2要求每个 block 具备稳定的机器名：

```text
name: section 机器名，用于路由、禁用、调试和裁剪
label: 面向调试的人类可读类名
priority: 渲染顺序
is_static: 是否可缓存
render(context): 返回 PromptBlockRenderResult
```

`name` 和 `label` 的职责不同。`label` 可以服务调试展示，`name` 必须稳定，因为它会进入 `disabled_sections`、context frame routing 和 trim plan。

### 4.2 Prompt Section

每个非空 block 渲染结果会转成 `PromptSectionRender`：

```text
name
content
priority
is_static
cache_hit, optional
```

后续组装不再只面对一段拼好的字符串，而是面对一组有名字的 section。

### 4.3 System Prompt

System prompt 保存相对稳定、权威性更高的材料：

```text
identity
behavior_rules
self_model
long_term_memory
```

这些内容更适合作为模型本轮行为的稳定边界。它们仍然每轮发送给 LLM，因为 LLM API 不会自动记住上一轮未发送的 prompt。

### 4.4 Context Frame

Context frame 是一个 role 为 `user` 的系统注入消息，但内容必须带系统标记：

```text
<system-reminder data-system-context-frame="true">
...
</system-reminder>
```

它不是用户原文，也不是助手结论，只能作为候选上下文。模型回复时不能引用、复述或展示这个提醒本身。

第一版 context frame sections：

```text
recent_context
retrieved_memory
active_skills
runtime_metadata
turn_injection_context entries
```

`runtime_metadata` 在 Amadeus 里也进入 context frame。原因是 channel、source、request metadata 这类信息通常随请求变化，不应该和稳定身份规则混在 system prompt。

## 5. 功能需求

### 5.1 PromptAssembler

系统需要新增 `PromptAssembler`，职责是：

```text
1. 接收 PromptSectionRender 列表
2. 按 priority 保持稳定顺序
3. 根据 section.name 把 section 分到 system prompt 或 context frame
4. 应用 disabled_sections
5. 追加 turn_injection_context 到 context frame
6. 输出 PromptAssemblyResult
```

`PromptAssemblyResult` 至少包含：

```text
system_sections
frame_sections
system_prompt
context_frame
```

### 5.2 MessageEnvelopeBuilder

Message envelope 需要支持 context frame。

输出顺序：

```text
[
  {"role": "system", "content": system_prompt},
  *history_window,
  {"role": "user", "content": context_frame},  # only when non-empty
  {"role": "user", "content": current_user_message},
]
```

如果 history 中包含 role 为 `system` 的消息，仍然必须拒绝，避免调用方注入第二个 system prompt。

### 5.3 RuntimeContext 扩展

`RuntimeContext` 需要在模块1字段基础上支持：

```text
disabled_sections: set[str]
turn_injection_context: dict[str, str]
history_window: int | None
```

语义：

```text
disabled_sections
  本轮禁用指定 section。用于调试、预算裁剪和风险隔离。

turn_injection_context
  本轮临时工具结果或预取材料。只进入 context frame，不进入 system prompt。

history_window
  限制发送给 LLM 的 history 条数。None 表示不裁剪；0 或负数表示不带 history。
```

### 5.4 Recent Context 注入规则

`RECENT_CONTEXT.md` 可以保存：

```text
Compression
Ongoing Threads
Recent Turns
```

但被动回复的 `RecentContextPromptBlock` 注入时必须裁掉 `## Recent Turns` 及其后面的内容。

原因：

```text
history window 已经提供最近对话原文。
如果 context frame 再注入 Recent Turns，会重复放大最近对话，浪费上下文窗口，也可能让模型过度依赖重复材料。
```

如果裁剪后没有剩余内容，该 block 应跳过，并在 debug breakdown 中说明原因。

### 5.5 Context Budget Trim Plan

系统需要提供一个轻量的预算裁剪计划生成器，不负责实际调用 provider retry。

第一版 trim attempts 应满足：

```text
核心 section 不被裁掉：identity, behavior_rules, self_model
先裁剪低权重动态材料：runtime_metadata, active_skills
再裁剪可恢复或可重新检索材料：long_term_memory, retrieved_memory
最后逐步缩小 history_window
```

这是一组候选策略，供后续 provider 调用层在 context length error 时选择使用。

### 5.6 Debug Breakdown

调试信息需要从模块1的 block breakdown 扩展为可区分 destination：

```text
name
label
priority
rendered
char_count
estimated_tokens
empty_reason
destination: system | context_frame
```

`turn_injection_context` 生成的 section 也应出现在 context frame breakdown 中。

### 5.7 Dev Provider Debug

需要提供开发期工具，支持：

```text
读取 .env 或环境变量中的 OpenAI-compatible 配置
渲染 Amadeus context messages
可选打印 messages 和 breakdown
向 /chat/completions 发起最小请求
返回 assistant content、response id、model、usage
```

配置项：

```text
OPENAI_BASE_URL
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_TIMEOUT_SECONDS, optional
```

该工具必须可测试，网络调用通过可注入 transport 隔离。

## 6. Source of Truth 边界

| 内容类型 | 来源 | 目标位置 | 说明 |
|---|---|---|---|
| 稳定身份 | code prompt | system prompt | 不随本轮检索变化 |
| 行为规则 | code prompt | system prompt | 高优先级边界 |
| Self model | `memory/SELF.md` | system prompt | Amadeus 自我认知 |
| 用户长期记忆 | `memory/MEMORY.md` | system prompt | 用户画像，不描述 agent |
| 近期上下文摘要 | `memory/RECENT_CONTEXT.md` 或 override | context frame | 裁掉 `## Recent Turns` |
| 本轮检索 | runtime field | context frame | 候选材料，不能覆盖身份 |
| 活跃技能 | runtime field | context frame | 本轮可用能力提示 |
| 运行元数据 | runtime field | context frame | channel/source/time 等动态信息 |
| 工具预取 | `turn_injection_context` | context frame | 本轮临时材料 |

## 7. 方案权衡

### 7.1 全部放 system prompt

优点：

```text
实现简单，模块1已有基础。
```

缺点：

```text
稳定身份和动态检索混在一起，边界不清。
后续裁剪只能裁整段 prompt，不容易按来源控制。
调试时不容易判断模型看到的材料属于规则、记忆还是候选上下文。
```

### 7.2 全部作为普通 history

优点：

```text
消息结构更接近普通对话。
```

缺点：

```text
系统注入材料容易被误认为用户真实发言。
长期身份规则失去 system prompt 的稳定位置。
```

### 7.3 推荐方案：stable system prompt + marked context frame

优点：

```text
保留 system prompt 的稳定边界。
动态材料有明确 marker，不冒充用户原文。
后续可以按 section name 做禁用、裁剪和调试。
```

代价：

```text
messages 结构比模块1复杂。
测试需要覆盖 routing、marker、history order 和 debug destination。
调用方必须知道 context frame 是系统注入消息，不应持久化为用户真实发言。
```

本项目选择这个方案，因为 Amadeus 当前正在建立长期可维护的 prompt runtime，而不是只追求最短路径调用一次 LLM。

## 8. 测试需求

至少覆盖：

```text
PromptAssembler 按 name 路由 system/context frame sections
context frame 使用 system-reminder marker
没有 frame sections 时不生成 context frame
disabled_sections 会跳过对应 section 和 turn injection
ContextBuilder 将 dynamic context 放入 context frame
MessageEnvelopeBuilder 顺序为 system -> history -> context frame -> current user
空 context frame 不插入 messages
history_window 能裁剪 history
RecentContextPromptBlock 裁掉 ## Recent Turns
只有 Recent Turns 时 recent_context block 跳过
核心 trim plans 不裁掉 identity / behavior_rules / self_model
trim attempts 能生成 section disable 和 history_window 组合
OpenAI-compatible provider 能读取配置、发送 payload、解析 assistant content
provider 网络层可用 fake transport 测试
```

## 9. 验收标准

模块2完成后，应满足：

```text
所有单元测试通过
可以打印一次完整 messages，确认 context frame 位于 current user message 前
retrieved_memory 不出现在 system prompt
recent_context 注入内容不包含 ## Recent Turns
debug breakdown 能看出每个 section 的 destination
trim plan 永远不裁掉核心身份 section
dev provider 工具可以在有 .env 时发起 OpenAI-compatible 调试请求
```

## 10. 后续演进

后续模块可以基于本模块继续做：

```text
provider context length retry
tool calling message schema
memory retrieval layer
RECENT_CONTEXT.md 自动压缩和刷新
context frame 过滤，避免进入可见用户历史
LLM judge eval 或行为漂移测试
```

这些不属于模块2的完成范围。
