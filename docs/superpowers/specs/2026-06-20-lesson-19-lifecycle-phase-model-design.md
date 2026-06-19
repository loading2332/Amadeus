# Lesson 19：Lifecycle Phase Model 设计

## 1. 目标

Lesson 19 开启 Lifecycle / Plugin Mini-Core 阶段。目标不是一次迁移 Akashic 完整 plugin system，而是先建立完整生命周期认知地图，再在 Amadeus 中复现三个 turn-level 稳定插入点：`before_turn`、`prompt_render`、`after_turn`。

本课完成后，用户应能说明：

- Akashic 七个 phase 在一次 passive turn 中的真实顺序和职责；
- Gate 与 Tap 的数据流和失败语义为什么不同；
- phase、phase module、context、EventBus 与主 loop 各自承担什么职责；
- Lesson 19 只实现了哪些 phase，哪些能力明确留给 Lesson 20–23；
- 为什么插件扩展应进入 lifecycle seam，而不是继续修改 `PassiveRuntime.run_turn()` 本体。

## 2. 当前阶段地图

已实现：

- `PassiveRuntime.run_turn()` 串联 session、memory retrieval、prompt render、LLM/tool loop、响应解析、持久化与 `TurnCommitted`。
- `EventBus` 已用于 tool-call 与 turn-commit 事件。
- `ContextBuilder` 已有 prompt block、context frame、disabled sections 与 trim/retry。
- `ToolExecutor` 已有工具级 before/after hook，但它不是 turn lifecycle。

当前缺口：

- turn 主链没有正式 lifecycle facade 或 typed phase context；扩展只能修改 runtime 本体或直接订阅零散事件。
- prompt render 之前没有稳定、可注册的生命周期入口。
- turn commit 后没有明确的只观察 Tap 边界。
- 尚无 plugin registry/loader、slot 协议、prompt injection plugin、完整 failure isolation 或 tool discovery。

下一个 Akashic 对齐复现切片是三个 turn-level phase。先做它们，因为它们分别包围输入准备、Prompt 构建和最终提交，能构成最小闭环，并为 Lesson 20–23 提供稳定宿主。

## 3. Part 1：Akashic 源码课设计

### 3.1 完整 phase map

课程先展示完整主链，避免把 Lesson 19 的三个 phase 误认为 Akashic 只有三个 phase：

```text
InboundMessage
  -> before_turn
  -> before_reasoning
  -> prompt_render
  -> before_step
  -> LLM/tool iteration
  -> after_step
  -> after_reasoning
  -> after_turn
  -> outbound/return
```

真实嵌套关系是：`prompt_render`、`before_step` 和 `after_step` 位于 reasoner 内部；其余 phase 位于 passive turn pipeline 外层。

### 3.2 关键源码

- `../akashic-agent/agent/core/passive_turn.py`：完整 phase 调用顺序、abort、commit 与 dispatch 边界。
- `../akashic-agent/agent/lifecycle/phase.py`：`PhaseFrame`、module chain、slot 校验与拓扑排序。
- `../akashic-agent/agent/lifecycle/types.py`：每个 phase 的 typed context。
- `../akashic-agent/agent/lifecycle/facade.py`：插件面向的稳定注册入口。
- `../akashic-agent/agent/lifecycle/phases/before_turn.py`：session/context 准备、Gate emit、abort exports。
- `../akashic-agent/agent/lifecycle/phases/prompt_render.py`：Prompt ctx、section/hint exports 与最终渲染。
- `../akashic-agent/agent/lifecycle/phases/after_turn.py`：`TurnCommitted`、AfterTurn fanout 与 dispatch 顺序。
- `../akashic-agent/bus/event_bus.py`：Gate `emit` 与 Tap `fanout` 的不同语义。

### 3.3 Gate 与 Tap

Gate 使用有序 `emit`：handler 可以返回修改后的 context，后一个 handler 看到前一个 handler 的结果。Gate 适用于需要影响后续执行的 phase，如 `before_turn`、`prompt_render`。

Tap 使用 `fanout`：观察者并发执行，单个观察者异常会记录但不阻断主流程。Tap 适用于已形成事实后的观察阶段，如 `after_turn`。

本课必须强调：Gate/Tap 是控制流语义，不是“before/after”的命名习惯。`after_reasoning` 仍是 Gate，因为它可以修改 reply、media 与 outbound metadata。

### 3.4 三个重点 phase

`before_turn`：

- 输入：`TurnState`，包含 inbound message、session key 与 dispatch intent。
- 内建模块：获取 session、准备 context bundle、构造 `BeforeTurnCtx`、Gate emit、收集 exports、返回 context。
- 可变结果：skills、extra hints、extra metadata、abort 与 abort reply。

`prompt_render`：

- 输入：当前消息、history、skills、retrieved memory、disabled sections 等渲染材料。
- Gate 可追加 top/bottom system sections 和 extra hints。
- 最终仍由 `ContextBuilder.render()` 统一完成 prompt assembly。

`after_turn`：

- 在 after-reasoning 已持久化 user/assistant 并构建 outbound 后运行。
- 先构造并 fanout `TurnCommitted`，再构造 `AfterTurnCtx` 并 fanout，最后 dispatch。
- `AfterTurnCtx.will_dispatch` 是发送意图快照；handler 运行时尚未真正 dispatch。

### 3.5 测试阅读路线

- `tests/test_lifecycle_phase.py`：module 顺序、输出要求、slot 依赖、循环依赖。
- `tests/test_lifecycle_phases.py`：before-turn abort、prompt section 注入、after-turn telemetry 与 commit 顺序。
- `tests/test_turn_pipelines.py`：lifecycle 在真实 passive pipeline 中的接线结果。

## 4. 方案选择

采用“现有 EventBus + typed lifecycle facade”的渐进方案。

### 方案 A：typed facade over EventBus（采用）

- 新增三个 typed context。
- 新增 `TurnLifecycle`，提供三个语义化注册方法。
- Gate 复用有序事件链，Tap 复用失败隔离 fanout。
- `PassiveRuntime` 只依赖 lifecycle facade，不感知具体插件。

优点：对齐 Akashic 的接口和控制流边界；复用现有 EventBus；不会提前引入 Lesson 21 的 slot 模型。

代价：Lesson 21 引入 `PhaseFrame/requires/produces` 时，内部执行模型仍会升级，但本课的 typed context 和 facade 可以保留。

### 方案 B：Runtime callback lists（不采用）

直接在 `PassiveRuntime` 保存三组 callback。代码最少，但 callback 所有权、错误策略和注册接口都会成为临时设计，后续 plugin manager 必须重写。

### 方案 C：完整 PhaseFrame（不采用）

一次迁移 module、slot、requires/produces、topological sort。对齐度最高，但提前吞并 Lesson 20–21，且在没有 plugin registry 时难以证明这些抽象的必要性。

## 5. Part 2：Amadeus 最小复现边界

### 5.1 组件

计划新增：

- `amadeus/lifecycle.py::BeforeTurnContext`：包含 session key、当前消息、history、retrieved memory、active skills 与 runtime metadata 的可修改输入准备结果。
- `amadeus/lifecycle.py::PromptRenderContext`：包含 attempt index/name 与本次独立 `RuntimeContext` 的可修改渲染输入。
- `amadeus/lifecycle.py::AfterTurnContext`：包含最终 message IDs、reply、tool chain 与 context-retry 摘要的冻结观察快照。
- `amadeus/lifecycle.py::TurnLifecycle`：提供 `on_before_turn()`、`on_prompt_render()`、`on_after_turn()`，并委托 EventBus 执行 Gate/Tap。
- `amadeus/events.py::EventBus.fanout()`：并发执行观察者并隔离单个观察者异常；现有 `emit()` 继续承担有序 Gate。

### 5.2 接入位置

`before_turn`：session/history/memory context 已准备后、构造 tool schema 和 prompt retry 之前运行。它可以修改 active skills、runtime metadata 与 retrieved memory。本课只讲解 Akashic 的 abort 语义，不在 Amadeus 生产接口复现 abort：当前 `PassiveTurnResult` 要求真实 user/assistant message IDs，强行中止会迫使实现制造空 ID 或改变持久化语义。abort 留作后续 outbound/result contract 切片。

`prompt_render`：每个 context-trim attempt 构造 `RuntimeContext` 后、调用 `ContextBuilder.render()` 前运行。这样 handler 的修改会参与本次真实 render，同时每次 retry 都重新得到与当前 disabled sections/history window 一致的 context。

`after_turn`：user/assistant 持久化和 `TurnCommitted` emit 完成后、返回 `PassiveTurnResult` 前运行。它是 Tap，只观察稳定快照；单个 observer 失败不得把已成功的回复改成失败。

### 5.3 不提前实现的能力

- `before_reasoning`、`before_step`、`after_step`、`after_reasoning`：保留完整 phase map，分配到 Lesson 20–23 或阶段 gap audit。
- `PhaseFrame`、slot、requires/produces、topological sort：Lesson 21。
- plugin registry、loader、config：Lesson 20。
- prompt section plugin exports：Lesson 22。Lesson 19 的 prompt-render context 只建立稳定 seam。
- tool hook/plugin failure isolation：Lesson 23。
- before-turn abort 与统一 control-outbound/result contract：后续 outbound 边界课程或 Lesson 23 gap audit 决定落点；Lesson 19 不制造空 message ID。
- tool visibility、deferred tools、tool_search、skill catalog、MCP boundary：Lesson 19–23 持续审计，Lesson 23 必须给出明确落点。

## 6. 数据流

```text
session/history/memory prepare
  -> BeforeTurnContext
  -> ordered Gate handlers
  -> tool schema + retry plan
  -> RuntimeContext per attempt
  -> PromptRenderContext
  -> ordered Gate handlers
  -> ContextBuilder.render
  -> provider/tool loop
  -> parse + persist
  -> TurnCommitted
  -> AfterTurnContext
  -> isolated Tap observers
  -> PassiveTurnResult
```

Lifecycle context 只暴露该 phase 合理拥有的数据，不能把整个 `PassiveRuntime` 或 store 实例交给 handler。这样插件不需要 import 主 loop 内部实现。

## 7. 错误与兼容边界

- Gate handler 异常属于前置控制流失败，本课直接向 `run_turn()` 调用方传播；不能静默吞掉并继续使用半修改 context。统一用户可见错误回复不在本课新增。
- Tap observer 异常必须隔离并记录，不能改变已持久化的回复结果。
- 没有注册 handler 时，现有 runtime 行为、prompt 内容、持久化与事件顺序必须保持不变。
- context-length retry 每次都经过 `prompt_render`，handler 不得跨 attempt 复用可变 context 导致 section 重复累积。
- lifecycle 不取代现有 tool hooks；turn phase 与 tool execution phase 是不同层次。

## 8. 验证设计

Part 2 至少需要以下测试：

1. 无 handler 时现有 passive turn 行为不变。
2. before-turn Gate 按注册顺序看到前一 handler 的修改。
3. prompt-render Gate 的修改进入 provider 收到的 messages。
4. context-length retry 为每个 attempt 创建独立 prompt context，不重复积累修改。
5. after-turn Tap 在 commit 后执行，并看到最终 message IDs、reply、tool chain/context retry 摘要。
6. after-turn observer 异常不影响成功返回。
7. 三阶段真实顺序 trace 为 `before_turn -> prompt_render -> commit -> after_turn`。

阶段结束运行 focused tests、全量 pytest、ruff、mypy，并提供命令、观察字段、通过条件与实际结果。

## 9. Coverage / Gap Audit

本课覆盖：

- Akashic 完整七 phase 认知地图；
- Gate/Tap 控制流语义；
- before-turn、prompt-render、after-turn 三个稳定 seam；
- 最小跨阶段顺序与失败路径测试。

本课不覆盖但仍属于 Akashic 关键机制：

- 其余四个 phase；
- PhaseFrame/slot dependency；
- plugin manager/registry/config；
- prompt section plugin；
- tool discovery/visibility；
- 完整 failure isolation 与 health reporting。

后续落点：Lesson 20–23；未完成项必须在 Lesson 23 gap audit 明确是否推迟到 Lesson 40 后扩展。

## 10. Eval Seeds

- 两个 before-turn Gate 依次修改同一字段，后注册者必须看到前者结果。
- prompt-render handler 加入标记，首次 provider payload 和 trim retry payload 各出现一次。
- after-turn observer 抛异常，回复仍持久化且 `PassiveTurnResult` 正常返回。
- 无 lifecycle handler 的基线 payload 与改造前一致。
- tool visibility 在 Lesson 19 不实现，但 trace/gap audit 必须明确它不是 lifecycle hook 的同义词。

## 11. 教学产物

- 新建 `lessons/0015-lesson-19-lifecycle-phase-model-part-1.html`。
- 标题明确标注“对应总计划 Lesson 19 / Part 1”。
- 包含当前阶段地图、完整 phase map、三个重点 phase、Gate/Tap、关键源码、测试阅读、常见误区、Coverage / Gap Audit、eval seeds 和必须复述问题。
- 用户能复述 Akashic 主链前，不创建 Part 2 实现，不新增 Lesson 19 learning record。
