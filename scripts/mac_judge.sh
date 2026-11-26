#!/usr/bin/env bash
# 裁判校准（D28，docs/report-lab/22-judge-calibration-freeze.md）在 Mac 上的各步。每步一条命令，按顺序做，
# 人工标注夹在两步之间。裁判用本机 Ollama 里已安装的模型（默认 qwen3:8b；换标签：JUDGE_MODEL=xxx bash ...）。
#   bash scripts/mac_judge.sh sample                 # 从 runs/ 抽样并冻结（不调模型）；RUNS=别的目录 可改来源
#   bash scripts/mac_judge.sh form dev|test|retest   # 生成标注表，浏览器打开，标完导出 JSON
#   bash scripts/mac_judge.sh labels dev|test|retest 导出的.json
#   bash scripts/mac_judge.sh smoke                  # 裁判只跑开发集前 3 条
#   bash scripts/mac_judge.sh dev                    # 裁判跑开发集并统计（可反复）
#   bash scripts/mac_judge.sh retest                 # 只看隔天重标的一致性
#   bash scripts/mac_judge.sh test 冻结提交的完整SHA   # 只能跑一次
#   bash scripts/mac_judge.sh annual-form | annual-labels 导出的.json | annual 冻结提交的完整SHA
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
MODEL="${JUDGE_MODEL:-qwen3:8b}"
DATA=benchmarks/judge_calib/v1/reply
OUT=reports/judge-calib/v1/reply
ANNUAL_DATA=benchmarks/judge_calib/v1/annual
ANNUAL_OUT=reports/judge-calib/v1/annual
mkdir -p "$OUT" "$ANNUAL_OUT"
STEP="${1:-}"
case "$STEP" in
  sample)
    el judge sample --runs "${RUNS:-runs}" --out "$DATA"
    echo "下一步：提交 $DATA，再 bash scripts/mac_judge.sh form dev"
    ;;
  form)
    el judge form --dataset "$DATA" --split "$2" --out "$OUT/form-$2.html"
    echo "用浏览器打开 $OUT/form-$2.html，标完点“导出标注”"
    ;;
  labels)
    el judge reconcile --dataset "$DATA" --split "$2" --submission "$3" --out "$OUT/labels-$2.json"
    ;;
  smoke)
    el judge run --dataset "$DATA" --split dev --model "$MODEL" --limit 3 --out "$OUT/judge-smoke-$(date +%Y%m%d-%H%M%S).jsonl"
    ;;
  dev)
    N=1
    while [ -e "$OUT/judge-dev-$N.jsonl" ]; do N=$((N + 1)); done
    el judge run --dataset "$DATA" --split dev --model "$MODEL" --out "$OUT/judge-dev-$N.jsonl"
    el judge agree --dataset "$DATA" --split dev --labels "$OUT/labels-dev.json" --judge "$OUT/judge-dev-$N.jsonl" \
       --out "$OUT/agree-dev-$N.json"
    ;;
  retest)
    el judge agree --dataset "$DATA" --split test --labels "$OUT/labels-test.json" \
       --retest-labels "$OUT/labels-retest.json" --out "$OUT/agree-retest.json"
    ;;
  test)
    # 裁判输出已经在的话只重新统计，不再调模型
    [ -e "$OUT/judge-test.jsonl" ] || \
      el judge run --dataset "$DATA" --split test --model "$MODEL" --freeze "$2" --labels "$OUT/labels-test.json" \
         --retest-labels "$OUT/labels-retest.json" --out "$OUT/judge-test.jsonl"
    el judge agree --dataset "$DATA" --split test --labels "$OUT/labels-test.json" --judge "$OUT/judge-test.jsonl" \
       --retest-labels "$OUT/labels-retest.json" --out "$OUT/agree-test.json"
    ;;
  annual-form)
    el judge form --dataset "$ANNUAL_DATA" --split all --out "$ANNUAL_OUT/form-all.html"
    echo "用浏览器打开 $ANNUAL_OUT/form-all.html，标完点“导出标注”"
    ;;
  annual-labels)
    el judge reconcile --dataset "$ANNUAL_DATA" --split all --submission "$2" --out "$ANNUAL_OUT/labels-all.json"
    ;;
  annual)
    [ -e "$ANNUAL_OUT/judge-all.jsonl" ] || \
      el judge run --dataset "$ANNUAL_DATA" --split all --model "$MODEL" --freeze "$2" --labels "$ANNUAL_OUT/labels-all.json" \
         --out "$ANNUAL_OUT/judge-all.jsonl"
    el judge agree --dataset "$ANNUAL_DATA" --split all --labels "$ANNUAL_OUT/labels-all.json" \
       --judge "$ANNUAL_OUT/judge-all.jsonl" --out "$ANNUAL_OUT/agree-all.json"
    ;;
  *)
    sed -n '2,12p' "$0"
    exit 1
    ;;
esac
