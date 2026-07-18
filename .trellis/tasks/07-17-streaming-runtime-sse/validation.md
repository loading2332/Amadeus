# 回答增量流式链路验收记录

## 公开行为结论

- Provider 在保留最终 `LLMResponse` 的同时立即发布普通文本增量；即使同一模型步骤稍后出现工具调用，先前文本也不会再被缓冲或丢弃。
- Runtime 只依赖 `TurnStreamSink`；同一次工具调用的 `started` 与 `completed/failed` 共享稳定 `activity_id`，消费端可以精确更新并折叠对应卡片。
- Worker 以 lease claim turn，按阈值写累计快照，心跳写入与取消只读检查分离，失败与取消均保留部分正文。
- PostgreSQL 保存单调 typed events；FastAPI 以 `after_seq` / `Last-Event-ID` 恢复 SSE，不持有执行状态。
- owner 边界覆盖时间线、状态、事件、取消与重试；越权与不存在统一 404。
- `failed/cancelled` 原 turn 不可变，重试创建带 `retry_of_turn_id` 的新 turn；终态不可取消或覆盖。
- stale lease 恢复先按消息 `turn_id` 对账，存在 assistant message 时收口为 done，否则为 `failed/interrupted`，不重新执行。
- SSE 发现终态后会先排空该轮已持久化的尾部事件再关闭，终态写入与轮询交错时不会漏发最终快照或 terminal event。
- 迁移在建立活跃唯一索引前收敛旧数据：遗留 processing 和重复 pending 变为可重试的 `failed/interrupted`，并保留安全 terminal event。
- `processing -> finalizing` 是取消/完成线性化点：此前已登记的取消获胜且不提交成功消息；进入后取消返回 409，成功提交继续收口。
- 流式产品协议不再区分“过程文本”和“最终回答文本”，也不需要 `answer_started`。累计 `content_snapshot` 与工具事件共享单调 `seq`；统一 reducer 可按新增文本后缀在工具事件两侧生成不同 text part。
- `done.answer` 保持 runtime 的最终回复；`partial_answer`/事件时间线允许保留工具调用前已经展示的普通文本，终态不会再用较短的最终回复覆盖它。

## R1-R27 映射

- R1-R8：`amadeus/provider.py`、`amadeus/runtime/reasoner.py`、`amadeus/runtime/passive.py` 与 provider/reasoner 测试。
- R9-R13：`amadeus/runtime/streaming.py`、`PersistedTurnStream`、工具边界和取消测试。
- R14-R20：turn store 活跃唯一索引、retry/timeline API 与 PostgreSQL/Web 测试。
- R21-R22：持久事件 SSE 与 `test_web_stream_cross_process.py` 的独立 API/worker 断线重连验收。
- R23-R27：lease/heartbeat、safe typed error、message `turn_id`、stale recovery 与竞态重校验测试。

## 验证命令与结果

```text
uv run ruff check amadeus tests migrations
结果：通过

uv run mypy amadeus
结果：通过，107 个源文件

uv run pytest tests/web/test_sse.py tests/turns/test_postgres_turn_store.py tests/worker/test_turn_worker.py tests/web/test_postgres_web_app.py tests/integration/test_web_stream_cross_process.py -q
结果：27 passed

uv run pytest tests/db/test_turn_streaming_migration.py tests/plugins/test_plugin_manager.py::test_initialize_failure_calls_terminate_and_terminate_error_does_not_leak tests/runtime/test_phase.py::test_phase_warns_when_data_slot_is_not_closed -q
结果：3 passed；证明程序化 Alembic 迁移不会关闭宿主进程 logger

.venv\Scripts\python.exe -m pytest -q
结果：634 passed，1 failed
```

全量唯一失败是本任务外既有基线：
`tests/evaluation/test_memory_retrieval_benchmark.py::test_approved_v1_is_formal_and_content_hash_is_frozen`
仍硬编码读取已归档任务的活动路径
`.trellis/tasks/07-11-memory-retrieval-parameter-evaluation/review/dataset-freeze.md`，抛出 `FileNotFoundError`。
本任务未修改该 benchmark，也未用跳过或复制历史文件掩盖问题。

Migration 已执行 `0005 -> 0004 -> 0005` 往返，并从 0004 注入重复 pending 与遗留 processing 验证升级收敛；最终 Alembic head 为 `20260718_0005`。

## 2026-07-18 交错文本/工具协议增量验证

```text
.venv\Scripts\python.exe -m pytest tests\runtime\test_reasoner_tool_loop.py -q
结果：9 passed

.venv\Scripts\python.exe -m pytest tests\app\test_provider.py tests\runtime\test_reasoner_tool_loop.py tests\turns\test_postgres_turn_store.py tests\worker\test_turn_worker.py tests\web\test_sse.py tests\web\test_postgres_web_app.py tests\integration\test_web_stream_cross_process.py -q
结果：42 passed，1 warning

.venv\Scripts\python.exe -m ruff check amadeus tests
结果：通过

.venv\Scripts\python.exe -m mypy amadeus
结果：通过，107 个源文件
```

新增回归明确证明：`text -> tool started -> tool completed -> text` 按序持久化；两个工具事件拥有相同 `activity_id`；worker 完成后保留工具前后的累计文本，而 `answer` 仍是 runtime 返回的最终回复。

## 未覆盖范围

- 未调用真实供应商网络；provider 流使用确定性 fake chunks，跨进程验收使用确定性 runner。
- React 渲染属于后续 `07-17-react-chat-client`；本任务已经交付前端可消费的交错 typed SSE 与时间线契约，但尚未实现“工具运行时展开、完成后自动折叠”的 React 组件和共享 reducer。
- 独立 provider thinking/reasoning channel 暂不伪装成普通文本；如果实际供应商提供且需要展示，应新增明确 typed part，而不是让前端猜字段。
