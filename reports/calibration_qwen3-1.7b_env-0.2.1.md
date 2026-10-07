# EvidenceLoop 基线报告

- qwen3-1.7b_env-0.2.1：环境 env-0.2.1，验证器 ver-0.1.5

| 指标 | qwen3-1.7b_env-0.2.1 |
| --- | --- |
| 成功数/总数 | 1/60 (2%) |
| numeric_pass | 2/60 (3%) |
| unit_pass | 41/60 (68%) |
| provenance_pass | 32/60 (53%) |
| state_pass | 40/60 (67%) |
| permission_pass | 58/60 (97%) |
| 数值失败中可归因到错误路径 | 17/58 (29%) |
| 有未溯源参数的轨迹 | 24/60 (40%) |
| 报告里有工具没算出过的数 | 16/60 (27%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/60 (0%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 28/60 (47%) |
| 平均轮数 | 9.3 |

## qwen3-1.7b_env-0.2.1：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 19 |
| schema_error | 18 |
| filter_error | 8 |
| unknown | 7 |
| unsupported_number | 2 |
| source_version_error | 2 |
| unit_error | 1 |
| unauthorized_write | 1 |
| calculation_error | 1 |

## qwen3-1.7b_env-0.2.1：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 0/3 (0%) |
| `F1|all_V|v1|noerr|sci` | 0/4 (0%) |
| `F1|all_V|v2-3|noerr|plain` | 0/3 (0%) |
| `F1|all_V|v2-3|noerr|sci` | 1/6 (17%) |
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
