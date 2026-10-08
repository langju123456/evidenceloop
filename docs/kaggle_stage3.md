# 阶段三在 Kaggle 上怎么跑

这份说明按顺序写，每一步都可以单独重跑。规则来自 D11：先预热，得到有对有错的模型 W，再从 W 出发做 B、C、D。D11 定的评测后端是 vLLM；如果它在 T4 上跑不起来，就改用 transformers 后端，这个改动和训练设置一起写进 D12。D12 提交之前，只做第 1–4 步。

## 0. 准备

- Kaggle 账号先完成手机验证，否则 Notebook 里不能开 GPU，也不能联网。
- 新建一个 Notebook，右侧设置里：Accelerator 选 GPU T4（选 T4 x2 也行，只用第一张卡），Internet 打开。
- 每周的 GPU 时长有上限，一次会话也有时长上限。会话一停，`/kaggle/working` 里的东西就没了，所以每跑完一步都按第 7 步把结果下载下来，不要攒到最后。

下面的命令都在 Notebook 的代码格里运行，前面加 `!`；切换目录用 `%cd`。

## 1. 拉代码，装依赖

```
!git clone https://github.com/langju123456/evidenceloop.git
%cd evidenceloop
!pip install -q -e ".[kaggle]"
!python -c "import torch, transformers, peft; print(torch.__version__, transformers.__version__, peft.__version__, torch.cuda.get_device_name(0))"
```

Kaggle 自带 torch 和 transformers。Qwen3 要 transformers 4.51 以上，版本低时上面的安装会顺带升级；peft 缺了也会装上。vLLM 放到第 4 步，在另一个会话里试。如果 D12 定了用 vLLM，以后每个会话都在这里加一行 `!pip install -q vllm==<D12 里记的版本>`。

## 2. 复现冻结的题目，核对哈希

```
!el frozen verify
```

四行都要显示"一致"。这一步会在 `data/tasks/gen-0.2.1/` 下重新生成四个划分。两个测试划分只用于这里的核对和第 3 步的查重，阶段三的最后一步之前不拿来跑模型。

## 3. 生成预热数据，核对哈希

```
!el warmup build --tasks-dir data/tasks/gen-0.2.1
```

最后一行要显示"和 configs/warmup.json 一致"。三档数据在 `data/warmup/` 下：`dose25.trl.jsonl`（201 条样本）、`dose50.trl.jsonl`（409 条）、`dose100.trl.jsonl`（816 条）。

再用真实的 Qwen3 模板检查 loss mask 会不会落错地方：

```
!python scripts/check_template.py --model Qwen/Qwen3-1.7B --records data/warmup/dose100.records.jsonl --n 100
```

要显示 `prefix consistency: 816/816 samples pass`。有任何一条不通过就停下，把输出发给我。

## 4. 冒烟：训三步，考 16 道题

**4a. 训练三步。**

```
!python scripts/train_lora.py --base Qwen/Qwen3-1.7B --data data/warmup/dose25.trl.jsonl --out runs/smoke --max-steps 3
```

看最后打印的汇总：能跑完；每步的 loss 是有限的数；`skipped_steps` 是 fp16 下梯度溢出、被跳过的步数，偶尔一步是正常的，三步都被跳过就把输出发给我；`peak_memory_gb` 是显存峰值。训练中途停下时，到那一步为止的记录在 `runs/smoke/train_log.json` 里。

**4b. transformers 后端考 16 道题（两批，每批 8 道）。**

```
!el run --backend hf --model Qwen/Qwen3-1.7B --adapter runs/smoke/adapter --tasks data/tasks/gen-0.2.1/validation.public.jsonl --limit 16 --gen-batch 8 --out runs/smoke_hf
!el eval --traces runs/smoke_hf/traces.jsonl --private data/tasks/gen-0.2.1/validation.private.jsonl --out runs/smoke_hf/evals.jsonl
!python scripts/peek.py runs/smoke_hf --full | head -80
```

基座在 validation 上本来就几乎全错，所以"跑完了"说明不了后端对不对，要看模型的原始输出：第一轮应该是 `<tool_call>` 包着的 JSON 工具调用，后面几轮接着调工具。16 道题大多是 parse_error，或者第一轮就直接答完，说明后端有问题，把输出发给我。进度行里有最长输入的 token 数和显存峰值；一批放不进显存时，会自动拆小重试。

**4c. 另开一个会话试 vLLM。** 安装 vLLM 会换掉 torch 和 transformers 的版本，所以不在 4a、4b 的会话里装。先把 4a、4b 的输出存下来，停掉会话（右上角的电源按钮），重新开一个，做完第 1–3 步，然后：

```
!pip install -q vllm
!python -c "import vllm, torch, transformers; print(vllm.__version__, torch.__version__, transformers.__version__)"
!python scripts/train_lora.py --base Qwen/Qwen3-1.7B --data data/warmup/dose25.trl.jsonl --out runs/smoke --max-steps 3
!el run --backend vllm --model Qwen/Qwen3-1.7B --adapter runs/smoke/adapter --tasks data/tasks/gen-0.2.1/validation.public.jsonl --limit 16 --out runs/smoke_vllm
!el eval --traces runs/smoke_vllm/traces.jsonl --private data/tasks/gen-0.2.1/validation.private.jsonl --out runs/smoke_vllm/evals.jsonl
!python scripts/peek.py runs/smoke_vllm --full | head -80
```

这样同时验证了：装上 vLLM 之后训练还能跑，vLLM 能在 T4 上带着 adapter 推理。装不上、或者报 GPU 不支持，就记下报错，阶段三用 transformers 后端。

把 4a、4b、4c 的输出（训练汇总、两次 `el run` 的最后几行、`peek` 的输出和报错）发给我。我据此起草 D12，写明：

- 评测后端用哪个、它和 torch、transformers 的版本；阶段三所有评测（包括 A 行）都用这一个。用 transformers 时，`--gen-batch` 也固定为一个值；
- 训练设置：学习率 1e-4，2 轮，LoRA 秩 16、alpha 32、dropout 0.05，作用在 7 种投影上，每步 16 条样本，预热 5 步，最长 8192 个 token，fp16（损失缩放从 4096 起），预热的训练种子 0（冒烟发现问题就在 D12 里改）；
- 冒烟时的速度、显存和最长输入；
- D11 之后，A-ICL 的上下文是加在 A 上还是加在 W 上。

D12 提交以后，才开始第 5 步。

## 5. A 行：基座在同一个后端上重考

下面用 `--backend hf` 举例；D12 定的是 vLLM，就换成 `--backend vllm`，并去掉 `--gen-batch`。

```
!el run --backend hf --model Qwen/Qwen3-1.7B --tasks data/tasks/gen-0.2.1/train_mining.public.jsonl --gen-batch 8 --out runs/A_train_mining
!el eval --traces runs/A_train_mining/traces.jsonl --private data/tasks/gen-0.2.1/train_mining.private.jsonl --out runs/A_train_mining/evals.jsonl
!el run --backend hf --model Qwen/Qwen3-1.7B --tasks data/tasks/gen-0.2.1/validation.public.jsonl --gen-batch 8 --out runs/A_validation
!el eval --traces runs/A_validation/traces.jsonl --private data/tasks/gen-0.2.1/validation.private.jsonl --out runs/A_validation/evals.jsonl
```

`el run` 中途断了，再运行同一条命令会接着跑；上次因为运行故障（infra_error）没跑完的题，会自动重跑，原文件留一份 `.bak` 备份。换了模型、权重或设置（包括 `--gen-batch`），它会拒绝往同一个目录里续写。

## 6. 预热：从 25 道题那一档开始

```
!python scripts/train_lora.py --base Qwen/Qwen3-1.7B --data data/warmup/dose25.trl.jsonl --out runs/W25 --merge-out runs/W25/merged
!el run --backend hf --model runs/W25/merged --tasks data/tasks/gen-0.2.1/train_mining.public.jsonl --gen-batch 8 --out runs/W25_train_mining
!el eval --traces runs/W25_train_mining/traces.jsonl --private data/tasks/gen-0.2.1/train_mining.private.jsonl --out runs/W25_train_mining/evals.jsonl
!el warmup check --evals runs/W25_train_mining/evals.jsonl --title "预热达标检查：25 道题" --out reports/warmup_check_W25.md
```

结果看 `reports/warmup_check_W25.md` 里"结论"那一行。检查只接受同一个模型配置在 train_mining 全部 200 道题上的结果；缺题、重复、混了两种配置、或者有运行故障的题，它会直接拒绝并说明原因（有运行故障就先用同一条 `el run` 重跑，再 `el eval`；重跑几次还是同几道题出故障，把输出发给我）。

- **达标**：W 就是 W25，停在这一档。再让它考 validation，得到报告里的 W 行：

  ```
  !el run --backend hf --model runs/W25/merged --tasks data/tasks/gen-0.2.1/validation.public.jsonl --gen-batch 8 --out runs/W25_validation
  !el eval --traces runs/W25_validation/traces.jsonl --private data/tasks/gen-0.2.1/validation.private.jsonl --out runs/W25_validation/evals.jsonl
  ```

- **不达标**：同样的四条命令，把 25 换成 50；还不达标就换成 100。
- **三档都不达标**：停下来，把三份检查结果发给我。按 D11，不临时加档，另记一条决策再定下一步。

## 7. 每跑完一步，把结果带回来

`runs/` 和 `data/` 不进版本库，要提交的是报告。报告按划分分开出，只放已经跑完的行。第 5 步跑完时：

```
!el report baseline --evals runs/A_train_mining/evals.jsonl --names A --title "阶段三：train_mining" --out reports/stage3_train_mining.md
!el report baseline --evals runs/A_validation/evals.jsonl --names A --title "阶段三：validation" --out reports/stage3_validation.md
```

第 6 步定下 W 以后，同样两条命令，在 `--evals` 和 `--names` 后面各加上 W 那一项（例如 `runs/W25_train_mining/evals.jsonl` 和 `W25`）。train_mining 那份报告里有 A 和 W 的失败类别分布，D11 要求报告这一项。某个文件还不存在时，命令会直接报错，不会生成空的一列。

然后打包：

```
!zip -qr stage3_results.zip reports runs/*/train_log.json runs/*/traces.jsonl runs/*/evals.jsonl runs/*/adapter
```

`runs/*/merged` 是合并后的完整模型，有几个 GB，不打包；需要时用 adapter 重新合并（第 8 步）。

在右侧的 Output 里下载 `stage3_results.zip`，把里面的 `reports/` 放进 Mac 上的项目文件夹，再运行 `bash scripts/checkpoint.sh "提交信息"`。压缩包本身自己留好，W 的 adapter 在里面。也可以直接把压缩包发给我，我来放。

## 8. 新会话里接着用 W

会话停了以后，先做第 1–3 步，再把压缩包里的两个目录放回 `runs/` 下：W 那一档的训练目录（例如 `runs/W25/`，里面有 `adapter/` 和 `train_log.json`），和它在 train_mining 上的结果（例如 `runs/W25_train_mining/`）。办法是在右侧 Add Input 里把它们上传成一个私有 Dataset，再从 `/kaggle/input/<数据集名>/` 复制过来。然后重新合并：

```
!python scripts/merge_lora.py --train-log runs/W25/train_log.json --out runs/W25/merged
```

它会核对 adapter 和基座都和训练日志对得上，并打印新模型的指纹；和训练时合并出的指纹一致，就是同一个 W。

B、C、D 的数据从 W 的错题构建，构建时加上 `--exclude-tasks-dir data/tasks/gen-0.2.1 --exclude-records data/warmup/dose100.records.jsonl`，排除冻结划分和全部预热题（三档都是 dose100 的前缀）。C、D 用 `--evals runs/W25_train_mining/evals.jsonl`。题数和训练次序在 W 定下来以后写进决策记录，到时这一步的完整命令再补上。
