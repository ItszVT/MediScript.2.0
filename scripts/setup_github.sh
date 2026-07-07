#!/usr/bin/env bash
# One-shot GitHub setup for MediScript (macOS/Linux/Git-Bash).
#   ./scripts/setup_github.sh <repo-name> [--private]
# If the GitHub CLI (gh) is installed and authenticated, this creates the repo
# and pushes. Otherwise it commits locally and prints the remote/push commands.
set -e
REPO="${1:-mediscript}"
VIS="public"; [ "${2:-}" = "--private" ] && VIS="private"

cd "$(dirname "$0")/.."

if [ ! -d .git ]; then git init -q; fi
git add -A
git commit -qm "Initial commit: MediScript prescription reader + pharmacy platform" || echo "(nothing new to commit)"
git branch -M main

if command -v gh >/dev/null 2>&1; then
  echo "Creating $VIS GitHub repo '$REPO' and pushing…"
  gh repo create "$REPO" --"$VIS" --source=. --remote=origin --push
  echo "Done → $(gh repo view --json url -q .url 2>/dev/null || echo pushed)"
else
  echo "GitHub CLI (gh) not found. Local commit is ready. To finish:"
  echo "  1) Create an empty repo named '$REPO' on github.com (no README)."
  echo "  2) Run:"
  echo "       git remote add origin https://github.com/<you>/$REPO.git"
  echo "       git push -u origin main"
fi
