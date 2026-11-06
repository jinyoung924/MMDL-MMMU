#!/usr/bin/env python3
"""Fetch pinned BMMR audit sources into an explicit cache, never a training folder.

Downloads train JSONL (206 MB), evaluation TSV (2.73 GB), and the ZIP central
directory only. Evaluation TSV is used solely for exclusion checks. The 10.5 GB
training image ZIP is not downloaded in full. Requires requests.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile

import requests

REVISION = "e07b24f9758b6421c8b92cc5cfb0de26dd722b5a"
FILES = {
    "trainset/bmmr-train-80k.jsonl": (205899775, "9ba5b51c37a800a6e523e46071b38c0821cb5ef74fa1f06bc22e3fc9ee8a5b4a"),
    "testset/BMMR.tsv": (2733381458, "8a1f80ea519ab1bd83739791ff0307c83ca438705cfe3f85ca978a34dd2859f5"),
}
ZIP_SIZE = 10529403922


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main(cache):
    cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    base = f"https://huggingface.co/datasets/guanyu615/BMMR/resolve/{REVISION}/"
    for source, (size, checksum) in FILES.items():
        dst = cache / Path(source).name
        if dst.exists() and dst.stat().st_size == size and sha256_file(dst) == checksum:
            print("Verified cached", dst.name, flush=True)
            continue
        partial = dst.with_suffix(dst.suffix + ".part")
        h = hashlib.sha256()
        n = 0
        last = time.monotonic()
        with session.get(base + source, stream=True, timeout=(30, 90)) as response:
            response.raise_for_status()
            with partial.open("wb") as f:
                for block in response.iter_content(4 * 1024 * 1024):
                    f.write(block)
                    h.update(block)
                    n += len(block)
                    if time.monotonic() - last > 25:
                        print(dst.name, round(n / 1e6), "MB", flush=True)
                        last = time.monotonic()
        if n != size or h.hexdigest() != checksum:
            raise ValueError(f"Source checksum failed: {source}")
        partial.replace(dst)
        print("Downloaded and verified", dst.name, flush=True)

    class RemoteZip(io.RawIOBase):
        def __init__(self):
            self.pos = 0

        def seekable(self):
            return True

        def seek(self, offset, whence=0):
            self.pos = offset if whence == 0 else (self.pos if whence == 1 else ZIP_SIZE) + offset
            return self.pos

        def tell(self):
            return self.pos

        def read(self, n=-1):
            n = ZIP_SIZE - self.pos if n < 0 else min(n, ZIP_SIZE - self.pos)
            if not n:
                return b""
            start, end = self.pos, self.pos + n - 1
            with session.get(base + "trainset/imgs.zip", headers={"Range": f"bytes={start}-{end}"},
                             stream=True, timeout=(30, 90)) as response:
                response.raise_for_status()
                if response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-"):
                    raise RuntimeError("Exact ZIP Range request not honored; refusing full archive download")
                data = response.content
            if len(data) != n:
                raise ValueError("Incomplete ZIP range")
            self.pos += n
            return data

    with zipfile.ZipFile(RemoteZip()) as archive:
        entries = [{k: getattr(entry, k) for k in
                    ("filename", "file_size", "compress_size", "header_offset", "CRC", "compress_type")}
                   for entry in archive.infolist()]
    (cache / "zip_index.json").write_text(json.dumps(entries))
    (cache / "source_lock.json").write_text(json.dumps({"repository": "guanyu615/BMMR", "revision": REVISION,
        "files": {k: {"size": v[0], "sha256": v[1]} for k, v in FILES.items()},
        "image_archive": {"path": "trainset/imgs.zip", "size": ZIP_SIZE, "download_mode": "central_directory_only"}}, indent=2) + "\n")
    print("ZIP entries indexed", len(entries), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    main(parser.parse_args().cache)
