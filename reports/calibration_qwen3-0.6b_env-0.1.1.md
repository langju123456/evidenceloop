# EvidenceLoop 基线报告

- qwen3-0.6b_env-0.1.1：环境 env-0.1.1，验证器 ver-0.1.6

| 指标 | qwen3-0.6b_env-0.1.1 |
| --- | --- |
| 成功数/总数 | 0/60 (0%) |
| numeric_pass | 0/60 (0%) |
| unit_pass | 10/60 (17%) |
| provenance_pass | 2/60 (3%) |
| state_pass | 10/60 (17%) |
| permission_pass | 60/60 (100%) |
| 数值失败中可归因到错误路径 | 0/60 (0%) |
| 有未溯源参数的轨迹 | 14/60 (23%) |
| 报告里有工具没算出过的数 | 10/60 (17%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 34/60 (57%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 0/60 (0%) |
| 平均轮数 | 2.8 |

## qwen3-0.6b_env-0.1.1：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| schema_error | 36 |
| dependency_error | 14 |
| unsupported_claim | 6 |
| recovery_failure | 2 |
| unknown | 2 |

## qwen3-0.6b_env-0.1.1：按难度分桶

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
| `F1|mixed|v2-3|noerr|plain` | 0/8 (0%) |
| `F1|mixed|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|mixed|v2-3|transient|sci` | 0/2 (0%) |
| `F2|all_mV|v1|noerr|plain` | 0/1 (0%) |
| `F2|all_mV|v1|transient|plain` | 0/1 (0%) |
| `F2|all_mV|v1|transient|sci` | 0/1 (0%) |
| `F2|all_mV|v2-3|noerr|plain` | 0/4 (0%) |
| `F2|all_mV|v2-3|noerr|sci` | 0/4 (0%) |
| `F2|all_mV|v2-3|transient|plain` | 0/2 (0%) |
| `F2|mixed|v1|noerr|plain` | 0/2 (0%) |
| `F2|mixed|v1|noerr|sci` | 0/3 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/3 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/2 (0%) |
| `F2|mixed|v2-3|transient|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|transient|sci` | 0/2 (0%) |
