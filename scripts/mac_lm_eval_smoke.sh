#!/usr/bin/env bash
# 用 lm-evaluation-harness 在 Mac 上跑一个公开小任务，确认公开评测工具能在本机走通。
# 和 EvidenceLoop 自己的环境分开：单独建一个 venv（默认在 ~/.venvs/evidenceloop-lm-eval），不动仓库里的 .venv。
# 模型 Qwen/Qwen3-0.6B，任务 arc_easy（科学常识选择题，按每个选项的对数似然打分，不生成文字）。
#   bash scripts/mac_lm_eval_smoke.sh          # 冒烟：前 50 题，CPU 和 MPS 各跑一遍，比较准确率
#   bash scripts/mac_lm_eval_smoke.sh full     # 全量（测试集 2376 题）；冒烟通过后再跑
# 可用环境变量改：LM_EVAL_MODEL、LM_EVAL_REVISION（把模型固定到某个提交）、LM_EVAL_TASK、LM_EVAL_LIMIT、
# LM_EVAL_DEVICE（全量用的设备，默认 mps；冒烟发现两种设备对不上时改成 cpu）、LM_EVAL_VENV。
# 第一次运行会下载 lm_eval、torch 和 arc_easy 数据集；模型用 Hugging Face 缓存里已有的。
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-smoke}"
MODEL="${LM_EVAL_MODEL:-Qwen/Qwen3-0.6B}"
TASK="${LM_EVAL_TASK:-arc_easy}"
LIMIT="${LM_EVAL_LIMIT:-50}"
DEVICE="${LM_EVAL_DEVICE:-mps}"
VENV="${LM_EVAL_VENV:-$HOME/.venvs/evidenceloop-lm-eval}"
LM_EVAL_VERSION=0.4.13
# float32：MPS 上半精度容易出数值问题，0.6B 用单精度也放得下
MODEL_ARGS="pretrained=${MODEL},dtype=float32${LM_EVAL_REVISION:+,revision=${LM_EVAL_REVISION}}"
NAME="$(basename "$MODEL" | tr '[:upper:]' '[:lower:]')"
OUT="runs/lm_eval/${TASK}_${NAME}"

if [ ! -x "$VENV/bin/lm-eval" ]; then
  PY=""
  for candidate in python3.12 python3.11 python3.13 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && \
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
      PY="$candidate"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "需要 Python 3.10 以上。先运行：brew install python@3.12"
    exit 1
  fi
  echo "== 建独立环境 $VENV 并安装 lm_eval[hf]==${LM_EVAL_VERSION}（几分钟，只做一次）=="
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q "lm_eval[hf]==${LM_EVAL_VERSION}"
fi

run_eval() {  # run_eval <设备> <输出目录> [其他 lm-eval 参数]
  local device="$1" out="$2"
  shift 2
  "$VENV/bin/lm-eval" run --model hf --model_args "$MODEL_ARGS" --tasks "$TASK" --device "$device" \
    --batch_size 8 --output_path "$out" --log_samples "$@"
}

accuracy() {  # 读某个输出目录里最新的结果文件，打印这个任务的 acc
  "$VENV/bin/python" - "$1" "$TASK" <<'PY'
import glob, json, os, sys
files = sorted(glob.glob(os.path.join(sys.argv[1], "**", "results_*.json"), recursive=True), key=os.path.getmtime)
if not files:
    sys.exit(f"{sys.argv[1]} 里没有结果文件")
scores = json.load(open(files[-1], encoding="utf-8"))["results"][sys.argv[2]]
print(next(value for name, value in scores.items() if name.split(",")[0] == "acc"))
PY
}

if [ "$MODE" = "smoke" ]; then
  echo "== 冒烟：${TASK} 前 ${LIMIT} 题，模型 ${MODEL}，先 CPU 后 MPS =="
  run_eval cpu "${OUT}_limit${LIMIT}_cpu" --limit "$LIMIT"
  run_eval mps "${OUT}_limit${LIMIT}_mps" --limit "$LIMIT"
  CPU_ACC="$(accuracy "${OUT}_limit${LIMIT}_cpu")"
  MPS_ACC="$(accuracy "${OUT}_limit${LIMIT}_mps")"
  echo "前 ${LIMIT} 题准确率：CPU ${CPU_ACC}，MPS ${MPS_ACC}"
  if [ "$CPU_ACC" != "$MPS_ACC" ]; then
    echo "两种设备的结果不一样。全量请用 CPU：LM_EVAL_DEVICE=cpu bash scripts/mac_lm_eval_smoke.sh full"
    exit 2
  fi
  echo "冒烟通过。全量：bash scripts/mac_lm_eval_smoke.sh full"
elif [ "$MODE" = "full" ]; then
  echo "== 全量：${TASK}，模型 ${MODEL}，设备 ${DEVICE} =="
  run_eval "$DEVICE" "${OUT}_full_${DEVICE}"
  echo "全量准确率：$(accuracy "${OUT}_full_${DEVICE}")（逐题输出在 ${OUT}_full_${DEVICE}）"
else
  echo "用法：bash scripts/mac_lm_eval_smoke.sh [smoke|full]"
  exit 1
fi
