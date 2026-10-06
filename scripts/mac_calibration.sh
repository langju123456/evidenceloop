#!/usr/bin/env bash
# Full calibration (60 tasks) on the Mac. Run after mac_quickstart.sh.
#   bash scripts/mac_calibration.sh                              # Qwen3-0.6B
#   bash scripts/mac_calibration.sh Qwen/Qwen3-1.7B              # a bigger base model
#   bash scripts/mac_calibration.sh Qwen/Qwen3-0.6B --thinking   # thinking mode
# Ctrl+C at any time; running the same command again resumes where it stopped.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
MODEL="${1:-Qwen/Qwen3-0.6B}"
EXTRA="${2:-}"
NAME="$(basename "$MODEL" | tr '[:upper:]' '[:lower:]')${EXTRA:+-thinking}"
ENV_VERSION="$(python -c 'from evidenceloop.common import ENV_VERSION; print(ENV_VERSION)')"
NAME="${NAME}_${ENV_VERSION}"
OUT="runs/calib_${NAME}"
echo "== calibration：60 道题，模型 ${MODEL} ${EXTRA}（可以随时 Ctrl+C，再运行同一条命令会接着跑）=="
el run --tasks data/tasks/calibration.public.jsonl --backend mlx --model "$MODEL" $EXTRA --out "$OUT" --batch-size 1
el eval --traces "$OUT/traces.jsonl" --private data/tasks/calibration.private.jsonl --out "$OUT/evals.jsonl"
el report baseline --evals "$OUT/evals.jsonl" --names "$NAME" --out "reports/calibration_${NAME}.md"
cat "reports/calibration_${NAME}.md"
echo
echo "完整报告：reports/calibration_${NAME}.md；逐题轨迹：python scripts/peek.py ${OUT}"
