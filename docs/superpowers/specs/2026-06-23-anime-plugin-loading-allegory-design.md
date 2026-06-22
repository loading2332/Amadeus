# 二次元插件加载寓言设计

## 目标

用一个异世界魔法学院寓言，间接讲清 Akashic 中 Pipeline、Phase、Module、Lifecycle seam、Hook Point、Handler、Gate/Tap，以及 Hello 插件的 discover、import、decorator metadata 注册、`__init_subclass__` class 注册、实例化、配置注入、绑定、initialize 和实际触发。读者应在故事接近结尾时才逐渐意识到它描述的是插件系统。

## 故事结构

故事发生在一所依靠夜间结界保护城市的魔法学院。

1. 学院每晚执行一次完整结界仪式；仪式由多个章节组成，每章包含固定岗位和工序。
2. 某些章节中留有“暗门”，暗门本身不工作，只在召唤铃响起时允许已绑定的使魔介入；不同暗门遵守不同的修改和观察规则。
3. 管理官在社团区发现 `Hello` 社团的房间与入口卷轴。展开卷轴时，方法上的印记自动进入“术式名册”，社团继承的血统徽记自动把社团类型写入“血统名册”。
4. 管理官通过共同的卷轴来源标识，把术式与社团类型对应起来，然后创建使魔实例、读取身份与配置、发放运行权限，并将术式绑定到结界暗门。
5. 只有初始化成功后，`Hello` 才进入“已值勤名册”。加载过程不等于执行任务。
6. 当学生在真实仪式中说出“仁王怎么配装”时，结界运行到对应暗门，召唤铃响起，`Hello` 的术式才第一次真正执行。
7. 结尾揭示魔法学院各元素与真实代码概念的对应关系，并指出注册、实例化、绑定和执行是四个不同时间点。

## 隐喻映射

| 寓言元素 | 工程概念 |
|---|---|
| 一整夜的结界仪式 | Pipeline / 一次 turn |
| 仪式章节 | Phase |
| 固定岗位与工序 | Module |
| 结界暗门 | Lifecycle seam |
| 召唤铃 | Hook Point，即 `bus.emit()` / `fanout()` |
| 被绑定的使魔术式 | Handler |
| 允许依次改写仪式卷轴的暗门规则 | Gate |
| 只能观察并记录结果的暗门规则 | Tap |
| 社团区巡查 | `discover()` |
| 展开并执行入口卷轴 | dynamic import |
| 方法上的术式印记 | decorator 注册 handler metadata |
| 继承时出现的血统徽记 | `Plugin.__init_subclass__()` 注册 class |
| 两本名册 | handler/class Registry |
| 管理官 | PluginManager |
| 创建使魔 | Plugin instance |
| 身份卷轴、参数卷轴、私人日志 | manifest、config、KV store |
| 发放学院资源权限 | PluginContext 注入 |
| 把术式接到召唤铃 | handler 绑定并注册 EventBus |
| 值勤前检查 | `initialize()` |
| 已值勤名册 | `_loaded` |

## 叙事约束

- 故事主体不出现 Python、插件、Registry、Manager、Hook 等术语。
- 前半段不解释隐喻；读者只能通过重复的仪式规则形成直觉。
- `Hello` 被发现、登记和初始化时不得真正处理学生请求，以突出“加载不等于执行”。
- 直到真实仪式到达暗门，使魔术式才执行。
- 结尾后的解释必须贴回 Akashic 真实加载顺序，不能只给抽象词典。
- 风格为二次元轻小说，但避免过度卖萌和无关战斗，技术关系优先。

## 成功标准

读者读完后应能回答：

1. Phase 为什么不等于 Hook，Module 为什么通常也不是 Handler。
2. Seam、Hook Point、Handler、Gate/Tap 分别描述位置、触发方式、被调用函数和执行合同。
3. decorator 与 `__init_subclass__` 在 import 期间分别登记什么。
4. 为什么 class 注册、instance 创建、EventBus 绑定、handler 执行是四个不同时间点。
5. 为什么只有 initialize 成功后插件才进入 loaded 状态。
