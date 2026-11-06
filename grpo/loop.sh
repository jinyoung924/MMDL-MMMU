#!/usr/bin/env bash
# GRPO rounds START..END-1: rollout (vLLM) then train (HF), each its own process so the GPU is freed.
# JUDGE_MODEL=<hf id> adds the v3 judge step between rollout and train.
# Resume by re-running with START = next round (see $RUN/log.jsonl).
set -euo pipefail
cd "$(dirname "$0")"
RUN=${RUN:-runs/v1}; START=${START:-0}; END=${END:-20}
source /home/leesg17/miniconda3/etc/profile.d/conda.sh && conda activate vllm-train
export HF_HUB_OFFLINE=1
for ((r=START; r<END; r++)); do
  f="$RUN/rounds/r$(printf %03d "$r").jsonl"  # existing rollouts / verdicts are reused on resume
  [ -f "$f" ] || python grpo.py rollout --run "$RUN" --round "$r" "$@" || python grpo.py rollout --run "$RUN" --round "$r" "$@"  # one retry
  if [ "${JUDGE_MODEL:-}" = cli ]; then  # v3 Amendment 4b: headless Claude Code judge sessions, run by the loop itself
    d="$RUN/judge/r$(printf %03d "$r")"
    [ -f "$d/manifest.json" ] || python grpo.py judge-packets --run "$RUN" --round "$r"
    if ! grep -q '"judge_text"' "$f"; then
      python grpo.py judge-run --run "$RUN" --round "$r" "$@"
      python grpo.py judge-apply --run "$RUN" --round "$r" "$@"
    fi
  elif [ "${JUDGE_MODEL:-}" = subagent ]; then  # v3 Amendment 1: verdicts come from the orchestrating Claude session
    d="$RUN/judge/r$(printf %03d "$r")"
    [ -f "$d/manifest.json" ] || python grpo.py judge-packets --run "$RUN" --round "$r"
    until [ -f "$d/DONE" ]; do sleep 20; done
    grep -q '"judge_text"' "$f" || python grpo.py judge-apply --run "$RUN" --round "$r"
  elif [ -n "${JUDGE_MODEL:-}" ] && ! grep -q '"judge_text"' "$f"; then
    python grpo.py judge --run "$RUN" --round "$r" --judge-model "$JUDGE_MODEL" "$@"
  fi
  if [ -n "${TEACHER:-}" ] && ! grep -q '"tlogps"' "$f"; then  # v6: teacher logprobs of the student's tokens
    python grpo.py teacher-score --run "$RUN" --round "$r" "$@"
  fi
  python grpo.py train --run "$RUN" --round "$r" "$@"
  python grpo.py guard --run "$RUN" "$@"
done
