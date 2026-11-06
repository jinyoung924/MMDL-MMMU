#!/usr/bin/env python3
"""Read-only source audit; creates review candidates, NEVER a training-ready dataset.

Run with the existing vllm Python (pyarrow, Pillow, numpy, tokenizers).
Raw BMMR downloads stay outside Git. Evaluation answers never enter candidate records.
See --help for inputs. Source filenames, revision, sizes and SHA256 are checked.
"""
import argparse
import ast
import base64
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import random
import re
import sys
import unicodedata

from PIL import Image, ImageOps
import numpy as np
import pyarrow as pa

REVISION = "e07b24f9758b6421c8b92cc5cfb0de26dd722b5a"
MMMU_REVISION = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"
TRAIN_SHA = "9ba5b51c37a800a6e523e46071b38c0821cb5ef74fa1f06bc22e3fc9ee8a5b4a"
EVAL_SHA = "8a1f80ea519ab1bd83739791ff0307c83ca438705cfe3f85ca978a34dd2859f5"
CJK = re.compile(r"[\u3400-\u9fff]")
EVAL_SUFFIX = "Here is a multiple-choice question or a short-answer question."
SOLUTION_CUE = re.compile(
    r"step.by.step|solution\s*:|the answer is|the correct answer|substituting|therefore[, ]|thus[, ]",
    re.I,
)


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def normalize(text):
    text = text.split(EVAL_SUFFIX)[0]
    text = re.sub(r"<image(?:\s+\d+)?>", " ", text)
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"\w+", text))


def shingles(text):
    words = normalize(text).split()
    return {tuple(words[i:i + 5]) for i in range(len(words) - 4)}


def image_fingerprint(blob):
    with Image.open(io.BytesIO(blob)) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        size = image.size
        pixel_hash = hashlib.sha256(str(size).encode() + image.tobytes()).hexdigest()
        thumb = np.asarray(image.convert("L").resize((9, 8), Image.Resampling.LANCZOS))
        bits = thumb[:, 1:] > thumb[:, :-1]
        dhash = sum(int(b) << i for i, b in enumerate(bits.ravel()))
    return {"bytes_sha256": hashlib.sha256(blob).hexdigest(), "pixels_sha256": pixel_hash,
            "dhash64": f"{dhash:016x}", "width": size[0], "height": size[1]}


def audit(args):
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    # Fail closed on substituted sources, including an eval file renamed as train.
    assert args.train.name == "bmmr-train-80k.jsonl"
    assert args.eval.name == "BMMR.tsv"
    assert file_sha(args.train) == TRAIN_SHA, "Unexpected training source"
    assert file_sha(args.eval) == EVAL_SHA, "Unexpected evaluation source"
    print("Source checksums verified", flush=True)
    protected = []
    image_index = defaultdict(list)
    image_problems = []
    eval_summary = Counter()
    eval_ids = set()

    def register_image(blob, reference):
        key = hashlib.sha256(blob).hexdigest()
        if key not in image_index:
            try:
                fp = image_fingerprint(blob)
            except Exception as e:
                image_problems.append({"reference": reference, "error": str(e)})
                return
            image_index[key] = [fp, []]
        image_index[key][1].append(reference)

    csv.field_size_limit(sys.maxsize)
    with args.eval.open(newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            rid = "BMMR-Eval/" + row["index"]
            eval_ids.add(row["id"])
            eval_summary["rows"] += 1
            eval_summary["language:" + row["language"]] += 1
            eval_summary["task_type:" + row["task_type"]] += 1
            eval_summary["cot:" + row["cot"]] += 1
            protected.append({"reference": rid, "id": row["id"], "question": row["question"].split(EVAL_SUFFIX)[0]})
            try:
                blobs = ast.literal_eval(row["image"])
                if not isinstance(blobs, list):
                    raise ValueError("Expected image base64 list")
                for k, encoded in enumerate(blobs):
                    register_image(base64.b64decode(encoded, validate=True), f"{rid}/image_{k}")
            except Exception as e:
                image_problems.append({"reference": rid, "error": str(e)})
            if eval_summary["rows"] % 5000 == 0:
                print("Protected BMMR-Eval rows", eval_summary["rows"], flush=True)

    n_mmmu = 0
    for path in sorted(args.mmmu_cache.glob(f"*/0.0.0/{MMMU_REVISION}/mmmu-validation.arrow")):
        with pa.memory_map(str(path), "r") as source:
            for batch in pa.ipc.open_stream(source):
                for row in batch.to_pylist():
                    n_mmmu += 1
                    rid = "MMMU/" + row["id"]
                    protected.append({"reference": rid, "id": row["id"], "question": row["question"]})
                    for k in range(1, 8):
                        img = row[f"image_{k}"]
                        if img:
                            assert img.get("bytes"), "MMMU image bytes missing"
                            register_image(img["bytes"], f"{rid}/image_{k}")
    assert n_mmmu == 900, f"Expected 900 protected MMMU questions, found {n_mmmu}"
    assert not image_problems, f"Cannot screen safely: {len(image_problems)} unreadable protected images"
    print("Protected images indexed", len(image_index), flush=True)
    dump(out / "protected_image_index.json", [dict(fp, references=refs) for fp, refs in image_index.values()])
    # This is an audit index only: no eval answers, solutions, pixels, or prompts.

    exact = defaultdict(list)
    inverted = defaultdict(set)
    protected_shingles = []
    for j, row in enumerate(protected):
        exact[normalize(row["question"])].append(row["reference"])
        grams = shingles(row["question"])
        protected_shingles.append(grams)
        for gram in grams:
            inverted[gram].add(j)

    stats = Counter()
    id_counts = Counter()
    image_counts = Counter()
    q_counts = Counter()
    candidates = []
    flagged = []
    lengths = []
    tokenizer = None
    token_lengths = []
    if args.tokenizer:
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(args.tokenizer))
    token_buffer = []
    for line_no, line in enumerate(args.train.open(), 1):
        row = json.loads(line)
        assert set(row) == {"id", "conversations", "image"}
        assert [c["from"] for c in row["conversations"]] == ["human", "gpt"]
        q, answer = [c["value"] for c in row["conversations"]]
        qnorm = normalize(q)
        id_counts[row["id"]] += 1
        q_counts[qnorm] += 1
        image_counts.update(row["image"])
        stats["rows"] += 1
        qc, ac = bool(CJK.search(q)), bool(CJK.search(answer))
        stats[f"question_cjk={qc},answer_cjk={ac}"] += 1
        stats["nonempty_assistant_response"] += bool(answer.strip())
        stats["reasoning_heading"] += "### Reasoning Process ###" in answer
        stats["final_answer_heading"] += "### Final answer ###" in answer
        stats["single_image"] += len(row["image"]) == 1
        stats["question_solution_cue_heuristic"] += bool(SOLUTION_CUE.search(q))
        lengths.append(len(answer))
        if tokenizer:
            token_buffer.append(answer)
            if len(token_buffer) == 512:
                token_lengths.extend(len(x.ids) for x in tokenizer.encode_batch(token_buffer, add_special_tokens=False))
                token_buffer.clear()
        reasons = []
        refs = set(exact.get(qnorm, []))
        if row["id"] in eval_ids:
            reasons.append("id_shared_with_bmmr_eval")
        if refs:
            reasons.append("exact_normalized_question_shared_with_evaluation")
        # Token-shingle overlap is a flag for review, not proof of semantic equivalence.
        grams = shingles(q)
        hits = Counter(j for gram in grams for j in inverted.get(gram, ()))
        for j, count in hits.items():
            if count >= 8 and count / min(len(grams), len(protected_shingles[j])) >= .8:
                refs.add(protected[j]["reference"])
        if refs and not reasons:
            reasons.append("high_question_shingle_overlap_with_evaluation")
        if reasons:
            flagged.append({"id": row["id"], "line": line_no, "reasons": reasons, "references": sorted(refs)})
            stats["text_or_id_flagged_rows"] += 1
        letter = re.search(r"\\boxed\{([A-Z])\}\s*$", answer)
        # No-CJK plus Latin is only an English-candidate heuristic; review is mandatory.
        eligible = (not qc and re.search(r"[a-zA-Z]{3,}", q) and letter
                    and re.search(r"(?:\([A-D]\)|\b[A-D][.:])", q)
                    and not SOLUTION_CUE.search(q) and len(row["image"]) == 1
                    and len(q) >= 50 and not reasons)
        if eligible:
            candidates.append({"id": row["id"], "source_line": line_no, "source_split": "train",
                               "source_path": "trainset/bmmr-train-80k.jsonl", "source_revision": REVISION,
                               "question": q, "image": row["image"],
                               "reference_final_from_assistant": letter[1],
                               "reference_is_independent_gold": False, "question_normalized": qnorm,
                               "ready_for_training": False,
                               "status": "requires_image_overlap_screen_and_annotation_review"})
    if token_buffer:
        token_lengths.extend(len(x.ids) for x in tokenizer.encode_batch(token_buffer, add_special_tokens=False))
    assert stats["rows"] == 88991
    assert len(id_counts) == stats["rows"], "Duplicate train IDs"
    # Do not select repeated questions or repeated image paths into a pilot by accident.
    unique_candidates = []
    seen_questions, seen_images = set(), set()
    random.Random(0).shuffle(candidates)
    for row in candidates:
        if row["question_normalized"] in seen_questions or any(x in seen_images for x in row["image"]):
            continue
        seen_questions.add(row.pop("question_normalized"))
        seen_images.update(row["image"])
        unique_candidates.append(row)
    with (out / "train_review_candidates.jsonl").open("w") as f:
        for row in unique_candidates:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out / "text_overlap_flags.jsonl").open("w") as f:
        for row in flagged:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    def quantiles(values):
        return {str(p): float(np.percentile(values, p)) for p in [0, 50, 90, 95, 99, 100]}
    report = {
        "source_repository": "guanyu615/BMMR", "source_revision": REVISION,
        "train_source_path": "trainset/bmmr-train-80k.jsonl", "train_sha256": TRAIN_SHA,
        "eval_source_path": "testset/BMMR.tsv", "eval_sha256": EVAL_SHA,
        "train": dict(stats), "eval": dict(eval_summary), "eval_unique_ids": len(eval_ids),
        "protected_mmmu_rows": n_mmmu, "protected_unique_image_bytes": len(image_index),
        "train_unique_ids": len(id_counts), "train_image_references": sum(image_counts.values()),
        "train_unique_image_paths": len(image_counts), "train_unique_normalized_questions": len(q_counts),
        "assistant_character_quantiles": quantiles(lengths),
        "assistant_token_quantiles": quantiles(token_lengths) if token_lengths else None,
        "tokenizer_file": str(args.tokenizer) if args.tokenizer else None,
        "review_candidates_before_internal_dedup": len(candidates),
        "review_candidates_after_internal_dedup": len(unique_candidates),
        "ready_for_training": False,
        "limitations": ["Train images have NOT all been checked against protected images.",
                        "Text checks do not rule out translations, paraphrases, crops or semantic duplicates.",
                        "Language, MC format and solution-in-question checks are heuristics.",
                        "Train has no separate gold, language, discipline or question_type fields.",
                        "Every candidate requires image screening, question review and verified annotation."]}
    dump(out / "summary.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--mmmu-cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path)
    audit(parser.parse_args())
