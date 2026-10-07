# EvidenceLoop 基线报告

| 指标 | qwen3-0.6b_env-0.2.0 |
| --- | --- |
| 成功数/总数 | 0/60 (0%) |
| numeric_pass | 0/60 (0%) |
| unit_pass | 44/60 (73%) |
| provenance_pass | 18/60 (30%) |
| state_pass | 44/60 (73%) |
| permission_pass | 60/60 (100%) |
| 数值失败中可归因到错误路径 | 0/60 (0%) |
| 有未溯源参数的轨迹 | 34/60 (57%) |
| 回复与状态不一致 | 12/60 (20%) |
| 平均轮数 | 2.7 |

## qwen3-0.6b_env-0.2.0：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 46 |
| unsupported_claim | 6 |
| unknown | 5 |
| recovery_failure | 2 |
| schema_error | 1 |

## qwen3-0.6b_env-0.2.0：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 0/3 (0%) |
| `F1|all_V|v1|noerr|sci` | 0/4 (0%) |
| `F1|all_V|v2-3|noerr|plain` | 0/3 (0%) |
| `F1|all_V|v2-3|noerr|sci` | 0/6 (0%) |
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
