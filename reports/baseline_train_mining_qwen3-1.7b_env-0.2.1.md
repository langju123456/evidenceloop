# EvidenceLoop 基线报告

- qwen3-1.7b_train_mining：环境 env-0.2.1，验证器 ver-0.1.6

| 指标 | qwen3-1.7b_train_mining |
| --- | --- |
| 成功数/总数 | 1/200 (0%) |
| numeric_pass | 1/200 (0%) |
| unit_pass | 143/200 (72%) |
| provenance_pass | 108/200 (54%) |
| state_pass | 151/200 (76%) |
| permission_pass | 199/200 (100%) |
| 数值失败中可归因到错误路径 | 92/199 (46%) |
| 有未溯源参数的轨迹 | 79/200 (40%) |
| 报告里有工具没算出过的数 | 57/200 (28%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/200 (0%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 120/200 (60%) |
| 平均轮数 | 9.0 |

## qwen3-1.7b_train_mining：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 61 |
| filter_error | 43 |
| schema_error | 39 |
| unknown | 29 |
| source_version_error | 17 |
| unit_error | 6 |
| unsupported_number | 3 |
| recovery_failure | 1 |

## qwen3-1.7b_train_mining：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 0/3 (0%) |
| `F1|all_V|v1|noerr|sci` | 0/4 (0%) |
| `F1|all_V|v2-3|noerr|plain` | 1/14 (7%) |
| `F1|all_V|v2-3|noerr|sci` | 0/10 (0%) |
| `F1|all_mV|v1|noerr|plain` | 0/5 (0%) |
| `F1|all_mV|v1|noerr|sci` | 0/2 (0%) |
| `F1|all_mV|v1|transient|plain` | 0/2 (0%) |
| `F1|all_mV|v1|transient|sci` | 0/2 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 0/7 (0%) |
| `F1|all_mV|v2-3|noerr|sci` | 0/8 (0%) |
| `F1|all_mV|v2-3|transient|plain` | 0/3 (0%) |
| `F1|all_mV|v2-3|transient|sci` | 0/5 (0%) |
| `F1|mixed|v1|noerr|plain` | 0/4 (0%) |
| `F1|mixed|v1|noerr|sci` | 0/7 (0%) |
| `F1|mixed|v1|transient|sci` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 0/6 (0%) |
| `F1|mixed|v2-3|noerr|sci` | 0/9 (0%) |
| `F1|mixed|v2-3|transient|plain` | 0/7 (0%) |
| `F1|mixed|v2-3|transient|sci` | 0/2 (0%) |
| `F2|all_V|v1|noerr|plain` | 0/8 (0%) |
| `F2|all_V|v1|noerr|sci` | 0/7 (0%) |
| `F2|all_V|v2-3|noerr|plain` | 0/8 (0%) |
| `F2|all_V|v2-3|noerr|sci` | 0/12 (0%) |
| `F2|all_mV|v1|noerr|plain` | 0/6 (0%) |
| `F2|all_mV|v1|noerr|sci` | 0/2 (0%) |
| `F2|all_mV|v1|transient|plain` | 0/2 (0%) |
| `F2|all_mV|v1|transient|sci` | 0/1 (0%) |
| `F2|all_mV|v2-3|noerr|plain` | 0/10 (0%) |
| `F2|all_mV|v2-3|noerr|sci` | 0/6 (0%) |
| `F2|all_mV|v2-3|transient|plain` | 0/6 (0%) |
| `F2|all_mV|v2-3|transient|sci` | 0/3 (0%) |
| `F2|mixed|v1|noerr|plain` | 0/4 (0%) |
| `F2|mixed|v1|noerr|sci` | 0/1 (0%) |
| `F2|mixed|v1|transient|plain` | 0/2 (0%) |
| `F2|mixed|v1|transient|sci` | 0/2 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/8 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/3 (0%) |
| `F2|mixed|v2-3|transient|plain` | 0/3 (0%) |
| `F2|mixed|v2-3|transient|sci` | 0/5 (0%) |
