#!/usr/bin/env bash
# v6 (v6_protocol.md): domain-matched VWI pool screened by the teacher, on-policy distillation from 8B-Instruct-FP8
# + outcome reward, no Sonnet. Rounds 0-29; §5.5 dev evaluation (900 q, seed 0) after rounds 9/19/29;
# dev accuracy <= 62.93 at r009/r019 stops the run. Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
V=v6; MEM=${MEM:-0.68}
ENV=/home/leesg17/miniconda3/etc/profile.d/conda.sh
if [ ! -f grpo/data/pool_v6.jsonl ]; then  # teacher screen: first 1,200 items, 1 sample, keep teacher-correct
  (source $ENV && conda activate vllm-train && cd grpo && export HF_HUB_OFFLINE=1 &&
   head -1200 data/pool_v6_all.jsonl | python3 -c "import json,sys; [print(json.loads(l)['qid']) for l in sys.stdin]" > data/screen_ids_v6.txt &&
   { [ -f data/screen_v6.jsonl ] || python grpo.py screen --pool data/pool_v6_all.jsonl --ids data/screen_ids_v6.txt \
       --screen-model Qwen/Qwen3-VL-8B-Instruct-FP8 --samples 1 --gpu-mem 0.80 --out data/screen_v6.jsonl; } &&
   python - <<'EOF'
import json, sys
from collections import Counter
from grpo import fix_gold
ok = {s['qid'] for s in map(json.loads, open('data/screen_v6.jsonl')) if s['correct'] >= 1}
out = [fix_gold(q) for q in map(json.loads, open('data/pool_v6_all.jsonl')) if q['qid'] in ok]
open('data/pool_v6.jsonl', 'w').writelines(json.dumps(q, ensure_ascii=False) + '\n' for q in out)
print(json.dumps({'screened': sum(1 for _ in open('data/screen_v6.jsonl')), 'kept': len(out),
                  'domain': Counter(q['domain'] for q in out)}))
sys.exit(0 if len(out) >= 496 else 1)  # protocol: fewer than 31 rounds x 16 -> screen the next 1,200 (by hand)
EOF
  )
fi
dev() {  # $1 = checkpoint round tag
  local m=grpo/runs/$V/merged_$1
  [ -f "$m/config.json" ] || (source $ENV && conda activate vllm-train && python grpo/grpo.py merge --adapter grpo/runs/$V/ckpt/$1 --out "$m")
  (source $ENV && conda activate vllm && SEEDS=0 bash eval.sh "$m" "runs/grpo_${V}_$1_full")
}
floor() {  # stop rule: dev accuracy <= 62.93 (delta <= -2.0 vs base mean 64.93)
  python3 -c "import json,sys; a=json.load(open('runs/grpo_${V}_$1_full/seed0/scores.json'))['overall_micro']; print('dev', '$1', a); sys.exit(1 if a <= 0.6293 else 0)"
}
for seg in "10 r009" "20 r019" "30 r029"; do
  set -- $seg
  next=$(grep -c '"phase": "train"' grpo/runs/$V/log.jsonl 2>/dev/null || true)
  RUN=runs/$V START=${next:-0} END=$1 TEACHER=1 bash grpo/loop.sh \
    --pool data/pool_v6.jsonl --questions 16 --pool-offset 0 --samples 8 --no-topup --teacher-coef 1 \
    --drop-truncated --length-guard --length-ref data/screen_v6.jsonl --acc-window 4 --groups-per-step 4 --lr 1e-4 --beta 0.01 --gpu-mem "$MEM"
  dev $2
  [ "$2" = r029 ] || floor $2
done
