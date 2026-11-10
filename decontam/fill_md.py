#!/usr/bin/env python
"""Write each dataset's column-4 line (report.json "line") into the tables of reports/dataset_search.md.

    python decontam/fill_md.py --runs runs/decontam_v1 --md reports/dataset_search.md --out runs/decontam_v1/filled.md
Rows are found by the dataset link text in column 0; rows without a report are left as they are.
"""
import argparse
import json
from pathlib import Path

ROW = {"cosyn_music": "[CoSyn-400K music]", "musixqa": "[MusiXQA]", "cosyn_circuit": "[CoSyn-400K circuit]",
       "circuitvqa": "[CircuitVQA]", "cosyn_chemical": "[CoSyn-400K chemical]", "pathvqa": "[PathVQA]",
       "slake": "[SLAKE]", "vqarad": "[VQA-RAD]", "pubmedvision": "[PubMedVision]", "chemvqa": "[ChemVQA-2K]",
       "ssmr": "[SSMR-Bench", "nota": "[NOTA]", "openmmreasoner": "[OpenMMReasoner", "virl39k": "[ViRL39K]"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--md", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    lines = {}
    for k, prefix in ROW.items():
        f = Path(a.runs) / k / "report.json"
        if f.exists():
            r = json.loads(f.read_text(encoding="utf-8"))
            lines[prefix] = r["line"] + ("" if r["images_checked"] else " (텍스트만)")
    out, n = [], 0
    for l in Path(a.md).read_text(encoding="utf-8").splitlines():
        cells = l.split("|")
        if l.startswith("| [") and len(cells) >= 7:
            name = cells[1].strip()
            hit = next((p for p in lines if name.startswith(p)), None)
            if hit:
                cells[5] = f" {lines[hit]} "
                l = "|".join(cells)
                n += 1
        out.append(l)
    Path(a.out).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[fill_md] {n} rows filled -> {a.out}")


if __name__ == "__main__":
    main()
