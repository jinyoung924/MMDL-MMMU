"""Diagnostic only (structreward/protocol.md, run log 2026-11-15): the frozen evaluation with the stage A2 format
instruction placed before the CoT suffix, exactly where `sr.py prep_own` puts it. run_eval.py is not edited.
scores.json does not record the prompt change, so the output directory must say it (runs/diag_base_format/...);
never aggregate such a run with base runs.

python structreward/diag_format_eval.py --seed 0 --gpu-mem-util 0.75 --out runs/diag_base_format/seed0   # env: vllm
"""
import sys
from pathlib import Path

S = Path(__file__).resolve().parent
sys.path[:0] = [str(S), str(S.parent)]
import run_eval
from sr import FORMAT

run_eval.COT_MC_SUFFIX = FORMAT + run_eval.COT_MC_SUFFIX
run_eval.COT_OPEN_SUFFIX = FORMAT + run_eval.COT_OPEN_SUFFIX
run_eval.main()
