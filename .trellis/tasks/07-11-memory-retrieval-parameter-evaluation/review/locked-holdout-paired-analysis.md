# Locked holdout 配对分析

- Dataset hash：`b0566f9a99a94761f4ba40669d70c7d941933464feac8b81830d5047d38499c9`
- Experiment：`memory-retrieval-v1-b0566f9a99a9-holdout`
- Holdout families：`18`
- Practical-equivalence：`1/18 = 5.56pp`
- Bootstrap：`10000` 次，seed `20260712`

## 总体结果

| Profile | 硬门 | Recall@8 | All required | Precision@8 | MRR@8 | nDCG@8 | Avg union |
|---|---:|---:|---:|---:|---:|---:|---:|
| `amadeus-baseline` | 通过 | 1.0000 | 1.0000 | 0.1339 | 0.9167 | 0.9325 | 37.3889 |
| `window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline` | 通过 | 1.0000 | 1.0000 | 0.1339 | 0.9524 | 0.9584 | 37.3889 |
| `window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline` | 通过 | 1.0000 | 1.0000 | 0.1339 | 0.9167 | 0.9319 | 21.1111 |

## 配对区间

区间基于同一 family 的 candidate - baseline 差值重采样。Recall 只在有正例的 family 上计算；abstention family 不进入 Recall 分母。

| Candidate | Recall Δ / 95% CI | MRR Δ / 95% CI | nDCG Δ / 95% CI | Recall 判定 |
|---|---:|---:|---:|---:|
| `window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline` | 0.0000 / [0.0000, 0.0000] | 0.0357 / [0.0000, 0.1071] | 0.0259 / [-0.0035, 0.0803] | 相当 |
| `window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline` | 0.0000 / [0.0000, 0.0000] | 0.0000 / [0.0000, 0.0000] | -0.0006 / [-0.0019, 0.0000] | 相当 |

## 逐 family：`window-v32-l30__fusion-w0.75-k10__threshold-0.40__hotness-baseline`

| Family | Baseline R | Candidate R | ΔR | ΔMRR | ΔnDCG |
|---|---:|---:|---:|---:|---:|
| `holdout_personal_call_time` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_diet_update` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_language_exception` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_morning_alarm` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0172 |
| `holdout_personal_pet_food` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_recipe_steps` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_tax_document` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_unknown_insurance` | - | - | - | - | - |
| `holdout_personal_unknown_locker` | - | - | - | - | - |
| `holdout_project_config_key` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_project_incident_time` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_project_queue_choice` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_project_review_rule` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_project_schema_update` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_project_unknown_flag` | - | - | - | - | - |
| `holdout_stress_conflict` | 1.0000 | 1.0000 | 0.0000 | 0.5000 | 0.3691 |
| `holdout_stress_cross_user` | - | - | - | - | - |
| `holdout_stress_homonym` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | -0.0242 |

## 逐 family：`window-v15-l16__fusion-w1-k60__threshold-0.40__hotness-baseline`

| Family | Baseline R | Candidate R | ΔR | ΔMRR | ΔnDCG |
|---|---:|---:|---:|---:|---:|
| `holdout_personal_call_time` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_diet_update` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_language_exception` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_morning_alarm` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_pet_food` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_recipe_steps` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_tax_document` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_personal_unknown_insurance` | - | - | - | - | - |
| `holdout_personal_unknown_locker` | - | - | - | - | - |
| `holdout_project_config_key` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_project_incident_time` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_project_queue_choice` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_project_review_rule` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_project_schema_update` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_project_unknown_flag` | - | - | - | - | - |
| `holdout_stress_conflict` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| `holdout_stress_cross_user` | - | - | - | - | - |
| `holdout_stress_homonym` | 1.0000 | 1.0000 | 0.0000 | 0.0000 | -0.0091 |
