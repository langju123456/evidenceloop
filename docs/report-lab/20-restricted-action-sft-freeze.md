# D27：受限动作交叉熵候选

D26 校正后显示 D25 在实际见过的 64 个 Dell/Cisco 训练展示上仅为 12/64，因此本轮只检验一个可证伪解释：全词表交叉熵与最终只允许 A--F 的受限路由不对齐。

与 D25 相同：32 条原训练委托、canonical/rotated 菜单各一次、固定64步、seed 23、最后4层 q/v LoRA（81,920 个参数）、rank 4/scale 8/dropout 0、Adam 0.0002。唯一改变是每步只从 A--F 六个 token 的 logits 计算交叉熵，目标为当前菜单中 gold action 的字母索引。

候选仅保存最后一个终态，不早停、不选择 checkpoint、不重跑。采集仍调用未改动的 D22 canonical 96 条收集和原 adoption gate；另外单独归档 64 条终态训练展示，按实际菜单解码语义。只有原 canonical gate 通过且训练展示严格 64/64 才可采用。腾讯/茅台、Oracle 均为已暴露复用回归，不能称为新留出集。
