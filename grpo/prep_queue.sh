#!/usr/bin/env bash
# v6 preparation diagnostics (v6_prep_protocol.md), one GPU job at a time; each waits for >= 15 GB free RAM.
set -u
cd "$(dirname "$0")/.."
source /home/leesg17/miniconda3/etc/profile.d/conda.sh && conda activate vllm
waitram() { until [ "$(awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo)" -ge 15 ]; do sleep 60; done; }
run() { local out=$1; shift; [ -f "$out/scores.json" ] && return; waitram; "$@" --seed 0 --gpu-mem-util 0.80 --out "$out"; }
run runs/diag_ste_base/seed0 python grpo/ste_eval.py
run runs/diag_teacher_8b_instruct_fp8/seed0 python run_eval.py --model Qwen/Qwen3-VL-8B-Instruct-FP8 --model-revision 9cdc6310a8cb770ce18efaf4e9935334512aee45
until ! systemctl --user is-active -q dl-8b-thinking-fp8; do sleep 60; done
run runs/diag_teacher_8b_thinking_fp8/seed0 python run_eval.py --model Qwen/Qwen3-VL-8B-Thinking-FP8 --model-revision a6638e84662f85a17bb8688224541e153d4f6c71
