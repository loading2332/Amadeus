# Akashic Memory System Design

日期：2026-07-01

## 1. 目标

本次重构把 Amadeus 现有的 `vector_memory` + `markdown memory` 组合，升级为更接近 Akashic 的完整记忆系统主链路，优先落地以下可证明能力：

- 被动 runtime 在 `before_turn` 自动检索并注入长期记忆；
- 记忆写入经过统一的 `memorizer` 生命周期，而不是散落在 tool、markdown consolidation、store 中；
- 支持显式 `memorize`、`recall_memory`、`forget_memory`、`undo_memory_by_source`；
- 支持 replacement graph，而不是只做单点 `correct_memory` 覆盖；
- 支持按 scope、类型、时间和热度进行检索与注入；
- 允许清空旧 `vector_memory.db`，迁移到新的长期记忆主库。

本轮明确不做：

- durability observation / retrieval trace 持久化；
- dashboard 或 inspect CLI；
- 主动 memory 写入策略扩展到 proactive loop；
- 为兼容旧 schema 保留 facade 翻译层。

## 2. 这次交付支撑的简历 claim

- `Akashic-inspired memory system with retrieval, source references, correction, and forgetting`
- `passive agent runtime that can run real LLM turns`

本次可观察行为：

- `before_turn` 自动拉取记忆并注入 prompt；
- 模型可通过 memory tools 显式查询、写入、遗忘、按消息来源撤销；
- 记忆返回稳定 `source_ref` / evidence，可继续用 `fetch_messages` 回源；
- 更正不再依赖单独的 `correct_memory` tool，而依赖 replacement/undo 语义。

Akashic 参考来源：

- `../akashic-agent/core/memory/engine.py`
- `../akashic-agent/plugins/default_memory/engine.py`
- `../akashic-agent/memory2/retriever.py`
- `../akashic-agent/tests/test_memory_undo.py`
- `../akashic-agent/tests/test_post_response_worker.py`

## 3. 当前问题

当前 Amadeus 已经有 passive memory 主链路，但边界仍偏 phase2 过渡态：

- `amadeus/memory/vector.py` 同时承担 schema、写入、纠错、检索、注入格式化；
- `correct_memory` 仍是单独工具能力，不是 replacement graph 的自然结果；
- markdown consolidation 会直接把内容灌进 vector store，缺少统一 memorizer；
- `before_turn` 只有一次简单 `query -> render_context_block`，没有 scope-aware retrieval 和类型优先级；
- 数据表缺少 Akashic 风格的 replacement、scope、procedure 元数据承载。

因此这次不做“补丁兼容”，而是直接把 memory public contract、schema、写入生命周期、retriever 责任一起重构。

## 4. 方案比较

### 方案 A：在现有 `VectorMemoryEngine` 上继续追加能力

优点：

- 改动面最小；
- 现有测试可部分复用。

缺点：

- `engine/store/retrieval/mutation/render` 会继续缠在一个文件里；
- 很难自然承接 replacement graph、undo by source、post-response worker；
- public contract 和真实内部能力会继续错位。

结论：不采用。

### 方案 B：原地分层重构为 Akashic 风格 memory stack

优点：

- 外部 runtime 仍在原仓库原路径下演进，不需要并行双栈；
- 内部边界可以清晰拆成 `store / retriever / memorizer / worker / engine-owned tools`；
- 能完整承接 Akashic 的 lifecycle 与数据模型。

缺点：

- 需要一次性调整较多测试和 tool contract；
- 旧数据库和部分旧 API 需要放弃。

结论：采用。

### 方案 C：影子实现一套新 memory stack，运行时双写双读后再切换

优点：

- 理论上切换风险最低。

缺点：

- 对当前单人仓库是过度工程；
- 双栈期间 schema、tool、测试都要维护两套；
- 不符合“尽量重构而不是为了节省而兼容”。

结论：不采用。

## 5. 目标架构

### 5.1 模块分层

新的 memory stack 分为五层：

1. `memory2 store`
   - 只负责 SQLite 持久化、schema 初始化、基础 CRUD、replacement 记录。
   - 不负责 ranking、injection、tool policy。

2. `memorizer`
   - 统一处理写入、去重、reinforcement、supersede、replacement、undo。
   - 所有长期记忆 mutation 都必须经过这里。

3. `retriever`
   - 负责 query planning、multi-lane retrieval、fusion、scope/time filtering、injection selection。
   - 输出 raw trace，但本轮不做 trace durability。

4. `post-response worker`
   - turn 结束后根据本轮 transcript、tool usage、显式记忆指令进行隐式记忆整理。
   - 是 Akashic 风格写入生命周期的一部分，但不承担存储策略本身。

5. `memory engine`
   - 对 runtime 和 tool registry 暴露统一 memory contract；
   - 组合 `store + retriever + memorizer + worker`；
   - 管理 memory-owned tools 的注册配置。

### 5.2 markdown memory 的位置

`SELF.md`、`MEMORY.md`、`HISTORY.md`、`PENDING.md`、`RECENT_CONTEXT.md` 保留，但角色调整为：

- `SELF.md`：用户或系统维护的人类可读长期档案；
- `MEMORY.md`：长期档案导出/审计层，不再是语义检索真源；
- `HISTORY.md` / `journal/`：对话整理产物和人工审计材料；
- `PENDING.md`：markdown consolidation 暂存层；
- `RECENT_CONTEXT.md`：近期上下文压缩层。

长期语义检索的真源改为 `memory/memory2.db`。

## 6. Public Contract

### 6.1 保留与新增工具

本轮的 memory tool 体系调整为：

- 保留 `recall_memory`
- 新增 `memorize`
- 保留 `forget_memory`
- 新增 `undo_memory_by_source`
- 保留 `fetch_messages` 作为证据回源工具，但它不属于 memory primitive

### 6.2 删除工具

- 删除 `correct_memory`

原因：

- Akashic 的“更正”不是一个独立 primitive；
- 正确模型是 `forget/replacement/memorize/undo_by_source` 的组合；
- 继续保留 `correct_memory` 会让 schema 与真实能力不匹配。

### 6.3 engine contract

`MemoryEngine` 不再维持当前仅有 `ingest/query/mutate/forget/render_context_block` 的过渡协议，而是直接重构为 Akashic 风格职责：

- `recall(...)`
- `memorize(...)`
- `forget(...)`
- `undo_by_source(...)`
- `build_context(...)`
- `run_post_response(...)`

tool 层只是参数校验和 I/O 包装，不再自己发明 mutation 语义。

## 7. 数据模型

### 7.1 数据库

弃用当前 `memory/vector_memory.db` 作为长期真源，改为新库：

- `memory/memory2.db`

允许清空旧 vector DB，不做在线兼容迁移。

### 7.2 主表

`memory_items`

- `id TEXT PRIMARY KEY`
- `memory_type TEXT NOT NULL`
- `summary TEXT NOT NULL`
- `content_hash TEXT NOT NULL`
- `embedding TEXT NOT NULL`
- `source_ref TEXT NOT NULL`
- `happened_at TEXT NULL`
- `status TEXT NOT NULL`
- `reinforcement INTEGER NOT NULL`
- `emotional_weight REAL NOT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `extra_json TEXT NOT NULL`

`extra_json` 统一承载：

- `scope_channel`
- `scope_chat_id`
- `tool_requirement`
- `steps`
- `rule_schema`
- `trigger_tags`
- `memory_tag`
- `verified_source_ref`
- 其它类型专属元数据

### 7.3 replacement 表

`memory_replacements`

- `old_item_id TEXT NOT NULL`
- `new_item_id TEXT NOT NULL`
- `source_ref TEXT NOT NULL`
- `created_at TEXT NOT NULL`

用途：

- 显式表达哪条旧记忆被哪条新记忆替换；
- 支撑 `undo_memory_by_source` 恢复链；
- 支撑未来 correction/explanation trace。

### 7.4 必要的记忆类型

首批至少支持：

- `profile`
- `preference`
- `fact`
- `event`
- `procedure`
- `constraint`

不要求在首批引入全部 Akashic 历史类型，但要求 schema 和 retriever 对新增类型开放。

## 8. 写入生命周期

### 8.1 统一入口

所有长期记忆写入都通过 `memorizer`，包括：

- markdown consolidation 写入；
- `memorize` tool；
- post-response worker 的隐式记忆写入；
- `forget_memory`；
- `undo_memory_by_source`。

store 不允许再直接暴露“带业务语义”的 upsert。

### 8.2 memorize 语义

`memorize` 输入至少包含：

- `summary`
- `memory_type`
- `source_ref`
- 可选 `scope_channel`
- 可选 `scope_chat_id`
- 可选 `happened_at`
- 可选结构化 `extra`

写入规则：

- 空摘要拒绝；
- 缺失 `source_ref` 拒绝；
- 同内容 hash 可以 reinforcement；
- 同来源但不同摘要是否替换，由 memorizer 明确决定，而不是静默覆盖。

### 8.3 forget 语义

`forget_memory(ids)`：

- 只把目标项标记为 inactive/superseded；
- 不删除 physical row；
- 保留 replacement/source 链用于审计和 undo。

### 8.4 undo by source 语义

`undo_memory_by_source(source_ref)`：

- 查出所有由该 `source_ref` 创建的 item；
- 回滚对应 replacement；
- 如果该 source 只负责 supersede，则恢复旧项 active 状态；
- 返回恢复项、移除项、跳过项。

这部分是当前 Amadeus 与 Akashic 的关键缺口之一，属于首批必须落地能力。

### 8.5 post-response worker

worker 在每轮 response 后运行，至少处理：

- 从 turn transcript 中提取候选长期记忆；
- 识别显式 `memorize` 已覆盖的内容，避免重复；
- 对需要 replacement 的内容交给 memorizer；
- 输出本轮 memory write 结果给 runtime trace。

本轮只做 runtime 内使用，不做 durable observation。

## 9. 检索与注入

### 9.1 retriever 职责

`retriever` 负责：

- query normalization / rewrite；
- vector lane；
- keyword lane；
- RRF 或等价融合；
- scope 过滤；
- time 过滤；
- reinforcement / hotness 排序因子；
- type-aware threshold；
- 注入块选择与预算裁剪。

### 9.2 before_turn 检索

`before_turn` 不再直接依赖旧式 `query -> render_context_block`，而是调用 engine 的高层接口，例如：

- `memory_engine.build_context(user_message, history, session_key, scope)`

返回：

- 注入文本；
- 注入项 id；
- 检索 trace；
- 被裁剪项 id。

### 9.3 注入排序

注入优先级按 Akashic 风格明确化：

1. `procedure` / `constraint`
2. `profile` / `preference`
3. `event` / `fact`

同组内再考虑：

- scope 匹配度
- 检索分数
- reinforcement
- 时间衰减

### 9.4 source references

`recall_memory` 返回 item 时必须保留：

- `id`
- `source_ref`
- `evidence`

回答若依赖具体历史事实，仍要求模型通过 `fetch_messages` 回源，而不是把 memory item 直接当最终证据。

## 10. 与现有模块的改动边界

### 10.1 必然重构

以下模块预计会被显著重写或拆分：

- `amadeus/memory/engine.py`
- `amadeus/memory/vector.py`
- `amadeus/tools/correct_memory.py`
- `amadeus/tools/recall_memory.py`
- `amadeus/tools/forget_memory.py`
- `amadeus/app/bootstrap.py`
- `amadeus/runtime/before_turn.py`
- `amadeus/runtime/after_turn.py`

### 10.2 预计新增

建议新增或拆分为：

- `amadeus/memory/store.py`
- `amadeus/memory/retriever.py`
- `amadeus/memory/memorizer.py`
- `amadeus/memory/post_response_worker.py`
- `amadeus/tools/memorize.py`
- `amadeus/tools/undo_memory_by_source.py`

是否保留 `vector.py` 取决于实现阶段拆分结果，但长期目标是让它不再承担主入口角色。

### 10.3 可尽量兼容的部分

以下内容可以尽量保留：

- `MarkdownMemoryStore` 维护 markdown 文件的职责；
- `fetch_messages` 工具；
- CLI 显示 memory trace 的外层输出位置；
- 现有 session/source_ref 基本形态。

兼容的意思不是保留旧 schema，而是保留外层使用位置和用户可见行为。

## 11. 错误边界

需要明确以下失败模式：

- embedding/provider 失败时，retriever 至少回退到 lexical lane；
- markdown consolidation 产生脏输入时，memorizer 必须拒绝非法 memory_type 或空 source；
- undo 遇到断裂 replacement 链时，结果应显式标记 partial；
- before_turn 检索失败不能中断主对话，只能降级为空记忆；
- post-response worker 失败不能影响本轮回复提交，但要把失败结果挂到 runtime trace。

## 12. 测试策略

### 12.1 单元测试

新增或重写：

- store schema / CRUD / replacement tests
- memorizer reinforcement / replacement / undo tests
- retriever scope + time + fusion tests
- tool parameter validation tests

### 12.2 集成测试

重点验证 public behavior：

- `before_turn` 自动注入正确类型和优先级的记忆；
- `memorize -> recall_memory -> fetch_messages` 主链路；
- `forget_memory` 后 recall 不再返回该项；
- `undo_memory_by_source` 后旧记忆恢复；
- markdown consolidation / post-response worker 能把 turn 中事实转为长期记忆。

### 12.3 Evals / smoke

本轮不要求先建 observation durability，但至少要准备可跑的行为验证：

- memory correction/replacement 的端到端 smoke；
- scope-aware recall 的 acceptance case；
- passive runtime real turn 的 memory injection smoke。

## 13. 实施顺序

按依赖顺序执行：

1. 重构 `MemoryEngine` contract 和 bootstrap 组装方式
2. 建 `memory2.db` schema 与 store
3. 建 memorizer，接管 ingest/forget/replacement/undo
4. 建 retriever，接管 recall/build_context
5. 接入 `before_turn` 与 `after_turn`/worker
6. 重写 tools：删除 `correct_memory`，新增 `memorize` 和 `undo_memory_by_source`
7. 补齐测试和 acceptance/eval
8. 最后再回头补 observation durability

## 14. 验收标准

以下条件同时满足才算本次 memory 迁移完成：

- 不再依赖 `correct_memory` 作为核心更正路径；
- 长期记忆真源是 `memory/memory2.db`；
- 所有长期记忆写入都经过 memorizer；
- `before_turn` 通过新 retriever 自动注入记忆；
- runtime 中存在 post-response memory worker；
- `recall_memory / memorize / forget_memory / undo_memory_by_source` 四个工具全部可用；
- 现有 passive runtime 集成测试通过；
- 新 memory acceptance tests 证明 replacement、forget、undo、scope recall。

## 15. Deferred

明确后置，不纳入本次实现：

- retrieval/raw trace 持久化
- inspection CLI
- dashboard
- 更复杂的 proactive memory strategy
