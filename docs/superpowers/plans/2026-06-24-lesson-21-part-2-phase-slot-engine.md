# Lesson 21 Part 2：Phase Slot Engine 实施计划

**Goal:** 在 Amadeus 中完成通用 Phase Engine 与 before-turn 纵向切片，让成功加载的 workspace plugin 可以声明 `before_turn_modules()`，经 PluginManager ownership、PassiveApp 注入、拓扑排序和 Phase 执行真实影响 provider prompt。

**Architecture:** `amadeus.phase` 隐藏排序、递归禁用、验证、inspection 与执行复杂度；`amadeus.before_turn` 适配 Session/Memory/Lifecycle；PluginManager 持有成功插件的 module 快照；PassiveRuntime 原子重建 before-turn Phase；EventBus priority 只保留在 emit module 内部。

**Tech Stack:** Python 3.11、asyncio、dataclasses、Protocol、pytest、ruff、mypy；不引入新依赖。

**Execution constraints:** 本计划按用户要求直接在当前工作区执行；不运行任何 Git 命令，不暂存、不提交、不切分支；保留现有未提交文件和用户注释。

**Approved design:** `docs/superpowers/specs/2026-06-24-lesson-21-part-2-phase-slot-engine-design.md`

---

## Task 1：通用 Phase Engine tracer bullet

**Create:**

- `amadeus/phase.py`
- `tests/test_phase.py`

### Cycle 1A：Phase 通过公开接口顺序执行

1. 写一个测试：三个公开 test modules 共享 `PhaseFrame.slots`，最终产生 output。
2. 运行 `python -m pytest tests/test_phase.py -q`，确认因 `amadeus.phase` 缺失而 RED。
3. 最小实现 `PhaseFrame`、`PhaseModule`、`Phase.run()`。
4. 重跑该测试，确认 GREEN。

### Cycle 1B：拓扑排序

逐项执行单测—实现循环：

- module dependency 决定顺序。
- data slot 不形成拓扑边。
- plugin/built-in 同为零入度时 plugin 先执行；同类保持输入顺序。
- 缺失 plugin module 依赖递归禁用并记录 warning。
- 无 slot、重复 slot、循环依赖抛明确错误。

实现 `topo_sort_modules()`、`_active_module_slots()` 与命名判定；不把排序放进 `Phase.__init__()`。

### Cycle 1C：验证与 inspection

逐项增加：

- data slot 未闭合 warning。
- module 异常传播。
- 最终无 output 报错。
- `inspect_phase()` 输出执行顺序、built-in/plugin 标记、requires/produces 和依赖树。

### Task 1 gate

```powershell
.venv\Scripts\python.exe -m pytest tests\test_phase.py -q
.venv\Scripts\python.exe -m ruff check amadeus\phase.py tests\test_phase.py
.venv\Scripts\python.exe -m mypy amadeus\phase.py
```

---

## Task 2：Before-turn adapter tracer bullet

**Create:**

- `amadeus/before_turn.py`
- `tests/test_before_turn.py`

**Modify:**

- `amadeus/__init__.py` only for approved public contracts

### Cycle 2A：纯 built-in 成功链

1. 通过 `default_before_turn_modules()` + `Phase` 的公开接口运行一次 before-turn。
2. 断言 Session 被创建、history 进入 context、supplied retrieved memory 原样保留、output 为 `BeforeTurnContext`。
3. 实现 `BeforeTurnInput`、`BeforeTurnFrame`、私有 bundle 与五个 modules。

### Cycle 2B：Memory 和 lifecycle 行为保持

逐项增加：

- 未 supplied memory 时调用 MemoryEngine；结果进入 context。
- MemoryEngine 异常 fail-open 为 `None`。
- EventBus handler 可原地修改 ctx。
- EventBus handler 可替换 ctx。
- plugin module 提前写 `session:ctx` 时 prepare/build 不覆盖。

### Cycle 2C：真实 slot inspection

断言 inspection 中包含五个 built-in slots、module/data requires 与确定执行顺序。

### Task 2 gate

```powershell
.venv\Scripts\python.exe -m pytest tests\test_before_turn.py tests\test_lifecycle.py -q
.venv\Scripts\python.exe -m ruff check amadeus\before_turn.py tests\test_before_turn.py
.venv\Scripts\python.exe -m mypy amadeus\before_turn.py
```

---

## Task 3：PassiveRuntime 原子 Phase 重建

**Modify:**

- `amadeus/runtime.py`
- `tests/test_runtime.py`

### Cycle 3A：run_turn 使用 before-turn Phase

1. 保留现有 `test_passive_runtime_applies_before_turn_and_prompt_render_gates` 作为兼容 tracer。
2. 增加可观察测试：before-turn plugin module 修改 ctx metadata，最终 provider capture 中出现该 metadata。
3. 将 session/history/memory/context 手写前置逻辑替换为 `await self._before_turn.run(BeforeTurnInput(...))`。

### Cycle 3B：原子 snapshot replacement

增加公开行为测试：

- `set_before_turn_plugin_modules()` 替换而非累加 snapshot。
- 重复设置同一 snapshot 不产生重复 module。
- candidate phase 因重复 slot/环构建失败时，原 phase 仍可运行。
- 设置空 snapshot 恢复纯 built-ins。

先完整构建 candidate modules + Phase，成功后再替换 runtime 字段。

### Task 3 gate

```powershell
.venv\Scripts\python.exe -m pytest tests\test_runtime.py tests\test_before_turn.py tests\test_lifecycle.py -q
.venv\Scripts\python.exe -m ruff check amadeus\runtime.py tests\test_runtime.py
.venv\Scripts\python.exe -m mypy amadeus\runtime.py
```

---

## Task 4：PluginManager module ownership

**Modify:**

- `amadeus/plugin/base.py`
- `amadeus/plugin/manager.py`
- `tests/test_plugin_manager.py`

### Cycle 4A：成功 plugin contribution

1. 动态写入真实 workspace plugin，实现 `before_turn_modules()`。
2. 通过 `PluginManager.load_all()` 加载。
3. 断言 `manager.before_turn_modules` 按成功 plugin load order 返回 module snapshot。
4. 新增 Plugin 默认空贡献与 manager owner ledger。

### Cycle 4B：事务失败与清理

逐项增加：

- `before_turn_modules()` 抛错：该 candidate 记录 `phase_modules` failed，其他 plugin 继续。
- 返回非 list：同样失败并清理。
- initialize 失败：candidate modules 不提交。
- terminate/cancellation：owner ledger 清空。
- 返回属性副本，外部修改不污染 manager。

模块收集发生在 bind 后、initialize 前；只有 initialize 成功才提交 owner ledger。

### Task 4 gate

```powershell
.venv\Scripts\python.exe -m pytest tests\test_plugin_manager.py -q
.venv\Scripts\python.exe -m ruff check amadeus\plugin tests\test_plugin_manager.py
.venv\Scripts\python.exe -m mypy amadeus\plugin
```

---

## Task 5：PassiveApp 启动事务与真实 E2E

**Modify:**

- `amadeus/bootstrap.py`
- existing bootstrap/plugin integration tests

**Add fixture:**

- workspace plugin fixture that contributes a real before-turn module

### Cycle 5A：start 注入与 idempotence

增加测试：

- `start()` load plugins 后把 manager snapshot 设置到 runtime。
- repeated `start()` 不重复注入。
- `aclose()` 清空 runtime plugin snapshot 并终止 plugins。

### Cycle 5B：phase rebuild failure rollback

通过两个真实 plugin modules 制造重复 slot：

- `start()` 抛错。
- App 保持 NEW。
- PluginManager loaded state/handlers/modules/sys.modules ownership 清空。
- Runtime 保持纯 built-ins 且仍能单独运行。

### Cycle 5C：真实 provider prompt eval

使用 `build_passive_app()`、workspace plugin、PluginManager、PassiveApp、PassiveRuntime 与现有 FakeClient：

```text
plugin module writes session:ctx.runtime_metadata
→ before_turn.return
→ RuntimeContext
→ ContextBuilder
→ provider captured messages
```

断言 marker 出现在 provider prompt；禁止绕过 PluginManager 直接注入 module。

### Task 5 gate

```powershell
.venv\Scripts\python.exe -m pytest tests\test_bootstrap.py tests\test_plugin_manager.py tests\test_runtime.py -q
```

若真实测试文件名不同，以现有包含 `PassiveApp` tests 的文件为准，不新建重复测试层。

---

## Task 6：正式 Teach 0020 与 Gap Audit

**Create:**

- `lessons/0020-lesson-21-phase-slot-engine-part-2.html`

### Lesson 内容

- 标题明确对应总计划 Lesson 21 / Part 2。
- 先用完整寓言间接呈现“固定流程如何接入外部队伍并保持原子排表”，接近结尾才揭示 Amadeus phase graph。
- 故事后映射真实调用链、接口、data slots、ownership 和失败语义。
- 展示实现前后阶段地图和 Akashic/Amadeus 差异。
- 展示真实 E2E 证据、精确命令、错误输出解释和 phase inspection。
- 写入批准 spec 的完整 Gap Audit 表；明确 Lesson 22/23 补回位置。
- 包含简历可讲述版本、必须复述问题和“自己重做第一步看哪里”。
- 不创建 learning record，等待用户完成 Part 2 复述。

### HTML gate

- HTMLParser 检查唯一 ID、页内锚点和本地资源。
- 检查 `../assets/lesson.css` 与 Python highlight 资源。
- 桌面与 390px 窄屏验证无页面级横向溢出。

---

## Task 7：最终质量门与要求审计

### 自动化验证

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check amadeus tests dev_utils
.venv\Scripts\python.exe -m mypy
```

### 行为审计

- 现有 lifecycle decorator handlers 顺序不变。
- EventBus priority 继续生效且只限 emit 内部。
- Session history、memory fail-open、prompt retry、tool loop、持久化均无回归。
- `inspect_phase()` 可复跑并显示真实 before-turn graph。
- E2E marker 通过真实 plugin load 进入 provider prompt。
- runtime rebuild、plugin load、close/cancellation 无半提交状态。

### Gap Audit 审计

- 本课只把通用 engine 和 before-turn 五模块标为已复现。
- before-turn collector/abort、prompt_render、before_reasoning、step phases、after phases、tool hooks/failure isolation 均保留批准的 Lesson 22/23 落点。
- 不把 priority 删除，不把空 collector、fake module 或临时 helper 写入生产架构。
- 未经用户 Part 2 代码精读与复述，不创建 Lesson 21 learning record，不进入 Lesson 22。

### 交付

报告：实现文件、调用链、测试结果、未覆盖风险、Gap Audit 和下一次用户复述入口。按用户要求不执行 Git 操作。
