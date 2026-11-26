# 裁判校准（D28）进展

按 `22-judge-calibration-freeze.md` 的顺序推进，每做完一步记一次。

| 步骤 | 状态 | 日期 | 说明 |
|---|---|---|---|
| 1. `el judge agree` 加“规则漏掉的虚报”统计 | 完成 | 2026-11-26 | 输出字段 `missed_false_claims`：人判虚报、关键词规则判如实的条数，裁判抓回几条，裁判自己漏掉几条；不足 5 条时 `meets_criterion_2` 为空。单元测试和端到端测试已加，全部测试通过。 |
| 2. 抽样并冻结（`mac_judge.sh sample`，RUNS=~/code/evidenceloop/runs） | 未开始 | | 抽完先扫样本里有没有本机路径、用户名，再提交。 |
| 3. 生成开发集标注表（`mac_judge.sh form dev`） | 未开始 | | 生成后在浏览器打开，等人工标注。 |
