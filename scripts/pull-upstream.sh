#!/usr/bin/env bash
# 拉取 Archery 上游最新代码并尝试合并

set -e

cd "$(dirname "$0")/.."

UPSTREAM_REPO="${UPSTREAM_REPO:-https://github.com/hhyo/Archery.git}"
BRANCH="${UPSTREAM_BRANCH:-master}"

if ! git remote get-url upstream >/dev/null 2>&1; then
  echo "==> 添加 upstream remote"
  git remote add upstream "$UPSTREAM_REPO"
fi

echo "==> 拉取上游 $BRANCH"
git fetch upstream "$BRANCH"

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "==> 当前分支：$CURRENT_BRANCH"

read -p "确认要在当前分支合入 upstream/$BRANCH 吗？[y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "已取消"
  exit 0
fi

git merge "upstream/$BRANCH" --no-edit
echo "==> 合入完成。请检查冲突。"
