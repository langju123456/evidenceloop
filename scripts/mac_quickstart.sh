#!/usr/bin/env bash
# Stage 1 on the Mac (Apple silicon). Run from anywhere:  bash scripts/mac_quickstart.sh
# Stops after a 5-task smoke run so you can check the harness before spending time on full calibration.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && \
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    PY="$candidate"; break
  fi
done
if [ -z "$PY" ]; then
  echo "需要 Python 3.10 以上（系统自带的通常是 3.9）。先运行：brew install python@3.12"
  exit 1
fi

echo "== 0/4 正在安装依赖（安静模式，约一两分钟，没有输出是正常的）=="
"$PY" -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[dev,mac]" transformers

echo "== 1/4 测试 =="
python -m pytest -q

echo "== 2/4 生成任务 =="
el tasks build --split calibration  --n 60  --out data/tasks
el tasks build --split train_mining --n 200 --out data/tasks
el tasks build --split validation   --n 50  --out data/tasks

echo "== 3/4 真模型冒烟：5 道题（第一次会下载 Qwen3-0.6B，约 1.2GB；之后用缓存）=="
rm -rf runs/smoke_mlx   # the smoke run always starts fresh
el run --tasks data/tasks/calibration.public.jsonl --backend mlx --model Qwen/Qwen3-0.6B \
       --out runs/smoke_mlx --limit 5 --batch-size 1
el eval --traces runs/smoke_mlx/traces.jsonl --private data/tasks/calibration.private.jsonl \
        --out runs/smoke_mlx/evals.jsonl

echo "== 4/4 报告 =="
el report baseline --evals runs/smoke_mlx/evals.jsonl --names qwen3-0.6b-mlx --out reports/smoke.md
cat reports/smoke.md
echo
echo "== 每道题的轨迹 =="
python scripts/peek.py runs/smoke_mlx

cat <<'NEXT'

冒烟跑完了。确认模型在调用工具（轮数大于 1）之后，跑完整 calibration：

  bash scripts/mac_calibration.sh                              # Qwen3-0.6B，60 道题
  bash scripts/mac_calibration.sh Qwen/Qwen3-1.7B              # 换更大的基座对比
  bash scripts/mac_calibration.sh Qwen/Qwen3-0.6B --thinking   # 开 thinking 模式对比
NEXT
