#!/usr/bin/env bash
# 阶段一基线：在冻结后的划分上跑一个模型，每跑完一个划分就提交并推送结果。test_id、test_ood 保持密封，不在这里跑。
#   bash scripts/mac_baseline.sh Qwen/Qwen3-1.7B                    # 基座：validation，然后 train_mining
#   bash scripts/mac_baseline.sh Qwen/Qwen3-0.6B validation         # 排行榜上的其他尺寸只跑 validation
# 可以随时 Ctrl+C，再运行同一条命令会接着跑。
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
MODEL="${1:-}"
if [ -z "$MODEL" ]; then
  echo "用法：bash scripts/mac_baseline.sh Qwen/Qwen3-1.7B [validation train_mining]"
  exit 1
fi
shift
SPLITS=("$@")
[ ${#SPLITS[@]} -gt 0 ] || SPLITS=(validation train_mining)
if [ ! -f configs/frozen.json ]; then
  echo "还没有冻结配置：先运行 el freeze"
  exit 1
fi
TASKS="$(python -c 'import json; print(json.load(open("configs/frozen.json"))["tasks_dir"])')"
ENV_VERSION="$(python -c 'from evidenceloop.common import ENV_VERSION; print(ENV_VERSION)')"
NAME="$(basename "$MODEL" | tr '[:upper:]' '[:lower:]')"
for SPLIT in "${SPLITS[@]}"; do
  OUT="runs/${SPLIT}_${NAME}_${ENV_VERSION}"
  echo "== ${SPLIT}：模型 ${MODEL}（${ENV_VERSION}）=="
  el run --tasks "$TASKS/${SPLIT}.public.jsonl" --backend mlx --model "$MODEL" --out "$OUT" --batch-size 1
  el eval --traces "$OUT/traces.jsonl" --private "$TASKS/${SPLIT}.private.jsonl" --out "$OUT/evals.jsonl"
  el report baseline --evals "$OUT/evals.jsonl" --names "${NAME}_${SPLIT}" --out "reports/baseline_${SPLIT}_${NAME}_${ENV_VERSION}.md"
  bash scripts/checkpoint.sh "加入 ${NAME} 在 ${SPLIT} 上的基线（${ENV_VERSION}）"
done
