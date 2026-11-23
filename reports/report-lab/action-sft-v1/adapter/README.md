# D22 本地 LoRA 权重

这个目录保存本项目在公开年报脚本上训练的低秩适配器。基座是 Qwen/Qwen3-0.6B，快照 c1899de289a04d12100db370d81485cdf75e47ca。原基座版权为 Copyright 2024 Alibaba Cloud，适配器按 Apache-2.0 提供；此处保存训练产生的增量张量，完整基座需从原来源取得。[原模型与许可](https://huggingface.co/Qwen/Qwen3-0.6B/blob/c1899de289a04d12100db370d81485cdf75e47ca/LICENSE) · [许可证副本](LICENSE)

用 mlx-lm 0.32.0 的 `load(local_base_path, adapter_path=adapter_dir)` 加载。该适配器在两份新年报上仅核准 1/18 个动作，请用于复核实验。用法、训练分组及发布判断见[结果](../../../../docs/report-lab/12-action-sft-results.md)。
