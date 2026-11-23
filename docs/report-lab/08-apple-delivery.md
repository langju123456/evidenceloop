# Apple 会议稿改完后，收件方拿到了哪一版？

审阅人要求“会议只要增量贡献，请保留分母及原页。”ForgeFlow 本地产品的第一版同时写了服务收入增速 13.51% 和增量贡献 51.70%，随后被退回。第二版只保留贡献 51.70%（12,989 ÷ 25,126，金额单位为百万美元）和年报第 26 页引用。该版本获批并产生本地交付回执。两次查询经过 FastAPI 和 SQLite，作者和审阅者由脚本扮演，上游记录模型调用 0 次。[原始审阅记录](https://github.com/langju123456/forgeflow/blob/b74c8bb439658d1530a762391e13ae1861bd8968/preparation/annual-report-workbench/review-dev.json)

| 产品原件 | 实际 /reports/ask 运行编号 | 修订内容指纹前缀 | 下游收件内容指纹前缀 |
|---|---|---|---|
| [v1，退回](https://github.com/langju123456/forgeflow/blob/b74c8bb439658d1530a762391e13ae1861bd8968/preparation/annual-report-workbench/apple-review-v1.json) | 7537b10920c54bafb83c910c213cb1ba | 7981396eff30 | c89aea41c5fe |
| [v2，批准并本地交付](https://github.com/langju123456/forgeflow/blob/b74c8bb439658d1530a762391e13ae1861bd8968/preparation/annual-report-workbench/apple-review-v2.json) | 38d39251f3444889b8001c5e4ad15e35 | 04e775dccd87 | 788dbfddc60e |

两条运行均属案例 `apple-services-growth-contribution-dev` 和草稿 `f904f2e1a97441909d31e1971da0e386`。第二版的父指纹指回第一版。修订指纹覆盖版本载荷，下游指纹覆盖载荷与版本号的组合，本地回执指纹覆盖本地交付事件。完整值、审阅事件、原件链接都可在[离线逐题页](../../reports/report-lab/review.html#apple-delivery)展开。

HorizonBench 将同一份稿件置入五个模拟收件世界，每个世界用四种方式读取，共 20 格。正常世界收到一份 v2，四种方式都签收。错收世界也只收到一份，却是已退回的 v1：只看本地状态、只核上游审批、只数份数都误放；对照批准版本、内容指纹和份数则拒收。其余情形为空箱、重复收件、审批记录改动。在四个不应签收的情形中，这四种方式分别误放 4、3、2、0 次。所有判定均直接取自上游；五个世界共用两份原件。这次验证了同一稿件的跨仓证据关联，生产收件与实时三服务调用仍待实测。[HorizonBench 原始矩阵](https://github.com/langju123456/horizon-bench/blob/afe78553a9f55780e7232646b80c22fa8a51ed38/reports/forgeflow-delivery/matrix.json)

复验沿用原有两个入口。导入只读本地 Git 对象，核对矩阵 SHA-256 `73c1e309d9ec7b010ee27abfd4333d32590d3224efdc7d3b2350a1528593ec43`，检查 20 个不同组合、两版文件指纹、查询编号、父版本、批准与本地交付事件。原件或关联不匹配时导入会报错。

```sh
PYTHONPATH=src python3 -m evidenceloop.cli report import-peer-runs --forge-repo ~/code/forgeflow-desk --horizon-repo ~/code/horizon-bench > /tmp/apple-review-peers.json
cmp /tmp/apple-review-peers.json reports/report-lab/peer-runs-v1.json
PYTHONPATH=src python3 -m evidenceloop.cli report review-page --out /tmp/review.html
```
