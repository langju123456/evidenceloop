# 阶段五（精简版，D17）进度

规则：D16，加上 D17 的缩减（P、CP 只跑种子 1）和 D18 的难题（改用 test_ood）。每做完一步在这里补一行。

| 日期 | 步骤 | 结果 |
|---|---|---|
| 2026-11-26 | 读 D16 和 `scripts/kaggle_stage5.sh` | 脚本是一次跑完的：核对 → 难度检查 → 训练 6 个 LoRA → 评测 → 报告。 |
| 2026-11-26 | 在 decisions.md 写下 D17 | 缩减如实记下：只训 P1、CP1；H4–H6 照 D16 的规则全部"不判定"，只作描述。 |
| 2026-11-26 | 脚本加两个开关（a3ea9a9） | `STAGE5_DPO_SEEDS=1`：P、CP、WC 只跑种子 1，C1–C3 的难度检查和 test_hard 不变；`STAGE5_GATE_ONLY=1`：核对和难度检查做完就打包停下。在 CPU 上预演两遍（参考策略，不合并、不训练）：只做难度检查的一遍在检查后停下；拿它的输出当输入再跑一遍，难度检查的评测直接恢复，只训 P1、CP1，对比报告里 H4–H6 显示"不判定：两边都完整的种子只有 1 个"。 |
| 2026-11-26 | 建 Kaggle notebook，开跑难度检查 | 私有 notebook `billina/evidenceloop-stage5` 第 1 版：GPU T4，联网，输入是 `billina/evidenceloop-stage4` 的输出（核对过里面有 W25、C1–C3 的 adapter 和训练日志、W25 在 train_mining 上的评测），运行上限 2 小时。命令：`STAGE5_DPO_SEEDS=1 STAGE5_GATE_ONLY=1 bash scripts/kaggle_stage5.sh`，代码是 stage5-dpo 分支。 |
| 2026-11-26 | 难度检查的结果：**不通过，停下，没有训练** | 开跑前的核对全部通过：环境和 D13 一样（vllm 0.31.0、torch 2.13.0+cu130、transformers 5.17.0、peft 0.21.2，Tesla T4）；四个旧划分、预热数据、`configs/stage4.json`、`configs/frozen_hard.json`（test_hard 56f6b56b1aac，calib_hard 30ca74bd1949）、`configs/stage5.json`（偏好对 407 / 409 / 407 对）的哈希都一致；W25 重新合并的指纹 b62475b2ae2ffdac 和训练时一致；真实模板下三个种子的偏好对全部通过；C1–C3 就是阶段四训好的那三个。难度检查：C1 50/50，C2 50/50，C3 46/50，合计 146/150（97.3%），高于 D16 定死的 90% 上限，照 D16 停下，不训练 P、CP。C3 错的 4 道都是用满 12 轮没交报告（budget_exhausted），主类别 dependency_error。整次运行 08:38–09:05（UTC），约 27 分钟。结果在 notebook `billina/evidenceloop-stage5` 第 1 版的输出 `stage5_results.zip`（`reports/stage5_gate.md`）。 |
| 2026-11-26 | 估算训练和评测的 GPU 时长 | 没做：难度检查没通过，按要求先停下。照 D16，要另记决策重新定难度。 |
| 2026-11-26 | 已接入收件箱 | 克隆 mac-bridge 到 `~/.mac-bridge/work/stage5-dpo`，本线读 `inbox/line3.md`。 |
| 2026-11-26 | 已处理 #1：写下 D18 | 难题改用已冻结的 test_ood，不再另跑难度检查（阶段四里 C 在 test_ood 上 131/450，29.1%）；P1、CP1 考 test_ood 和 test_id；W25、C 在这两个划分上用阶段四的评测；三点限制如实写明。时间上限改为 240 分钟，也写进 D18。 |
| 2026-11-26 | 脚本照 D18 改（a3ebe13） | `STAGE5_PRIMARY`，默认 test_ood（D18）：不另跑难度检查；P、CP 考 test_ood + test_id（两个冻结划分原样接起来，300 道）；W25、C 在这两个划分上用阶段四的评测，缺了 test_ood 的就停下；对比报告标 D18，主结论看 test_ood，test_id 只作描述。`STAGE5_PRIMARY=test_hard` 保留 D16 原来的做法。新增一个测试，全部 128 个测试通过。在 CPU 上预演一遍（参考策略，不合并、不训练，阶段四的评测用参考策略代替）：只训 P1、CP1，评测 P1、CP1、WC1，报告里 H4–H6 显示"不判定：两边都完整的种子只有 1 个"。 |
| 2026-11-26 | 估算 GPU 时长：约 3.5 小时（3.3–4.9 小时），不超过 5 小时，直接开跑 | 开机、装环境、核对、合并 W25：约 10 分钟（这次实测 8 分钟加开机）。P1 训练约 70 分钟（65–80）：C1 训练 2678 秒，偏好对的序列平均比 C1 的样本长 1.25 倍（3135 对 2509 个字符），带梯度的部分约 56 分钟，加上 reference 前向（梯度检查点下约为训练的四分之一）约 14 分钟。CP1 同样约 70 分钟。WC1 合并两次约 4 分钟。P1、CP1 各考 300 道，每个约 23 分钟（阶段四正常的行 300–350 道是 23–26 分钟；DPO 要是把模型训坏、像 W25+ICL 那样乱写，会到约 55 分钟）。WC1 考 calib_hard 约 7 分钟（这次实测 6–7.5 分钟）。W25、C 不重考。时间上限 240 分钟（D18），最坏情况下最后一项也在约 290 分钟内结束。 |
| 2026-11-26 | 开跑：等 Kaggle 的空位 | notebook 第 2 版（输入加上第 1 版自己的输出，命令 `STAGE5_PRIMARY=test_ood STAGE5_DPO_SEEDS=1 STAGE5_STOP_AFTER_MIN=240 bash scripts/kaggle_stage5.sh`，运行上限 5 小时）提交被拒：Kaggle 同一账号同时最多 2 个 GPU 批处理会话，线 1 的 vpe-step1-smolvla-a 在跑、-b 在排队。每 5 分钟重试一次，有空位就开跑。 |
