# 排行榜（validation，Mac 上 MLX 运行）

- 0.6B：环境 env-0.2.1，验证器 ver-0.1.6
- 1.7B：环境 env-0.2.1，验证器 ver-0.1.6
- 4B：环境 env-0.2.1，验证器 ver-0.1.6

| 指标 | 0.6B | 1.7B | 4B |
| --- | --- | --- | --- |
| 成功数/总数 | 0/50 (0%) | 0/50 (0%) | 6/50 (12%) |
| numeric_pass | 0/50 (0%) | 0/50 (0%) | 6/50 (12%) |
| unit_pass | 31/50 (62%) | 35/50 (70%) | 44/50 (88%) |
| provenance_pass | 13/50 (26%) | 29/50 (58%) | 40/50 (80%) |
| state_pass | 31/50 (62%) | 36/50 (72%) | 44/50 (88%) |
| permission_pass | 50/50 (100%) | 50/50 (100%) | 50/50 (100%) |
| 数值失败中可归因到错误路径 | 0/50 (0%) | 18/50 (36%) | 19/44 (43%) |
| 有未溯源参数的轨迹 | 23/50 (46%) | 18/50 (36%) | 0/50 (0%) |
| 报告里有工具没算出过的数 | 31/50 (62%) | 17/50 (34%) | 13/50 (26%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 9/50 (18%) | 0/50 (0%) | 0/50 (0%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 9/50 (18%) | 27/50 (54%) | 26/50 (52%) |
| 平均轮数 | 3.3 | 8.9 | 8.8 |

## 0.6B：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 33 |
| unknown | 9 |
| unsupported_claim | 7 |
| recovery_failure | 1 |

## 0.6B：按难度分桶

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

## 1.7B：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 14 |
| schema_error | 13 |
| unknown | 13 |
| filter_error | 9 |
| source_version_error | 1 |

## 1.7B：按难度分桶

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

## 4B：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| filter_error | 17 |
| unknown | 15 |
| source_version_error | 5 |
| unsupported_number | 4 |
| schema_error | 3 |

## 4B：按难度分桶

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
