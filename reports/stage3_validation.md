# 阶段三：validation

- A：环境 env-0.2.1，验证器 ver-0.1.6
- W25：环境 env-0.2.1，验证器 ver-0.1.6

| 指标 | A | W25 |
| --- | --- | --- |
| 成功数/总数 | 0/50 (0%) | 33/50 (66%) |
| numeric_pass | 0/50 (0%) | 33/50 (66%) |
| unit_pass | 36/50 (72%) | 49/50 (98%) |
| provenance_pass | 29/50 (58%) | 46/50 (92%) |
| state_pass | 37/50 (74%) | 50/50 (100%) |
| permission_pass | 50/50 (100%) | 50/50 (100%) |
| 数值失败中可归因到错误路径 | 19/50 (38%) | 12/17 (71%) |
| 有未溯源参数的轨迹 | 19/50 (38%) | 0/50 (0%) |
| 报告里有工具没算出过的数 | 20/50 (40%) | 0/50 (0%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/50 (0%) | 0/50 (0%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 27/50 (54%) | 0/50 (0%) |
| 平均轮数 | 8.8 | 7.9 |

## A：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 17 |
| unknown | 12 |
| filter_error | 10 |
| schema_error | 10 |
| source_version_error | 1 |

## A：按难度分桶

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

## W25：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| unit_error | 9 |
| source_version_error | 4 |
| unknown | 3 |
| filter_error | 1 |

## W25：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 1/2 (50%) |
| `F1|all_V|v1|noerr|sci` | 1/1 (100%) |
| `F1|all_V|v2-3|noerr|plain` | 3/3 (100%) |
| `F1|all_V|v2-3|noerr|sci` | 2/2 (100%) |
| `F1|all_mV|v1|noerr|plain` | 1/1 (100%) |
| `F1|all_mV|v1|noerr|sci` | 1/2 (50%) |
| `F1|all_mV|v1|transient|plain` | 2/2 (100%) |
| `F1|all_mV|v2-3|noerr|plain` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|sci` | 1/2 (50%) |
| `F1|all_mV|v2-3|transient|plain` | 1/1 (100%) |
| `F1|all_mV|v2-3|transient|sci` | 1/1 (100%) |
| `F1|mixed|v2-3|noerr|plain` | 0/2 (0%) |
| `F1|mixed|v2-3|noerr|sci` | 1/4 (25%) |
| `F1|mixed|v2-3|transient|plain` | 1/1 (100%) |
| `F2|all_V|v1|noerr|sci` | 1/1 (100%) |
| `F2|all_V|v2-3|noerr|plain` | 2/2 (100%) |
| `F2|all_mV|v1|noerr|sci` | 2/2 (100%) |
| `F2|all_mV|v1|transient|plain` | 1/2 (50%) |
| `F2|all_mV|v2-3|noerr|plain` | 2/4 (50%) |
| `F2|all_mV|v2-3|noerr|sci` | 3/4 (75%) |
| `F2|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v1|noerr|sci` | 2/2 (100%) |
| `F2|mixed|v2-3|noerr|plain` | 1/1 (100%) |
| `F2|mixed|v2-3|noerr|sci` | 2/4 (50%) |
| `F2|mixed|v2-3|transient|sci` | 1/2 (50%) |
