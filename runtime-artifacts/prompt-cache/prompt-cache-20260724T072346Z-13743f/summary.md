# DeepSeek Prompt Cache A/B 基准结果

- run_id: `prompt-cache-20260724T072346Z-13743f`
- model: `deepseek-v4-flash`
- 预算截断: `False`

| 组别 | 可观测请求 | Token 缓存读取率 | 请求命中率 | 中位总耗时 (ms) | P95 (ms) |
|---|---:|---:|---:|---:|---:|
| A | 0 | - | - | - | - |
| B | 0 | - | - | - | - |

缓存读取率基于 DeepSeek 返回的 prompt_cache_hit_tokens / (hit + miss)；缺少字段不推断命中。
