#!/usr/bin/env bash
# Local-side git helper. The ONLY git commands a Claude session needs for the experiment loop
# (cloud/README.md §0). Each subcommand is one safe, idempotent step:
#
#   bash cloud/local.sh push-code "message"   # ① commit code/docs on main and push (pull --rebase first). Never adds runs/
#   bash cloud/local.sh list                  #    result branches on origin, with their status
#   bash cloud/local.sh fetch  <RUN_NAME>     # ③ copy runs/<RUN_NAME>/ from origin into the working tree (no git state change)
#   bash cloud/local.sh merge  <RUN_NAME>     # ④ keep: merge results/<RUN_NAME> into main, push, delete the remote branch
#   bash cloud/local.sh drop   <RUN_NAME>     # ④ discard: delete the remote branch and the local copy
#   bash cloud/local.sh status                #    where am I, what is uncommitted, what is unmerged
set -euo pipefail
cd "$(dirname "$0")/.."
cmd="${1:-status}"; arg="${2:-}"
die() { echo "local.sh: $*" >&2; exit 1; }
need_run() { [[ -n "$arg" ]] || die "usage: $0 $cmd <RUN_NAME>"; }
on_main() { [[ "$(git rev-parse --abbrev-ref HEAD)" == main ]] || die "switch to main first: git checkout main"; }
clean_tracked() {
  [[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "uncommitted changes to tracked files. Run: bash cloud/local.sh push-code \"msg\"  (or git stash)"
}

case "$cmd" in
  push-code)
    on_main
    git fetch -q origin
    git add -A -- . ':!runs'                       # runs/ is written only by pods (via results/* branches)
    if git diff --cached --quiet; then echo "nothing to commit"; else
      git commit -q -m "${arg:-update}" && echo "committed: ${arg:-update}"
    fi
    git pull -q --rebase origin main || die "rebase conflict with origin/main. Resolve, then: git rebase --continue && git push origin main"
    git push -q origin main && echo "pushed main -> origin ($(git rev-parse --short HEAD))"
    ;;

  list)
    git fetch -q --prune origin
    git for-each-ref --format='%(refname:short)' refs/remotes/origin/results/ | while read -r ref; do
      name="${ref#origin/results/}"
      merged=$(git merge-base --is-ancestor "$ref" origin/main 2>/dev/null && echo merged || echo unmerged)
      st=$(git show "$ref:runs/$name/cloud_run.json" 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status","?"), d.get("model",""), d.get("elapsed_min",""),"min")' 2>/dev/null || echo "running/partial")
      printf '%-40s %-9s %s\n' "$name" "$merged" "$st"
    done
    ;;

  fetch)
    need_run
    git fetch -q origin "results/$arg" || die "origin has no branch results/$arg (still running? check: bash cloud/local.sh list)"
    rm -rf "runs/$arg"
    git archive FETCH_HEAD "runs/$arg" | tar -x
    echo "runs/$arg/ updated from origin/results/$arg (untracked; analyze it, then merge or drop)"
    ls "runs/$arg"
    ;;

  merge)
    need_run; on_main; clean_tracked
    git fetch -q origin "results/$arg" main
    rm -rf "runs/$arg"                                # the untracked copy from `fetch` would block the merge
    git merge -q --no-ff FETCH_HEAD -m "merge results/$arg" \
      || die "merge failed (unexpected: results branches only add runs/$arg/). git merge --abort to undo"
    git push -q origin main && echo "merged results/$arg into main and pushed"
    git push -q origin --delete "results/$arg" && echo "deleted origin/results/$arg"
    ;;

  drop)
    need_run
    git push -q origin --delete "results/$arg" 2>/dev/null && echo "deleted origin/results/$arg" || echo "origin/results/$arg already gone"
    rm -rf "runs/$arg" && echo "removed local runs/$arg"
    ;;

  status)
    echo "branch : $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)"
    git fetch -q origin 2>/dev/null || true
    echo "vs main: $(git rev-list --count origin/main..HEAD 2>/dev/null || echo ?) ahead, $(git rev-list --count HEAD..origin/main 2>/dev/null || echo ?) behind"
    echo "uncommitted tracked changes:"; git status --short --untracked-files=no | sed 's/^/    /'
    echo "local runs/ not in git:"; git status --short --untracked-files=all -- runs 2>/dev/null | cut -d/ -f1-2 | sort -u | sed 's/^/    /'
    echo "result branches:"; "$0" list | sed 's/^/    /'
    ;;
  *) die "unknown subcommand '$cmd'. See header of $0" ;;
esac
