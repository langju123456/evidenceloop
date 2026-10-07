# EvidenceLoop 基线报告

- qwen3-1.7b_env-0.2.0：环境 env-0.2.0，验证器 ver-0.1.5

| 指标 | qwen3-1.7b_env-0.2.0 |
| --- | --- |
| 成功数/总数 | 1/60 (2%) |
| numeric_pass | 2/60 (3%) |
| unit_pass | 47/60 (78%) |
| provenance_pass | 39/60 (65%) |
| state_pass | 51/60 (85%) |
| permission_pass | 60/60 (100%) |
| 数值失败中可归因到错误路径 | 24/58 (41%) |
| 有未溯源参数的轨迹 | 26/60 (43%) |
| 报告里有工具没算出过的数 | 26/60 (43%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/60 (0%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 46/60 (77%) |
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
| unsupported_number | 2 |
| calculation_error | 1 |

## qwen3-1.7b_env-0.2.0：按难度分桶

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
