#!/usr/bin/env python3
"""Fetch training images by HTTP Range and screen a review pool against eval images.

Never fetches evaluation examples as training inputs. Requires the exact-source
audit from audit_bmmr.py. Outputs remain NOT ready for training: this is screening,
not annotation or proof that all semantic overlap has been eliminated.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

import requests

from audit_bmmr import REVISION, TRAIN_SHA, dump, file_sha, image_fingerprint


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main(args):
    summary = json.loads((args.audit / "summary.json").read_text())
    assert summary["source_revision"] == REVISION
    assert summary["train_sha256"] == TRAIN_SHA == file_sha(args.train)
    candidates = read_jsonl(args.candidates or args.audit / "train_review_candidates.jsonl")[:args.limit]
    originals = {r["source_line"]: r for r in candidates}
    assert len(originals) == len(candidates), "Repeated source lines in candidate pool"
    assert len({r["id"] for r in candidates}) == len(candidates), "Repeated candidate IDs"
    verified = set()
    for line_no, line in enumerate(args.train.open(), 1):
        if line_no in originals:
            original, candidate = json.loads(line), originals[line_no]
            assert original["id"] == candidate["id"] and original["image"] == candidate["image"]
            assert original["conversations"][0]["value"] == candidate["question"]
            assert candidate["source_split"] == "train"
            assert candidate["source_path"] == "trainset/bmmr-train-80k.jsonl"
            assert candidate["source_revision"] == REVISION
            verified.add(line_no)
    assert verified == set(originals), "Candidate source lines absent from original training file"
    index = {x["filename"]: x for x in json.loads(args.zip_index.read_text())}
    protected = json.loads((args.audit / "protected_image_index.json").read_text())
    protected_bytes = {r["bytes_sha256"]: r["references"] for r in protected}
    protected_pixels = {r["pixels_sha256"]: r["references"] for r in protected}
    protected_dhashes = [(int(r["dhash64"], 16), r) for r in protected]
    args.images.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/datasets/guanyu615/BMMR/resolve/{REVISION}/trainset/imgs.zip"

    def range_read(start, end):
        for attempt in range(3):
            with requests.get(url, headers={"Range": f"bytes={start}-{end}"}, stream=True,
                              timeout=(30, 90)) as response:
                if response.status_code >= 500 and attempt < 2:
                    continue
                response.raise_for_status()
                if response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-"):
                    raise RuntimeError("Server did not honor exact Range request")
                data = response.content
                assert len(data) == end - start + 1
                return data

    def fetch(name):
        assert Path(name).name == name, "Unexpected nested image path"
        entry = index["imgs/" + name]
        dst = args.images / name
        if dst.exists():
            blob = dst.read_bytes()
        else:
            start = entry["header_offset"]
            header = range_read(start, start + 29)
            assert header[:4] == b"PK\x03\x04"
            filename_len, extra_len = struct.unpack_from("<HH", header, 26)
            payload_start = start + 30 + filename_len + extra_len
            data = range_read(payload_start, payload_start + entry["compress_size"] - 1)
            assert entry["compress_type"] in (0, 8)
            blob = zlib.decompress(data, -15) if entry["compress_type"] == 8 else data
        assert len(blob) == entry["file_size"] and zlib.crc32(blob) == entry["CRC"], "ZIP CRC or size mismatch"
        if not dst.exists():
            dst.write_bytes(blob)
        return name, image_fingerprint(blob)

    names = sorted({n for r in candidates for n in r["image"]})
    with ThreadPoolExecutor(max_workers=4) as executor:
        fingerprints = dict(executor.map(fetch, names))
    screened = []
    stats = {"candidates_checked": len(candidates), "images_checked": len(names),
             "exact_image_overlap_rows": 0, "near_image_review_rows": 0,
             "no_detected_image_overlap_rows": 0, "insufficient_question_text_rows": 0}
    for row in candidates:
        matches = []
        for name in row["image"]:
            fp = fingerprints[name]
            for method, lookup, key in (("bytes_sha256", protected_bytes, fp["bytes_sha256"]),
                                        ("pixels_sha256", protected_pixels, fp["pixels_sha256"])):
                if key in lookup:
                    matches.append({"image": name, "method": method, "references": lookup[key]})
            h = int(fp["dhash64"], 16)
            for other_h, other in protected_dhashes:
                distance = (h ^ other_h).bit_count()
                if distance <= 4:
                    matches.append({"image": name, "method": "dhash64_hamming_le_4", "distance": distance,
                                    "references": other["references"]})
        if any(m["method"] in ("bytes_sha256", "pixels_sha256") for m in matches):
            status = "excluded_exact_evaluation_image_overlap"
            stats["exact_image_overlap_rows"] += 1
        elif matches:
            status = "held_for_possible_evaluation_image_overlap"
            stats["near_image_review_rows"] += 1
        else:
            status = "requires_question_and_annotation_review"
            stats["no_detected_image_overlap_rows"] += 1
        question_text = re.sub(r"<image(?:\s+\d+)?>", " ", row["question"])
        if len(re.findall(r"[A-Za-z]{3,}", question_text)) < 3:
            # A placeholder named 'image' is not evidence of an English question.
            stats["insufficient_question_text_rows"] += 1
            if not matches:
                status = "excluded_insufficient_question_text_for_english_pilot"
        screened.append({**row, "status": status, "ready_for_training": False,
                         "image_fingerprints": {n: fingerprints[n] for n in row["image"]},
                         "image_overlap_matches": matches})
    with (args.audit / f"{args.output_prefix}_image_screen.jsonl").open("w") as f:
        for row in screened:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats.update({"ready_for_training": False,
                  "awaiting_question_and_annotation_review": sum(r["status"] == "requires_question_and_annotation_review" for r in screened),
                  "protected_image_index_sha256": file_sha(args.audit / "protected_image_index.json"),
                  "limitations": ["Only this pilot pool's train images were checked.",
                                  "dHash is a review heuristic, not proof of equivalence or non-overlap.",
                                  "Crops, diagrams redrawn from the same source, translations and answer-in-image leakage need review.",
                                  "Partial ZIP entries checked by CRC; full ZIP SHA256 was not downloaded or verified."]})
    dump(args.audit / f"{args.output_prefix}_image_summary.json", stats)
    print(json.dumps(stats, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--zip-index", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--candidates", type=Path, help="Optional train-only candidate manifest")
    parser.add_argument("--output-prefix", default="pilot")
    args = parser.parse_args()
    assert args.limit > 0
    assert re.fullmatch(r"[a-zA-Z0-9_-]+", args.output_prefix)
    main(args)
