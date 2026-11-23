# 同一份宁德时代报告的问答与收件证据

分析师问全年经营现金流，发布负责人要核对三个事实。答案读的是哪一年？出处能否核对？恢复后，收件方真正拿到了几份？打开[逐题页](../../reports/report-lab/review.html)的「产品与收件回执」即可逐项展开。这里接入其他两个项目的固定产物，保留各自的运行事实和判定权限。

## 产品问答

ForgeFlow 通过 FastAPI TestClient 实际调用查询入口和确定性工具，整批 0 次模型调用、外部费用 0。EvidenceLoop 独立抄录原件第 11 页年度列，校验回答的数值、单位、该表引用、产品状态。2025、2024、2023 年依次答出 **133,219,982、96,990,345、92,826,124 千元**；原表未披露 2022 年，该请求得到「待核对」与空引用。验收为 3 次通过、1 次证据不足；第四次的安全弃答单独计数。四条逐次耗时来自上游本机测量。[问答原件](https://github.com/langju123456/forgeflow/blob/e195a0a2f764d30e2d1b5be8a131ceeef95d4b71/preparation/annual-report-workbench/annual-cash-dev.json) · [披露原文](https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF)

## 收件核对

HorizonBench 的任务号是 `catl-fy2025-cfo-receipt`。脚本操作本地收件环境，共用同一份载荷和三个故障条件，每格运行一次。EvidenceLoop 导入既有独立终态断言、收件条数、恢复事件和进程退出码，并核验收件内容指纹。

| 恢复方式 | 正常回执 | 请求未到 | 已收件后回执丢失并崩溃 |
|---|---|---|---|
| 超时即记成功 | 通过 | 失败，0 份 | 通过 |
| 等人工 | 通过 | 失败，仍待处理 | 失败，仍待处理 |
| 换编号重试 | 通过 | 通过 | 失败，2 份 |
| 原编号查收再补送 | 通过 | 通过 | 通过 |

换编号重试与直接记成功同为 2/3，却修好一个场景、同时毁掉另一个场景。可以在逐题页核对第三列的两条收件编号、相同内容指纹和初始退出码 −9。等待人工的终态以本次实验观察截止时点为准。[收件矩阵](https://github.com/langju123456/horizon-bench/blob/c69eb0ef2a32a45eef8057ab7ebd3065e8cc7f88/reports/receipt-experiment/manifest.json) · [重复收件原件](https://github.com/langju123456/horizon-bench/blob/c69eb0ef2a32a45eef8057ab7ebd3065e8cc7f88/reports/receipt-experiment/retry_new_key--receipt_lost_crash/verdict.json)

## 在本机复验

正常浏览和生成 HTML 只需本仓库。交叉复验需要另两个本地 Git 克隆中具备文中指定提交。在 EvidenceLoop 仓库根执行以下命令，替换为自己的克隆路径。

```sh
PYTHONPATH=src python3 -m evidenceloop.cli report import-peer-runs --forge-repo ~/code/forgeflow-desk --horizon-repo ~/code/horizon-bench > /tmp/report-peer-runs.json
cmp /tmp/report-peer-runs.json reports/report-lab/peer-runs-v1.json
PYTHONPATH=src python3 -m evidenceloop.cli report review-page --out /tmp/report-review.html
```

导入从提交读取原始字节，记录 SHA-256 和定位链接；每个来源有单独的派生运行编号，原始任务号、评估编号和来源各占独立字段。问答阶段没有交付产物指纹，收件实验中的内容由场景预置。两者共享业务事实，本次跨项目贯通运行数为 0。下一步由 ForgeFlow 实际产生带共享运行编号、版本和指纹的稿件，再由 HorizonBench 对同一份稿件验收；EvidenceLoop 才能统计整份委托是否成功。
