#!/usr/bin/env bash
# 阶段五在 Kaggle 上一键跑完，规则全部来自 D12、D14、D16，不做任何临时判断。
#
# Notebook 设置：Accelerator 选 GPU T4（P100 不行，见 D14），Internet 打开；右侧 Add Input 加上阶段四那个 Notebook
# 的输出（stage4_results.zip：W25 和 C1–C3 的 adapter、训练日志、W25 在 train_mining 上的评测、阶段四的评测）。
# 只要一格，再点 Save Version → Save & Run All：
#   !git clone -q https://github.com/langju123456/evidenceloop.git /kaggle/working/evidenceloop
#   !bash /kaggle/working/evidenceloop/scripts/kaggle_stage5.sh
#
# 三组（D16）：C = 阶段四训好的 C1–C3（只做 SFT，不重训）；P = 在 W25 上只用偏好对做 DPO；
#   CP = 把 C_s 合并进 W25 得到 WC_s，再用同一份偏好对做 DPO。
# 流程：恢复阶段四的结果 → 装环境（D12、D14 钉住的版本）→ 核对六个冻结划分、预热数据、W25、阶段四的数据和
#   C 的 adapter → el stage5 build：偏好对的哈希要和 configs/stage5.json 一样 → 真实模板检查
#   → 难度检查：C1–C3 考 calib_hard，成功率不在 20%–90% 之间就停下，不训练
#   → 先训完全部 6 个 LoRA（P1 CP1 P2 CP2 P3 CP3）→ 再评测：W25、C、P、CP 考 test_hard，P、CP 另考 test_id，
#   WC_s 考 calib_hard（只作描述）→ 出报告 → 打包。
# 进度和结论写在 /kaggle/working/STATUS.md，结果在 stage5_results.zip（不含几 GB 的合并模型）。
# 用了 STAGE5_STOP_AFTER_MIN 分钟（默认 600）以后不再开始新的训练或评测，先打包；把这次的输出也加为 Input，
# 用同一格再跑一次就接着跑（训好的不重训，el run 自己续跑）。
# STAGE5_DRY_RUN=1：没有 GPU 的预演。不装环境、不合并、不训练（只打印命令），用脚本化参考策略代替模型跑完全部评测
# 和报告，报告写进 reports_dryrun/，用来检查脚本本身。参考策略每道题都做对，所以预演里难度检查必然"不通过"，
# 预演只把它记下来，接着往下走。
#   mkdir -p /tmp/s5 && git clone -q . /tmp/s5/evidenceloop
#   STAGE5_DRY_RUN=1 KAGGLE_WORK=/tmp/s5 KAGGLE_INPUT=/tmp/s5/none bash /tmp/s5/evidenceloop/scripts/kaggle_stage5.sh
set -uo pipefail

WORK="${KAGGLE_WORK:-/kaggle/working}"
INPUT="${KAGGLE_INPUT:-/kaggle/input}"
REPO="$WORK/evidenceloop"
STATUS="$WORK/STATUS.md"
ZIP="$WORK/stage5_results.zip"
DRY_RUN="${STAGE5_DRY_RUN:-0}"
STOP_AFTER_MIN="${STAGE5_STOP_AFTER_MIN:-600}"
BASE=Qwen/Qwen3-1.7B
TASKS=data/tasks/gen-0.2.1
W=runs/W25/merged
SEEDS=(1 2 3)
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
  for f in runs/*/train_log.json runs/*/traces.jsonl runs/*/evals*.jsonl runs/*/adapter runs/*/fingerprint.txt \
           data/stage5/*.manifest.json; do
    [ -e "$f" ] && files+=("$f")
  done
  rm -f "$ZIP"
  zip -qr "$ZIP" "${files[@]}" && note "已打包：$ZIP"
}

# D14、D16 的时间上限：到了就不再开始新的训练或评测，先打包，下次接着跑。
check_time() {
  local used=$(( ($(date +%s) - START) / 60 ))
  if [ "$used" -ge "$STOP_AFTER_MIN" ]; then
    note "已用 $used 分钟，到了 $STOP_AFTER_MIN 分钟的上限：不再开始新的训练或评测。把这次的输出加为 Input，用同一格再跑一次会接着跑。"
    package
    exit 0
  fi
}

# 上一次阶段五的结果先恢复（里面的进度最新），再是阶段四、阶段三的。已有的文件不覆盖。
restore() {
  local z d
  [ -d "$INPUT" ] || return 0
  while IFS= read -r z; do
    unzip -n -q "$z" -x 'reports/*' 'data/*' -d "$REPO" && note "从 $z 恢复了 runs/"
  done < <(find "$INPUT" -name 'stage5_results.zip' 2>/dev/null | sort; find "$INPUT" -name 'stage[34]_results.zip' 2>/dev/null | sort -r)
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

fingerprint() {  # $1 目录
  python - "$1" <<'PY'
import sys
from evidenceloop.harness.backends import weights_fingerprint
print(weights_fingerprint(sys.argv[1]) or "")
PY
}

# 一次训练是否已经按规则跑完：日志完整、adapter 对得上、数据是这一份、起点是指定的模型、设置没有改。
# kind = sft：阶段四的 C（D14 的设置）；kind = dpo：这次的 P、CP（D16 的设置）。
trained() {  # $1 kind $2 训练目录 $3 数据 $4 种子 $5 起点的指纹
  [ $# = 5 ] && [ -f "$2/train_log.json" ] && [ -f "$2/adapter/adapter_config.json" ] || return 1
  python - "$@" <<'PY'
import hashlib, json, sys
from evidenceloop.data import stage4, stage5
from evidenceloop.harness.backends import weights_fingerprint
kind, run, data, seed, base_fp = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
if not base_fp:
    sys.exit(f"{run}：没有给起点的指纹，不能核对")
with open(f"{run}/train_log.json", encoding="utf-8") as fh:
    log = json.load(fh)
with open(data, "rb") as fh:
    sha = hashlib.sha256(fh.read()).hexdigest()
check = stage4.training_problems if kind == "sft" else stage5.training_problems
problems = check(log, sha, base_fp, seed, weights_fingerprint(f"{run}/adapter"))
for p in problems:
    print(f"{run}：{p}")
sys.exit(1 if problems else 0)
PY
}

# WC_s = W25 + C_s 合并（CP 的起点，也是它的 reference）。几个 GB 一份，用完就删；再合并时指纹要和第一次一样。
ensure_wc() {  # $1 种子
  local s="$1" dir="runs/WC$1/merged" fp old
  if [ "$DRY_RUN" = 1 ]; then
    note "[预演] python scripts/merge_lora.py --train-log runs/C$s/train_log.json --out $dir"
    return 0
  fi
  if [ ! -f "$dir/config.json" ]; then
    rm -rf "$dir"
    python scripts/merge_lora.py --train-log "runs/C$s/train_log.json" --out "$dir" 2>&1 | tail -n 2 | tee -a "$STATUS"
    [ "${PIPESTATUS[0]}" = 0 ] || { note "合并 WC$s 失败"; return 1; }
  fi
  fp=$(fingerprint "$dir")
  old=$(cat "runs/WC$s/fingerprint.txt" 2>/dev/null)
  if [ -z "$fp" ] || { [ -n "$old" ] && [ "$fp" != "$old" ]; }; then
    note "WC$s 这次合并的指纹是 ${fp:-空}，上一次是 ${old:-空}：不是同一个模型"
    return 1
  fi
  echo "$fp" > "runs/WC$s/fingerprint.txt"
  note "WC$s = W25 + C$s，指纹 $fp"
}

drop_wc() { rm -rf "runs/WC$1/merged"; }

# 一个 DPO 的 LoRA：D12 的设置加 β = 0.1、每步 8 对（D16），1 轮，训练种子 = 复现种子。reference 就是起点模型。
# 失败就用同一条命令再训一次，还失败记为没跑成。
train_one() {  # $1 行名 $2 种子 $3 起点模型 $4 起点的指纹
  local name="$1" seed="$2" base="$3" base_fp="$4" data="data/stage5/prefs_s$2.trl.jsonl" i
  local cmd=(python scripts/train_dpo.py --base "$base" --data "$data" --beta 0.1 --grad-accum 8 --epochs 1 --seed "$seed" --out "runs/$name")
  if [ "$DRY_RUN" = 1 ]; then note "[预演] ${cmd[*]}"; return 0; fi
  if trained dpo "runs/$name" "$data" "$seed" "$base_fp" >/dev/null; then note "$name 已经训好，跳过"; return 0; fi
  for i in 1 2; do
    check_time
    rm -rf "runs/$name"
    note "训练 $name（第 $i 次）"
    "${cmd[@]}"
    if trained dpo "runs/$name" "$data" "$seed" "$base_fp" 2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ]; then
      note "$name 训练完成"
      return 0
    fi
  done
  FAILED+=("$name：训练两次都没成")
  note "$name 训练两次都没成，记为没跑成（D14、D16），其余照常"
  return 1
}

# P、CP 只考按 D16 训好的那一个：日志、adapter、偏好对、起点都对得上。预演里没有训练，直接放行。
usable() {  # $1 行名 $2 种子 $3 起点的指纹
  [ "$DRY_RUN" = 1 ] && return 0
  trained dpo "runs/$1" "data/stage5/prefs_s$2.trl.jsonl" "$2" "$3" >/dev/null && return 0
  note "$1 没有按 D16 训好的 adapter（或者起点对不上），不考"
  return 1
}

# 一行评测：同一个目录里续跑，运行故障的题最多重跑三次；还有没跑成的题，这一行记为没跑成。
eval_row() {  # $1 行名 $2 题目文件 $3 模型 $4 adapter（空 = 不用）；后面是要评分的划分
  local row="$1" tasks="$2" model="$3" adapter="$4" out="runs/${1}_stage5" i left split
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
    note "$row 重跑三次仍有 $left 道没跑成，记为没跑成（D14、D16），其余照常"
    return 1
  fi
  for split in "$@"; do
    el eval --traces "$out/traces.jsonl" --private "$TASKS/$split.private.jsonl" --out "$out/evals_$split.jsonl" \
      | tail -n 1 | sed "s#^#  $row $split：#" | tee -a "$STATUS"
    [ "${PIPESTATUS[0]}" = 0 ] || stop "el eval 失败：$out $split"
  done
}

# 每个划分上的行：组[:种子]=评测文件。W25 和 C 在 test_id 上用阶段四的结果（同一后端、同一个 W25、同一批 adapter）。
rows_for() {  # $1 划分
  local split="$1" s
  if [ "$split" = calib_hard ]; then
    for s in "${SEEDS[@]}"; do echo "C:$s=runs/C${s}cal_stage5/evals_calib_hard.jsonl"; done
    for s in "${SEEDS[@]}"; do echo "WC:$s=runs/WC${s}_stage5/evals_calib_hard.jsonl"; done
    return
  fi
  if [ "$split" = test_id ]; then
    echo "W=runs/W25_stage4/evals_test_id.jsonl"
    for s in "${SEEDS[@]}"; do echo "C:$s=runs/C${s}_stage4/evals_test_id.jsonl"; done
  else
    echo "W=runs/W25_stage5/evals_$split.jsonl"
    for s in "${SEEDS[@]}"; do echo "C:$s=runs/C${s}_stage5/evals_$split.jsonl"; done
  fi
  for s in "${SEEDS[@]}"; do echo "P:$s=runs/P${s}_stage5/evals_$split.jsonl"; done
  for s in "${SEEDS[@]}"; do echo "CP:$s=runs/CP${s}_stage5/evals_$split.jsonl"; done
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
    el report baseline --evals "${files[@]}" --names "${names[@]}" --title "阶段五：$split" --out "$REPORTS/stage5_$split.md"
  fi
  [ "$split" = calib_hard ] && return 0  # 只并排列出 C_s 和 WC_s，不做对比（D16）
  el stage5 compare --split "$split" "${args[@]}" --out "$REPORTS/stage5_compare_$split.md" >/dev/null \
    || note "对比报告没写成：$split"
}

# 训练日志里 D16 要描述的两项：reference 本来就更偏向 chosen 的偏好对占多少；chosen、rejected 的平均对数概率怎么变。
training_summary() {
  python - <<'PY'
import glob, json
for path in sorted(glob.glob("runs/P[0-9]/train_log.json") + glob.glob("runs/CP[0-9]/train_log.json")):
    with open(path, encoding="utf-8") as fh:
        log = json.load(fh)
    if log.get("loss") != "dpo" or not log.get("steps"):
        continue
    ref, first, last = log["reference"], log["steps"][0], log["steps"][-1]
    print(f"  {path.split('/')[1]}：{log['pairs']} 对，{log['optimizer_steps']} 步（跳过 {log['skipped_steps']}），"
          f"reference 本来就更偏向 chosen 的 {ref['chosen_more_likely']} 对；loss {first['loss']:.4f} → {last['loss']:.4f}；"
          f"chosen 的平均对数概率 {first['logp_chosen']:.2f} → {last['logp_chosen']:.2f}，"
          f"rejected {first['logp_rejected']:.2f} → {last['logp_rejected']:.2f}；"
          f"用时 {log['seconds']} 秒（其中 reference {ref['seconds']} 秒），显存峰值 {log['peak_memory_gb']} GB")
PY
}

echo "# 阶段五运行状态" > "$STATUS"
note "开始，代码 $(git rev-parse --short HEAD 2>/dev/null || echo '?')$([ "$DRY_RUN" = 1 ] && echo '（预演：脚本化参考策略，不合并、不训练）')"
mkdir -p "$REPORTS"

# ---- 0. 恢复阶段四（和上一次阶段五）的结果
restore

# ---- 1. 环境（D12；D14 钉住的 transformers 和 peft，重新合并 W25 才能得到同一个指纹）
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

# ---- 2. 四个旧的冻结划分、预热数据
el frozen verify 2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ] || stop "冻结划分的哈希对不上"
el warmup build --tasks-dir "$TASKS" 2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ] || stop "预热数据和 configs/warmup.json 对不上"

# ---- 3. W25：评测要和 D13 的报告一字不差，重新合并的权重要和训练时的指纹一样（和阶段四同一套核对）
if [ "$DRY_RUN" = 1 ]; then
  W_FP="预演"
  MINING=(--mining-report reports/warmup_check_W25.md)
else
  for f in runs/W25/train_log.json runs/W25/adapter/adapter_config.json runs/W25_train_mining/evals.jsonl; do
    [ -e "$f" ] || stop "找不到 $f：右侧 Add Input 加上阶段四 Notebook 的输出（stage4_results.zip）"
  done
  el warmup check --evals runs/W25_train_mining/evals.jsonl --title "预热达标检查：25 道题" --out "$WORK/warmup_check_W25.again.md" >/dev/null \
    || stop "W25 的 train_mining 评测不能做达标检查"
  cmp -s "$WORK/warmup_check_W25.again.md" reports/warmup_check_W25.md || stop "W25 的 train_mining 评测和 reports/warmup_check_W25.md（D13）对不上"
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
  [ -n "$W_FP" ] || stop "重新合并出的 W25 和训练时的指纹不一样：不在没测过的 W 上训练（D14）"
  note "W25 重新合并，指纹 $W_FP，和训练时一致"
  MINING=(--evals runs/W25_train_mining/evals.jsonl)
fi

# ---- 4. 阶段四的数据（C 的训练文件从这里来）、两个新的冻结划分、偏好对：哈希都要和 configs/ 里记的一样
el stage4 build "${MINING[@]}" --tasks-dir "$TASKS" --warmup-records data/warmup/dose100.records.jsonl 2>&1 | tail -n 1 | tee -a "$STATUS"
[ "${PIPESTATUS[0]}" = 0 ] || stop "阶段四的数据和 configs/stage4.json 对不上"
TRAINED=(data/warmup/dose100.records.jsonl)
for s in "${SEEDS[@]}"; do for arm in B C D; do TRAINED+=("data/stage4/$arm$s/records.jsonl"); done; done
el stage5 freeze --tasks-dir "$TASKS" --exclude-records "${TRAINED[@]}" 2>&1 | tee -a "$STATUS"
[ "${PIPESTATUS[0]}" = 0 ] || stop "test_hard、calib_hard 和 configs/frozen_hard.json 对不上"
el stage5 build "${MINING[@]}" --tasks-dir "$TASKS" --warmup-records data/warmup/dose100.records.jsonl 2>&1 | tee -a "$STATUS"
[ "${PIPESTATUS[0]}" = 0 ] || stop "阶段五的数据和 configs/stage5.json 对不上"
if [ "$DRY_RUN" != 1 ]; then
  for s in "${SEEDS[@]}"; do
    python scripts/check_template.py --model "$BASE" --pairs "data/stage5/prefs_s$s.trl.jsonl" 2>&1 | tail -n 3 | tee -a "$STATUS"
    [ "${PIPESTATUS[0]}" = 0 ] || stop "真实模板的前缀一致性检查没有全部通过：种子 $s 的偏好对"
  done
  # C1–C3 必须就是阶段四训的那三个：数据是 configs/stage4.json 记的那一份，起点是这个 W25，设置是 D12 的加 1 轮
  for s in "${SEEDS[@]}"; do
    if trained sft "runs/C$s" "data/stage4/export_s$s/C$s.trl.jsonl" "$s" "$W_FP" 2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ]; then
      note "C$s 是阶段四训好的那个（数据、起点、设置都对得上）"
    else
      stop "runs/C$s 不是阶段四按 D14 训好的 C$s：右侧 Add Input 加上阶段四 Notebook 的输出（stage4_results.zip）"
    fi
  done
  for f in runs/W25_stage4/evals_test_id.jsonl runs/C1_stage4/evals_test_id.jsonl runs/C2_stage4/evals_test_id.jsonl runs/C3_stage4/evals_test_id.jsonl; do
    [ -f "$f" ] || note "注意：没有 $f，test_id 上的对比会缺这一行（主指标在 test_hard 上，不受影响）"
  done
fi

# ---- 5. 难度检查（D16，在任何训练之前）：C1–C3 考 calib_hard，三个种子合起来的成功率要在 20%–90% 之间
GATE=()
for s in "${SEEDS[@]}"; do
  eval_row "C${s}cal" "$TASKS/calib_hard.public.jsonl" "$W" "runs/C$s/adapter" calib_hard
  GATE+=(--row "C:$s=runs/C${s}cal_stage5/evals_calib_hard.jsonl")
done
el stage5 gate "${GATE[@]}" --out "$REPORTS/stage5_gate.md" 2>&1 | tee -a "$STATUS"
case "${PIPESTATUS[0]}" in
  0) note "难度检查通过，开始训练" ;;
  3) if [ "$DRY_RUN" = 1 ]; then
       note "[预演] 参考策略每道题都做对，难度检查必然不通过；预演接着往下走"
     else
       stop "难度检查不通过：不训练，如实报告，另记决策重新定难度（D16）。报告在 $REPORTS/stage5_gate.md"
     fi ;;
  *) stop "难度检查做不了：C 在 calib_hard 上的评测不完整" ;;
esac

# ---- 6. 先训完全部 6 个 LoRA，再开始 test_hard、test_id 上的任何评测（D16）。P 从 W25 出发，CP 从 WC_s 出发
for s in "${SEEDS[@]}"; do
  train_one "P$s" "$s" "$W" "$W_FP"
  WC_FP=$(cat "runs/WC$s/fingerprint.txt" 2>/dev/null)
  if [ "$DRY_RUN" != 1 ] && [ -n "$WC_FP" ] && trained dpo "runs/CP$s" "data/stage5/prefs_s$s.trl.jsonl" "$s" "$WC_FP" >/dev/null; then
    note "CP$s 已经训好，跳过"
    continue
  fi
  check_time
  if ensure_wc "$s"; then
    train_one "CP$s" "$s" "runs/WC$s/merged" "$(cat "runs/WC$s/fingerprint.txt" 2>/dev/null)"
  else
    FAILED+=("CP$s：WC$s 没合并成")
    note "CP$s 的起点 WC$s 没合并成，记为没跑成（D16），其余照常"
  fi
  drop_wc "$s"
done
[ "$DRY_RUN" = 1 ] || training_summary 2>&1 | tee -a "$STATUS"

# ---- 7. 评测：W25 → 每个种子的 C、P、CP → WC（calib_hard，只作描述）。CP 和 WC 的基座是重新合并的 WC_s
eval_row W25 "$TASKS/test_hard.public.jsonl" "$W" "" test_hard
for s in "${SEEDS[@]}"; do
  eval_row "C$s" "$TASKS/test_hard.public.jsonl" "$W" "runs/C$s/adapter" test_hard
  usable "P$s" "$s" "$W_FP" && eval_row "P$s" data/stage5/eval.public.jsonl "$W" "runs/P$s/adapter" test_hard test_id
  check_time
  # 两行都已经跑完（上一次会话）就不用再合并 WC_s，只重新评分
  if { [ "$(pending data/stage5/eval.public.jsonl "runs/CP${s}_stage5/traces.jsonl")" = 0 ] \
       && [ "$(pending "$TASKS/calib_hard.public.jsonl" "runs/WC${s}_stage5/traces.jsonl")" = 0 ]; } || ensure_wc "$s"; then
    usable "CP$s" "$s" "$(cat "runs/WC$s/fingerprint.txt" 2>/dev/null)" \
      && eval_row "CP$s" data/stage5/eval.public.jsonl "runs/WC$s/merged" "runs/CP$s/adapter" test_hard test_id
    eval_row "WC$s" "$TASKS/calib_hard.public.jsonl" "runs/WC$s/merged" "" calib_hard
  else
    FAILED+=("CP$s、WC$s：评测前 WC$s 没合并成，或者和训练时不是同一个模型")
    note "CP$s、WC$s 不考：WC$s 没合并成，或者和训练时不是同一个模型"
  fi
  drop_wc "$s"
done

# ---- 8. 报告：结论只看 test_hard 上的 H4（D16）；test_id 和 calib_hard 只作描述
for split in test_hard test_id calib_hard; do report_split "$split"; done
if [ ${#FAILED[@]} -gt 0 ]; then
  note "没跑成的（D14、D16：如实列出，不补跑、不换设置）："
  for f in "${FAILED[@]}"; do note "  - $f"; done
fi
note "完成：结论在 $REPORTS/stage5_compare_test_hard.md"
package
