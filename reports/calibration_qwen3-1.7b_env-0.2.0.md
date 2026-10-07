# EvidenceLoop 基线报告

| 指标 | qwen3-1.7b_env-0.2.0 |
| --- | --- |
| 成功数/总数 | 3/60 (5%) |
| numeric_pass | 4/60 (7%) |
| unit_pass | 47/60 (78%) |
| provenance_pass | 39/60 (65%) |
| state_pass | 51/60 (85%) |
| permission_pass | 60/60 (100%) |
| 数值失败中可归因到错误路径 | 24/56 (43%) |
| 有未溯源参数的轨迹 | 26/60 (43%) |
| 回复与状态不一致 | 46/60 (77%) |
| 平均轮数 | 8.2 |

## qwen3-1.7b_env-0.2.0：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 21 |
| filter_error | 11 |
| unknown | 10 |
| schema_error | 6 |
| unit_error | 4 |
| source_version_error | 4 |
| calculation_error | 1 |

## qwen3-1.7b_env-0.2.0：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 0/3 (0%) |
| `F1|all_V|v1|noerr|sci` | 1/4 (25%) |
| `F1|all_V|v2-3|noerr|plain` | 0/3 (0%) |
| `F1|all_V|v2-3|noerr|sci` | 2/6 (33%) |
| `F1|all_mV|v1|noerr|plain` | 0/2 (0%) |
| `F1|all_mV|v1|transient|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|sci` | 0/4 (0%) |
| `F1|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F1|mixed|v1|noerr|sci` | 0/1 (0%) |
| `F1|mixed|v1|transient|plain` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 0/3 (0%) |
| `F1|mixed|v2-3|transient|plain` | 0/3 (0%) |
| `F2|all_V|v1|noerr|plain` | 0/1 (0%) |
| `F2|all_V|v1|noerr|sci` | 0/1 (0%) |
| `F2|all_V|v2-3|noerr|plain` | 0/2 (0%) |
| `F2|all_V|v2-3|noerr|sci` | 0/1 (0%) |
| `F2|all_mV|v1|noerr|plain` | 0/2 (0%) |
| `F2|all_mV|v1|noerr|sci` | 0/3 (0%) |
| `F2|all_mV|v2-3|noerr|plain` | 0/2 (0%) |
| `F2|all_mV|v2-3|noerr|sci` | 0/2 (0%) |
| `F2|all_mV|v2-3|transient|sci` | 0/1 (0%) |
| `F2|mixed|v1|noerr|sci` | 0/2 (0%) |
| `F2|mixed|v1|transient|sci` | 0/2 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/2 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/6 (0%) |
