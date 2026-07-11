# PostgreSQL lexical channel 方案研究

## 研究问题

Amadeus 需要一个不依赖 pgvector shortlist 的 PostgreSQL lexical candidate channel。该通道必须：

- 保持已确认的 Akashic-compatible ASCII/CJK term 的字面 substring 语义；
- 支持中英文与稀有标识符；
- 不把 PostgreSQL `ts_rank` 错称为 BM25；
- 在当前 `pgvector/pgvector:pg16` 运行环境中可交付；
- 对索引能做什么、不能做什么给出真实证据。

## 官方资料结论

### pg_trgm

PostgreSQL 官方文档说明：

- `pg_trgm` 使用连续三个字符形成 trigram；
- GiST/GIN operator class 支持 `LIKE`、`ILIKE`、正则与相似度查询；
- substring pattern 不需要左锚定；
- pattern 可提取的 trigram 越多，索引越有效；
- 没有可提取 trigram 的 pattern 会退化为 full-index scan；
- `pg_trgm` 是 trusted extension，有数据库 `CREATE` 权限的非 superuser 也可安装。

来源：[PostgreSQL `pg_trgm` 官方文档](https://www.postgresql.org/docs/current/pgtrgm.html)。

### built-in FTS

PostgreSQL full-text search 先由 parser 切 token，再由 dictionary 生成 lexeme。官方文档说明当前只有一个 built-in parser，token 边界由 parser 与 locale 决定；它没有提供符合 Amadeus CJK bigram 合同的内建中文分词器。

来源：

- [PostgreSQL text search parsers](https://www.postgresql.org/docs/current/textsearch-parsers.html)
- [PostgreSQL text search configuration](https://www.postgresql.org/docs/current/textsearch-configuration.html)

### LIKE 字面量

PostgreSQL `LIKE` / `ILIKE` 中，`_` 表示任意单字符，`%` 表示任意长度字符串。若目标是字面 substring，应用必须转义 `_`、`%` 和 escape character 本身。

来源：[PostgreSQL pattern matching](https://www.postgresql.org/docs/current/functions-matching.html)。

## WSL PostgreSQL 16 实验

环境：

- WSL Debian；
- `pgvector/pgvector:pg16`；
- 100,000 行临时表；
- `CREATE EXTENSION pg_trgm`、临时表、索引和样本全部位于未提交事务；
- 实验后确认 `pg_trgm_persisted=False`，未修改项目 schema 或 `memory_items`。

索引：

```sql
CREATE INDEX trgm_probe_summary_idx
ON trgm_probe USING gin (summary gin_trgm_ops);
```

查询使用 psycopg 参数和显式 escape：

```sql
summary ILIKE %s ESCAPE '!'
```

结果：

| Pattern | 命中 | 默认计划 | 执行时间 |
|---|---:|---|---:|
| `%支付%`（2 CJK chars） | 1 | Seq Scan | 27.841 ms |
| `%支付宝支付%`（5 CJK chars） | 1 | Bitmap Index + Heap Scan | 0.082 ms |
| `%ZXQ-4917%` | 1 | Bitmap Index + Heap Scan | 0.030 ms |
| `%foo!_bar% ESCAPE '!'` | 1 | Bitmap Index + Heap Scan | 0.049 ms |

对 `%支付%` 强制 `enable_seqscan=off` 后，PostgreSQL 做 full trigram index scan，执行时间升至 41.446 ms。这与官方“无可提取 trigram 时退化为 full-index scan”的说明一致。

字面量安全实验：

- 未转义 `%foo_bar%` 同时命中 `foo_bar` 与 `fooxbar`，共 2 行；
- `%foo!_bar% ESCAPE '!'` 只命中字面下划线，1 行。

当前 `extract_terms()` 会保留 `foo_bar`，甚至可能返回单独 `_`，因此 SQL 层转义不是可选优化，而是正确性要求。

### 当前 CJK extractor 对索引收益的影响

当前 `extract_terms()` 会把所有长度大于 2 的中文块拆成相邻 bigram。例如 `支付宝支付` 变成：

```text
支付, 付宝, 宝支
```

因此，单独测试 `%支付宝支付%` 能走 trigram index，并不代表当前端到端中文查询会生成这个 pattern。追加的 100,000 行实验结果：

| Predicates | 默认计划 | 执行时间 |
|---|---|---:|
| `%支付% OR %付宝% OR %宝支%` | Seq Scan | 80.017 ms |
| `%支付宝支付% OR %支付%` | Seq Scan | 52.587 ms |
| `%zxq% OR %4917%` | BitmapOr + two GIN scans | 0.078 ms |

结论：只要 OR 中存在无法提取 trigram 的 2 字 pattern，planner 就可能放弃整个 trigram index。当前设计下，plain `pg_trgm` 的确定收益主要是纯 ASCII/数字/标识符查询；CJK bigram 仍是 scoped scan。未来即使给 extractor 追加完整中文 chunk，只要继续 OR bigram，也不能宣称端到端走索引。

### 已确认的目标 extractor

目标实现不沿用上述“所有长度大于 2 都拆 bigram”的当前行为，而是对齐 Akashic：2～4 字 CJK chunk 保留完整，超过 4 字才拆相邻 bigram。因此 3～4 字完整 pattern 有机会被 `pg_trgm` 提取 trigram 并使用索引；2 字 chunk 和超过 4 字产生的 bigram OR 仍可能走 scoped Seq Scan。这个改变改善了部分查询的索引条件，但不改变“正确性由 ILIKE、索引只做 best-effort 加速”的边界。

## FTS 中文实验

```sql
SELECT alias, token
FROM ts_debug('simple', '用户使用支付宝支付');
```

PostgreSQL 16 把整段无空格中文识别为一个 `word` token：

```text
用户使用支付宝支付
```

随后：

```sql
to_tsvector('simple', '用户使用支付宝支付')
@@ plainto_tsquery('simple', '支付')
```

结果为 `false`。因此 built-in `simple` FTS 不能保留当前“查询 bigram 可命中长中文 summary substring”的行为，除非额外引入中文 parser/dictionary 或自行维护 ngram 数据。

## 方案比较

| 方案 | 字面正确性 | 2 字 CJK 性能 | 部署成本 | 结论 |
|---|---|---|---|---|
| 参数化 `ILIKE` + plain `pg_trgm` GIN | 保留 substring；需 escape | CJK bigram 扫描；ASCII/标识符可加速 | 低；当前镜像已验证可创建 | MVP 推荐 |
| `tsvector` + built-in `simple` | 不保留无空格 CJK substring | 不适用 | 低 | 拒绝 |
| `pg_bigm` | 保留 bigram/LIKE | 快 | 高；自编译、custom image、preload | 当前任务拒绝 |
| 应用维护 bigram array + GIN | 可自定义 | 快 | 中高；写入、回填、算法一致性 | 规模证据出现后再评估 |
| 无索引 OR-ILIKE | 保留 substring | 扫描 | 最低 | correctness fallback，不作为唯一优化 |

`pg_bigm` 官方项目明确以 2-gram 支持日文等非字母语言和 1-2 字关键词，但需要构建 extension、修改 `shared_preload_libraries` 并维护定制 PostgreSQL 镜像。来源：[pgbigm/pg_bigm](https://github.com/pgbigm/pg_bigm)。这会扩大当前 Amadeus 的部署边界，不符合本任务的小垂直切片。

## 最终建议

1. 独立 lexical candidate 的正确性由参数化 `summary ILIKE ... ESCAPE '!'` 提供，不依赖 trigram index 是否被 planner 采用。
2. 在 bare `summary` 上建立 `gin_trgm_ops`，直接服务 `ILIKE`；不要建立 `lower(summary)` expression index，除非查询也固定写成完全一致的 `lower(summary) LIKE ...`。
3. pattern builder 必须依次转义 `! -> !!`、`% -> !%`、`_ -> !_`，再包裹 `%...%`。
4. 对纯 ASCII/数字/标识符及部分 3～4 字完整 CJK term，trigram GIN 可提供实际加速；2 字 CJK、超过 4 字产生的 bigram 与混合 OR 查询接受 user/status/scope/time 预过滤后的扫描，并在 trace/性能测试中保持诚实。
5. 如果真实 corpus/eval 证明短 CJK scan 成为瓶颈，再单独评估 `pg_bigm` 或 canonical ngram array；不得为了索引性能退回共享 vector shortlist。

## 实施前置验证

- migration 后用真实 `memory_items` 运行 `ANALYZE`；expression/GIN index 的统计信息不能靠临时小表推断。
- `EXPLAIN (ANALYZE, BUFFERS)` 至少覆盖 2 字 CJK、3+ 字 CJK、ASCII identifier、escaped underscore。
- 生产表规模若已足以让常规 `CREATE INDEX` 阻塞写入，评估 Alembic `autocommit_block()` + `CREATE INDEX CONCURRENTLY`；官方文档明确 `CONCURRENTLY` 不能在 transaction block 内运行，并可能在失败后留下 INVALID index。

来源：[PostgreSQL `CREATE INDEX`](https://www.postgresql.org/docs/current/sql-createindex.html)。
