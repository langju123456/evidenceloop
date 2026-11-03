#!/usr/bin/env bash
# 阶段四在 Kaggle 上一键跑完（docs/kaggle_stage4.md），规则全部来自 D11、D12、D14，不做任何临时判断。
#
# Notebook 设置：Accelerator 选 GPU T4，Internet 打开；右侧 Add Input 加上阶段三那个 Notebook 的输出
# （里面有 stage3_results.zip：W25 的 adapter、训练日志和评测）。只要一格，再点 Save Version → Save & Run All：
#   !git clone -q https://github.com/langju123456/evidenceloop.git /kaggle/working/evidenceloop
#   !bash /kaggle/working/evidenceloop/scripts/kaggle_stage4.sh
#
# 流程（D14）：恢复阶段三的结果 → 装环境（D12，外加 D13 的 transformers、peft 版本）→ 核对冻结划分、预热数据
#   → 核对 W25 的 train_mining 评测和 D13 的报告一字不差 → 用 adapter 重新合并 W25，指纹要和训练时一样
#   → el stage4 build：B、C、D 各 3 个种子各 100 道题，按种子对齐样本数，哈希要和 configs/stage4.json 一样
#   → 真实模板与 token 预算检查 → 先训完全部 9 个 LoRA（B1 C1 D1 B2 C2 D2 B3 C3 D3，都从 W25 出发）
#   → 再评测：W25、9 个 W25+X（validation + test_id + test_ood），A，3 个 W25+ICL（test_id）→ 出报告 → 打包。
# 进度和结论写在 /kaggle/working/STATUS.md，结果在 stage4_results.zip（不含几 GB 的合并模型）。
# 用了 STAGE4_STOP_AFTER_MIN 分钟（默认 600）以后不再开始新的训练或评测，先打包；把这次的输出也加为 Input，
# 用同一格再跑一次就接着跑（训好的不重训，el run 自己续跑）。
# STAGE4_DRY_RUN=1：没有 GPU 的预演。不装环境、不训练（只打印训练命令），用脚本化参考策略代替模型跑完全部评测
# 和报告，报告写进 reports_dryrun/，用来检查脚本本身。
set -uo pipefail

WORK="${KAGGLE_WORK:-/kaggle/working}"
INPUT="${KAGGLE_INPUT:-/kaggle/input}"
REPO="$WORK/evidenceloop"
STATUS="$WORK/STATUS.md"
ZIP="$WORK/stage4_results.zip"
DRY_RUN="${STAGE4_DRY_RUN:-0}"
STOP_AFTER_MIN="${STAGE4_STOP_AFTER_MIN:-600}"
BASE=Qwen/Qwen3-1.7B
TASKS=data/tasks/gen-0.2.1
W=runs/W25/merged
SEEDS=(1 2 3)
ARMS=(B C D)
START=$(date +%s)
FAILED=()
if [ "$DRY_RUN" = 1 ]; then BACKEND=scripted; REPORTS=reports_dryrun; else BACKEND=vllm; REPORTS=reports; fi
cd "$REPO" || exit 1

note() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$STATUS"; }
stop() { note "停下：$*"; package; exit 1; }

package() {
  cd "$REPO" || return
  rm -rf runs/*/merged
  local files=("$REPORTS") f
  for f in runs/*/train_log.json runs/*/traces.jsonl runs/*/evals*.jsonl runs/*/adapter \
           data/stage4/*/build.json data/stage4/export_s*/*.manifest.json; do
    [ -e "$f" ] && files+=("$f")
  done
  rm -f "$ZIP"
  zip -qr "$ZIP" "${files[@]}" && note "已打包：$ZIP"
}

# D14 的时间上限：到了就不再开始新的训练或评测，先打包，下次接着跑。
check_time() {
  local used=$(( ($(date +%s) - START) / 60 ))
  if [ "$used" -ge "$STOP_AFTER_MIN" ]; then
    note "已用 $used 分钟，到了 $STOP_AFTER_MIN 分钟的上限：不再开始新的训练或评测。把这次的输出加为 Input，用同一格再跑一次会接着跑。"
    package
    exit 0
  fi
}

# 阶段三（和上一次阶段四）的结果：notebook 输出里的 zip，或者被 Kaggle 解开的目录。已有的文件不覆盖。
restore() {
  local z d
  [ -d "$INPUT" ] || return 0
  while IFS= read -r z; do
    unzip -n -q "$z" -x 'reports/*' 'data/*' -d "$REPO" && note "从 $z 恢复了 runs/"
  done < <(find "$INPUT" -name 'stage[34]_results.zip' 2>/dev/null | sort)
  while IFS= read -r d; do
    mkdir -p runs && cp -rn "$d"/. runs/ && note "从 $d 恢复了 runs/"
  done < <(find "$INPUT" -path '*/runs/W25/train_log.json' 2>/dev/null | sed 's#/W25/train_log.json$##' | sort -u)
}

# 还没跑的题：不在 traces 里，或者上次是运行故障（infra_error）。
pending() {  # $1 题目文件 $2 traces
  python - "$1" "$2" <<'PY'
import json, os, sys
tasks = {json.loads(line)["task_id"] for line in open(sys.argv[1], encoding="utf-8") if line.strip()}
done = set()
if os.path.exists(sys.argv[2]):
    with open(sys.argv[2], encoding="utf-8") as fh:
        done = {t["task_id"] for t in map(json.loads, filter(str.strip, fh)) if t.get("termination") != "infra_error"}
print(len(tasks - done))
PY
}

# 训练是否已经按 D14 跑完：日志完整、adapter 对得上、数据是这一份、基座是 W25、设置是 D12 的加 1 轮。
trained() {  # $1 训练目录 $2 数据 $3 种子
  [ -f "$1/train_log.json" ] && [ -f "$1/adapter/adapter_config.json" ] || return 1
  python - "$1" "$2" "$W_FP" "$3" <<'PY'
import hashlib, json, sys
from evidenceloop.data.stage4 import training_problems
from evidenceloop.harness.backends import weights_fingerprint
run, data, base_fp, seed = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
with open(f"{run}/train_log.json", encoding="utf-8") as fh:
    log = json.load(fh)
with open(data, "rb") as fh:
    sha = hashlib.sha256(fh.read()).hexdigest()
problems = training_problems(log, sha, base_fp, seed, weights_fingerprint(f"{run}/adapter"))
for p in problems:
    print(f"{run}：{p}")
sys.exit(1 if problems else 0)
PY
}

# 一个 LoRA：从 W25 出发，D12 的设置，1 轮，训练种子 = 复现种子。失败就用同一条命令再训一次，还失败记为没跑成。
train_one() {  # $1 组 $2 种子
  local name="$1$2" data="data/stage4/export_s$2/$1$2.trl.jsonl" i
  if [ "$DRY_RUN" = 1 ]; then
    note "[预演] python scripts/train_lora.py --base $W --data $data --epochs 1 --seed $2 --out runs/$name"
    return 0
  fi
  if trained "runs/$name" "$data" "$2" >/dev/null; then note "$name 已经训好，跳过"; return 0; fi
  for i in 1 2; do
    check_time
    rm -rf "runs/$name"
    note "训练 $name（第 $i 次）"
    python scripts/train_lora.py --base "$W" --data "$data" --epochs 1 --seed "$2" --out "runs/$name"
    if trained "runs/$name" "$data" "$2" 2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ]; then
      note "$name 训练完成"
      return 0
    fi
  done
  FAILED+=("$name：训练两次都没成")
  note "$name 训练两次都没成，记为没跑成（D14），其余照常"
  return 1
}

# 一行评测：同一个目录里续跑，运行故障的题最多重跑三次；还有没跑成的题，这一行记为没跑成。
eval_row() {  # $1 行名 $2 题目文件 $3 模型 $4 adapter（空 = 不用）；后面是要评分的划分
  local row="$1" tasks="$2" model="$3" adapter="$4" out="runs/${1}_stage4" i left split
  shift 4
  if [ -n "$adapter" ] && [ "$DRY_RUN" != 1 ] && [ ! -f "$adapter/adapter_config.json" ]; then
    FAILED+=("$row：没有训好的 adapter")
    note "$row 没有训好的 adapter，不考"
    return 1
  fi
  for i in 1 2 3; do
    left=$(pending "$tasks" "$out/traces.jsonl")
    [ "$left" = 0 ] && break
    check_time
    note "评测 $row：还有 $left 道（第 $i 次）"
    el run --backend "$BACKEND" --model "$model" ${adapter:+--adapter "$adapter"} --tasks "$tasks" --out "$out" \
      || note "el run 返回非零（$row，第 $i 次）"
  done
  left=$(pending "$tasks" "$out/traces.jsonl")
  if [ "$left" != 0 ]; then
    FAILED+=("$row：重跑三次仍有 $left 道没跑成")
    note "$row 重跑三次仍有 $left 道没跑成，记为没跑成（D14），其余照常"
    return 1
  fi
  for split in "$@"; do
    el eval --traces "$out/traces.jsonl" --private "$TASKS/$split.private.jsonl" --out "$out/evals_$split.jsonl" \
      | tail -n 1 | sed "s#^#  $row $split：#" | tee -a "$STATUS"
    [ "${PIPESTATUS[0]}" = 0 ] || stop "el eval 失败：$out $split"
  done
}

# 每个划分上的行：组[:种子]=评测文件。A、W 在 validation 上用阶段三的结果（同一后端、同一个 W25）。
rows_for() {  # $1 划分
  local split="$1" s arm
  if [ "$split" = validation ]; then
    echo "A=runs/A_validation/evals.jsonl"
    echo "W=runs/W25_validation/evals.jsonl"
  else
    echo "A=runs/A_stage4/evals_$split.jsonl"
    echo "W=runs/W25_stage4/evals_$split.jsonl"
  fi
  for s in "${SEEDS[@]}"; do for arm in "${ARMS[@]}"; do echo "$arm:$s=runs/$arm${s}_stage4/evals_$split.jsonl"; done; done
  if [ "$split" = test_id ]; then
    for s in "${SEEDS[@]}"; do echo "ICL:$s=runs/ICL${s}_stage4/evals_test_id.jsonl"; done
  fi
}

report_split() {  # $1 划分
  local split="$1" spec name path names=() files=() args=()
  while IFS= read -r spec; do
    name="${spec%%=*}"; path="${spec#*=}"
    args+=(--row "$spec")
    [ -f "$path" ] || continue
    name="${name/:/}"; [ "$name" = W ] && name=W25
    names+=("$name"); files+=("$path")
  done < <(rows_for "$split")
  if [ ${#files[@]} -gt 0 ]; then
    el report baseline --evals "${files[@]}" --names "${names[@]}" --title "阶段四：$split" --out "$REPORTS/stage4_$split.md"
  fi
  el stage4 compare --split "$split" "${args[@]}" --out "$REPORTS/stage4_compare_$split.md" >/dev/null \
    || note "对比报告没写成：$split"
}

echo "# 阶段四运行状态" > "$STATUS"
note "开始，代码 $(git rev-parse --short HEAD 2>/dev/null || echo '?')$([ "$DRY_RUN" = 1 ] && echo '（预演：脚本化参考策略，不训练）')"
mkdir -p "$REPORTS"

# ---- 0. 恢复阶段三（和上一次阶段四）的结果
restore

# ---- 1. 环境（D12；D14 另外钉住 D13 那次的 transformers 和 peft，重新合并 W25 才能得到同一个指纹）
if [ "$DRY_RUN" != 1 ]; then
  pip install -q -e ".[kaggle]" || stop "pip install 失败"
  pip install -q vllm==0.31.0 transformers==5.17.0 peft==0.21.2 || stop "安装 vllm、transformers、peft 失败"
  pip uninstall -y -q torchaudio torchao >/dev/null 2>&1
  python - <<'PY' 2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ] || stop "环境检查没通过（见上一行）"
import torch, transformers, peft, vllm
want = {"torch": "2.13.0+cu130", "transformers": "5.17.0", "peft": "0.21.2", "vllm": "0.31.0"}  # D13
got = {"torch": torch.__version__, "transformers": transformers.__version__, "peft": peft.__version__, "vllm": vllm.__version__}
print("环境", got, torch.cuda.get_device_name(0) if torch.cuda.is_available() else "没有 GPU")
assert torch.cuda.is_available(), "没有 GPU：Accelerator 选 GPU T4"
assert torch.cuda.get_device_capability(0) >= (7, 0), "vLLM 要求算力 7.0 以上，P100 是 6.0：Accelerator 选 GPU T4"
assert got == want, f"和 D13 的环境不一样：{ {k: v for k, v in got.items() if v != want[k]} }"
PY
fi

# ---- 2. 冻结划分、预热数据
el frozen verify 2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ] || stop "冻结划分的哈希对不上"
el warmup build --tasks-dir "$TASKS" 2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ] || stop "预热数据和 configs/warmup.json 对不上"

# ---- 3. W25：评测要和 D13 的报告一字不差，重新合并的权重要和训练时的指纹一样
if [ "$DRY_RUN" = 1 ]; then
  W_FP="预演"
  MINING=(--mining-report reports/warmup_check_W25.md)
else
  for f in runs/W25/train_log.json runs/W25/adapter/adapter_config.json runs/W25_train_mining/evals.jsonl; do
    [ -e "$f" ] || stop "找不到阶段三的 $f：右侧 Add Input 加上阶段三 Notebook 的输出（stage3_results.zip）"
  done
  el warmup check --evals runs/W25_train_mining/evals.jsonl --title "预热达标检查：25 道题" --out "$WORK/warmup_check_W25.again.md" >/dev/null \
    || stop "W25 的 train_mining 评测不能做达标检查"
  cmp -s "$WORK/warmup_check_W25.again.md" reports/warmup_check_W25.md || stop "W25 的 train_mining 评测和 reports/warmup_check_W25.md（D13）对不上"
  python - <<'PY' 2>&1 | tee -a "$STATUS"
import json
log = json.load(open("runs/W25/train_log.json", encoding="utf-8"))
print(f"W25 训练 {log['optimizer_steps']} 步，用时 {log['seconds']} 秒，显存峰值 {log['peak_memory_gb']} GB（D14 的时间估计按这个核对）")
PY
  if [ ! -f "$W/config.json" ]; then
    python scripts/merge_lora.py --train-log runs/W25/train_log.json --out "$W" 2>&1 | tee -a "$STATUS"
    [ "${PIPESTATUS[0]}" = 0 ] || stop "重新合并 W25 失败"
  fi
  W_FP=$(python - <<'PY'
import json
from evidenceloop.harness.backends import weights_fingerprint
log = json.load(open("runs/W25/train_log.json", encoding="utf-8"))
fp = weights_fingerprint("runs/W25/merged")
print(fp if fp and fp == log.get("merged_fingerprint") else "")
PY
)
  [ -n "$W_FP" ] || stop "重新合并出的 W25 和训练时的指纹不一样：D14 不在没测过的 W 上训练"
  note "W25 重新合并，指纹 $W_FP，和训练时一致"
  MINING=(--evals runs/W25_train_mining/evals.jsonl)
fi

# ---- 4. B、C、D 的数据、对齐、评测题和 W+ICL 的题（D14），哈希和 configs/stage4.json 核对
el stage4 build "${MINING[@]}" --tasks-dir "$TASKS" --warmup-records data/warmup/dose100.records.jsonl 2>&1 | tee -a "$STATUS"
[ "${PIPESTATUS[0]}" = 0 ] || stop "阶段四的数据和 configs/stage4.json 对不上"
if [ "$DRY_RUN" != 1 ]; then
  for s in "${SEEDS[@]}"; do
    for arm in "${ARMS[@]}"; do
      python scripts/check_template.py --model "$BASE" --records "data/stage4/$arm$s/records.jsonl" --n 100 2>&1 | tail -n 3 | tee -a "$STATUS"
      [ "${PIPESTATUS[0]}" = 0 ] || stop "真实模板的前缀一致性检查没有全部通过：$arm$s"
    done
    python scripts/check_template.py --model "$BASE" --budget "data/stage4/export_s$s/B$s.trl.jsonl" \
      "data/stage4/export_s$s/C$s.trl.jsonl" "data/stage4/export_s$s/D$s.trl.jsonl" 2>&1 | tail -n 4 | tee -a "$STATUS"
    [ "${PIPESTATUS[0]}" = 0 ] || stop "种子 $s 三组的监督 token 数相差超过 5%（D10、D14）"
  done
fi

# ---- 5. 先训完全部 9 个 LoRA，再开始任何评测（D14）
for s in "${SEEDS[@]}"; do for arm in "${ARMS[@]}"; do train_one "$arm" "$s"; done; done

# ---- 6. 评测：W25 → B、C、D（按种子）→ A → W25+ICL。A、W25 的 validation 用阶段三的结果
eval_row W25 data/stage4/test.public.jsonl "$W" "" test_id test_ood
for s in "${SEEDS[@]}"; do
  for arm in "${ARMS[@]}"; do
    eval_row "$arm$s" data/stage4/eval.public.jsonl "$W" "runs/$arm$s/adapter" validation test_id test_ood
  done
done
eval_row A data/stage4/test.public.jsonl "$BASE" "" test_id test_ood
for s in "${SEEDS[@]}"; do
  eval_row "ICL$s" "data/stage4/icl$s.test_id.public.jsonl" "$W" "" test_id
done

# ---- 7. 报告：每个划分一份总表、一份对比；结论只看 test_id（D14）
for split in validation test_id test_ood; do report_split "$split"; done
if [ ${#FAILED[@]} -gt 0 ]; then
  note "没跑成的（D14：如实列出，不补跑、不换设置）："
  for f in "${FAILED[@]}"; do note "  - $f"; done
fi
note "完成：结论在 $REPORTS/stage4_compare_test_id.md"
package
