# 阶段五：test_id

- W25：环境 env-0.2.1，验证器 ver-0.1.6
- C1：环境 env-0.2.1，验证器 ver-0.1.6
- C2：环境 env-0.2.1，验证器 ver-0.1.6
- C3：环境 env-0.2.1，验证器 ver-0.1.6
- P1：环境 env-0.2.1，验证器 ver-0.1.6
- CP1：环境 env-0.2.1，验证器 ver-0.1.6

| 指标 | W25 | C1 | C2 | C3 | P1 | CP1 |
| --- | --- | --- | --- | --- | --- | --- |
| 成功数/总数 | 100/150 (67%) | 149/150 (99%) | 149/150 (99%) | 150/150 (100%) | 70/150 (47%) | 0/150 (0%) |
| numeric_pass | 100/150 (67%) | 149/150 (99%) | 149/150 (99%) | 150/150 (100%) | 70/150 (47%) | 0/150 (0%) |
| unit_pass | 146/150 (97%) | 149/150 (99%) | 150/150 (100%) | 150/150 (100%) | 87/150 (58%) | 19/150 (13%) |
| provenance_pass | 138/150 (92%) | 150/150 (100%) | 150/150 (100%) | 150/150 (100%) | 89/150 (59%) | 13/150 (9%) |
| state_pass | 148/150 (99%) | 150/150 (100%) | 150/150 (100%) | 150/150 (100%) | 89/150 (59%) | 21/150 (14%) |
| permission_pass | 150/150 (100%) | 150/150 (100%) | 150/150 (100%) | 150/150 (100%) | 150/150 (100%) | 150/150 (100%) |
| 数值失败中可归因到错误路径 | 34/50 (68%) | 0/1 (0%) | 1/1 (100%) | 0/0 | 9/80 (11%) | 1/150 (1%) |
| 有未溯源参数的轨迹 | 2/150 (1%) | 0/150 (0%) | 0/150 (0%) | 0/150 (0%) | 52/150 (35%) | 78/150 (52%) |
| 报告里有工具没算出过的数 | 1/150 (1%) | 0/150 (0%) | 0/150 (0%) | 0/150 (0%) | 6/150 (4%) | 20/150 (13%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/150 (0%) | 0/150 (0%) | 0/150 (0%) | 0/150 (0%) | 2/150 (1%) | 2/150 (1%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 0/150 (0%) | 0/150 (0%) | 0/150 (0%) | 0/150 (0%) | 19/150 (13%) | 1/150 (1%) |
| 平均轮数 | 7.9 | 8.2 | 8.2 | 8.2 | 8.3 | 10.8 |

## W25：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| unit_error | 25 |
| source_version_error | 9 |
| unknown | 8 |
| filter_error | 6 |
| schema_error | 2 |

## W25：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 1/1 (100%) |
| `F1|all_V|v1|noerr|sci` | 4/4 (100%) |
| `F1|all_V|v2-3|noerr|plain` | 5/7 (71%) |
| `F1|all_V|v2-3|noerr|sci` | 7/8 (88%) |
| `F1|all_mV|v1|noerr|plain` | 3/4 (75%) |
| `F1|all_mV|v1|noerr|sci` | 4/6 (67%) |
| `F1|all_mV|v1|transient|plain` | 2/3 (67%) |
| `F1|all_mV|v1|transient|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 5/6 (83%) |
| `F1|all_mV|v2-3|noerr|sci` | 3/5 (60%) |
| `F1|all_mV|v2-3|transient|sci` | 2/3 (67%) |
| `F1|mixed|v1|noerr|plain` | 2/2 (100%) |
| `F1|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F1|mixed|v1|transient|plain` | 0/1 (0%) |
| `F1|mixed|v1|transient|sci` | 1/1 (100%) |
| `F1|mixed|v2-3|noerr|plain` | 2/8 (25%) |
| `F1|mixed|v2-3|noerr|sci` | 8/9 (89%) |
| `F1|mixed|v2-3|transient|plain` | 1/2 (50%) |
| `F1|mixed|v2-3|transient|sci` | 2/4 (50%) |
| `F2|all_V|v1|noerr|plain` | 3/3 (100%) |
| `F2|all_V|v1|noerr|sci` | 4/4 (100%) |
| `F2|all_V|v2-3|noerr|plain` | 4/4 (100%) |
| `F2|all_V|v2-3|noerr|sci` | 8/8 (100%) |
| `F2|all_mV|v1|noerr|plain` | 1/2 (50%) |
| `F2|all_mV|v1|noerr|sci` | 1/3 (33%) |
| `F2|all_mV|v1|transient|sci` | 3/4 (75%) |
| `F2|all_mV|v2-3|noerr|plain` | 2/6 (33%) |
| `F2|all_mV|v2-3|noerr|sci` | 3/4 (75%) |
| `F2|all_mV|v2-3|transient|plain` | 1/2 (50%) |
| `F2|all_mV|v2-3|transient|sci` | 3/3 (100%) |
| `F2|mixed|v1|noerr|plain` | 0/3 (0%) |
| `F2|mixed|v1|noerr|sci` | 1/3 (33%) |
| `F2|mixed|v1|transient|plain` | 1/2 (50%) |
| `F2|mixed|v1|transient|sci` | 1/2 (50%) |
| `F2|mixed|v2-3|noerr|plain` | 5/9 (56%) |
| `F2|mixed|v2-3|noerr|sci` | 2/4 (50%) |
| `F2|mixed|v2-3|transient|plain` | 1/3 (33%) |
| `F2|mixed|v2-3|transient|sci` | 1/3 (33%) |

## C1：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| unit_error | 1 |

## C1：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 1/1 (100%) |
| `F1|all_V|v1|noerr|sci` | 4/4 (100%) |
| `F1|all_V|v2-3|noerr|plain` | 7/7 (100%) |
| `F1|all_V|v2-3|noerr|sci` | 7/8 (88%) |
| `F1|all_mV|v1|noerr|plain` | 4/4 (100%) |
| `F1|all_mV|v1|noerr|sci` | 6/6 (100%) |
| `F1|all_mV|v1|transient|plain` | 3/3 (100%) |
| `F1|all_mV|v1|transient|sci` | 1/1 (100%) |
| `F1|all_mV|v2-3|noerr|plain` | 6/6 (100%) |
| `F1|all_mV|v2-3|noerr|sci` | 5/5 (100%) |
| `F1|all_mV|v2-3|transient|sci` | 3/3 (100%) |
| `F1|mixed|v1|noerr|plain` | 2/2 (100%) |
| `F1|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F1|mixed|v1|transient|plain` | 1/1 (100%) |
| `F1|mixed|v1|transient|sci` | 1/1 (100%) |
| `F1|mixed|v2-3|noerr|plain` | 8/8 (100%) |
| `F1|mixed|v2-3|noerr|sci` | 9/9 (100%) |
| `F1|mixed|v2-3|transient|plain` | 2/2 (100%) |
| `F1|mixed|v2-3|transient|sci` | 4/4 (100%) |
| `F2|all_V|v1|noerr|plain` | 3/3 (100%) |
| `F2|all_V|v1|noerr|sci` | 4/4 (100%) |
| `F2|all_V|v2-3|noerr|plain` | 4/4 (100%) |
| `F2|all_V|v2-3|noerr|sci` | 8/8 (100%) |
| `F2|all_mV|v1|noerr|plain` | 2/2 (100%) |
| `F2|all_mV|v1|noerr|sci` | 3/3 (100%) |
| `F2|all_mV|v1|transient|sci` | 4/4 (100%) |
| `F2|all_mV|v2-3|noerr|plain` | 6/6 (100%) |
| `F2|all_mV|v2-3|noerr|sci` | 4/4 (100%) |
| `F2|all_mV|v2-3|transient|plain` | 2/2 (100%) |
| `F2|all_mV|v2-3|transient|sci` | 3/3 (100%) |
| `F2|mixed|v1|noerr|plain` | 3/3 (100%) |
| `F2|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F2|mixed|v1|transient|plain` | 2/2 (100%) |
| `F2|mixed|v1|transient|sci` | 2/2 (100%) |
| `F2|mixed|v2-3|noerr|plain` | 9/9 (100%) |
| `F2|mixed|v2-3|noerr|sci` | 4/4 (100%) |
| `F2|mixed|v2-3|transient|plain` | 3/3 (100%) |
| `F2|mixed|v2-3|transient|sci` | 3/3 (100%) |

## C2：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| filter_error | 1 |

## C2：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 1/1 (100%) |
| `F1|all_V|v1|noerr|sci` | 4/4 (100%) |
| `F1|all_V|v2-3|noerr|plain` | 7/7 (100%) |
| `F1|all_V|v2-3|noerr|sci` | 8/8 (100%) |
| `F1|all_mV|v1|noerr|plain` | 4/4 (100%) |
| `F1|all_mV|v1|noerr|sci` | 6/6 (100%) |
| `F1|all_mV|v1|transient|plain` | 3/3 (100%) |
| `F1|all_mV|v1|transient|sci` | 1/1 (100%) |
| `F1|all_mV|v2-3|noerr|plain` | 6/6 (100%) |
| `F1|all_mV|v2-3|noerr|sci` | 5/5 (100%) |
| `F1|all_mV|v2-3|transient|sci` | 3/3 (100%) |
| `F1|mixed|v1|noerr|plain` | 2/2 (100%) |
| `F1|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F1|mixed|v1|transient|plain` | 1/1 (100%) |
| `F1|mixed|v1|transient|sci` | 1/1 (100%) |
| `F1|mixed|v2-3|noerr|plain` | 8/8 (100%) |
| `F1|mixed|v2-3|noerr|sci` | 9/9 (100%) |
| `F1|mixed|v2-3|transient|plain` | 2/2 (100%) |
| `F1|mixed|v2-3|transient|sci` | 4/4 (100%) |
| `F2|all_V|v1|noerr|plain` | 3/3 (100%) |
| `F2|all_V|v1|noerr|sci` | 4/4 (100%) |
| `F2|all_V|v2-3|noerr|plain` | 3/4 (75%) |
| `F2|all_V|v2-3|noerr|sci` | 8/8 (100%) |
| `F2|all_mV|v1|noerr|plain` | 2/2 (100%) |
| `F2|all_mV|v1|noerr|sci` | 3/3 (100%) |
| `F2|all_mV|v1|transient|sci` | 4/4 (100%) |
| `F2|all_mV|v2-3|noerr|plain` | 6/6 (100%) |
| `F2|all_mV|v2-3|noerr|sci` | 4/4 (100%) |
| `F2|all_mV|v2-3|transient|plain` | 2/2 (100%) |
| `F2|all_mV|v2-3|transient|sci` | 3/3 (100%) |
| `F2|mixed|v1|noerr|plain` | 3/3 (100%) |
| `F2|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F2|mixed|v1|transient|plain` | 2/2 (100%) |
| `F2|mixed|v1|transient|sci` | 2/2 (100%) |
| `F2|mixed|v2-3|noerr|plain` | 9/9 (100%) |
| `F2|mixed|v2-3|noerr|sci` | 4/4 (100%) |
| `F2|mixed|v2-3|transient|plain` | 3/3 (100%) |
| `F2|mixed|v2-3|transient|sci` | 3/3 (100%) |

## C3：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| （无失败） | 0 |

## C3：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 1/1 (100%) |
| `F1|all_V|v1|noerr|sci` | 4/4 (100%) |
| `F1|all_V|v2-3|noerr|plain` | 7/7 (100%) |
| `F1|all_V|v2-3|noerr|sci` | 8/8 (100%) |
| `F1|all_mV|v1|noerr|plain` | 4/4 (100%) |
| `F1|all_mV|v1|noerr|sci` | 6/6 (100%) |
| `F1|all_mV|v1|transient|plain` | 3/3 (100%) |
| `F1|all_mV|v1|transient|sci` | 1/1 (100%) |
| `F1|all_mV|v2-3|noerr|plain` | 6/6 (100%) |
| `F1|all_mV|v2-3|noerr|sci` | 5/5 (100%) |
| `F1|all_mV|v2-3|transient|sci` | 3/3 (100%) |
| `F1|mixed|v1|noerr|plain` | 2/2 (100%) |
| `F1|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F1|mixed|v1|transient|plain` | 1/1 (100%) |
| `F1|mixed|v1|transient|sci` | 1/1 (100%) |
| `F1|mixed|v2-3|noerr|plain` | 8/8 (100%) |
| `F1|mixed|v2-3|noerr|sci` | 9/9 (100%) |
| `F1|mixed|v2-3|transient|plain` | 2/2 (100%) |
| `F1|mixed|v2-3|transient|sci` | 4/4 (100%) |
| `F2|all_V|v1|noerr|plain` | 3/3 (100%) |
| `F2|all_V|v1|noerr|sci` | 4/4 (100%) |
| `F2|all_V|v2-3|noerr|plain` | 4/4 (100%) |
| `F2|all_V|v2-3|noerr|sci` | 8/8 (100%) |
| `F2|all_mV|v1|noerr|plain` | 2/2 (100%) |
| `F2|all_mV|v1|noerr|sci` | 3/3 (100%) |
| `F2|all_mV|v1|transient|sci` | 4/4 (100%) |
| `F2|all_mV|v2-3|noerr|plain` | 6/6 (100%) |
| `F2|all_mV|v2-3|noerr|sci` | 4/4 (100%) |
| `F2|all_mV|v2-3|transient|plain` | 2/2 (100%) |
| `F2|all_mV|v2-3|transient|sci` | 3/3 (100%) |
| `F2|mixed|v1|noerr|plain` | 3/3 (100%) |
| `F2|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F2|mixed|v1|transient|plain` | 2/2 (100%) |
| `F2|mixed|v1|transient|sci` | 2/2 (100%) |
| `F2|mixed|v2-3|noerr|plain` | 9/9 (100%) |
| `F2|mixed|v2-3|noerr|sci` | 4/4 (100%) |
| `F2|mixed|v2-3|transient|plain` | 3/3 (100%) |
| `F2|mixed|v2-3|transient|sci` | 3/3 (100%) |

## P1：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 56 |
| schema_error | 8 |
| unknown | 7 |
| filter_error | 5 |
| unit_error | 3 |
| recovery_failure | 1 |

## P1：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 0/1 (0%) |
| `F1|all_V|v1|noerr|sci` | 2/4 (50%) |
| `F1|all_V|v2-3|noerr|plain` | 2/7 (29%) |
| `F1|all_V|v2-3|noerr|sci` | 2/8 (25%) |
| `F1|all_mV|v1|noerr|plain` | 2/4 (50%) |
| `F1|all_mV|v1|noerr|sci` | 3/6 (50%) |
| `F1|all_mV|v1|transient|plain` | 1/3 (33%) |
| `F1|all_mV|v1|transient|sci` | 1/1 (100%) |
| `F1|all_mV|v2-3|noerr|plain` | 2/6 (33%) |
| `F1|all_mV|v2-3|noerr|sci` | 2/5 (40%) |
| `F1|all_mV|v2-3|transient|sci` | 2/3 (67%) |
| `F1|mixed|v1|noerr|plain` | 0/2 (0%) |
| `F1|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F1|mixed|v1|transient|plain` | 0/1 (0%) |
| `F1|mixed|v1|transient|sci` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 2/8 (25%) |
| `F1|mixed|v2-3|noerr|sci` | 3/9 (33%) |
| `F1|mixed|v2-3|transient|plain` | 1/2 (50%) |
| `F1|mixed|v2-3|transient|sci` | 2/4 (50%) |
| `F2|all_V|v1|noerr|plain` | 1/3 (33%) |
| `F2|all_V|v1|noerr|sci` | 3/4 (75%) |
| `F2|all_V|v2-3|noerr|plain` | 2/4 (50%) |
| `F2|all_V|v2-3|noerr|sci` | 3/8 (38%) |
| `F2|all_mV|v1|noerr|plain` | 1/2 (50%) |
| `F2|all_mV|v1|noerr|sci` | 2/3 (67%) |
| `F2|all_mV|v1|transient|sci` | 1/4 (25%) |
| `F2|all_mV|v2-3|noerr|plain` | 4/6 (67%) |
| `F2|all_mV|v2-3|noerr|sci` | 3/4 (75%) |
| `F2|all_mV|v2-3|transient|plain` | 2/2 (100%) |
| `F2|all_mV|v2-3|transient|sci` | 2/3 (67%) |
| `F2|mixed|v1|noerr|plain` | 2/3 (67%) |
| `F2|mixed|v1|noerr|sci` | 2/3 (67%) |
| `F2|mixed|v1|transient|plain` | 0/2 (0%) |
| `F2|mixed|v1|transient|sci` | 2/2 (100%) |
| `F2|mixed|v2-3|noerr|plain` | 5/9 (56%) |
| `F2|mixed|v2-3|noerr|sci` | 2/4 (50%) |
| `F2|mixed|v2-3|transient|plain` | 1/3 (33%) |
| `F2|mixed|v2-3|transient|sci` | 2/3 (67%) |

## CP1：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| schema_error | 82 |
| dependency_error | 49 |
| unknown | 16 |
| no_tool_use | 2 |
| filter_error | 1 |

## CP1：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 0/1 (0%) |
| `F1|all_V|v1|noerr|sci` | 0/4 (0%) |
| `F1|all_V|v2-3|noerr|plain` | 0/7 (0%) |
| `F1|all_V|v2-3|noerr|sci` | 0/8 (0%) |
| `F1|all_mV|v1|noerr|plain` | 0/4 (0%) |
| `F1|all_mV|v1|noerr|sci` | 0/6 (0%) |
| `F1|all_mV|v1|transient|plain` | 0/3 (0%) |
| `F1|all_mV|v1|transient|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 0/6 (0%) |
| `F1|all_mV|v2-3|noerr|sci` | 0/5 (0%) |
| `F1|all_mV|v2-3|transient|sci` | 0/3 (0%) |
| `F1|mixed|v1|noerr|plain` | 0/2 (0%) |
| `F1|mixed|v1|noerr|sci` | 0/3 (0%) |
| `F1|mixed|v1|transient|plain` | 0/1 (0%) |
| `F1|mixed|v1|transient|sci` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 0/8 (0%) |
| `F1|mixed|v2-3|noerr|sci` | 0/9 (0%) |
| `F1|mixed|v2-3|transient|plain` | 0/2 (0%) |
| `F1|mixed|v2-3|transient|sci` | 0/4 (0%) |
| `F2|all_V|v1|noerr|plain` | 0/3 (0%) |
| `F2|all_V|v1|noerr|sci` | 0/4 (0%) |
| `F2|all_V|v2-3|noerr|plain` | 0/4 (0%) |
| `F2|all_V|v2-3|noerr|sci` | 0/8 (0%) |
| `F2|all_mV|v1|noerr|plain` | 0/2 (0%) |
| `F2|all_mV|v1|noerr|sci` | 0/3 (0%) |
| `F2|all_mV|v1|transient|sci` | 0/4 (0%) |
| `F2|all_mV|v2-3|noerr|plain` | 0/6 (0%) |
| `F2|all_mV|v2-3|noerr|sci` | 0/4 (0%) |
| `F2|all_mV|v2-3|transient|plain` | 0/2 (0%) |
| `F2|all_mV|v2-3|transient|sci` | 0/3 (0%) |
| `F2|mixed|v1|noerr|plain` | 0/3 (0%) |
| `F2|mixed|v1|noerr|sci` | 0/3 (0%) |
| `F2|mixed|v1|transient|plain` | 0/2 (0%) |
| `F2|mixed|v1|transient|sci` | 0/2 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/9 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/4 (0%) |
| `F2|mixed|v2-3|transient|plain` | 0/3 (0%) |
| `F2|mixed|v2-3|transient|sci` | 0/3 (0%) |
