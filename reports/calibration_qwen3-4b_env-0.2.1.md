# EvidenceLoop 基线报告

- qwen3-4b_env-0.2.1：环境 env-0.2.1，验证器 ver-0.1.5

| 指标 | qwen3-4b_env-0.2.1 |
| --- | --- |
| 成功数/总数 | 6/60 (10%) |
| numeric_pass | 7/60 (12%) |
| unit_pass | 51/60 (85%) |
| provenance_pass | 47/60 (78%) |
| state_pass | 51/60 (85%) |
| permission_pass | 60/60 (100%) |
| 数值失败中可归因到错误路径 | 10/53 (19%) |
| 有未溯源参数的轨迹 | 0/60 (0%) |
| 报告里有工具没算出过的数 | 16/60 (27%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/60 (0%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 32/60 (53%) |
| 平均轮数 | 8.9 |

## qwen3-4b_env-0.2.1：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| unknown | 26 |
| unsupported_number | 9 |
| filter_error | 8 |
| source_version_error | 5 |
| schema_error | 5 |
| recovery_failure | 1 |

## qwen3-4b_env-0.2.1：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 1/3 (33%) |
| `F1|all_V|v1|noerr|sci` | 0/4 (0%) |
| `F1|all_V|v2-3|noerr|plain` | 1/3 (33%) |
| `F1|all_V|v2-3|noerr|sci` | 2/6 (33%) |
| `F1|all_mV|v1|noerr|plain` | 0/2 (0%) |
| `F1|all_mV|v1|transient|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|sci` | 1/4 (25%) |
| `F1|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F1|mixed|v1|noerr|sci` | 0/1 (0%) |
| `F1|mixed|v1|transient|plain` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 0/3 (0%) |
| `F1|mixed|v2-3|transient|plain` | 1/3 (33%) |
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
