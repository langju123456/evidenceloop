# D25 预登记：仅用菜单置换训练诊断原LoRA退化

本轮唯一候选沿用D22原Dell/Cisco 32条训练委托、Qwen3-0.6B基座、最后四层q/v LoRA、rank 4、scale 8、Adam 0.0002、种子23、单条批量和64次更新。每条原委托在两轮中各见一次canonical菜单和一次rotated菜单；轮次内的case顺序仍为D22的`random.Random(23)`连续shuffle。菜单由原case索引和轮次固定决定，因此每个epoch为16/16，且不根据loss、开发集或评测结果调整。

canonical输入与D22基础输入逐字一致。rotated只改变六项菜单的字母编码，并把“送审前动作”映射到相同业务动作的新字母；分析师消息、年报表格、单位和业务含义不变。正确监督token也按相同业务动作重新编码。模型只收到messages；gold_action、目标token和训练日志不进入模型上下文。

训练仅包含Dell/Cisco。Apple开发集、Tencent/Moutai的18题与Oracle8题均不进入训练。本轮已知此前D22、D24在后两组上的结果，因此继续沿用D22完整门槛作**复用回归**：相对base与coached各至少+2；两家公司均不下降；已正确暂停不得变成计算；Oracle不低于base。它们不是新的留出或泛化证明。失败、首答、adapter和最终单一checkpoint全量归档；不重试、不早停、不选最佳checkpoint。

执行先创建不可覆盖`freeze.json`，其中固定新旧代码、数据、模型配置和协议的内容哈希。训练和收集分别在独立进程从磁盘载入权重；收集调用D22未改的collector与summarize，因此评分逻辑和采用门槛不变。若冻结校验、基础权重、运行环境、token预算或输出目录不满足，任务失败而不改写既有记录。
