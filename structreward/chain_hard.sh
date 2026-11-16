#!/usr/bin/env bash
# Amendment 9 (structreward/protocol.md): outcome-only GRPO on the hard pool (structreward/data/pool_hard.jsonl), from
# the base model (or from grpo/runs/$COLD/merged). Reward = 1 for a right finished answer, else 0; responses cut at the
# token limit stay in training; loss per response. 12 questions (8 multiple choice + 4 numeric) x 8 responses a round;
# hard-question probe every 8 rounds; MMMU dev (900 q, seed 0) after rounds 24 and 49; dev <= 63.06 at round 24 stops.
# Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1 SR_POOL=pool_hard
[ -z "${COLD:-}" ] || export GRPO_MODEL=$PWD/grpo/runs/$COLD/merged
NAME=${RUN_NAME:-hard1}; RUN=runs/$NAME; MEM=${MEM:-0.75}; R=structreward/runs; REF=probe_${COLD:+cold}; REF=${REF/%probe_/probe_base}
# guards (grpo.py guard): accuracy of the last 4 rounds below 0.5 x round 0, more than 50 % of a round cut, KL above 0.1,
# finished length relative to the base's length on the same question below 0.6 x its round-0 value
ARGS="--pool ../structreward/data/pool_hard.jsonl --questions 12 --samples 8 --no-topup --per-response --length-guard
  --length-ref ../structreward/data/pool_hard_len.jsonl --acc-window 4 --acc-floor 0.5 --trunc-max 0.5 --groups-per-step 4
  --lr 1e-4 --beta 0.01 --ckpt-every 25 --gpu-mem $MEM"
probe() {  # $1 = tag, $2 = adapter (empty: the starting model). 100 hard questions outside every training pool, 1 response each
  [ -f $R/$1.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v4.jsonl --ids ../structreward/data/probe_ids.txt \
    --samples 1 --seed 0 --gpu-mem $MEM ${2:+--adapter $2} --out ../$R/$1.jsonl)
}
dev() {  # $1 = checkpoint tag
  local m=grpo/$RUN/merged_$1
  [ -f "$m/config.json" ] || python grpo/grpo.py merge --adapter grpo/$RUN/ckpt/$1 --out "$m"
  (conda activate vllm && { [ -f "runs/${NAME}_$1_full/seed0/scores.json" ] || python run_eval.py --model "$m" --seed 0 --gpu-mem-util $MEM --out "runs/${NAME}_$1_full/seed0"; } &&
   python analyze.py compare results/seed* vs "runs/${NAME}_$1_full/seed0" --base-mean 1 | tee "runs/${NAME}_$1_full/compare_base_mean.txt")
  python3 -c "
import json, sys; a = 100 * json.load(open('runs/${NAME}_$1_full/seed0/scores.json'))['overall_micro']
print(f'dev $NAME $1 {a:.2f}  (base 5-seed mean 65.16)'); sys.exit(1 if a <= 63.06 else 0)" | tee $R/gate_dev_${NAME}_$1.txt
}
conda activate vllm-train
date; echo "== probe of the starting model ($REF)"; probe $REF ""
for seg in "25 r024" "50 r049"; do
  set -- $seg
  start=$(grep -c '"phase": "train"' grpo/$RUN/log.jsonl 2>/dev/null || true)
  for ((r=${start:-0}; r<$1; r++)); do
    f=grpo/$RUN/rounds/r$(printf %03d "$r").jsonl
    [ -f "$f" ] || (cd grpo && { python grpo.py rollout --run $RUN --round "$r" $ARGS || python grpo.py rollout --run $RUN --round "$r" $ARGS; })
    grep -q '"sr": ' "$f" || python structreward/sr.py reward $RUN "$r" right | tee -a $R/reward_$NAME.log
    (cd grpo && python grpo.py train --run $RUN --round "$r" $ARGS && python grpo.py guard --run $RUN $ARGS)
    if (( (r + 1) % 8 == 0 )); then  # probe guard: cut share more than 8 points above, or right share more than 12 points below, the starting model
      t=probe_${NAME}_r$(printf %03d "$r"); probe $t $RUN/adapter
      python3 -c "
import json, sys
def share(f): v = [json.loads(l) for l in open(f)]; return 100 * sum(r['finish'] != 'stop' for r in v) / len(v), 100 * sum(bool(r['correct']) for r in v) / len(v)
(c, k), (c0, k0) = share('$R/$t.rows.jsonl'), share('$R/$REF.rows.jsonl'); bad = c > c0 + 8 or k < k0 - 12
print('probe guard', {'round': $r, 'cut': c, 'right': k, 'start_cut': c0, 'start_right': k0, 'stop': bad}); sys.exit(bad)" | tee -a $R/probe_$NAME.log
    fi
  done
  date; echo "== dev $2"
  dev "$2" || { [ "$2" = r049 ] || { echo "== dev floor at $2: stop"; exit 0; }; }
done
date; echo "== hard-pool run done"
