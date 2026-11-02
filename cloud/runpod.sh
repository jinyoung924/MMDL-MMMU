#!/usr/bin/env bash
# RunPod entry point: setup -> smoke test -> RUN_CMD -> push results -> terminate the pod.
#
#   RUN_NAME=baseline_repro bash cloud/runpod.sh                     # 5-seed baseline -> runs/<RUN_NAME>/
#   MODEL=/workspace/ckpt_merged RUN_NAME=sft_lr1e-4 bash cloud/runpod.sh      # fine-tuned checkpoint
#   TRAIN=1 RUN_NAME=sft RUN_CMD='python pilot_forgetting/train_sft.py --out runs/$RUN_NAME/train && \
#     python pilot_forgetting/train_sft.py --merge runs/$RUN_NAME/train/step2000 && \
#     bash eval.sh $PWD/runs/$RUN_NAME/train/step2000_merged runs/$RUN_NAME/eval' bash cloud/runpod.sh
#
# Deploy page env vars: GITHUB_TOKEN, RUNPOD_USER_API_KEY, PUBLIC_KEY (cloud/README.md §1.2).
# Every knob is an env var with a default (table in cloud/README.md). The evaluation code itself
# (run_eval.py / analyze.py / eval.sh) is untouched: this file only wraps it.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"
T_START=$(date +%s)

# --- pod environment -----------------------------------------------------------------------------------
# The RunPod deploy page sets exactly three variables: GITHUB_TOKEN, RUNPOD_USER_API_KEY, PUBLIC_KEY
# (RunPod adds RUNPOD_POD_ID itself). An SSH session does not inherit the container env, so every value is
# looked up as: shell env -> PID 1 env (what the deploy page set) -> default. Any knob below can therefore be
# given either on the command line (`RUN_NAME=x bash cloud/runpod.sh`) or on the deploy page.
pid1() { tr '\0' '\n' 2>/dev/null < /proc/1/environ | sed -n "s/^$1=//p" | head -1; }
envor() { local v="${!1:-}"; [[ -n "$v" ]] || v="$(pid1 "$1")"; [[ -n "$v" ]] || v="${2:-}"; printf '%s' "$v"; }

export GITHUB_TOKEN="$(envor GITHUB_TOKEN)"                # required: results push
export RUNPOD_USER_API_KEY="$(envor RUNPOD_USER_API_KEY)"  # pod self-termination
export PUBLIC_KEY="$(envor PUBLIC_KEY)"                    # ssh access (RunPod images install it; we make sure)
export RUNPOD_POD_ID="$(envor RUNPOD_POD_ID)"

if [[ -n "$PUBLIC_KEY" ]]; then   # idempotent: only add the key if the image has not done it already
  mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
  grep -qxF "$PUBLIC_KEY" ~/.ssh/authorized_keys || echo "$PUBLIC_KEY" >> ~/.ssh/authorized_keys
fi
if [[ -z "$GITHUB_TOKEN" && "$(envor ALLOW_NO_PUSH 0)" != "1" ]]; then
  echo "FATAL: GITHUB_TOKEN is not set (deploy page -> Environment Variables). Without it the results of a" >&2
  echo "       multi-hour run stay on this pod only. Set it, or run with ALLOW_NO_PUSH=1 on purpose." >&2
  exit 2
fi
[[ -n "$RUNPOD_USER_API_KEY" ]] || echo "WARNING: RUNPOD_USER_API_KEY not set -> the pod will NOT terminate itself"

# --- knobs -------------------------------------------------------------------------------------------
export RUN_NAME="$(envor RUN_NAME "$(date -u +%Y%m%d-%H%M)-${RUNPOD_POD_ID:-$(hostname)}")"
MODEL="$(envor MODEL Qwen/Qwen3-VL-4B-Instruct)"
OUT="$(envor OUT "runs/$RUN_NAME")"
export SEEDS="$(envor SEEDS "0 1 2 3 4")"
RUN_CMD="$(envor RUN_CMD "bash eval.sh \"$MODEL\" \"$OUT\"")"
export TRAIN="$(envor TRAIN 0)"
SKIP_SMOKE="$(envor SKIP_SMOKE 0)"
AUTO_TERMINATE="$(envor AUTO_TERMINATE 1)"        # terminate the pod after a successful run
TERMINATE_ON_FAIL="$(envor TERMINATE_ON_FAIL 0)"  # 0 = keep a failed pod alive so you can ssh in and look
export RESULTS_BRANCH="results/$RUN_NAME"
export AFTER_SEED="$REPO_DIR/cloud/push_results.sh"   # eval.sh calls this after every finished seed
export HF_HOME="$(envor HF_HOME /workspace/hf)"
export VENV_DIR="$(envor VENV_DIR "")"
export TOKENIZERS_PARALLELISM=false

mkdir -p "$OUT"
exec > >(tee -a "$OUT/console.log") 2>&1          # *.log is gitignored: console stays on the pod

# --- wrap-up runs on ANY exit: record, push what exists, terminate -----------------------------------
STATUS=running
finish() {
  rc=$?
  [[ "$STATUS" == running ]] && STATUS=failed
  trap - EXIT
  echo "== wrap-up: status=$STATUS rc=$rc =="
  python3 - "$OUT/cloud_run.json" <<PY || true
import json, sys, datetime
p = sys.argv[1]
try:
    d = json.load(open(p))
except Exception:
    d = {}
d.update(status="$STATUS", exit_code=$rc, finished_utc=datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
         elapsed_min=round(($(date +%s) - $T_START) / 60, 1))
json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
PY
  PUSHED=1
  if [[ "$(git rev-parse --abbrev-ref HEAD)" == results/* ]]; then
    bash cloud/push_results.sh "$OUT" || PUSHED=0
  else
    echo "stopped before the results branch was created -> nothing to push"
  fi
  if [[ "$PUSHED" == 0 ]]; then
    echo "results are NOT on GitHub -> keeping the pod alive. Fix and run: bash cloud/push_results.sh $OUT"
  elif [[ "$AUTO_TERMINATE" == "1" && ( "$STATUS" == ok || "$TERMINATE_ON_FAIL" == "1" ) ]]; then
    if [[ -n "$RUNPOD_USER_API_KEY" && -n "$RUNPOD_POD_ID" ]]; then
      echo "terminating pod $RUNPOD_POD_ID in 30 s (Ctrl-C to keep it)"; sleep 30
      curl -s -X POST "https://api.runpod.io/graphql?api_key=$RUNPOD_USER_API_KEY" -H 'Content-Type: application/json' \
        -d "{\"query\":\"mutation { podTerminate(input: {podId: \\\"$RUNPOD_POD_ID\\\"}) }\"}" && echo
    else
      echo "no RUNPOD_USER_API_KEY / RUNPOD_POD_ID -> pod left running, terminate it yourself"
    fi
  fi
}
trap finish EXIT

# --- git: put this run on its own results/<RUN_NAME> branch ------------------------------------------
# Code commits stay on main; every commit this pod makes lands on results/<RUN_NAME> and only adds
# files under $OUT. A pod restart with the same RUN_NAME resumes from the remote branch (finished seeds
# come back, eval.sh skips them). Different runs never share a branch or a directory -> no conflicts.
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "FATAL: tracked files are modified in the working tree. Commit them to main (or discard) before running." >&2
  git status --short --untracked-files=no; exit 2
fi
REPO_SLUG="${REPO_SLUG:-$(git remote get-url origin | sed -E 's#.*github\.com[:/]##; s#\.git$##')}"
FETCH_URL="${PUSH_URL:-https://github.com/${REPO_SLUG}.git}"
[[ -z "${PUSH_URL:-}" && -n "$GITHUB_TOKEN" ]] && FETCH_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO_SLUG}.git"
BASE_COMMIT="$(git rev-parse HEAD)"
if git fetch -q "$FETCH_URL" "$RESULTS_BRANCH" 2>/dev/null; then
  echo "resuming existing branch $RESULTS_BRANCH"
  git checkout -q -B "$RESULTS_BRANCH" FETCH_HEAD
else
  git checkout -q -B "$RESULTS_BRANCH"
fi
echo "branch: $RESULTS_BRANCH (code base $BASE_COMMIT)"

# Can this token actually push? Checked now, not after six hours of GPU time. (A fine-grained PAT with
# Contents: read-only reads the repo fine and fails only here with 403.)
if [[ -n "$GITHUB_TOKEN" ]]; then
  if ! git push -q --dry-run "$FETCH_URL" "HEAD:refs/heads/$RESULTS_BRANCH" 2>"$OUT/.push_probe"; then
    sed "s#${GITHUB_TOKEN}#TOKEN#g" "$OUT/.push_probe" >&2
    echo "FATAL: GITHUB_TOKEN cannot push to $REPO_SLUG. Fine-grained PAT needs: Repository access -> this repo," >&2
    echo "       Permissions -> Contents: Read and write. Classic PAT needs the 'repo' scope." >&2
    echo "       A running pod keeps its old env: pass the new token on the command line, GITHUB_TOKEN=... bash cloud/runpod.sh" >&2
    exit 2
  fi
  rm -f "$OUT/.push_probe"; echo "push preflight OK ($REPO_SLUG:$RESULTS_BRANCH)"
fi

# --- environment ------------------------------------------------------------------------------------
bash cloud/setup_runpod.sh
for v in "${VENV_DIR:-}" /workspace/venv "$PWD/.venv"; do
  if [[ -n "$v" && -f "$v/bin/activate" ]]; then source "$v/bin/activate"; break; fi
done
_hl="${NVIDIA_CTK_LIBCUDA_DIR:-/usr/lib/x86_64-linux-gnu}"
[[ -e "$_hl/libcuda.so.1" ]] && export LD_LIBRARY_PATH="$_hl${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
python -m pip freeze > "$OUT/requirements.lock.txt"

python3 - "$OUT/cloud_run.json" <<PY
import json, sys, datetime, subprocess
gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                     capture_output=True, text=True).stdout.strip()
json.dump({"run_name": "$RUN_NAME", "results_branch": "$RESULTS_BRANCH", "code_commit": "$BASE_COMMIT",
           "model": "$MODEL", "out": "$OUT", "seeds": "$SEEDS", "run_cmd": ${RUN_CMD@Q},
           "pod_id": "$RUNPOD_POD_ID", "gpu": gpu,
           "started_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z", "status": "running"},
          open(sys.argv[1], "w"), indent=2, ensure_ascii=False)
PY

# --- smoke test: 1 question per subject, seed 0. Catches env/model/data problems in ~5 min ------------
if [[ "$SKIP_SMOKE" != "1" ]]; then
  echo "== smoke test =="
  python run_eval.py --model "$MODEL" --seed 0 --limit 1 --out "$OUT/smoke" --subjects Art Math
  echo "smoke OK"
fi

# --- main job ---------------------------------------------------------------------------------------
echo "== RUN_CMD: $RUN_CMD =="
eval "$RUN_CMD"
STATUS=ok
echo "== done in $(( ($(date +%s) - T_START) / 60 )) min =="
