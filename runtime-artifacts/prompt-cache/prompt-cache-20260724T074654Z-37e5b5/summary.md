# DeepSeek Prompt Cache A/B 基准结果

- run_id: `prompt-cache-20260724T074654Z-37e5b5`
- model: `deepseek-v4-flash`
- 预算截断: `False`
- 因供应商错误停止: `False`

| 组别 | 可观测请求 | Token 缓存读取率 | 请求命中率 | 中位总耗时 (ms) | P95 (ms) |
|---|---:|---:|---:|---:|---:|
| A | 30 | 0.0000 | 0.0000 | 1646.0848 | 1965.5593 |
| B | 30 | 0.9494 | 1.0000 | 1682.2639 | 2072.0277 |

缓存读取率基于 DeepSeek 返回的 prompt_cache_hit_tokens / (hit + miss)；缺少字段不推断命中。
