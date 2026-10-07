#!/usr/bin/env bash
# 每完成一个阶段性的事情，就用它提交并推送到 GitHub：
#   bash scripts/checkpoint.sh "提交信息"
# 代码有改动时先跑测试，不通过就不提交；只提交项目文件（runs/、data/、日志留在本地）；
# 提交信息原样使用，不加任何署名行。
set -euo pipefail
cd "$(dirname "$0")/.."
MSG="${1:-}"
if [ -z "$MSG" ]; then
  echo '用法：bash scripts/checkpoint.sh "提交信息"'
  exit 1
fi
source .venv/bin/activate
chmod +x scripts/*.sh

CODE_PATHS=(src tests scripts pyproject.toml)
if ! git diff --quiet HEAD -- "${CODE_PATHS[@]}" || [ -n "$(git ls-files --others --exclude-standard -- "${CODE_PATHS[@]}")" ]; then
  echo "== 代码有改动，先跑测试 =="
  python -m pytest -q
fi

PATHS=()
for path in README.md LICENSE pyproject.toml .gitignore configs docs reports scripts src tests; do
  [ -e "$path" ] && PATHS+=("$path")
done
git add -A -- "${PATHS[@]}"
if git diff --cached --quiet; then
  echo "没有新的改动要提交。"
else
  git commit -q -m "$MSG"
  echo "已提交：$(git log -1 --format='%h %s')"
fi

git push -q origin HEAD   # also sends earlier local commits that never reached GitHub
echo "GitHub 已同步到：$(git log -1 --format='%h %s')"
