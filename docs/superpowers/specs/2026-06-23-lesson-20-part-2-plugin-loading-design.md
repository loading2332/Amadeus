# Lesson 20 Part 2：Plugin Registry、Loader 与 Config 复现设计

## 1. 目标

在 Amadeus 中复现 Akashic Plugin System 的最小纵向切片：插件从官方或用户目录被发现，经动态导入、注册、配置、依赖注入、Lifecycle 绑定和异步初始化后，成为可参与真实 passive turn 的运行时对象。

本课迁移 Akashic 的核心接口、数据流和生命周期边界，同时修复参考实现中已确认的原子清理与跨插件 priority 缺口。实现完成后，一个用户插件必须能够在不修改 `PassiveRuntime` 的前提下，通过 Lesson 19 的 Lifecycle seam 修改实际 provider prompt。

## 2. Akashic 事实边界

参考实现：

- `../akashic-agent/agent/plugins/base.py`
- `../akashic-agent/agent/plugins/config.py`
- `../akashic-agent/agent/plugins/context.py`
- `../akashic-agent/agent/plugins/decorators.py`
- `../akashic-agent/agent/plugins/manager.py`
- `../akashic-agent/agent/plugins/registry.py`
- `../akashic-agent/bus/event_bus.py`
- `../akashic-agent/bootstrap/tools.py`
- `../akashic-agent/bootstrap/app.py`
- `../akashic-agent/tests/test_plugin_manager.py`
- `../akashic-agent/tests/fixtures/plugins/`

Akashic 的真实主链是：

```text
discover
→ dynamic import
→ decorator / __init_subclass__ registration
→ instantiate
→ manifest / config
→ PluginContext injection
→ bind / collect
→ initialize
→ _loaded commit
```

Akashic 当前还存在以下已确认缺口：

- initialize 失败或 terminate 后，绑定到共享 EventBus 的 handler 没有被精确注销。
- 导入或初始化失败后，动态模块可能残留在 `sys.modules`。
- Registry 虽按 metadata priority 排序，但 Manager 逐插件绑定，跨插件 priority 实际受加载顺序支配。
- 同一 `plugin.py` 定义多个 Plugin 子类时，后注册的 class 静默覆盖前一个。
- 最终 `plugin_id` 没有全局唯一性检查。
- PluginKVStore 是无锁的整文件 JSON 读写，不保证并发更新或崩溃时的原子写入。

Amadeus 继承其职责分层和加载链，但不会复制上述可验证缺陷。

## 3. 当前 Amadeus 状态

仓库中已有一版未提交的 Plugin 垂直切片：

- `amadeus/plugin/base.py`
- `amadeus/plugin/decorators.py`
- `amadeus/plugin/registry.py`
- `amadeus/plugin/manager.py`
- `tests/test_plugin_manager.py`
- `tests/fixtures/plugins/`

该版本已覆盖基础 discovery、动态导入、class/instance/handler registry、Lifecycle 绑定、配置合并和 initialize 隔离，聚焦测试当前通过。但它仍有以下偏差：

- 使用 `.disabled`，而 Akashic 合同是 `plugin.disabled`。
- `_conf_schema.json` 使用 `properties` 包装，而 Akashic 使用顶层字段定义。
- config 永远是原始 `dict`，没有 `PluginConfig | None` 语义。
- 未实现 `manifest.yaml`。
- `PluginContext` 只包含 identity、路径和 config。
- initialize 失败仅清 Registry，没有清 EventBus 或 `sys.modules`。
- `_loaded` 使用目录名，而 Registry 使用 import path。
- priority metadata 尚未真正影响 EventBus 顺序。
- 尚未接入 `PassiveApp` 启停和真实 passive turn。

Part 2 将重构这版未提交代码以符合本设计，不在偏差上继续叠加补丁。

## 4. 目录模型与信任边界

插件目录按以下顺序扫描：

```text
amadeus/builtin_plugins/       # 官方插件
<workspace_root>/plugins/      # 用户插件
```

`amadeus/builtin_plugins` 位于 Python package 内，保证安装后仍可随 Amadeus 分发。Lesson 20 只建立目录和加载能力，不发布无实际业务价值的示例官方插件。

discovery 采用 Akashic 的 first-wins 语义：

- 目录列表按声明顺序处理。
- 单个目录内按子目录名排序。
- 相同子目录名只接受第一次发现的候选项。
- 官方目录先于用户目录，因此官方插件不能被同名用户插件覆盖。
- 重复候选写入结构化报告和 warning，但不执行被跳过插件的 `plugin.py`。

用户插件默认自动加载；存在 `plugin.disabled` 时跳过。插件代码拥有普通 Python 代码的全部权限，`PluginContext` 也是依赖容器而非权限沙箱。Lesson、日志和开发文档必须明确：只能加载受信任的插件目录。

## 5. 核心对象

### 5.1 PluginCandidate

discovery 输出稳定的候选描述，至少包含：

- `name`：插件目录名，用于发现冲突和人类可读日志。
- `source`：`builtin` 或 `workspace`。
- `plugin_dir`：插件目录的绝对 Path。
- `module_path`：入口 `plugin.py` 的绝对 Path。
- `import_path`：动态模块和 Manager 内部唯一身份。

候选描述不导入或执行插件代码。

### 5.2 PluginRegistry

Registry 保存：

- import 时由 decorator 写入的 handler metadata。
- import 时由 `Plugin.__init_subclass__()` 写入的 Plugin classes。
- instantiate 后由 Manager 写入的 Plugin instance。

同一 import path 必须且只能注册一个 Plugin class：

- 0 个：加载失败。
- 1 个：继续加载。
- 2 个及以上：合同错误，加载失败并完整回滚。

Registry 不扫描磁盘、不解析配置、不调用 initialize，也不直接驱动 Lifecycle。

### 5.3 PluginConfig

`PluginConfig` 复制输入字典，并仅暴露：

- `get(key, default)`
- `as_dict()`，返回副本
- 属性读取，例如 `config.api_key`

没有 `_conf_schema.json` 时，`PluginContext.config` 为 `None`。有合法 schema 时，即使最终值为空，也返回 `PluginConfig`。这保留“插件没有声明配置”和“插件声明了空配置”的语义差异。

### 5.4 PluginContext

Manager 在实例化和配置后注入完整 Context：

- `event_bus`
- `tool_registry`
- `plugin_id`
- `plugin_dir`
- `kv_store`
- `config`
- `workspace`
- `session_manager`
- `memory_engine`

Context 在 handler 绑定和 initialize 之前完成注入。插件通过 Context 使用宿主提供的真实依赖，而不是自行 import bootstrap 全局对象。

### 5.5 PluginKVStore

每个插件得到绑定到 `<plugin_dir>/.kv.json` 的独立 KVStore，提供：

- `get(key, default)`
- `set(key, value)`
- `increment(key, delta=1)`

本课复现 Akashic 的低频整文件 JSON 语义，不宣称并发安全或崩溃原子性。配置与状态必须分开：`PluginConfig` 表达用户期望，PluginKVStore 保存插件运行状态。

### 5.6 PluginLoadReport

`load_all()` 不因单个插件失败而抛出聚合异常，而是返回结构化报告。报告必须能区分：

- `loaded`
- `disabled`
- `duplicate`
- `already_loaded`
- `failed`

失败记录至少包含 candidate identity、失败阶段和安全错误摘要。详细 traceback 进入日志；报告和普通日志不得包含 config 值、API key 或其他 secret。

## 6. 配置合同

Lesson 20 引入运行依赖 `PyYAML`，使用 `yaml.safe_load()` 读取 `manifest.yaml`。

### 6.1 manifest.yaml

manifest 只覆盖：

- `name`
- `version`
- `desc`
- `author`

字段存在且非 `None` 时转换为字符串并覆盖 class 属性。缺失或损坏 manifest 时记录 warning，继续使用 class 属性。

最终 `plugin_id` 为 manifest/class 的非空 `name`，否则退回目录名。成功加载的 plugin_id 必须唯一；冲突候选完整回滚并进入 failed 报告。内部加载、Registry 和 cleanup 始终使用 import path，不使用可变的展示名称。

### 6.2 _conf_schema.json

schema 严格采用 Akashic 的顶层字段合同：

```json
{
  "api_key": {"type": "string", "default": ""},
  "max_results": {"type": "number", "default": 10}
}
```

本课只提取每个字段的 `default`，不验证 type、required 或未知键。

### 6.3 plugin_config.json

用户配置是顶层对象，同名键覆盖 schema default，未覆盖字段保留默认值。当前实现允许额外键，不执行 schema validation。

### 6.4 Fail-open 与 fail-closed

外围配置采用 fail-open：

- manifest 损坏：保留 class 元信息。
- schema 损坏：`config=None`。
- override 损坏：保留 schema 默认值。

可执行链采用 fail-closed：

- import 失败。
- Plugin class 数量不合法。
- 实例化失败。
- plugin_id 冲突。
- bind 失败。
- initialize 失败。

必需配置由插件在 initialize 中验证。插件主动拒绝初始化时，Manager 将其视为该插件加载失败并完整回滚。

## 7. 加载事务与状态提交

Manager 内部唯一身份是 import path。一个候选项的加载事务为：

```text
disabled / already-loaded check
→ dynamic import
→ validate exactly one Plugin class
→ instantiate
→ apply manifest
→ validate unique plugin_id
→ load PluginConfig
→ inject PluginContext + PluginKVStore
→ register instance
→ bind decorator-declared Lifecycle handlers
→ initialize
→ commit import_path and plugin_id to loaded state
```

只有 initialize 成功后才能提交 `_loaded` 和 plugin_id ownership。单个插件失败不阻止其他插件加载；Lesson 20 中所有插件均为可选扩展。必需插件和依赖图语义留给 Lesson 21 的 `requires / produces / slots`。

## 8. 原子清理与 handler 所有权

失败回滚、正常 `aclose()` 和未来显式 unload 复用同一个 `_cleanup_plugin()` 路径。清理顺序为：

```text
best-effort await instance.terminate()
→ 精确注销该插件的 EventBus bindings
→ 清理 Registry class / instance / metadata
→ 从 sys.modules 移除动态模块及其动态子模块
→ 清理 _loaded 和 plugin_id ownership
```

`terminate()` 抛错只记录日志，不能阻断其余宿主状态清理。

Manager 必须保存每个 import path 实际注册到 EventBus 的 `(event_type, exact_handler)` binding ledger。不能重新创建 `functools.partial` 后尝试删除，也不能清空整个 event type，因为共享 EventBus 同时拥有核心 handler 和其他插件 handler。

所有插件收到同一个共享 EventBus：

- decorator 声明的 Lifecycle handler 由 Manager 注册并自动清理。
- 插件在 initialize 中直接调用 `context.event_bus.on()` 建立的额外订阅由插件自己拥有，必须在 terminate 中注销。

“原子”只覆盖宿主管理的 Registry、EventBus、动态模块和 Manager 状态。插件导入顶层代码或 initialize 产生的任意外部副作用无法被宿主自动撤销；这也是插件必须受信任、terminate 必须可清理资源的原因。

## 9. EventBus priority 与 off

Amadeus EventBus 增加：

- `on(event_type, handler, *, priority=0)`
- `off(event_type, handler)`

执行顺序为：

- priority 数值更高者先执行。
- priority 相同时保持注册顺序。

Manager 绑定 decorator metadata 时把 `metadata.priority` 传给 EventBus。这是对 Akashic 意图的忠实复现，同时修复其跨插件 priority 受逐插件绑定顺序支配的缺口。

`off()` 只移除传入的精确 handler 对象；不存在时安全返回。正常 emit/fanout 的 Gate/Tap 语义保持 Lesson 19 合同不变。

## 10. 应用生命周期与 bootstrap

`build_passive_app()` 保持同步和纯 composition：

- 初始化 workspace。
- 创建共享依赖。
- 创建官方目录和用户目录对应的 PluginManager。
- 返回尚未启动的 PassiveApp。

PassiveApp 增加显式异步生命周期：

```text
NEW → STARTED → CLOSED
```

规则：

- NEW + `start()`：加载插件，成功后进入 STARTED。
- STARTED + `start()`：幂等返回。
- NEW/STARTED + `aclose()`：终止插件并关闭 Session Store，进入 CLOSED。
- CLOSED + `aclose()`：幂等返回。
- CLOSED + `start()`：明确报错；关闭后的 App 不可复活。

`start()` 与 `aclose()` 共享异步锁，顺序和并发重复调用均不得重复 initialize、绑定、terminate 或关闭资源。只有完整 start 成功后才提交 STARTED；非插件级的意外启动异常必须 best-effort 清理已加载插件。

当前单轮 CLI 只是对话效果测试适配器：

```python
app = build_passive_app(...)
await app.start()
try:
    result = await app.runtime.run_turn(...)
finally:
    await app.aclose()
```

本课不新增 `PassiveApp.run_turn()`。未来接入长期运行的 channel bot 时，再建立与 Akashic `AkashicApp.run()` 对应的顶层 orchestration。

## 11. 验证设计

### 11.1 Discovery 与 identity

- 官方目录先于用户目录。
- 同目录名 first-wins，后续候选不执行。
- `plugin.disabled` 在 import 前阻止执行。
- import path 作为幂等与 cleanup identity。
- manifest/class name 形成最终 plugin_id。
- plugin_id 冲突只失败后加载候选，不污染已加载插件。

### 11.2 Registration 与 order

- 0 个 Plugin class 失败。
- 1 个 Plugin class 成功。
- 多个 Plugin class 失败，无 last-class-wins。
- decorator metadata 与 class 通过 import path 对齐。
- 跨插件高 priority 先执行，同 priority 保持注册顺序。
- 精确 off 不影响其他插件或核心 handler。

### 11.3 Config、Context 与 KV

- manifest 覆盖 name/version/desc/author。
- 无 manifest 使用 class 属性。
- schema 顶层 default 被提取。
- user override 覆盖同名 default，保留其余 default。
- 无 schema 时 config 为 None。
- 损坏 manifest/schema/override 按各自 fail-open 降级。
- PluginContext 注入的是 bootstrap 创建的同一组依赖。
- KV get/set/increment 在 App 重建后仍能读取之前状态。

### 11.4 Failure 与 cleanup

- import、实例化、bind、initialize 分别失败时无 Registry、EventBus、sys.modules、loaded 或 plugin_id 残留。
- initialize 部分执行后，Manager best-effort 调用 terminate。
- terminate 再失败不阻断宿主清理。
- 坏插件不阻塞好插件。
- 失败 handler 不会在后续 turn 成为幽灵 handler。
- `aclose()` 后插件 handler 不再触发。

### 11.5 Bootstrap 与真实 turn

- `build_passive_app()` 构造出共享 EventBus、PluginManager 和 Runtime，但不提前加载插件。
- 顺序与并发重复 `start()` 均只 initialize 一次。
- 顺序与并发重复 `aclose()` 均只 terminate 和关闭一次。
- 临时 workspace 用户插件经 `PassiveApp.start()` 加载。
- 插件通过 BeforeTurn 修改 `runtime_metadata`。
- 真实 `PassiveRuntime.run_turn()` 渲染后的 provider messages 包含插件标记。
- provider fake 仅用于隔离网络和 LLM nondeterminism，不进入生产架构。

### 11.6 工程验证命令

实现阶段至少执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_plugin_manager.py tests/test_lifecycle.py tests/test_bootstrap.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check amadeus tests dev_utils
.\.venv\Scripts\mypy.exe amadeus tests dev_utils
```

还需按真实 CLI 顺序验证：build → start → one turn → aclose，并明确查看插件加载报告、provider prompt marker、关闭日志和持久化文件。

## 12. Coverage / Gap Audit

本课覆盖：

- 官方和用户 plugin directory discovery。
- first-wins、disabled 和动态 import。
- Plugin class / instance / lifecycle metadata registry。
- manifest、PluginConfig、PluginContext 和 PluginKVStore。
- Lifecycle handler binding、priority 和精确 cleanup。
- initialize / terminate、加载事务与失败隔离。
- PassiveApp 显式异步生命周期。
- 用户插件影响真实 provider prompt 的 end-to-end eval seed。

本课明确不覆盖：

- `requires / produces / slots`：Lesson 21。
- prompt section plugin：Lesson 22。
- tool decorator、tool hook 和 plugin tool failure：Lesson 23。
- PluginKVStore 并发控制与崩溃原子写：Lesson 23 failure-isolation 收口。验收必须覆盖并发 increment 无丢失、异常写后 JSON 合法、多个插件 KV 隔离。
- plugin signature、allowlist 和 sandbox：Lesson 40 安全审计；届时必须明确迁移、拒绝或下一轮增强，不允许模糊写成“后续优化”。
- 长期运行 channel bot 和顶层 `App.run()`：后续 transport/channel 阶段。
- 热重载：当前无 Akashic 对齐需求，不进入 Lesson 20。

## 13. 简历可讲述版本

参考 Akashic 的 Plugin Registry / Manager 设计，在 Amadeus 中实现官方与用户插件的动态发现、配置注入、Lifecycle 绑定和异步启停。以 import path 统一 Registry 与加载事务身份，以结构化报告隔离单插件失败，并通过精确 EventBus 注销和 `sys.modules` 清理补齐参考实现的半加载残留问题；同时让 priority 在跨插件场景真正生效。最后通过真实 PassiveApp 启动和 provider prompt 捕获验证插件效果，而不是只断言 Registry 内部状态。

## 14. 实现顺序约束

实现必须按可复跑切片推进：

1. 收紧 Registry、PluginConfig、PluginContext 和 KV 类型合同。
2. 对齐 manifest/config/disabled/identity discovery 合同。
3. 为 EventBus 建立 priority 与精确 off。
4. 把 `_load_one()` 收口成可回滚加载事务。
5. 增加结构化 PluginLoadReport。
6. 接入官方/用户目录和 PassiveApp start/aclose。
7. 完成真实 turn eval、全量静态检查和 gap audit。
8. 生成正式 `lessons/0018-lesson-20-plugin-registry-loader-config-part-2.html`。

未经本 spec 复核确认，不进入实现。实现完成后必须先做代码精读和用户复述；只有用户能讲清加载事务、Context/KV、失败清理和 bootstrap 主链后，才创建 Lesson 20 learning record 并进入 Lesson 21。
