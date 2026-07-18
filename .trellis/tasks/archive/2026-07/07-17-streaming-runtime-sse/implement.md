# 回答增量流式链路实施计划

## 1. 实施前置门

- [ ] `07-18-owner-scoped-web-identity` 已完成并通过其验证；本任务不得临时恢复客户端 `user_id`。
- [ ] 运行 `trellis-before-dev`，加载 backend、database、error-handling 与 cross-layer 规范。
- [ ] 确认工作树中的用户改动并只修改本任务相关文件。
- [ ] 重新检查 `../akashic-agent/agent/provider.py`、`agent/looping/core.py` 及相应测试，只迁移契约。

## 2. 数据模型与深模块

- [ ] 新增 Alembic migration：扩展 `conversation_turns`、建立活跃 turn partial unique index、建立 `conversation_turn_events`、加入消息 `turn_id` 幂等关联。
- [ ] 扩展 `Turn` 状态与 typed error；加入 `cancelled`、快照版本、lease、取消、重试关联字段。
- [ ] 将 store 接口按职责拆成稳定操作：创建/重试、claim/lease、快照/事件、取消、终态、时间线与中断对账。
- [ ] 所有状态变化使用条件更新或行锁；终态不可逆，写入必须校验 `lease_id`。
- [ ] 先完成 migration/store 单元与 PostgreSQL 集成测试。

风险点：当前 `conversation_turns` 的 user/session 是独立外键；owner task 的组合归属检查必须在进入 turn store 前完成。数据库活跃唯一索引上线前需确认不存在同会话多条未终态数据，并提供明确迁移处理。

## 3. Provider 流式能力

- [ ] 为 provider 定义可选、框架无关的普通文本 stream sink。
- [ ] 实现供应商 streaming chunk 累计：正文增量、工具调用分片、最终 usage/raw 兼容。
- [ ] 普通 text/content delta 到达即发布；删除“带 tools 时整轮缓冲，发现 tool call 后丢弃文本”的旧策略。
- [ ] 独立 thinking/reasoning channel 不伪装成普通文本；若未来展示，另立 typed part 能力。
- [ ] 保留无 sink 的非流式路径或提供等价兼容适配。
- [ ] 用确定性 fake chunks 覆盖正常流、工具调用、多 choice/空 delta、异常和最终一致性。

风险点：工具调用 JSON 可能跨多个 chunk，不能把分片当正文；异常前必须让 worker 有机会 flush 已累计正文。

## 4. Runtime 与工具生命周期

- [ ] 在 `Reasoner`/`PassiveRuntime.run_turn()` 贯穿可选 `TurnStreamSink`，不引入 Web/PostgreSQL 依赖。
- [ ] 工具执行边界发布白名单生命周期事件；确认工具参数、结果和推理不能进入事件对象。
- [ ] 定义内部取消异常并在 LLM 增量、工具步骤边界检查；取消不得进入 `_complete_turn()` 成功提交路径。
- [ ] 确保失败/取消不运行成功专属 after-reasoning 持久化或 after-turn memory；既有 after-turn failure isolation 保持。
- [ ] 给成功消息写入稳定 `turn_id` 并实现幂等提交/查询。
- [ ] 运行 runtime、reasoner、session history 聚焦测试。

风险点：现有 after-reasoning 先写 user/assistant message，worker 后写 turn done。必须先实现 `turn_id` 幂等关联与恢复对账，不能只靠异常捕获掩盖双写窗口。

## 5. Worker、批量持久化与恢复

- [ ] claim 时生成 `lease_id`，启动心跳/取消观察器。
- [ ] `PersistedTurnStream` 继续写 turn 级累计正文快照；工具事件前强制 flush，使单调 `seq` 足以让消费端从快照新增后缀切分 text part。
- [ ] 实现 `pending` 与 `processing` 取消路径，保证已完成工具副作用不被描述为回滚。
- [ ] 实现过期 lease 扫描：先对账已提交 assistant message；存在则 `done`，否则 `failed/interrupted`；禁止自动执行。
- [ ] 将原始异常留在结构化日志，把数据库/API 错误映射为安全 typed error。
- [ ] 覆盖 worker crash window、旧 lease 写入拒绝、终态后事件拒绝、同/跨 session 并发测试。

## 6. Web API 与 SSE

- [ ] 扩展 Pydantic schema：turn snapshot、typed event、typed error、timeline、cancel/retry response。
- [ ] 新增 turns 时间线、取消和重试端点；所有端点复用 `OwnerScope`，未知/越权统一 404。
- [ ] 重试事务复用原始输入与 session，写 `retry_of_turn_id`；只允许 `failed/cancelled`，活跃冲突返回 409。
- [ ] SSE 按 `after_seq`/`Last-Event-ID` 读取 PostgreSQL，发送单调 typed envelopes 与 keepalive；连接断开不取消 turn。
- [ ] SSE 保持累计 `content_snapshot`；共享 reducer 以快照新增后缀和工具事件 `seq` 恢复 `text -> tool -> text` 的原始顺序，并以对应工具 `activity_id` 驱动卡片完成后立即折叠。
- [ ] 终态后发送最后事件并关闭；累计快照由客户端替换而非拼接。
- [ ] 保留现有 messages/status 调用的兼容行为，更新旧静态前端测试中受契约变化影响的断言。

## 7. 验证顺序

按由窄到宽、数据库测试单进程串行执行：

```powershell
python -m pytest tests/turns -q
python -m pytest tests/runtime/test_reasoner_tool_loop.py tests/runtime/test_runtime.py -q
python -m pytest tests/worker -q
python -m pytest tests/web/test_postgres_web_app.py -q
python -m pytest tests/db tests/turns tests/worker tests/web -q
python -m ruff check amadeus tests
python -m mypy amadeus
python -m pytest tests -q
```

补充一个真实分进程 smoke：启动 PostgreSQL、FastAPI 与 worker，创建 turn 后在生成中断开 SSE，再按 cursor 重连，验证正文/工具事件恢复、终态一致；若缺少真实 LLM 配置，使用确定性 provider fixture 完成同等跨进程验证并明确未覆盖真实供应商网络。

## 8. 回滚点与完成条件

- 数据迁移、provider、runtime、worker、Web 每层独立通过聚焦测试后再进入下一层。
- 如果 provider stream 兼容性失败，可暂时保持可选非流式路径，但不得宣称流式任务完成。
- 如果 PostgreSQL 写放大超出阈值，先调大 flush 阈值并测量；不得绕过持久化改成 API 进程内状态。
- 完成时必须逐条映射 `prd.md` 的 R1-R27 与 acceptance criteria，并说明真实 LLM/跨进程 smoke 的覆盖范围。

## 9. 规划审批

- 状态：用户已于 2026-07-18 批准 PRD、技术设计与实施计划。
- 审批只允许后续进入 `task.py start`，不等于本轮已经实施。
