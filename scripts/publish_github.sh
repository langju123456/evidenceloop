#!/usr/bin/env bash
# First (and every later) upload to GitHub.
#   bash scripts/publish_github.sh                  # creates a public repo named evidenceloop on first run
#   bash scripts/publish_github.sh evidenceloop "说明这次改了什么"
# Needs git and the GitHub CLI (gh), logged in once with: gh auth login
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="${1:-evidenceloop}"
MESSAGE="${2:-EvidenceLoop: environment, verifier, data pipeline, calibration runs and decision log}"

command -v git >/dev/null || { echo "没有 git：在终端运行 xcode-select --install 安装命令行工具后再试"; exit 1; }
command -v gh >/dev/null || { echo "没有 GitHub CLI：运行 brew install gh，或从 https://cli.github.com 下载 macOS 安装包"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "还没登录 GitHub：先运行 gh auth login，按提示用浏览器登录"; exit 1; }
if [ -z "$(git config user.name || true)" ] || [ -z "$(git config user.email || true)" ]; then
  echo "先设置提交者信息（会公开显示在提交记录里）："
  echo '  git config --global user.name "你的名字"'
  echo '  git config --global user.email "你的邮箱"'
  exit 1
fi

[ -d .git ] || git init -q -b main
git add -A
echo "== 这次会上传的文件 =="
git status --short | head -80
if git diff --cached --quiet; then
  echo "没有新的改动需要提交"
else
  git commit -q -m "$MESSAGE"
fi
if git remote get-url origin >/dev/null 2>&1; then
  git push -u origin main
else
  gh repo create "$NAME" --public --source=. --remote=origin --push
fi
echo "完成：$(gh repo view --json url -q .url)"
