# 阶段三：train_mining

- A：环境 env-0.2.1，验证器 ver-0.1.6
- W25：环境 env-0.2.1，验证器 ver-0.1.6

| 指标 | A | W25 |
| --- | --- | --- |
| 成功数/总数 | 1/200 (0%) | 131/200 (66%) |
| numeric_pass | 1/200 (0%) | 131/200 (66%) |
| unit_pass | 142/200 (71%) | 196/200 (98%) |
| provenance_pass | 107/200 (54%) | 177/200 (88%) |
| state_pass | 150/200 (75%) | 200/200 (100%) |
| permission_pass | 200/200 (100%) | 200/200 (100%) |
| 数值失败中可归因到错误路径 | 91/199 (46%) | 57/69 (83%) |
| 有未溯源参数的轨迹 | 84/200 (42%) | 2/200 (1%) |
| 报告里有工具没算出过的数 | 53/200 (26%) | 1/200 (0%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/200 (0%) | 0/200 (0%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 122/200 (61%) | 0/200 (0%) |
| 平均轮数 | 9.1 | 8.0 |

## A：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 65 |
| filter_error | 44 |
| schema_error | 42 |
| unknown | 25 |
| source_version_error | 16 |
| unit_error | 5 |
| unsupported_number | 2 |

## A：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 0/3 (0%) |
| `F1|all_V|v1|noerr|sci` | 0/4 (0%) |
| `F1|all_V|v2-3|noerr|plain` | 0/14 (0%) |
| `F1|all_V|v2-3|noerr|sci` | 1/10 (10%) |
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

## W25：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| unit_error | 32 |
| source_version_error | 22 |
| filter_error | 10 |
| unknown | 5 |

## W25：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_V|v1|noerr|plain` | 3/3 (100%) |
| `F1|all_V|v1|noerr|sci` | 4/4 (100%) |
| `F1|all_V|v2-3|noerr|plain` | 13/14 (93%) |
| `F1|all_V|v2-3|noerr|sci` | 10/10 (100%) |
| `F1|all_mV|v1|noerr|plain` | 4/5 (80%) |
| `F1|all_mV|v1|noerr|sci` | 2/2 (100%) |
| `F1|all_mV|v1|transient|plain` | 2/2 (100%) |
| `F1|all_mV|v1|transient|sci` | 2/2 (100%) |
| `F1|all_mV|v2-3|noerr|plain` | 3/7 (43%) |
| `F1|all_mV|v2-3|noerr|sci` | 5/8 (62%) |
| `F1|all_mV|v2-3|transient|plain` | 0/3 (0%) |
| `F1|all_mV|v2-3|transient|sci` | 0/5 (0%) |
| `F1|mixed|v1|noerr|plain` | 4/4 (100%) |
| `F1|mixed|v1|noerr|sci` | 5/7 (71%) |
| `F1|mixed|v1|transient|sci` | 1/1 (100%) |
| `F1|mixed|v2-3|noerr|plain` | 4/6 (67%) |
| `F1|mixed|v2-3|noerr|sci` | 4/9 (44%) |
| `F1|mixed|v2-3|transient|plain` | 2/7 (29%) |
| `F1|mixed|v2-3|transient|sci` | 1/2 (50%) |
| `F2|all_V|v1|noerr|plain` | 8/8 (100%) |
| `F2|all_V|v1|noerr|sci` | 5/7 (71%) |
| `F2|all_V|v2-3|noerr|plain` | 7/8 (88%) |
| `F2|all_V|v2-3|noerr|sci` | 11/12 (92%) |
| `F2|all_mV|v1|noerr|plain` | 3/6 (50%) |
| `F2|all_mV|v1|noerr|sci` | 2/2 (100%) |
| `F2|all_mV|v1|transient|plain` | 2/2 (100%) |
| `F2|all_mV|v1|transient|sci` | 0/1 (0%) |
| `F2|all_mV|v2-3|noerr|plain` | 4/10 (40%) |
| `F2|all_mV|v2-3|noerr|sci` | 1/6 (17%) |
| `F2|all_mV|v2-3|transient|plain` | 2/6 (33%) |
| `F2|all_mV|v2-3|transient|sci` | 0/3 (0%) |
| `F2|mixed|v1|noerr|plain` | 4/4 (100%) |
| `F2|mixed|v1|noerr|sci` | 1/1 (100%) |
| `F2|mixed|v1|transient|plain` | 2/2 (100%) |
| `F2|mixed|v1|transient|sci` | 1/2 (50%) |
| `F2|mixed|v2-3|noerr|plain` | 6/8 (75%) |
| `F2|mixed|v2-3|noerr|sci` | 1/3 (33%) |
| `F2|mixed|v2-3|transient|plain` | 1/3 (33%) |
| `F2|mixed|v2-3|transient|sci` | 1/5 (20%) |
