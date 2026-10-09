# 阶段三在 Kaggle 上怎么跑

这份说明按顺序写，每一步都可以单独重跑。规则来自 D11：先预热，得到有对有错的模型 W，再从 W 出发做 B、C、D。按 D12，评测和训练都用 vLLM 的环境（第 1 步），第 4 步的冒烟已经做完，下面从第 5 步接着跑。

## 0. 准备

- Kaggle 账号先完成手机验证，否则 Notebook 里不能开 GPU，也不能联网。
- 新建一个 Notebook，右侧设置里：Accelerator 选 GPU T4（选 T4 x2 也行，只用第一张卡），Internet 打开。新建的 Notebook 默认不带 GPU，不选的话 `nvidia-smi` 找不到，训练会退到 CPU 上。
- 每周的 GPU 时长有上限，一次会话也有时长上限。会话一停，`/kaggle/working` 里的东西就没了，所以每跑完一步都按第 7 步把结果下载下来，不要攒到最后。

下面的命令都在 Notebook 的代码格里运行，前面加 `!`；切换目录用 `%cd`。

## 1. 拉代码，装依赖

第一格：

```
%cd /kaggle/working
!git clone https://github.com/langju123456/evidenceloop.git
%cd /kaggle/working/evidenceloop
!pip install -q -e ".[kaggle]"
```

第二格：

```
!pip install -q vllm==0.31.0
!pip uninstall -y -q torchaudio torchao
!python -c "import torch, torchvision; print(torch.__version__, torchvision.__version__)"
!python -c "import transformers, peft, vllm; print('导入正常', transformers.__version__, peft.__version__, vllm.__version__)"
!python -c "import torch; print('GPU', torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

装 vLLM 会把 torch 换成 CUDA 13.0 的版本（`+cu130`）。中间那一大段红色的 `dependency conflicts` 是 Kaggle 预装的其他包（RAPIDS、protobuf 等），本项目用不到，不用管。之后要卸载两个预装包：torchao 0.10（新版 peft 遇到旧 torchao 会报错退出）和 torchaudio（按 CUDA 12.8 编译，transformers 一导入就报错）。最后三行要看到两个版本号都带 `+cu130`、"导入正常"、`GPU True Tesla T4`。

先第一格、再第二格，顺序不能反；之后的步骤另起新格。整页点 Run All 之前，确认格子是按这个顺序排的。

## 2. 复现冻结的题目，核对哈希

```
!el frozen verify
```

四行都要显示"一致"。这一步会在 `data/tasks/gen-0.2.1/` 下重新生成四个划分。两个测试划分只用于这里的核对和第 3 步的查重，阶段三的最后一步之前不拿来跑模型。

## 3. 生成预热数据，核对哈希

```
!el warmup build --tasks-dir data/tasks/gen-0.2.1
```

最后一行要显示"和 configs/warmup.json 一致"。四档数据在 `data/warmup/` 下：`dose10.trl.jsonl`（77 条样本，D12 加入）、`dose25.trl.jsonl`（201 条）、`dose50.trl.jsonl`（409 条）、`dose100.trl.jsonl`（816 条）。

再用真实的 Qwen3 模板检查 loss mask 会不会落错地方：

```
!python scripts/check_template.py --model Qwen/Qwen3-1.7B --records data/warmup/dose100.records.jsonl --n 100
```

要显示 `prefix consistency: 816/816 samples pass`。有任何一条不通过就停下，把输出发给我。

## 4. 冒烟（已完成）

在 transformers 和 vLLM 两个后端上各训了 3 步、考了 16 道题，结果和据此定下的设置见 D12。以后换了环境（比如 vLLM 升级）要重做一次时，在第 1–3 步之后运行：

```
!python scripts/train_lora.py --base Qwen/Qwen3-1.7B --data data/warmup/dose25.trl.jsonl --out runs/smoke --max-steps 3
!el run --backend vllm --model Qwen/Qwen3-1.7B --adapter runs/smoke/adapter --tasks data/tasks/gen-0.2.1/validation.public.jsonl --limit 16 --out runs/smoke_vllm
!el eval --traces runs/smoke_vllm/traces.jsonl --private data/tasks/gen-0.2.1/validation.private.jsonl --out runs/smoke_vllm/evals.jsonl
!python scripts/peek.py runs/smoke_vllm --full | head -80
```

vLLM 启动时日志很长，`FA2 is only supported on devices with compute capability >= 8` 这类提示是正常的（T4 改用 Triton 注意力）。`el run` 一批跑完才打印进度，中途没有输出不代表卡住。最后的 `BrokenPipeError` 是 `head` 截断输出造成的，不用管。

## 5. A 行：基座在同一个后端上重考

```
!el run --backend vllm --model Qwen/Qwen3-1.7B --tasks data/tasks/gen-0.2.1/train_mining.public.jsonl --out runs/A_train_mining
!el eval --traces runs/A_train_mining/traces.jsonl --private data/tasks/gen-0.2.1/train_mining.private.jsonl --out runs/A_train_mining/evals.jsonl
!el run --backend vllm --model Qwen/Qwen3-1.7B --tasks data/tasks/gen-0.2.1/validation.public.jsonl --out runs/A_validation
!el eval --traces runs/A_validation/traces.jsonl --private data/tasks/gen-0.2.1/validation.private.jsonl --out runs/A_validation/evals.jsonl
```

按冒烟的速度，train_mining 的 200 道大约 20 分钟，validation 的 50 道大约 5 分钟，每次 `el run` 另加约 3 分钟启动。`el run` 中途断了，再运行同一条命令会接着跑；上次因为运行故障（infra_error）没跑完的题，会自动重跑，原文件留一份 `.bak` 备份。换了模型、权重或设置，它会拒绝往同一个目录里续写。

跑完先判定 A 本身是不是已经有对有错（D12）：

```
!el warmup check --evals runs/A_train_mining/evals.jsonl --title "预热达标检查：A（不预热）" --out reports/warmup_check_A.md
```

结论是达标，就不预热，W 就是 A，跳过第 6 步（A 的 validation 结果就是 W 行）；不达标再做第 6 步。

## 6. 预热：从 10 道题那一档开始

预热只训 1 轮（`--epochs 1`，D12）。下面的 `N` 是剂量，先用 10：

```
!python scripts/train_lora.py --base Qwen/Qwen3-1.7B --data data/warmup/doseN.trl.jsonl --epochs 1 --out runs/WN --merge-out runs/WN/merged
!el run --backend vllm --model runs/WN/merged --tasks data/tasks/gen-0.2.1/train_mining.public.jsonl --out runs/WN_train_mining
!el eval --traces runs/WN_train_mining/traces.jsonl --private data/tasks/gen-0.2.1/train_mining.private.jsonl --out runs/WN_train_mining/evals.jsonl
!el warmup check --evals runs/WN_train_mining/evals.jsonl --title "预热达标检查：N 道题" --out reports/warmup_check_WN.md
```

结果看 `reports/warmup_check_WN.md` 里"结论"那一行。检查只接受同一个模型配置在 train_mining 全部 200 道题上的结果；缺题、重复、混了两种配置、或者有运行故障的题，它会直接拒绝并说明原因（有运行故障就先用同一条 `el run` 重跑，再 `el eval`；重跑几次还是同几道题出故障，把输出发给我）。

按 D12 的顺序换剂量：从小到大，10 → 25 → 50 → 100，取第一个达标的一档，W 就是那一档。四档都不达标就停下来，把检查结果发给我。任何情况下都不临时加档。

定下 W 以后，让它考 validation，得到报告里的 W 行：

```
!el run --backend vllm --model runs/WN/merged --tasks data/tasks/gen-0.2.1/validation.public.jsonl --out runs/WN_validation
!el eval --traces runs/WN_validation/traces.jsonl --private data/tasks/gen-0.2.1/validation.private.jsonl --out runs/WN_validation/evals.jsonl
```

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

B、C、D 的数据从 W 的错题构建，构建时加上 `--exclude-tasks-dir data/tasks/gen-0.2.1 --exclude-records data/warmup/dose100.records.jsonl`，排除冻结划分和全部预热题（四档都是 dose100 的前缀）。C、D 用 `--evals runs/W25_train_mining/evals.jsonl`。题数和训练次序在 W 定下来以后写进决策记录，到时这一步的完整命令再补上。
