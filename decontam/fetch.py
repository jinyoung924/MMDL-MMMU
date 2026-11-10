#!/usr/bin/env python
"""Download part of an HF dataset repo (or a Google Drive file) and unpack its archives.

    python decontam/fetch.py hf BoKelvin/SLAKE --patterns "*.json,imgs.zip" --to /workspace/decontam/data/slake
    python decontam/fetch.py gdrive <file-id> --to /workspace/decontam/data/circuitvqa
Prints the local directory. Archives (.zip/.tar/.tar.gz) are unpacked next to themselves, once.
"""
import argparse
import tarfile
import zipfile
from pathlib import Path


def unpack(d):
    for p in sorted(Path(d).rglob("*")):
        done = p.with_name(p.name + ".unpacked")
        if done.exists() or not p.is_file():
            continue
        if p.suffix == ".zip":
            with zipfile.ZipFile(p) as z:
                z.extractall(p.parent)
        elif p.name.endswith((".tar", ".tar.gz", ".tgz")):
            with tarfile.open(p) as t:
                t.extractall(p.parent, filter="data")
        else:
            continue
        done.touch()
        print(f"[fetch] unpacked {p.name}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["hf", "gdrive"])
    ap.add_argument("ref")
    ap.add_argument("--patterns", default="")
    ap.add_argument("--to", required=True)
    a = ap.parse_args()
    to = Path(a.to)
    to.mkdir(parents=True, exist_ok=True)
    if a.kind == "hf":
        from huggingface_hub import snapshot_download
        pats = [p for p in a.patterns.split(",") if p] or None
        snapshot_download(a.ref, repo_type="dataset", allow_patterns=pats, local_dir=to)
    else:
        import gdown
        gdown.download(id=a.ref, output=str(to) + "/", quiet=False)
    unpack(to)
    print(to)


if __name__ == "__main__":
    main()
