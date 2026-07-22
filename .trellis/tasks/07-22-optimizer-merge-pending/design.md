# 定期合并待处理记忆：设计

## 边界与职责

- `MemoryOptimizer` 继续是唯一可修改 `PENDING.md` / `MEMORY.md` 合并事务的组件；循环只调用其公开的 `optimize()`。
- 新增 `MemoryOptimizerLoop`，只负责计算下一次时间边界、休眠、调用优化器以及记录“跳过/失败”。它不读取或写入记忆文件。
- `PassiveApp` 在插件成功加载后创建该循环任务，并在关闭 provider、数据库连接和会话存储之前停止并等待它。
- `amadeus.web.app.create_app()` 不承担该职责：它是 HTTP 入队端，既不运行 LLM turn，也不拥有 `PassiveApp` 生命周期。实际 worker 进程启动的 `PassiveApp` 才拥有循环。

## 配置契约

- `AMADEUS_MEMORY_OPTIMIZER_ENABLED`：布尔值，默认 `true`。
- `AMADEUS_MEMORY_OPTIMIZER_INTERVAL_SECONDS`：正整数，默认 `64800`。
- 这两个字段进入不可变 `RuntimeConfig`，并在 `.env.example` 中说明。

## 调度与关闭

`MemoryOptimizerLoop.run()` 依据当前墙上时间计算下一个区间边界，使用 `asyncio.sleep()` 等待；到点后调用一次 `optimizer.optimize()`，然后再次计算下一边界。

这使首次执行受真实时间影响，而非 Docker 启动时刻：比如容器在某个边界前 5 分钟启动，则约 5 分钟后执行；在运行中重启也只重新计算下一边界。未持久化“上次成功时间”，因此停机期间错过的周期不会在启动时补跑。

循环遇到 `MemoryOptimizerBusy` 只记录跳过；其他异常记录后继续。`CancelledError` 必须向上抛出，使 `PassiveApp.aclose()` 可以可靠地等待终止。关闭时先取消后台任务并 await，再关闭 provider，避免后台任务使用已关闭的客户端。

## 一致性与风险

`MemoryOptimizer` 的锁以及快照/提交/回滚语义维持不变：空输出或异常会恢复 pending 快照。该锁只覆盖单一 Python 进程；多 worker/多副本的分布式互斥不在本次范围内。

## 可观察行为

日志应分别表明循环启用、禁用、触发时跳过以及异常失败；不记录 `PENDING.md` 内容，避免将长期记忆写入日志。
