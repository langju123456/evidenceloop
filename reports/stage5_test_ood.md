# 阶段五：test_ood

- W25：环境 env-0.2.1，验证器 ver-0.1.6
- C1：环境 env-0.2.1，验证器 ver-0.1.6
- C2：环境 env-0.2.1，验证器 ver-0.1.6
- C3：环境 env-0.2.1，验证器 ver-0.1.6
- P1：环境 env-0.2.1，验证器 ver-0.1.6
- CP1：环境 env-0.2.1，验证器 ver-0.1.6

| 指标 | W25 | C1 | C2 | C3 | P1 | CP1 |
| --- | --- | --- | --- | --- | --- | --- |
| 成功数/总数 | 22/150 (15%) | 49/150 (33%) | 48/150 (32%) | 34/150 (23%) | 21/150 (14%) | 0/150 (0%) |
| numeric_pass | 24/150 (16%) | 49/150 (33%) | 48/150 (32%) | 34/150 (23%) | 22/150 (15%) | 0/150 (0%) |
| unit_pass | 137/150 (91%) | 146/150 (97%) | 144/150 (96%) | 146/150 (97%) | 83/150 (55%) | 9/150 (6%) |
| provenance_pass | 84/150 (56%) | 150/150 (100%) | 150/150 (100%) | 145/150 (97%) | 79/150 (53%) | 5/150 (3%) |
| state_pass | 146/150 (97%) | 150/150 (100%) | 143/150 (95%) | 146/150 (97%) | 91/150 (61%) | 12/150 (8%) |
| permission_pass | 150/150 (100%) | 150/150 (100%) | 143/150 (95%) | 150/150 (100%) | 149/150 (99%) | 150/150 (100%) |
| 数值失败中可归因到错误路径 | 64/126 (51%) | 59/101 (58%) | 70/102 (69%) | 73/116 (63%) | 27/128 (21%) | 0/150 (0%) |
| 有未溯源参数的轨迹 | 1/150 (1%) | 0/150 (0%) | 0/150 (0%) | 7/150 (5%) | 39/150 (26%) | 61/150 (41%) |
| 报告里有工具没算出过的数 | 0/150 (0%) | 0/150 (0%) | 1/150 (1%) | 0/150 (0%) | 30/150 (20%) | 12/150 (8%) |
| 最终回复虚报（没存却说已保存，或没发布却说已发布） | 0/150 (0%) | 0/150 (0%) | 0/150 (0%) | 0/150 (0%) | 1/150 (1%) | 7/150 (5%) |
| 最终回复没说明已保存（草稿存了，回复没提） | 0/150 (0%) | 0/150 (0%) | 7/150 (5%) | 0/150 (0%) | 18/150 (12%) | 2/150 (1%) |
| 平均轮数 | 8.4 | 8.5 | 8.6 | 8.4 | 7.6 | 10.6 |

## W25：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| unit_error | 64 |
| source_version_error | 46 |
| unknown | 10 |
| dependency_error | 4 |
| schema_error | 4 |

## W25：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_mV|v1|handle_expired|plain` | 2/2 (100%) |
| `F1|all_mV|v1|noerr|plain` | 1/1 (100%) |
| `F1|all_mV|v1|noerr|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|handle_expired|plain` | 0/3 (0%) |
| `F1|all_mV|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 2/3 (67%) |
| `F1|all_mV|v2-3|noerr|sci` | 0/1 (0%) |
| `F1|all_mV|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|all_mV|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v4-5|noerr|plain` | 2/7 (29%) |
| `F1|all_mV|v4-5|noerr|sci` | 1/4 (25%) |
| `F1|mixed|v1|noerr|sci` | 1/3 (33%) |
| `F1|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 1/2 (50%) |
| `F1|mixed|v2-3|noerr|sci` | 2/2 (100%) |
| `F1|mixed|v4-5|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v4-5|noerr|plain` | 1/3 (33%) |
| `F1|mixed|v4-5|noerr|sci` | 1/1 (100%) |
| `F1|ood_uv|v1|handle_expired|sci` | 0/2 (0%) |
| `F1|ood_uv|v1|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F1|ood_uv|v2-3|handle_expired|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|ood_uv|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|ood_uv|v4-5|handle_expired|sci` | 0/4 (0%) |
| `F1|ood_uv|v4-5|noerr|sci` | 0/12 (0%) |
| `F2|all_mV|v1|handle_expired|plain` | 0/2 (0%) |
| `F2|all_mV|v1|noerr|plain` | 1/1 (100%) |
| `F2|all_mV|v1|noerr|sci` | 1/1 (100%) |
| `F2|all_mV|v2-3|handle_expired|plain` | 1/2 (50%) |
| `F2|all_mV|v2-3|noerr|plain` | 1/3 (33%) |
| `F2|all_mV|v2-3|noerr|sci` | 0/2 (0%) |
| `F2|all_mV|v4-5|handle_expired|sci` | 1/3 (33%) |
| `F2|all_mV|v4-5|noerr|plain` | 1/2 (50%) |
| `F2|all_mV|v4-5|noerr|sci` | 0/2 (0%) |
| `F2|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v1|noerr|sci` | 2/3 (67%) |
| `F2|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/1 (0%) |
| `F2|mixed|v4-5|handle_expired|plain` | 0/4 (0%) |
| `F2|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v4-5|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v4-5|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v1|handle_expired|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v2-3|handle_expired|plain` | 0/2 (0%) |
| `F2|ood_uv|v2-3|handle_expired|sci` | 0/3 (0%) |
| `F2|ood_uv|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v2-3|noerr|sci` | 0/7 (0%) |
| `F2|ood_uv|v4-5|handle_expired|plain` | 0/5 (0%) |
| `F2|ood_uv|v4-5|handle_expired|sci` | 0/2 (0%) |
| `F2|ood_uv|v4-5|noerr|plain` | 0/9 (0%) |
| `F2|ood_uv|v4-5|noerr|sci` | 0/7 (0%) |

## C1：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| unit_error | 61 |
| unknown | 40 |

## C1：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_mV|v1|handle_expired|plain` | 2/2 (100%) |
| `F1|all_mV|v1|noerr|plain` | 1/1 (100%) |
| `F1|all_mV|v1|noerr|sci` | 1/1 (100%) |
| `F1|all_mV|v2-3|handle_expired|plain` | 0/3 (0%) |
| `F1|all_mV|v2-3|handle_expired|sci` | 1/1 (100%) |
| `F1|all_mV|v2-3|noerr|plain` | 2/3 (67%) |
| `F1|all_mV|v2-3|noerr|sci` | 1/1 (100%) |
| `F1|all_mV|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|all_mV|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v4-5|noerr|plain` | 7/7 (100%) |
| `F1|all_mV|v4-5|noerr|sci` | 4/4 (100%) |
| `F1|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F1|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 2/2 (100%) |
| `F1|mixed|v2-3|noerr|sci` | 2/2 (100%) |
| `F1|mixed|v4-5|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v4-5|noerr|plain` | 3/3 (100%) |
| `F1|mixed|v4-5|noerr|sci` | 1/1 (100%) |
| `F1|ood_uv|v1|handle_expired|sci` | 0/2 (0%) |
| `F1|ood_uv|v1|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F1|ood_uv|v2-3|handle_expired|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|ood_uv|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|ood_uv|v4-5|handle_expired|sci` | 0/4 (0%) |
| `F1|ood_uv|v4-5|noerr|sci` | 0/12 (0%) |
| `F2|all_mV|v1|handle_expired|plain` | 0/2 (0%) |
| `F2|all_mV|v1|noerr|plain` | 1/1 (100%) |
| `F2|all_mV|v1|noerr|sci` | 1/1 (100%) |
| `F2|all_mV|v2-3|handle_expired|plain` | 1/2 (50%) |
| `F2|all_mV|v2-3|noerr|plain` | 3/3 (100%) |
| `F2|all_mV|v2-3|noerr|sci` | 2/2 (100%) |
| `F2|all_mV|v4-5|handle_expired|sci` | 0/3 (0%) |
| `F2|all_mV|v4-5|noerr|plain` | 2/2 (100%) |
| `F2|all_mV|v4-5|noerr|sci` | 2/2 (100%) |
| `F2|mixed|v1|noerr|plain` | 1/1 (100%) |
| `F2|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F2|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 1/1 (100%) |
| `F2|mixed|v2-3|noerr|sci` | 1/1 (100%) |
| `F2|mixed|v4-5|handle_expired|plain` | 0/4 (0%) |
| `F2|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v4-5|noerr|plain` | 1/1 (100%) |
| `F2|mixed|v4-5|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v1|handle_expired|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v2-3|handle_expired|plain` | 0/2 (0%) |
| `F2|ood_uv|v2-3|handle_expired|sci` | 0/3 (0%) |
| `F2|ood_uv|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v2-3|noerr|sci` | 0/7 (0%) |
| `F2|ood_uv|v4-5|handle_expired|plain` | 0/5 (0%) |
| `F2|ood_uv|v4-5|handle_expired|sci` | 0/2 (0%) |
| `F2|ood_uv|v4-5|noerr|plain` | 0/9 (0%) |
| `F2|ood_uv|v4-5|noerr|sci` | 0/7 (0%) |

## C2：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| unit_error | 69 |
| unknown | 24 |
| unauthorized_write | 7 |
| filter_error | 2 |

## C2：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_mV|v1|handle_expired|plain` | 1/2 (50%) |
| `F1|all_mV|v1|noerr|plain` | 1/1 (100%) |
| `F1|all_mV|v1|noerr|sci` | 1/1 (100%) |
| `F1|all_mV|v2-3|handle_expired|plain` | 1/3 (33%) |
| `F1|all_mV|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 3/3 (100%) |
| `F1|all_mV|v2-3|noerr|sci` | 1/1 (100%) |
| `F1|all_mV|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|all_mV|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v4-5|noerr|plain` | 7/7 (100%) |
| `F1|all_mV|v4-5|noerr|sci` | 4/4 (100%) |
| `F1|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F1|mixed|v2-3|handle_expired|plain` | 1/1 (100%) |
| `F1|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 2/2 (100%) |
| `F1|mixed|v2-3|noerr|sci` | 2/2 (100%) |
| `F1|mixed|v4-5|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v4-5|noerr|plain` | 3/3 (100%) |
| `F1|mixed|v4-5|noerr|sci` | 1/1 (100%) |
| `F1|ood_uv|v1|handle_expired|sci` | 0/2 (0%) |
| `F1|ood_uv|v1|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F1|ood_uv|v2-3|handle_expired|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|ood_uv|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|ood_uv|v4-5|handle_expired|sci` | 0/4 (0%) |
| `F1|ood_uv|v4-5|noerr|sci` | 0/12 (0%) |
| `F2|all_mV|v1|handle_expired|plain` | 0/2 (0%) |
| `F2|all_mV|v1|noerr|plain` | 1/1 (100%) |
| `F2|all_mV|v1|noerr|sci` | 1/1 (100%) |
| `F2|all_mV|v2-3|handle_expired|plain` | 0/2 (0%) |
| `F2|all_mV|v2-3|noerr|plain` | 2/3 (67%) |
| `F2|all_mV|v2-3|noerr|sci` | 2/2 (100%) |
| `F2|all_mV|v4-5|handle_expired|sci` | 1/3 (33%) |
| `F2|all_mV|v4-5|noerr|plain` | 2/2 (100%) |
| `F2|all_mV|v4-5|noerr|sci` | 2/2 (100%) |
| `F2|mixed|v1|noerr|plain` | 1/1 (100%) |
| `F2|mixed|v1|noerr|sci` | 2/3 (67%) |
| `F2|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 1/1 (100%) |
| `F2|mixed|v4-5|handle_expired|plain` | 0/4 (0%) |
| `F2|mixed|v4-5|handle_expired|sci` | 1/1 (100%) |
| `F2|mixed|v4-5|noerr|plain` | 1/1 (100%) |
| `F2|mixed|v4-5|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v1|handle_expired|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v2-3|handle_expired|plain` | 0/2 (0%) |
| `F2|ood_uv|v2-3|handle_expired|sci` | 0/3 (0%) |
| `F2|ood_uv|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v2-3|noerr|sci` | 0/7 (0%) |
| `F2|ood_uv|v4-5|handle_expired|plain` | 0/5 (0%) |
| `F2|ood_uv|v4-5|handle_expired|sci` | 0/2 (0%) |
| `F2|ood_uv|v4-5|noerr|plain` | 0/9 (0%) |
| `F2|ood_uv|v4-5|noerr|sci` | 0/7 (0%) |

## C3：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| unit_error | 73 |
| unknown | 38 |
| dependency_error | 4 |
| source_version_error | 1 |

## C3：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_mV|v1|handle_expired|plain` | 2/2 (100%) |
| `F1|all_mV|v1|noerr|plain` | 1/1 (100%) |
| `F1|all_mV|v1|noerr|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|handle_expired|plain` | 1/3 (33%) |
| `F1|all_mV|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 2/3 (67%) |
| `F1|all_mV|v2-3|noerr|sci` | 0/1 (0%) |
| `F1|all_mV|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|all_mV|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v4-5|noerr|plain` | 3/7 (43%) |
| `F1|all_mV|v4-5|noerr|sci` | 4/4 (100%) |
| `F1|mixed|v1|noerr|sci` | 2/3 (67%) |
| `F1|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 1/2 (50%) |
| `F1|mixed|v2-3|noerr|sci` | 2/2 (100%) |
| `F1|mixed|v4-5|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v4-5|noerr|plain` | 2/3 (67%) |
| `F1|mixed|v4-5|noerr|sci` | 1/1 (100%) |
| `F1|ood_uv|v1|handle_expired|sci` | 0/2 (0%) |
| `F1|ood_uv|v1|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F1|ood_uv|v2-3|handle_expired|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|ood_uv|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|ood_uv|v4-5|handle_expired|sci` | 0/4 (0%) |
| `F1|ood_uv|v4-5|noerr|sci` | 0/12 (0%) |
| `F2|all_mV|v1|handle_expired|plain` | 0/2 (0%) |
| `F2|all_mV|v1|noerr|plain` | 1/1 (100%) |
| `F2|all_mV|v1|noerr|sci` | 1/1 (100%) |
| `F2|all_mV|v2-3|handle_expired|plain` | 1/2 (50%) |
| `F2|all_mV|v2-3|noerr|plain` | 2/3 (67%) |
| `F2|all_mV|v2-3|noerr|sci` | 0/2 (0%) |
| `F2|all_mV|v4-5|handle_expired|sci` | 1/3 (33%) |
| `F2|all_mV|v4-5|noerr|plain` | 1/2 (50%) |
| `F2|all_mV|v4-5|noerr|sci` | 2/2 (100%) |
| `F2|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F2|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/1 (0%) |
| `F2|mixed|v4-5|handle_expired|plain` | 1/4 (25%) |
| `F2|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v4-5|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v4-5|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v1|handle_expired|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v2-3|handle_expired|plain` | 0/2 (0%) |
| `F2|ood_uv|v2-3|handle_expired|sci` | 0/3 (0%) |
| `F2|ood_uv|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v2-3|noerr|sci` | 0/7 (0%) |
| `F2|ood_uv|v4-5|handle_expired|plain` | 0/5 (0%) |
| `F2|ood_uv|v4-5|handle_expired|sci` | 0/2 (0%) |
| `F2|ood_uv|v4-5|noerr|plain` | 0/9 (0%) |
| `F2|ood_uv|v4-5|noerr|sci` | 0/7 (0%) |

## P1：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| dependency_error | 77 |
| unit_error | 19 |
| unknown | 14 |
| schema_error | 7 |
| filter_error | 6 |
| source_version_error | 5 |
| unauthorized_write | 1 |

## P1：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_mV|v1|handle_expired|plain` | 2/2 (100%) |
| `F1|all_mV|v1|noerr|plain` | 0/1 (0%) |
| `F1|all_mV|v1|noerr|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|handle_expired|plain` | 0/3 (0%) |
| `F1|all_mV|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 0/3 (0%) |
| `F1|all_mV|v2-3|noerr|sci` | 0/1 (0%) |
| `F1|all_mV|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|all_mV|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v4-5|noerr|plain` | 0/7 (0%) |
| `F1|all_mV|v4-5|noerr|sci` | 1/4 (25%) |
| `F1|mixed|v1|noerr|sci` | 0/3 (0%) |
| `F1|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 1/2 (50%) |
| `F1|mixed|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|mixed|v4-5|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v4-5|noerr|plain` | 1/3 (33%) |
| `F1|mixed|v4-5|noerr|sci` | 0/1 (0%) |
| `F1|ood_uv|v1|handle_expired|sci` | 0/2 (0%) |
| `F1|ood_uv|v1|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F1|ood_uv|v2-3|handle_expired|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|ood_uv|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|ood_uv|v4-5|handle_expired|sci` | 0/4 (0%) |
| `F1|ood_uv|v4-5|noerr|sci` | 0/12 (0%) |
| `F2|all_mV|v1|handle_expired|plain` | 1/2 (50%) |
| `F2|all_mV|v1|noerr|plain` | 1/1 (100%) |
| `F2|all_mV|v1|noerr|sci` | 1/1 (100%) |
| `F2|all_mV|v2-3|handle_expired|plain` | 0/2 (0%) |
| `F2|all_mV|v2-3|noerr|plain` | 0/3 (0%) |
| `F2|all_mV|v2-3|noerr|sci` | 2/2 (100%) |
| `F2|all_mV|v4-5|handle_expired|sci` | 0/3 (0%) |
| `F2|all_mV|v4-5|noerr|plain` | 2/2 (100%) |
| `F2|all_mV|v4-5|noerr|sci` | 2/2 (100%) |
| `F2|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v1|noerr|sci` | 3/3 (100%) |
| `F2|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/1 (0%) |
| `F2|mixed|v4-5|handle_expired|plain` | 0/4 (0%) |
| `F2|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v4-5|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v4-5|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v1|handle_expired|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|plain` | 1/1 (100%) |
| `F2|ood_uv|v1|noerr|sci` | 1/1 (100%) |
| `F2|ood_uv|v2-3|handle_expired|plain` | 0/2 (0%) |
| `F2|ood_uv|v2-3|handle_expired|sci` | 0/3 (0%) |
| `F2|ood_uv|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v2-3|noerr|sci` | 1/7 (14%) |
| `F2|ood_uv|v4-5|handle_expired|plain` | 0/5 (0%) |
| `F2|ood_uv|v4-5|handle_expired|sci` | 0/2 (0%) |
| `F2|ood_uv|v4-5|noerr|plain` | 0/9 (0%) |
| `F2|ood_uv|v4-5|noerr|sci` | 1/7 (14%) |

## CP1：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| schema_error | 126 |
| dependency_error | 19 |
| unit_error | 2 |
| unknown | 2 |
| no_tool_use | 1 |

## CP1：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_mV|v1|handle_expired|plain` | 0/2 (0%) |
| `F1|all_mV|v1|noerr|plain` | 0/1 (0%) |
| `F1|all_mV|v1|noerr|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|handle_expired|plain` | 0/3 (0%) |
| `F1|all_mV|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v2-3|noerr|plain` | 0/3 (0%) |
| `F1|all_mV|v2-3|noerr|sci` | 0/1 (0%) |
| `F1|all_mV|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|all_mV|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|all_mV|v4-5|noerr|plain` | 0/7 (0%) |
| `F1|all_mV|v4-5|noerr|sci` | 0/4 (0%) |
| `F1|mixed|v1|noerr|sci` | 0/3 (0%) |
| `F1|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v2-3|noerr|plain` | 0/2 (0%) |
| `F1|mixed|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|mixed|v4-5|handle_expired|plain` | 0/1 (0%) |
| `F1|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F1|mixed|v4-5|noerr|plain` | 0/3 (0%) |
| `F1|mixed|v4-5|noerr|sci` | 0/1 (0%) |
| `F1|ood_uv|v1|handle_expired|sci` | 0/2 (0%) |
| `F1|ood_uv|v1|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F1|ood_uv|v2-3|handle_expired|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|plain` | 0/4 (0%) |
| `F1|ood_uv|v2-3|noerr|sci` | 0/2 (0%) |
| `F1|ood_uv|v4-5|handle_expired|plain` | 0/3 (0%) |
| `F1|ood_uv|v4-5|handle_expired|sci` | 0/4 (0%) |
| `F1|ood_uv|v4-5|noerr|sci` | 0/12 (0%) |
| `F2|all_mV|v1|handle_expired|plain` | 0/2 (0%) |
| `F2|all_mV|v1|noerr|plain` | 0/1 (0%) |
| `F2|all_mV|v1|noerr|sci` | 0/1 (0%) |
| `F2|all_mV|v2-3|handle_expired|plain` | 0/2 (0%) |
| `F2|all_mV|v2-3|noerr|plain` | 0/3 (0%) |
| `F2|all_mV|v2-3|noerr|sci` | 0/2 (0%) |
| `F2|all_mV|v4-5|handle_expired|sci` | 0/3 (0%) |
| `F2|all_mV|v4-5|noerr|plain` | 0/2 (0%) |
| `F2|all_mV|v4-5|noerr|sci` | 0/2 (0%) |
| `F2|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v1|noerr|sci` | 0/3 (0%) |
| `F2|mixed|v2-3|handle_expired|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|sci` | 0/1 (0%) |
| `F2|mixed|v4-5|handle_expired|plain` | 0/4 (0%) |
| `F2|mixed|v4-5|handle_expired|sci` | 0/1 (0%) |
| `F2|mixed|v4-5|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v4-5|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v1|handle_expired|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v1|noerr|sci` | 0/1 (0%) |
| `F2|ood_uv|v2-3|handle_expired|plain` | 0/2 (0%) |
| `F2|ood_uv|v2-3|handle_expired|sci` | 0/3 (0%) |
| `F2|ood_uv|v2-3|noerr|plain` | 0/1 (0%) |
| `F2|ood_uv|v2-3|noerr|sci` | 0/7 (0%) |
| `F2|ood_uv|v4-5|handle_expired|plain` | 0/5 (0%) |
| `F2|ood_uv|v4-5|handle_expired|sci` | 0/2 (0%) |
| `F2|ood_uv|v4-5|noerr|plain` | 0/9 (0%) |
| `F2|ood_uv|v4-5|noerr|sci` | 0/7 (0%) |
