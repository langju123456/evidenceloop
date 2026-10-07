# EvidenceLoop 基线报告

- qwen3-4b_validation：环境 env-0.2.1，验证器 ver-0.1.6

| 指标 | qwen3-4b_validation |
| --- | --- |
| 成功数/总数 | 6/50 (12%) |
| numeric_pass | 6/50 (12%) |
| unit_pass | 44/50 (88%) |
| provenance_pass | 40/50 (80%) |
| state_pass | 44/50 (88%) |
| permission_pass | 50/50 (100%) |
| 数值失败中可归因到错误路径 | 19/44 (43%) |
| 有未溯源参数的轨迹 | 0/50 (0%) |
| 报告里有工具没算出过的数 | 13/50 (26%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/50 (0%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 26/50 (52%) |
| 平均轮数 | 8.8 |

## qwen3-4b_validation：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| filter_error | 17 |
| unknown | 15 |
| source_version_error | 5 |
| unsupported_number | 4 |
| schema_error | 3 |

## qwen3-4b_validation：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 0/2 (0%) |
| `F1|all_V|v1|noerr|sci` | 0/1 (0%) |
| `F1|all_V|v2-3|noerr|plain` | 1/3 (33%) |
| `F1|all_V|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|all_mV|v1|noerr|plain` | 0/1 (0%) |
| `F1|all_mV|v1|noerr|sci` | 0/2 (0%) |
| `F1|all_mV|v1|transient|plain` | 1/2 (50%) |
| `F1|all_mV|v2-3|noerr|plain` | 1/1 (100%) |
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
| `F2|all_mV|v2-3|noerr|sci` | 3/4 (75%) |
| `F2|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v1|noerr|sci` | 0/2 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/4 (0%) |
| `F2|mixed|v2-3|transient|sci` | 0/2 (0%) |
