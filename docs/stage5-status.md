# 阶段五（精简版，D17）进度

规则：D16，加上 D17 的缩减（P、CP 只跑种子 1）。每做完一步在这里补一行。

| 日期 | 步骤 | 结果 |
|---|---|---|
| 2026-11-26 | 读 D16 和 `scripts/kaggle_stage5.sh` | 脚本是一次跑完的：核对 → 难度检查 → 训练 6 个 LoRA → 评测 → 报告。 |
| 2026-11-26 | 在 decisions.md 写下 D17 | 缩减如实记下：只训 P1、CP1；H4–H6 照 D16 的规则全部"不判定"，只作描述。 |
| 2026-11-26 | 脚本加两个开关（a3ea9a9） | `STAGE5_DPO_SEEDS=1`：P、CP、WC 只跑种子 1，C1–C3 的难度检查和 test_hard 不变；`STAGE5_GATE_ONLY=1`：核对和难度检查做完就打包停下。在 CPU 上预演两遍（参考策略，不合并、不训练）：只做难度检查的一遍在检查后停下；拿它的输出当输入再跑一遍，难度检查的评测直接恢复，只训 P1、CP1，对比报告里 H4–H6 显示"不判定：两边都完整的种子只有 1 个"。 |
| 2026-11-26 | 建 Kaggle notebook，开跑难度检查 | 私有 notebook `billina/evidenceloop-stage5` 第 1 版：GPU T4，联网，输入是 `billina/evidenceloop-stage4` 的输出（核对过里面有 W25、C1–C3 的 adapter 和训练日志、W25 在 train_mining 上的评测），运行上限 2 小时。命令：`STAGE5_DPO_SEEDS=1 STAGE5_GATE_ONLY=1 bash scripts/kaggle_stage5.sh`，代码是 stage5-dpo 分支。 |
| | 难度检查的结果 | 跑着，还没出结果 |
| | 估算训练和评测的 GPU 时长 | 还没做 |
