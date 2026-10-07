# EvidenceLoop 基线报告

- qwen3-1.7b_env-0.1.1：环境 env-0.1.1，验证器 ver-0.1.6

| 指标 | qwen3-1.7b_env-0.1.1 |
| --- | --- |
| 成功数/总数 | 2/60 (3%) |
| numeric_pass | 3/60 (5%) |
| unit_pass | 23/60 (38%) |
| provenance_pass | 10/60 (17%) |
| state_pass | 26/60 (43%) |
| permission_pass | 60/60 (100%) |
| 数值失败中可归因到错误路径 | 8/57 (14%) |
| 有未溯源参数的轨迹 | 18/60 (30%) |
| 报告里有工具没算出过的数 | 4/60 (7%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/60 (0%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 26/60 (43%) |
| 平均轮数 | 10.3 |

## qwen3-1.7b_env-0.1.1：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| schema_error | 30 |
| dependency_error | 13 |
| source_version_error | 9 |
| unit_error | 2 |
| unknown | 2 |
| calculation_error | 1 |
| filter_error | 1 |

## qwen3-1.7b_env-0.1.1：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_mV|v1|noerr|plain` | 0/4 (0%) |
| `F1|all_mV|v1|noerr|sci` | 0/2 (0%) |
| `F1|all_mV|v1|transient|plain` | 0/2 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 0/2 (0%) |
| `F1|all_mV|v2-3|noerr|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|transient|plain` | 0/3 (0%) |
| `F1|all_mV|v2-3|transient|sci` | 0/2 (0%) |
| `F1|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F1|mixed|v1|noerr|sci` | 0/5 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 1/8 (12%) |
| `F1|mixed|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|mixed|v2-3|transient|sci` | 0/2 (0%) |
| `F2|all_mV|v1|noerr|plain` | 0/1 (0%) |
| `F2|all_mV|v1|transient|plain` | 0/1 (0%) |
| `F2|all_mV|v1|transient|sci` | 0/1 (0%) |
| `F2|all_mV|v2-3|noerr|plain` | 0/4 (0%) |
| `F2|all_mV|v2-3|noerr|sci` | 0/4 (0%) |
| `F2|all_mV|v2-3|transient|plain` | 0/2 (0%) |
| `F2|mixed|v1|noerr|plain` | 1/2 (50%) |
| `F2|mixed|v1|noerr|sci` | 0/3 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/3 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/2 (0%) |
| `F2|mixed|v2-3|transient|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|transient|sci` | 0/2 (0%) |
