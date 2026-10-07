# EvidenceLoop 基线报告

- qwen3-1.7b_validation：环境 env-0.2.1，验证器 ver-0.1.6

| 指标 | qwen3-1.7b_validation |
| --- | --- |
| 成功数/总数 | 0/50 (0%) |
| numeric_pass | 0/50 (0%) |
| unit_pass | 35/50 (70%) |
| provenance_pass | 29/50 (58%) |
| state_pass | 36/50 (72%) |
| permission_pass | 50/50 (100%) |
| 数值失败中可归因到错误路径 | 18/50 (36%) |
| 有未溯源参数的轨迹 | 18/50 (36%) |
| 报告里有工具没算出过的数 | 17/50 (34%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/50 (0%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 27/50 (54%) |
| 平均轮数 | 8.9 |

## qwen3-1.7b_validation：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 14 |
| schema_error | 13 |
| unknown | 13 |
| filter_error | 9 |
| source_version_error | 1 |

## qwen3-1.7b_validation：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 0/2 (0%) |
| `F1|all_V|v1|noerr|sci` | 0/1 (0%) |
| `F1|all_V|v2-3|noerr|plain` | 0/3 (0%) |
| `F1|all_V|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|all_mV|v1|noerr|plain` | 0/1 (0%) |
| `F1|all_mV|v1|noerr|sci` | 0/2 (0%) |
| `F1|all_mV|v1|transient|plain` | 0/2 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|all_mV|v2-3|transient|plain` | 0/1 (0%) |
| `F1|all_mV|v2-3|transient|sci` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 0/2 (0%) |
| `F1|mixed|v2-3|noerr|sci` | 0/4 (0%) |
| `F1|mixed|v2-3|transient|plain` | 0/1 (0%) |
| `F2|all_V|v1|noerr|sci` | 0/1 (0%) |
| `F2|all_V|v2-3|noerr|plain` | 0/2 (0%) |
| `F2|all_mV|v1|noerr|sci` | 0/2 (0%) |
| `F2|all_mV|v1|transient|plain` | 0/2 (0%) |
| `F2|all_mV|v2-3|noerr|plain` | 0/4 (0%) |
| `F2|all_mV|v2-3|noerr|sci` | 0/4 (0%) |
| `F2|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v1|noerr|sci` | 0/2 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/4 (0%) |
| `F2|mixed|v2-3|transient|sci` | 0/2 (0%) |
