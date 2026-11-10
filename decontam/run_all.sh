#!/usr/bin/env bash
# Contamination test for every candidate in reports/dataset_search.md, on one GPU pod (24 GB is enough).
#   RUN_NAME=decontam_v1 TRAIN=1 SKIP_SMOKE=1 RUN_CMD='bash decontam/run_all.sh "$OUT"' bash cloud/runpod.sh
# Only DATASETS="cosyn_music slake" to run a few. Each dataset is independent: one failure is logged, the rest go on.
# Heavy files live in $WORK (/workspace); only reports and removed-id lists land in $OUT (pushed to git).
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=${1:-runs/decontam}
WORK=${WORK:-$( [[ -d /workspace && -w /workspace ]] && echo /workspace/decontam || echo decontam/work )}
IDX="$WORK/eval_index"; RES="$WORK/results"; DATA="$WORK/data"; REC="$WORK/recall"
DATASETS=${DATASETS:-"cosyn_music musixqa cosyn_circuit circuitvqa cosyn_chemical pathvqa slake vqarad pubmedvision chemvqa ssmr nota openmmreasoner virl39k"}
mkdir -p "$OUT" "$RES" "$DATA"
python -m pip install -q gdown pyarrow 2>/dev/null || true
log() { echo "[run_all $(date +%H:%M:%S)] $*"; }

# ---- 0. E index and recall (shared by all datasets) ------------------------------------------------------------
[[ -s "$IDX/calib.json" ]] || python decontam/build_eval_index.py --out "$IDX" || { log "E index failed"; exit 1; }
cp "$IDX/calib.json" "$OUT/eval_index_calib.json"
if [[ ! -s "$REC/recall.json" ]]; then
  python decontam/recall.py make --out "$REC" && \
  python decontam/check.py detect --index "$IDX" --out "$REC" --json "$REC/records.jsonl" --image-root "$REC" && \
  python decontam/judge.py --cands "$REC/judge_candidates.jsonl" && \
  python decontam/recall.py score --out "$REC" || log "recall failed (verdicts will say: pending)"
fi
cp "$REC/recall.json" "$OUT/" 2>/dev/null || true

# ---- 1. per dataset: detect -> judge -> grade ------------------------------------------------------------------
# kinds = the recall kinds that apply (section 2.3: smallest r among them). Text-only runs skip image kinds.
run() {   # run NAME KINDS check-args...
  local name=$1 kinds=$2; shift 2
  local o="$RES/$name"
  log "== $name =="
  python decontam/check.py inspect "$@" > "$o.inspect.txt" 2>&1; mkdir -p "$o"; mv "$o.inspect.txt" "$o/inspect.txt"
  [[ -s "$o/detect.json" ]] || python decontam/check.py detect --index "$IDX" --out "$o" "$@" || { log "$name: detect failed"; return 1; }
  [[ -s "$o/verdicts.jsonl" || ! -s "$o/judge_candidates.jsonl" ]] || python decontam/judge.py --cands "$o/judge_candidates.jsonl"
  local v=(); [[ -s "$o/verdicts.jsonl" ]] && v=(--verdicts "$o/verdicts.jsonl")
  [[ ! -s "$o/judge_candidates.jsonl" && ! -e "$o/verdicts.jsonl" ]] && : > "$o/verdicts.jsonl" && v=(--verdicts "$o/verdicts.jsonl")
  python decontam/check.py grade --out "$o" "${v[@]}" --recall "$REC/recall.json" --recall-kinds "$kinds" || return 1
  mkdir -p "$OUT/$name"
  cp "$o"/{report.json,detect.json,removed_ids.txt,inspect.txt} "$OUT/$name/" 2>/dev/null
  ls "$o/review" > "$OUT/$name/review_list.txt" 2>/dev/null
}
fetch() { python decontam/fetch.py "$@" | tail -1; }
need() { [[ -n "$(ls -A "$1" 2>/dev/null)" ]] || { log "$2"; return 1; }; }

for ds in $DATASETS; do
  case $ds in
    cosyn_music|cosyn_circuit|cosyn_chemical)
      run "$ds" image,text,trans,both --hf allenai/CoSyn-400K --config "${ds#cosyn_}" --split train ;;
    musixqa)
      # train_qa_simple = chord/layout/OCR questions (column 2); train_qa_omr (1.1 GB, note-by-note transcription) is not used
      d=$(fetch hf puar-playground/MusiXQA --patterns "train_qa_simple.json,images.tar" --to "$DATA/musixqa") && \
      run musixqa image,text,trans,both --json "$d/train_qa_simple.json" --image-root "$d" --fields image=doc_id ;;
    circuitvqa)   # Google Drive links from the github README (QA pairs, images); file format checked by inspect.txt
      if ! ls "$DATA/circuitvqa"/*.unpacked >/dev/null 2>&1; then
        fetch gdrive 10kqGKCNAIG3VpOUvj4Ym6AH49ZaLvC_1 --to "$DATA/circuitvqa" >/dev/null
        fetch gdrive 1qH6jfWym0Wjg9KKCPQto7MZr0VWM9QpF --to "$DATA/circuitvqa" >/dev/null
      fi
      # master.json holds every QA once (master_*.json are prompt variants of the same QA); images by file name
      need "$DATA/circuitvqa/questions/all/master.json" "circuitvqa: download failed -> put files under $DATA/circuitvqa" && \
      run circuitvqa image,text,trans,both --json "$DATA/circuitvqa/questions/all/master.json" --where splittype=train \
          --image-root "$DATA/circuitvqa/384a/model-inputs" --fields image=file ;;
    pathvqa)  run pathvqa image,text,trans,both --hf flaviagiammarino/path-vqa --split train ;;
    vqarad)   run vqarad image,text,trans,both --hf flaviagiammarino/vqa-rad --split train ;;
    slake)
      d=$(fetch hf BoKelvin/SLAKE --patterns "*.json,imgs.zip" --to "$DATA/slake") && \
      run slake image,text,trans,both --json "$d/train.json" --image-root "$d" --fields image=img_name --where q_lang=en ;;
    pubmedvision)   # text only by default (images are 60 GB of zips); PMV_IMAGES=1 to check images too
      if [[ "${PMV_IMAGES:-0}" == 1 ]]; then
        d=$(fetch hf FreedomIntelligence/PubMedVision --patterns "*InstructionTuning*.json,images_*.zip" --to "$DATA/pubmedvision") && \
        run pubmedvision image,text,trans,both --json "$d/*InstructionTuning*.json" --image-root "$d"
      else
        d=$(fetch hf FreedomIntelligence/PubMedVision --patterns "*InstructionTuning*.json" --to "$DATA/pubmedvision") && \
        run pubmedvision text,trans --json "$d/*InstructionTuning*.json" --no-images
      fi ;;
    chemvqa)      # IEEE DataPort / Mendeley: put the csv/json + images under $DATA/chemvqa first
      need "$DATA/chemvqa" "chemvqa: manual download needed -> $DATA/chemvqa" && \
      run chemvqa image,text,trans,both --json "$DATA/chemvqa/*.csv" --image-root "$DATA/chemvqa" --fields image=image_name ;;
    ssmr)     run ssmr image,text,trans,both --hf Sylence/SSMR-Bench --split Train_visual,Train_textual ;;
    nota)         # 153 GB of images; the HF rows hold paths. Text check on the analysis/alignment/IE prompts only
      run nota text,trans --hf MYTH-Lab/NOTA-dataset --split train_analysis,train_alignment,train_IE --no-images ;;
    openmmreasoner)  # rows are messages only; images come from the authors' download script
      run openmmreasoner text,trans --hf OpenMMReasoner/OpenMMReasoner-SFT-874K --no-images ;;
    virl39k)
      d=$(fetch hf TIGER-Lab/ViRL39K --patterns "39Krelease.parquet,images.zip" --to "$DATA/virl39k") && \
      run virl39k image,text,trans,both --json "$d/39Krelease.parquet" --image-root "$d" --fields image=image ;;
    *) log "unknown dataset $ds" ;;
  esac || log "$ds: FAILED (see above), continuing"
done

python decontam/fill_md.py --runs "$OUT" --md reports/dataset_search.md --out "$OUT/dataset_search_filled.md"
log "done -> $OUT"
