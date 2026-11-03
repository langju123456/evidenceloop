# 阶段四在 Kaggle 上怎么跑

规则来自 D14：从 W25（D13）出发，B、C、D 各 3 个种子、每组 100 道题，各自训一个新的 LoRA；9 个全部训完以后，再和 A、W25、W25+ICL 一起考 test_id 和 test_ood。主结论只看 test_id 上的 H1（C 对 B）。环境和训练设置照 D12，下面每一步都可以单独重跑。

## 一键跑法（推荐）

`scripts/kaggle_stage4.sh` 把下面第 1–7 步一次跑完，判定规则完全照 D14，不做临时判断。

1. 新建一个 Notebook，右侧设置里 Accelerator 选 **GPU T4**（P100 不行：vLLM 要求算力 7.0 以上，P100 是 6.0），Internet 打开。
2. 右侧 **Add Input**，加上阶段三那个 Notebook（evidenceloop-stage3）的输出。脚本会在 `/kaggle/input` 下面自己找 `stage3_results.zip`，用到的是里面 W25 的 adapter、训练日志和评测。如果当时是把压缩包下载下来、再上传成私有 Dataset 的，也一样能找到。
3. 只要一格，然后 Save Version → Save & Run All，关掉页面也会在后台跑完：

```
!git clone -q https://github.com/langju123456/evidenceloop.git /kaggle/working/evidenceloop
!bash /kaggle/working/evidenceloop/scripts/kaggle_stage4.sh
```

进度和结论在 Output 的 `STATUS.md`，结果在 `stage4_results.zip`（不含几 GB 的合并模型；9 个 adapter、训练日志、全部轨迹和评测、报告都在里面）。结论在压缩包里的 `reports/stage4_compare_test_id.md`。

要多久：D14 估计 6–11.5 小时（是估计，不是测出来的）。开始后满 600 分钟，脚本就不再开始新的训练或评测，先打包，`STATUS.md` 最后一行会写明。这时把这次的输出也加为 Input（Notebook 的输出，或者下载 `stage4_results.zip` 再上传成私有 Dataset），用同一格再 Save & Run All 一次：训好的不重训，评测从断点接着跑。

下面是分步做法，排查问题时用。

## 0. 准备

- Kaggle 账号要先完成手机验证，否则不能开 GPU、不能联网。每周的 GPU 时长有上限，这一步要用掉其中大约 6–11.5 小时。
- 会话一停，`/kaggle/working` 里的东西就没了；一键脚本在停下、到时间、跑完这三种情况下都会先打包。

## 1. 拉代码，装依赖

```
%cd /kaggle/working
!git clone https://github.com/langju123456/evidenceloop.git
%cd /kaggle/working/evidenceloop
!pip install -q -e ".[kaggle]"
!pip install -q vllm==0.31.0 transformers==5.17.0 peft==0.21.2
!pip uninstall -y -q torchaudio torchao
!python -c "import torch, transformers, peft, vllm; print(torch.__version__, transformers.__version__, peft.__version__, vllm.__version__, torch.cuda.get_device_name(0))"
```

最后一行要看到 `2.13.0+cu130 5.17.0 0.21.2 0.31.0 Tesla T4`，和 D13 那次一样。比阶段三多钉了 transformers 和 peft 的版本（D14）：重新合并 W25 时，合并模型的指纹也覆盖 transformers 写出的配置和分词器文件，版本一变，指纹就对不上。

## 2. 冻结划分、预热数据

```
!el frozen verify
!el warmup build --tasks-dir data/tasks/gen-0.2.1
```

要显示"四个划分都和 configs/frozen.json 一致"和"和 configs/warmup.json 一致"。

## 3. 恢复 W25，核对它就是 D13 的那个

把阶段三压缩包里的 `runs/` 放回项目里（一键脚本会自己做）：

```
!unzip -n -q /kaggle/input/<阶段三的输入>/stage3_results.zip -x 'reports/*' -d /kaggle/working/evidenceloop
```

W25 在 train_mining 上的评测，重新出一遍达标检查，要和仓库里的报告一字不差（包括模型配置的哈希）：

```
!el warmup check --evals runs/W25_train_mining/evals.jsonl --title "预热达标检查：25 道题" --out /kaggle/working/again.md
!cmp /kaggle/working/again.md reports/warmup_check_W25.md && echo 一致
```

再用 adapter 重新合并出 W25：

```
!python scripts/merge_lora.py --train-log runs/W25/train_log.json --out runs/W25/merged
```

要显示"和训练时合并出的模型一致"。不一致就停下（D14：不在没测过的 W 上训练），把输出发给我。

## 4. 构建 B、C、D 和 W+ICL 的数据

```
!el stage4 build --evals runs/W25_train_mining/evals.jsonl --tasks-dir data/tasks/gen-0.2.1 --warmup-records data/warmup/dose100.records.jsonl
```

最后一行要显示"和 configs/stage4.json 一致"。每个种子会打印：B、C、D 各 100 道，D 的错误示范 25 道，对齐后每组的样本数（种子 1、2、3 分别是 814、818、815），以及 W+ICL 用的那条示范。生成的东西在 `data/stage4/`：

- `B1/ C1/ D1/ … D3/`：每组的 records（和 `el data build` 写的一样）；
- `export_s1/ … export_s3/`：每个种子三组对齐后的训练文件 `B1.trl.jsonl` 等（和 `el export sft` 写的一样）；
- `eval.public.jsonl`（validation + test_id + test_ood，350 道）、`test.public.jsonl`（test_id + test_ood，300 道）；
- `icl1.test_id.public.jsonl` 等：test_id 的 150 道题，系统提示后面附了一条 C 的示范（D14）。

这一条等价于下面的命令（种子 s 取 1、2、3；`tests/test_stage4.py` 检查两种做法得到的文件逐字节相同）：

```
!el data build --policy uniform    --seed s --n 100 --exclude-tasks-dir data/tasks/gen-0.2.1 --exclude-records data/warmup/dose100.records.jsonl --out data/stage4/Bs
!el data build --policy targeted   --seed s --n 100 --evals runs/W25_train_mining/evals.jsonl --exclude-tasks-dir data/tasks/gen-0.2.1 --exclude-records data/warmup/dose100.records.jsonl --out data/stage4/Cs
!el data build --policy unfiltered --seed s --n 100 --evals runs/W25_train_mining/evals.jsonl --exclude-tasks-dir data/tasks/gen-0.2.1 --exclude-records data/warmup/dose100.records.jsonl --out data/stage4/Ds
!el export sft --records data/stage4/Bs/records.jsonl data/stage4/Cs/records.jsonl data/stage4/Ds/records.jsonl --names Bs Cs Ds --format trl --seed s --out data/stage4/export_ss
```

然后用真实的 Qwen3 模板检查（每个种子、每一组）和 token 预算（每个种子三组相差不超过 5%，D10）：

```
!python scripts/check_template.py --model Qwen/Qwen3-1.7B --records data/stage4/D1/records.jsonl --n 100
!python scripts/check_template.py --model Qwen/Qwen3-1.7B --budget data/stage4/export_s1/B1.trl.jsonl data/stage4/export_s1/C1.trl.jsonl data/stage4/export_s1/D1.trl.jsonl
```

前一条要显示 `N/N samples pass`，后一条要显示 `spread x.x% (must be <= 5%)` 且退出码为 0。

## 5. 训练 9 个 LoRA

次序 B1、C1、D1、B2、C2、D2、B3、C3、D3，全部从合并好的 W25 出发，设置照 D12，1 轮，训练种子就是 s：

```
!python scripts/train_lora.py --base runs/W25/merged --data data/stage4/export_s1/B1.trl.jsonl --epochs 1 --seed 1 --out runs/B1
```

不加 `--merge-out`：评测时 adapter 直接挂在 W25 上（D14）。每次 51 或 52 步。9 个全部训完以后，才开始第 6 步。

## 6. 评测

```
!el run --backend vllm --model runs/W25/merged --tasks data/stage4/test.public.jsonl --out runs/W25_stage4
!el run --backend vllm --model runs/W25/merged --adapter runs/B1/adapter --tasks data/stage4/eval.public.jsonl --out runs/B1_stage4
!el run --backend vllm --model Qwen/Qwen3-1.7B --tasks data/stage4/test.public.jsonl --out runs/A_stage4
!el run --backend vllm --model runs/W25/merged --tasks data/stage4/icl1.test_id.public.jsonl --out runs/ICL1_stage4
```

次序：W25 → B1 C1 D1 B2 C2 D2 B3 C3 D3 → A → ICL1 ICL2 ICL3。每次跑完按划分分别评分，例如：

```
!el eval --traces runs/B1_stage4/traces.jsonl --private data/tasks/gen-0.2.1/test_id.private.jsonl --out runs/B1_stage4/evals_test_id.jsonl
```

（traces 里别的划分的题会被跳过，并打印跳过了几条。）有运行故障的题，用同一条 `el run` 重跑，最多三次；还有没跑成的，这一行记为没跑成，不补、不换设置（D14）。

## 7. 报告与打包

每个划分一份总表（`el report baseline`）和一份对比（`el stage4 compare`）：

```
!el stage4 compare --split test_id --row A=runs/A_stage4/evals_test_id.jsonl --row W=runs/W25_stage4/evals_test_id.jsonl \
    --row B:1=runs/B1_stage4/evals_test_id.jsonl --row C:1=runs/C1_stage4/evals_test_id.jsonl --row D:1=runs/D1_stage4/evals_test_id.jsonl \
    … --row ICL:3=runs/ICL3_stage4/evals_test_id.jsonl --out reports/stage4_compare_test_id.md
```

结论表里，H1（C − B）在 test_id 上的结论回答主问题；validation、test_ood 的对比只作描述。validation 上的 A、W25 用阶段三的 `runs/A_validation/`、`runs/W25_validation/`。

下载 `stage4_results.zip`，把里面的 `reports/` 放进 Mac 上的项目文件夹，再运行 `bash scripts/checkpoint.sh "提交信息"`；也可以直接把压缩包发给我。

## 没有 GPU 时的预演

在任何一台装了项目的机器上，可以把整个脚本走一遍：不装环境、不训练（只打印训练命令），用脚本化参考策略代替模型跑完全部评测和报告，报告写进 `reports_dryrun/`，不碰 `reports/`：

```
mkdir -p /tmp/s4 && git clone -q . /tmp/s4/evidenceloop
STAGE4_DRY_RUN=1 KAGGLE_WORK=/tmp/s4 KAGGLE_INPUT=/tmp/s4/none bash /tmp/s4/evidenceloop/scripts/kaggle_stage4.sh
```

预演里 C、D 的数据用 `reports/warmup_check_W25.md` 里的分组表代替真实评测（`el stage4 build --mining-report`），得到的数据和 `configs/stage4.json` 一致。参考策略每道题都做对，所以预演的对比全是"分不出"，只说明脚本本身走得通。
