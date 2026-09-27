#!/usr/bin/env bash
# Commit ONE result directory and push it to the current results/<RUN_NAME> branch.
#   bash cloud/push_results.sh runs/<RUN_NAME>/seed0
# Called by eval.sh after every finished seed (AFTER_SEED) and by cloud/runpod.sh at the end, so a pod
# that dies later cannot lose finished work. Safe to call repeatedly and from several pods at once.
#
# Rules that keep code history and experiment history apart (cloud/README.md §결과 브랜치):
#   1. refuses to run unless the checked-out branch is results/*  -> never commits to main
#   2. stages only the given directory                            -> a results commit never carries code edits
#   3. push rejected? fetch + rebase + retry; still failing? push to a uniquely named fallback branch
#   4. without GITHUB_TOKEN it does nothing (local runs are unaffected)
set -uo pipefail
[[ $# -eq 1 ]] || { echo "usage: $0 <result dir>" >&2; exit 1; }
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"
REL="$(python3 -c 'import os, sys; print(os.path.relpath(os.path.abspath(sys.argv[1]), sys.argv[2]))' "$1" "$REPO_DIR")"
[[ "$REL" == ..* || "$REL" == /* ]] && { echo "push_results: $1 is outside the repo -> refusing" >&2; exit 1; }
[[ -d "$REL" ]] || { echo "push_results: $REL does not exist -> nothing to push"; exit 0; }

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != results/* ]]; then
  echo "push_results: current branch '$BRANCH' is not a results/* branch -> refusing (see cloud/README.md)" >&2
  exit 1
fi
RUN_NAME="${RUN_NAME:-${BRANCH#results/}}"

pid1() { tr '\0' '\n' 2>/dev/null < /proc/1/environ | sed -n "s/^$1=//p" | head -1; }
TOKEN="${GITHUB_TOKEN:-$(pid1 GITHUB_TOKEN)}"
[[ -z "$TOKEN" ]] && { echo "push_results: no GITHUB_TOKEN -> skipped (results stay local)"; exit 0; }
REPO_SLUG="${REPO_SLUG:-$(git remote get-url origin | sed -E 's#.*github\.com[:/]##; s#\.git$##')}"
URL="${PUSH_URL:-https://x-access-token:${TOKEN}@github.com/${REPO_SLUG}.git}"   # PUSH_URL: non-GitHub remote / tests

git config user.name  "${GIT_AUTHOR_NAME:-runpod-bot}"
git config user.email "${GIT_AUTHOR_EMAIL:-runpod-bot@users.noreply.github.com}"

git add -A -- "$REL"
OTHER="$(git diff --cached --name-only | grep -v "^$REL/" || true)"   # belt and braces: only the result dir
if [[ -n "$OTHER" ]]; then
  git reset -q -- $OTHER
  echo "push_results: left unstaged (not part of $REL):"; echo "$OTHER" | sed 's/^/    /'
fi
if git diff --cached --quiet; then
  echo "push_results: nothing new under $REL (pushing unpushed commits, if any)"   # e.g. an earlier push failed
else
  git commit -q -m "results($RUN_NAME): $REL" \
    -m "pod: ${RUNPOD_POD_ID:-$(hostname)}  time: $(date -u +%Y-%m-%dT%H:%M:%SZ)  pushed by cloud/push_results.sh"
fi

for i in 1 2 3 4 5; do
  if git push -q "$URL" "HEAD:refs/heads/$BRANCH"; then
    echo "push_results: pushed $REL -> $REPO_SLUG:$BRANCH"; exit 0
  fi
  echo "push_results: push rejected (attempt $i), rebasing onto remote $BRANCH"
  if git fetch -q "$URL" "$BRANCH" 2>/dev/null; then
    git rebase -q FETCH_HEAD || { git rebase --abort; break; }   # result dirs are unique per run, so this is rare
  fi
  sleep 10
done

FALLBACK="$BRANCH-$(hostname)-$(date -u +%H%M%S)"
if git push -q "$URL" "HEAD:refs/heads/$FALLBACK"; then
  echo "push_results: WARNING pushed to fallback branch $FALLBACK (merge it by hand)"; exit 0
fi
echo "push_results: PUSH FAILED for $REL (commit is kept locally on $BRANCH)" >&2
exit 1
