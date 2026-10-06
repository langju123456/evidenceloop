# EvidenceLoop 基线报告

| 指标 | qwen3-0.6b-mlx |
| --- | --- |
| 成功数/总数 | 0/5 (0%) |
| numeric_pass | 0/5 (0%) |
| unit_pass | 0/5 (0%) |
| provenance_pass | 0/5 (0%) |
| state_pass | 0/5 (0%) |
| permission_pass | 5/5 (100%) |
| 数值失败中可归因到错误路径 | 0/5 (0%) |
| 有未溯源参数的轨迹 | 2/5 (40%) |
| 回复与状态不一致 | 3/5 (60%) |
| 平均轮数 | 2.8 |

## qwen3-0.6b-mlx：失败类别（主类别）

| 类别 | 数量 |
| --- | --- |
| unsupported_claim | 2 |
| no_tool_use | 2 |
| recovery_failure | 1 |

## qwen3-0.6b-mlx：按难度分桶

| 分桶 | 成功 |
| --- | --- |
| `F1|all_mV|v2-3|transient|plain` | 0/1 (0%) |
| `F2|all_mV|v2-3|noerr|sci` | 0/1 (0%) |
| `F2|all_mV|v2-3|transient|plain` | 0/1 (0%) |
| `F2|mixed|v1|noerr|plain` | 0/1 (0%) |
| `F2|mixed|v2-3|noerr|plain` | 0/1 (0%) |
