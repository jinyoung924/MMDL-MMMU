#!/usr/bin/env bash
# StructReward stage B (structreward/protocol.md): structured-reward GRPO + judgment/choice tasks on top of the merged
# stage A model. 50 rounds x 20 questions x 8 responses; MMMU dev (900 q, seed 0) after rounds 24 and 49;
# dev <= 63.06 at round 24 stops the run. Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh
export HF_HUB_OFFLINE=1
export GRPO_MODEL=$PWD/grpo/runs/${COLD:-sr_sft}/merged   # rollouts, training and the KL reference all start from the cold-start model
NAME=${RUN_NAME:-sr_rl}; RUN=runs/$NAME   # COLD / RUN_NAME: sr_sft2 / sr_rl2 for the own-solution cold start (Amendment 1)
MEM=${MEM:-0.75}   # GPU share for vLLM (other GPU jobs run on this machine; see chain_a.sh)
# length guard: finished tokens relative to the reference solution of the same question (same-question rule, v6 Amendment 1)
# Amendment 7: TRUNC= (empty) keeps responses cut at the token limit in training, NORM=--per-response averages the loss
# per response, AUX=balanced draws the judgment examples evenly, PROBE=n runs the hard-question probe every n rounds
ARGS="--pool ../structreward/data/pool_rl.jsonl --questions ${QUESTIONS:-20} --samples 8 --no-topup ${TRUNC---drop-truncated} ${NORM:-} --length-guard
  --length-ref ../structreward/data/pool_rl_len.jsonl --acc-window 4 --groups-per-step 4 --lr 1e-4 --beta ${BETA:-0.001} --ckpt-every 25 --gpu-mem $MEM"
dev() {  # $1 = checkpoint tag
  local m=grpo/$RUN/merged_$1
  [ -f "$m/config.json" ] || (conda activate vllm-train && python grpo/grpo.py merge --adapter grpo/$RUN/ckpt/$1 --out "$m")
  (conda activate vllm && { [ -f "runs/${NAME}_$1_full/seed0/scores.json" ] || python run_eval.py --model "$m" --seed 0 --gpu-mem-util $MEM --out "runs/${NAME}_$1_full/seed0"; } &&
   python analyze.py compare results/seed* vs "runs/${NAME}_$1_full/seed0" --base-mean 1 | tee "runs/${NAME}_$1_full/compare_base_mean.txt")
  python3 -c "
import json, sys; a = 100 * json.load(open('runs/${NAME}_$1_full/seed0/scores.json'))['overall_micro']
print(f'dev $NAME $1 {a:.2f}  (base 5-seed mean 65.16)'); sys.exit(1 if a <= 63.06 else 0)" | tee structreward/runs/gate_dev_${NAME}_$1.txt
}
conda activate vllm-train
for seg in "25 r024" "50 r049"; do
  set -- $seg
  [ "$1" -le "${MAX_ROUNDS:-50}" ] || break   # diagnostic 6: 40 questions a round use the pool up in 25 rounds
  start=$(grep -c '"phase": "train"' grpo/$RUN/log.jsonl 2>/dev/null || true)
  for ((r=${start:-0}; r<$1; r++)); do
    f=grpo/$RUN/rounds/r$(printf %03d "$r").jsonl
    [ -f "$f" ] || (cd grpo && { python grpo.py rollout --run $RUN --round "$r" $ARGS || python grpo.py rollout --run $RUN --round "$r" $ARGS; })
    grep -q '"sr": ' "$f" || python structreward/sr.py reward $RUN "$r" ${STEPS:-} | tee -a structreward/runs/reward_$NAME.log  # STEPS=steps: Amendment 4, recall: 5, both: 6
    python3 -c "  # step guard (Amendment 5): steps per response, mean of the last 2 rounds, outside 0.5-2 x round 0 stops the run
import json, sys; log = [json.loads(l) for l in open('structreward/runs/reward_$NAME.log')]; mean = lambda v: sum(v) / len(v)
s = [x['steps'] for x in log]; m = mean(s[-2:]); bad = not 0.5 * s[0] <= m <= 2 * s[0]; print('step guard', {'steps_2round': round(m, 2), 'steps_round0': s[0], 'stop': bad})
v = [x['values'] for x in log if 'values' in x]  # value guard (Amendment 8): values read per response, last 4 rounds over the first 4
if len(v) >= 8: r = mean(v[-4:]) / mean(v[:4]); b = not 0.5 <= r <= 2; bad |= b; print('value guard', {'last4_over_first4': round(r, 2), 'stop': b})
sys.exit(bad)"
    [ "${AUX:-}" = none ] || python structreward/sr.py aux $RUN "$r" ${AUX:-} | tee -a structreward/runs/aux_$NAME.log  # AUX=none: no judgment tasks
    (cd grpo && python grpo.py train --run $RUN --round "$r" $ARGS && python grpo.py guard --run $RUN $ARGS)
    if [ -n "${PROBE:-}" ] && (( (r + 1) % PROBE == 0 )); then  # probe guard: 100 hard questions outside the pool, 1 response each
      p=structreward/runs/probe_${NAME}_r$(printf %03d "$r")
      [ -f $p.jsonl ] || (cd grpo && python grpo.py screen --pool data/pool_v4.jsonl --ids ../structreward/data/probe_ids.txt \
        --samples 1 --seed 0 --gpu-mem $MEM --adapter $RUN/adapter --out ../$p.jsonl)
      python3 -c "
import json, sys; cut = lambda f: 100 * (lambda v: sum(v) / len(v))([json.loads(l)['finish'] != 'stop' for l in open(f)])
a, c = cut('$p.rows.jsonl'), cut('structreward/runs/probe_cold.rows.jsonl'); bad = a > c + ${PROBE_MAX:-10}
print('probe guard', {'round': $r, 'cut': round(a, 1), 'cold_start': round(c, 1), 'stop': bad}); sys.exit(bad)" | tee -a structreward/runs/probe_$NAME.log
    fi
  done
  date; echo "== dev $2"
  dev "$2" || { [ "$2" = r049 ] || { echo "== dev floor at $2: stop"; exit 0; }; }
done
date; echo "== stage B done"
