# Lesson 21 Part 2：Phase Slot Engine 设计

**状态：** 已完成对话设计，等待书面 spec 复核
**日期：** 2026-06-24
**参考实现：** `../akashic-agent/agent/lifecycle/phase.py`、`../akashic-agent/agent/lifecycle/phases/before_turn.py`、PluginManager 与 CoreRuntime 注入链

## 1. 目标与当前阶段

Lesson 19 已在 Amadeus 建立 typed lifecycle contexts、Gate/Tap seam 和 EventBus；Lesson 20 已建立插件发现、加载事务、配置、KV、handler ownership 与应用启停。Lesson 21 Part 1 已完成 Akashic `slot / requires / produces`、拓扑排序、plugin module 注入和失败边界的源码复述。

Part 2 只复现一条可运行的 `before_turn` 纵向切片：

```text
Plugin.before_turn_modules()
→ PluginManager 收集并持有成功插件的 modules
→ PassiveApp 注入 PassiveRuntime
→ default_before_turn_modules() 合并 built-ins + plugins
→ topo_sort_modules()
→ Phase 接收有序 modules、验证合同
→ Phase.run() 顺序执行
→ BeforeTurnContext 进入后续 prompt/tool 主链
```

完成后，workspace plugin 无需 import 或修改 `PassiveRuntime` 内部实现，只需通过稳定 phase 合同声明 module，即可在 before-turn 内部精确插入能力。

本课不提前实现 prompt section exports、tool-step phases 或 plugin failure isolation；这些缺口必须按第 11 节的 Gap Audit 在 Lesson 22–23 补回，不能以“后续优化”跳过并直接进入 Scheduler。

## 2. 采用方案与取舍

### 2.1 采用：通用 Phase Engine + before-turn 纵向切片

- 新建通用 Phase Engine，完整迁移 Akashic 的 frame、排序、缺失依赖禁用、闭合校验、执行与 inspection 思想。
- 将当前 `PassiveRuntime.run_turn()` 中 session/history/memory/before-turn context 的手写前置逻辑迁入 before-turn modules。
- 保留 `TurnLifecycle` 和 EventBus；`before_turn.emit` built-in module 调用现有 facade，保护 Lesson 19/20 handler 兼容性。
- PluginManager 新增 before-turn module contribution ownership；PassiveApp 在插件成功加载后把完整快照注入 runtime。

优点：第一课就有真实消费者、真实插件和真实 provider prompt 证据；不会产生一个只在单测里存在的排序工具。代价：需要同时调整 runtime、bootstrap 和 plugin ownership，但改动仍集中在 before-turn 一条链。

### 2.2 不采用：只实现排序引擎

代码少，但无法证明 plugin module 真正进入生产 turn，也无法验证 session/context 数据合同。它会把核心迁移问题推迟成下一次重构。

### 2.3 不采用：一次迁移全部七阶段

会提前吞并 Lesson 22 的 prompt exports 和 Lesson 23 的 tool-step/failure isolation，工作记忆和回归面过大，不符合一次一个 Akashic 对齐切片的协议。

## 3. 模块与 seam

### 3.1 通用深模块：`amadeus/phase.py`

公开接口：

```python
@dataclass
class PhaseFrame(Generic[I, O]):
    input: I
    slots: dict[str, Any]
    output: O | None

class PhaseModule(Protocol[F]):
    async def run(self, frame: F) -> F: ...

def topo_sort_modules(modules: Sequence[object]) -> list[object]: ...
def inspect_phase(modules: Sequence[object]) -> str: ...

class Phase(Generic[I, O, F]):
    def __init__(self, modules: Sequence[PhaseModule[F]], *, frame_factory: Callable[[I], F]): ...
    async def run(self, input: I) -> O: ...
```

调用者必须知道的接口合同：

- 每个参与排序的 module 必须有唯一且非空的 `slot: str`。
- `requires` 与 `produces` 是可选 tuple 类属性。
- module slot 参与拓扑排序；data slot 只参与闭合校验。
- `Phase` 接收已经排好序的列表；它不偷偷调用拓扑排序。
- module 异常向上传播；最终没有 output 时 Phase 抛错。

排序、递归禁用、图渲染和验证细节封装在该模块内，runtime 和 plugin manager 不复制算法。

### 3.2 Before-turn adapter：`amadeus/before_turn.py`

该模块定义：

- `BeforeTurnInput`
- 私有 `_BeforeTurnContextBundle`
- `BeforeTurnFrame`
- 五个 built-in modules
- `default_before_turn_modules()`

它把通用 Phase Engine 适配到 Amadeus 现有 SessionManager、MemoryEngine、TurnLifecycle 与 BeforeTurnContext，不在通用引擎中 import 这些业务类型。

### 3.3 保留的 seam

`TurnLifecycle` 继续作为 typed facade：

```text
_EmitBeforeTurnCtxModule.run()
→ TurnLifecycle.before_turn(ctx)
→ EventBus.emit(ctx)
→ decorator-declared handlers
```

EventBus priority 继续只负责同一个 emit 节点内部 handler 的稳定 tie-break；Phase 依赖图负责 modules 之间的因果顺序。Priority 不被删除，也不能伪装成 `requires`。

## 4. Before-turn 数据合同

### 4.1 输入与 bundle

`BeforeTurnInput` 保存 `run_turn()` 已有调用参数：

```python
@dataclass
class BeforeTurnInput:
    session_key: str
    user_message: str
    retrieved_memory: str | None
    active_skills: tuple[str, ...]
    runtime_metadata: dict[str, str]
```

调用方在创建 input 时把可选 list/dict 归一化为 tuple/dict，避免 modules 重复处理 `None`。

私有 `_BeforeTurnContextBundle` 保存：

```python
session: Session
history: tuple[Message, ...]
retrieved_memory: str | None
```

### 4.2 Data slots

```python
_SESSION_SLOT = "session:session"
_CONTEXT_BUNDLE_SLOT = "session:context_bundle"
_CTX_SLOT = "session:ctx"
```

### 4.3 五个 built-in modules

```text
before_turn.acquire_session
  requires ()
  produces session:session
  get_or_create session，并写入 frame.slots

before_turn.prepare_context
  requires before_turn.acquire_session + session:session
  produces session:context_bundle
  读取 history；只有 input 未提供 retrieved_memory 时才查询 MemoryEngine
  MemoryEngine 异常保持现有 fail-open 语义，resolved memory 为 None

before_turn.build_ctx
  requires before_turn.prepare_context + session:context_bundle
  produces session:ctx
  构造当前公开 BeforeTurnContext

before_turn.emit
  requires before_turn.build_ctx + session:ctx
  produces session:ctx
  通过 TurnLifecycle/EventBus 允许旧 handler 修改或替换 ctx

before_turn.return
  requires before_turn.emit + session:ctx
  设置 frame.output
```

`prepare_context` 与 `build_ctx` 在 `session:ctx` 已由前置 plugin module 产出时直接返回，以保留 Akashic 的 early-control 扩展能力；本课不新增 abort 字段或空 collector。

### 4.4 组装与拓扑排序位置

```python
def default_before_turn_modules(..., plugin_modules=None):
    builtins = [...]
    return topo_sort_modules(builtins + list(plugin_modules or []))
```

Runtime 的重建链：

```text
set_before_turn_plugin_modules(snapshot)
→ _build_before_turn_phase(candidate_modules)
→ default_before_turn_modules()
→ topo_sort_modules()
→ Phase(sorted_modules, frame_factory=BeforeTurnFrame)
→ 构建成功后再原子替换 runtime 当前 modules + phase
```

Amadeus 使用“完整快照替换”而不是 Akashic 的 append-only `add_*`。原因是 PassiveApp 已拥有完整 manager snapshot，替换接口可以避免重试重复注入，并能在关闭时释放 plugin module 引用；合并、拓扑排序和重建的核心数据流保持一致。该差异必须在 Part 2 lesson 中明确讲述。

## 5. 排序与验证语义

`topo_sort_modules()` 对齐 Akashic 当前行为：

1. 建立 `module.slot → module` 与原始顺序映射。
2. 无 slot 或重复 slot 立即抛 `RuntimeError`。
3. 递归禁用依赖缺失 module slot 的 plugin modules；built-in 不因缺失依赖静默禁用。
4. 只有存在于 `slot_map` 的 requires 才形成拓扑边；data slots 不形成边。
5. 每轮从零入度队列取 module；当前 tie-break 为 plugin 先于 built-in，同类按原始注册顺序。
6. 剩余非零入度节点表示循环依赖，抛出包含未解析 slots 的 `RuntimeError`。

`Phase._validate()` 按有序列表维护 `provided`：

- module dependency 尚未满足：warning。
- data slot 尚未 produced：`Phase slot 未闭合` warning。
- validation 不推断生产者、不重排、不自动禁用 data consumer。

本课为 plugin/built-in 零入度 tie-break 增加明确回归测试。Akashic 当前只有源码行为、没有独立测试；Amadeus 将它锁定为本切片合同，未来若改变必须显式改测试和 lesson。

## 6. Plugin module contribution 与所有权

### 6.1 Plugin 接口

`Plugin` 新增：

```python
def before_turn_modules(self) -> list[object]:
    return []
```

Plugin 可以从稳定的 `amadeus.phase`、`amadeus.before_turn` 和 `amadeus.lifecycle` import 合同类型；不得 import `PassiveRuntime` 私有实现。

### 6.2 PluginManager 事务

加载 candidate 时，在 bind 后、initialize 前调用 `before_turn_modules()`。返回值必须是 list；调用异常或类型错误属于 `phase_modules` 加载阶段失败。

Candidate modules 暂存在当前加载事务中：

```text
collect candidate modules
→ initialize
→ initialize 成功后，按 import_path 提交 owner ledger
→ loaded/load_order/plugin_id 同时提交
```

初始化失败时 candidate modules 从未进入已提交快照；cleanup、terminate 和 cancellation 都删除 owner ledger。`PluginManager.before_turn_modules` 按成功插件的 `_load_order` 返回新 list，调用方不能修改 manager 内部状态。

这与 Akashic“先追加、失败再切片回滚”在外部生命周期语义上等价，但更适合 Amadeus 已有的 per-plugin ownership ledger；差异必须在 Gap Audit 中标为“有意适配”，不是未完成机制。

## 7. Runtime 与 PassiveApp 生命周期

`PassiveRuntime.__init__()` 先以纯 built-ins 构建 before-turn Phase。

`PassiveRuntime.set_before_turn_plugin_modules(modules)`：

- 复制输入快照。
- 先构建 candidate sorted modules 与 candidate Phase。
- 构建成功后再替换当前状态。
- 构建失败时保留原 Phase，不留下半更新 modules。

`PassiveRuntime.run_turn()`：

```text
BeforeTurnInput
→ await self._before_turn.run(input)
→ 读取 BeforeTurnContext.history / retrieved_memory / active_skills / runtime_metadata
→ 原有 tool schema、prompt retry、reasoner、持久化主链
```

`PassiveApp.start()`：

```text
await plugin_manager.load_all()
→ runtime.set_before_turn_plugin_modules(manager.before_turn_modules)
→ 成功后提交 PluginLoadReport 与 STARTED
```

若 runtime 重建因重复 slot、环等失败，App 调用 `plugin_manager.terminate_all()`、恢复 runtime 为 built-ins、保持 NEW 并向上传播异常。

`PassiveApp.aclose()` 在终止 plugins 后恢复 runtime 的空 plugin snapshot，释放 plugin module 引用，然后关闭 session store；现有 cancellation-safe cleanup 语义必须保留。

## 8. 失败语义

| 情况 | 行为 |
|---|---|
| plugin module 依赖不存在的 module slot | warning；递归禁用该 plugin module 及其下游 plugin modules |
| data slot 未闭合 | warning；不推断、不排序、不禁用 |
| module 缺少 slot | runtime rebuild/start 抛错 |
| module slot 重复 | runtime rebuild/start 抛错 |
| 循环依赖 | runtime rebuild/start 抛错并列出 unresolved slots |
| module `run()` 异常 | Phase 向上传播；本课不引入 isolation |
| module 链无 output | Phase 抛错 |
| plugin `before_turn_modules()` 异常/非 list | 该 plugin 的加载事务失败并清理，不影响其他 candidate |
| plugin 初始化失败 | modules 不提交，现有 handler/tool/config/KV ownership 一并清理 |

Phase execution failure isolation 明确属于 Lesson 23；本课不得写 fake wrapper 吞掉异常。

## 9. 兼容性与公共接口

- 保留 `BeforeTurnContext`、`TurnLifecycle.on_before_turn()`、decorator handler 和 EventBus priority 行为。
- 保留 `PassiveRuntime.run_turn()` 的调用参数与 `PassiveTurnResult`。
- Session history、memory fail-open、prompt retry、tool execution 和持久化结果不得发生行为回归。
- 新公共接口为 `amadeus.phase` 的 frame/module/phase/inspection 合同、`amadeus.before_turn` 的 input/frame 合同，以及 `Plugin.before_turn_modules()`。
- 不新增第三方依赖，不修改 Akashic。

## 10. 测试与验收

### 10.1 Phase Engine

- modules 按有序列表运行并共享 slots。
- frame 透传、module 异常传播、无 output 报错。
- module dependency 拓扑排序。
- plugin 零入度先于 built-in；同类保持注册顺序。
- data slot 不形成拓扑边。
- 缺失 plugin module 依赖递归禁用。
- data slot 未闭合 warning。
- 无 slot、重复 slot、循环依赖拒绝。
- `inspect_phase()` 输出执行顺序与依赖树。

### 10.2 Before-turn

- session 被创建并通过 `session:session` 传递。
- history 与 supplied retrieved memory 进入 context bundle。
- 未 supplied memory 时调用 MemoryEngine；查询异常保持 fail-open。
- EventBus handler 可以原地修改或替换 `session:ctx`。
- plugin 提前产生 `session:ctx` 时普通 prepare/build 跳过。

### 10.3 Plugin ownership 与 App

- 成功插件 modules 按 load order 暴露。
- 初始化失败、collection 失败、terminate 和 cancellation 不残留 modules。
- repeated `start()` 不重复注入。
- phase rebuild 失败时 runtime 保留 built-ins、App 不提交 STARTED、plugins 完整清理。
- `aclose()` 释放 runtime 中的 plugin module 引用。

### 10.4 真实 E2E / eval seed

新增真实 workspace fixture plugin：贡献一个依赖 `before_turn.build_ctx + session:ctx` 的 module，写入 `BeforeTurnContext.runtime_metadata`。通过 `build_passive_app()`、`start()`、`run_turn()` 与真实 FakeProvider capture 证明该 metadata 进入最终 provider prompt；不能用绕过 PluginManager 的直接 module 注入代替此验收。

最终运行：

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check amadeus tests dev_utils
.venv\Scripts\python.exe -m mypy
```

并执行 CLI/smoke，检查成功输出、phase inspection、plugin load report 和错误日志。

## 11. Akashic Gap Audit 与补回计划

| Akashic 机制 | 本课状态 | 明确补回位置 | 不能偏离的边界 / eval |
|---|---|---|---|
| 通用 PhaseFrame/Phase/topo/validate/inspect | 完整复现 | 本课 | 所有后续 phase 复用同一深模块，不复制算法 |
| before-turn acquire/prepare/build/emit/return | 完整复现 | 本课 | 真实 session/history/memory/EventBus E2E |
| before-turn export collector、extra hints、abort | 暂未复现 | Lesson 23 Part 2C | prefix collector、control result 和 outbound 行为必须联合测试 |
| prompt_render Phase 与 section exports | 暂未复现 | Lesson 22 | plugin section 不得直接修改 ContextBuilder 私有实现 |
| before_reasoning Phase | 暂未复现 | Lesson 23 Part 2A | tool sync/context 输入输出合同 |
| before_step / after_step Phase | 暂未复现 | Lesson 23 Part 2B | 每个 tool iteration 的 Gate/Tap 与 telemetry eval |
| after_reasoning / after_turn Phase | 暂未复现 | Lesson 23 Part 2C | 持久化/outbound/commit 顺序与 tap isolation |
| tool hooks 与 plugin failure isolation | 暂未复现 | Lesson 23 Part 2D | deny/rewrite/post-hook 和主回复存活路径 |
| 七阶段联合图与 E2E | 暂未复现 | Lesson 23 结束验收 | 最终 Gap Audit 必须为零或产生单独批准的新 Lesson，不能静默进入 Lesson 24 |
| PluginManager candidate-local module commit | 有意适配 | 本课记录 | 外部 collect→initialize→commit/rollback 生命周期与 Akashic 等价 |
| Runtime snapshot replacement vs Akashic append | 有意适配 | 本课记录 | repeated start、cleanup 和 rebuild 原子性必须有测试 |

## 12. 教学交付与复述门禁

实现完成后创建 `lessons/0020-lesson-21-phase-slot-engine-part-2.html`，标题明确“对应总计划 Lesson 21 / Part 2”。课程继续遵守 `NOTES.md`：先用完整寓言间接呈现 Amadeus 迁移问题，接近结尾再揭示 module graph；随后沿真实调用链讲解：

```text
workspace plugin
→ PluginManager ownership
→ PassiveApp.start
→ PassiveRuntime phase rebuild
→ before-turn slots
→ provider prompt evidence
```

课程必须包含实现前后阶段地图、Akashic/Amadeus 对照、关键代码、失败路径、精确验证命令、Gap Audit、简历可讲述版本和必须复述问题。

本课实现完成不自动创建 learning record。只有用户能说明 Phase Engine、before-turn data flow、plugin ownership、原子 rebuild、验证方法和剩余 Gap 后，才新增 Lesson 21 learning record 并进入 Lesson 22。
