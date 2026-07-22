# 定期合并待处理记忆：实施计划

1. 在 `amadeus.memory.markdown` 增加可取消的 `MemoryOptimizerLoop`，并为时间计算提供可控注入点，复用 `MemoryOptimizer.optimize()`。
2. 扩展 `RuntimeConfig` 和 `load_runtime_config()`，解析优化器的启用开关与正整数周期；更新 `.env.example`。
3. 在 `PassiveApp.start()` 的插件装配成功后启动循环；在 `aclose()` 最先取消并等待该任务。
4. 增加/更新测试，覆盖：默认与覆写配置、客观时间边界计算、定时调用、禁用、异常后继续、关闭时取消等待。
5. 依次运行记忆模块与 bootstrap 的聚焦测试，随后运行 Ruff；如本地 PostgreSQL 可用，再执行共享运行时的相关测试。

## 回滚点

- 配置开关可将后台任务完全关闭。
- 若循环实现出现问题，可移除其在 `PassiveApp` 的启动调用；现有 `MemoryOptimizer` 手动调用路径与文件数据均不受影响。
