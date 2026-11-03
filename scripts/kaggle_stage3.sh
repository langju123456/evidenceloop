#!/usr/bin/env bash
# 阶段三在 Kaggle 上一键跑完（docs/kaggle_stage3.md 第 1–3、5、6、7 步），规则全部来自 D11、D12，不做任何临时判断。
#
# Notebook 里只要一格（右侧 Accelerator 选 GPU T4，Internet 打开），再点 Save Version → Save & Run All：
#   !git clone -q https://github.com/langju123456/evidenceloop.git /kaggle/working/evidenceloop
#   !bash /kaggle/working/evidenceloop/scripts/kaggle_stage3.sh
#
# 流程：装环境 → 核对冻结划分和预热数据的哈希 → 真实模板检查 → A 行（train_mining + validation）
#   → A 达标就 W = A；否则按 10 → 25 → 50 → 100 预热，取第一个达标的一档；四档都不达标就停下如实报告
#   → W 考 validation → 出报告 → 打包 stage3_results.zip（不含几 GB 的合并模型，adapter 在里面）。
# 进度和结论写在 /kaggle/working/STATUS.md；同一条命令重跑会跳过已经完成的步骤（el run 自己会续跑）。
set -uo pipefail

WORK="${KAGGLE_WORK:-/kaggle/working}"
REPO="$WORK/evidenceloop"
STATUS="$WORK/STATUS.md"
BASE=Qwen/Qwen3-1.7B
TASKS=data/tasks/gen-0.2.1
cd "$REPO" || exit 1

note() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$STATUS"; }
stop() { note "停下：$*"; package; exit 1; }

package() {
  cd "$REPO" || return
  rm -rf runs/*/merged
  local files=(reports)
  for f in runs/*/train_log.json runs/*/traces.jsonl runs/*/evals.jsonl runs/*/adapter; do [ -e "$f" ] && files+=("$f"); done
  zip -qr "$WORK/stage3_results.zip" "${files[@]}" && note "已打包：$WORK/stage3_results.zip"
}

# 跑一个划分并评测；有运行故障（infra_error）就用同一条 el run 重跑，最多三次。
run_split() {  # $1 模型 $2 划分 $3 输出目录
  local model="$1" split="$2" out="$3" i
  for i in 1 2 3; do
    el run --backend vllm --model "$model" --tasks "$TASKS/$split.public.jsonl" --out "$out" || note "el run 返回非零（第 $i 次）"
    el eval --traces "$out/traces.jsonl" --private "$TASKS/$split.private.jsonl" --out "$out/evals.jsonl" || stop "el eval 失败：$out"
    local infra
    infra=$(python - "$out/evals.jsonl" <<'PY'
import json, sys
from evidenceloop.data.selection import is_infra_error
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print(sum(1 for r in rows if is_infra_error(r)))
PY
)
    [ "$infra" = "0" ] && return 0
    note "$out 有 $infra 道运行故障，重跑（第 $i 次）"
  done
  stop "$out 重跑三次仍有运行故障"
}

# D11 的达标检查；返回 0 = 达标，1 = 不达标。检查报告写进 reports/。
passes() {  # $1 evals $2 标题 $3 报告名
  el warmup check --evals "$1" --title "$2" --out "reports/$3.md" 2>&1 | tee -a "$STATUS"
  [ "${PIPESTATUS[0]}" = 0 ] || stop "达标检查拒绝了输入：$1"
  python - "$1" <<'PY'
import json, sys
from evidenceloop.data.warmup import check_warmup
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
sys.exit(0 if check_warmup(rows)["passed"] else 1)
PY
}

echo "# 阶段三运行状态" > "$STATUS"
note "开始，代码 $(git rev-parse --short HEAD)"

# ---- 1. 环境（D12）
pip install -q -e ".[kaggle]" || stop "pip install 失败"
pip install -q vllm==0.31.0 || stop "安装 vllm 失败"
pip uninstall -y -q torchaudio torchao >/dev/null 2>&1
python -c "import torch, transformers, peft, vllm; assert torch.cuda.is_available(), 'no GPU'; print('环境', torch.__version__, transformers.__version__, peft.__version__, vllm.__version__, torch.cuda.get_device_name(0))" \
  2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ] || stop "环境检查失败（没开 GPU，或依赖导入出错）"

# ---- 2–3. 冻结划分、预热数据、真实模板
el frozen verify 2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ] || stop "冻结划分的哈希对不上"
el warmup build --tasks-dir "$TASKS" 2>&1 | tee -a "$STATUS"; [ "${PIPESTATUS[0]}" = 0 ] || stop "预热数据和 configs/warmup.json 对不上"
python scripts/check_template.py --model "$BASE" --records data/warmup/dose100.records.jsonl --n 100 2>&1 | tee -a "$STATUS"
tail -n 3 "$STATUS" | grep -q "816/816 samples pass" || stop "真实模板的前缀一致性检查没有全部通过"

# ---- 5. A 行
run_split "$BASE" train_mining runs/A_train_mining
run_split "$BASE" validation runs/A_validation
W=""; WVAL=""
if passes runs/A_train_mining/evals.jsonl "预热达标检查：A（不预热）" warmup_check_A; then
  note "A 已达标：不预热，W 就是 A"
  W=A; WVAL=runs/A_validation
else
  # ---- 6. 预热：10 → 25 → 50 → 100，取第一个达标的一档（D12）
  for N in 10 25 50 100; do
    note "预热剂量 $N"
    if [ ! -f "runs/W$N/merged/config.json" ]; then
      python scripts/train_lora.py --base "$BASE" --data "data/warmup/dose$N.trl.jsonl" --epochs 1 \
        --out "runs/W$N" --merge-out "runs/W$N/merged" || stop "训练失败：剂量 $N"
    fi
    run_split "runs/W$N/merged" train_mining "runs/W${N}_train_mining"
    if passes "runs/W${N}_train_mining/evals.jsonl" "预热达标检查：$N 道题" "warmup_check_W$N"; then
      note "剂量 $N 达标：W = W$N"
      W="W$N"
      run_split "runs/W$N/merged" validation "runs/W${N}_validation"
      WVAL="runs/W${N}_validation"
      break
    fi
    rm -rf "runs/W$N/merged"
  done
  [ -n "$W" ] || stop "四档剂量都不达标（按 D12 停下如实报告，另记决策再定下一步）"
fi

# ---- 7. 报告
if [ "$W" = "A" ]; then
  el report baseline --evals runs/A_train_mining/evals.jsonl --names A --title "阶段三：train_mining" --out reports/stage3_train_mining.md
  el report baseline --evals runs/A_validation/evals.jsonl --names A --title "阶段三：validation" --out reports/stage3_validation.md
else
  el report baseline --evals runs/A_train_mining/evals.jsonl "runs/${W}_train_mining/evals.jsonl" --names A "$W" \
    --title "阶段三：train_mining" --out reports/stage3_train_mining.md
  el report baseline --evals runs/A_validation/evals.jsonl "$WVAL/evals.jsonl" --names A "$W" \
    --title "阶段三：validation" --out reports/stage3_validation.md
fi
note "完成：W = $W"
package
