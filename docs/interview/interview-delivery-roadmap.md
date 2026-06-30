# 面试交付路线图

这份路线图的目标是：保留简历项目的交付速度，但不破坏架构顺序。不能在底层契约还没有验证之前，提前实现上层的简历亮点。

## 阶段 0：执行协议切换

- 把旧的教学型工作区提示词切换成面试交付模式。
- 保留 Akashic 作为只读参考实现。
- 把本路线图和 `resume-claim-gap-audit.md` 作为当前主动规划来源。

验收标准：

- 根目录提示词不再默认生成课程产物。
- 新任务都能映射到一条简历亮点和一条验证路径。

## 阶段 1：Akashic-style passive agent runtime ✅

Phase 1 实现了一个可面试展示的被动 agent runtime，包括：

| Issue | 交付物 | 验证 |
|-------|--------|------|
| 01 | Reasoner 独立边界：提取 provider/tool-loop 到 Reasoner，PassiveRuntime 保持 lifecycle orchestration | 300+ 测试，13 个 Reasoner 专用测试 |
| 02 | 文件工具集：read_file（offset/limit）、write_file、edit_file（exact-match+diff）、list_dir | 22 个文件工具测试 |
| 03 | Runtime filesystem hook policy：read/list 全 workspace、write/edit 仅 artifacts/ 子目录 | 双层防御验证 |
| 04 | 把多步 tool loop 完整移入 Reasoner，before_step/after_step 生命周期由 Reasoner 执行 | 多步工具链测试 |
| 05 | Tool loop guard：重复 tool signature 检测、max iteration guard、stop reason 记录 | 重复检测和上限测试 |
| 06 | CLI trace 模式：显示 session key、message IDs、tool chain、provider model/usage、sessions DB path | CLI trace formatting 测试 |
| 07 | 面试文档更新：resume-claim-gap-audit 和 roadmap 反映 Phase 1 完成状态 | 文档可读审查 |

验收标准：

- 能讲清楚 `输入 -> context -> Reasoner.reason() -> tool loop -> commit -> memory event`。
- 能展示文件工具 write -> read -> edit 的文件操作 trace。
- 有一条命令或测试证明端到端链路工作。
- 能解释 Reasoner 与 PassiveRuntime 的边界划分理由。

## 阶段 2：补强记忆系统

- 统一 retrieval trace 字段。
- 让 reinforcement 真正影响排序或注入选择。
- 只有在能确定性测试时，才加入 time decay。
- `source_ref` fetch 和 forget/supersede 是不能退让的核心契约。

验收标准：

- memory eval 覆盖 recall、source_ref fetch、correction、forgetting、fallback、context-frame injection。
- 简历措辞不能写尚未实现的 sqlite-vec、emotional_weight 等具体能力。

## 阶段 3：产品化 Evaluation

- 增加 eval case schema 和 runner。
- 输出人类可读报告和机器可读 JSON 结果。
- 覆盖 memory、retrieval、context isolation、tool loop、proactive decisions。
- 回归测试使用确定性 fake；集成验证可以额外使用真实 LLM smoke。

验收标准：

- Evaluation 能独立于普通单元测试运行。
- 失败报告能说明哪一个公开行为退化了，而不只是某个私有 helper 失败。

## 阶段 4：Telegram Outbound

- 在 Telegram adapter 之前先定义 `OutboundPort` 边界。
- 增加 Telegram adapter，支持 dry-run mode 和 real-send mode。
- 增加一个类似 `message_push` 的工具或 runtime service，统一走 outbound 边界。

验收标准：

- dry-run smoke 能证明消息可以被准备和记录。
- 配置凭据后可以做真实发送验证。
- 核心 runtime 不直接 import Telegram 具体实现。

## 阶段 5：Scheduler

- 增加 scheduled job model、JSON 或 SQLite store、fire-at parser、tick execution。
- 区分 instant jobs 和需要进入 agent/runtime 的 soft jobs。
- 先走 outbound dry-run，再在配置完整时接 Telegram。

验收标准：

- eval 或 smoke 覆盖 after/at/every、cancel、recovery、避免重复 in-flight execution。

## 阶段 6：ProactiveLoop

- 实现真实 pipeline：gate、DataGateway、LLM judge、resolve、outbound、ACK 或 dry-run trace。
- 第一版先使用本地 fixture sources：alert、content、context。
- memory/context 只能通过已有边界接入，不能直接读底层存储。

验收标准：

- proactive eval 覆盖 send、skip、duplicate suppression、no-content skip、source-bound message evidence。
- Telegram outbound 可以被使用，但 ProactiveLoop 不耦合 Telegram 内部实现。

## 阶段 7：DriftRunner

- 只在 ProactiveLoop 稳定之后增加可用 task runner。
- 第一版只做一个有价值的维护任务，例如 memory audit 或 proactive rule review。
- 必须有明确 finish state 和 trace。

验收标准：

- Drift 可以静默运行，或通过 outbound 边界产出一条 summary。
- 如果暂未实现，简历措辞必须保持为计划中或未来工作，不能写成已完成能力。
