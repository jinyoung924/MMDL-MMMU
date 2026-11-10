#!/usr/bin/env python
"""Turn quick_check.py results into a review page teammates can fill in, and read their answers back.

    python decontam/review_md.py                     # -> reports/decontam_review.md + reports/decontam_review/*.jpg
    (teammates write Y or N in the first column of each candidate row, commit)
    python decontam/review_md.py --apply             # answers -> qc_work/results/*/..._candidates.csv
    python decontam/review_md.py --apply-json answers.json   # same, from the HTML page's export
    python decontam/quick_check.py grade             # verdicts and column 4 again
"""
import argparse
import csv
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE / "qc_work"
OUT_MD = HERE.parent / "reports" / "decontam_review.md"
PIC = OUT_MD.with_suffix("")          # reports/decontam_review/
MAX_ROWS = 100


def cell(x, n=220):
    x = re.sub(r"\s+", " ", str(x)).replace("|", "\\|").strip()
    return x[:n] + ("…" if len(x) > n else "")


def read_csv(p):
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build():
    s = json.loads((WORK / "summary.json").read_text(encoding="utf-8"))
    sp = WORK / "suggestions.json"     # optional first-pass opinions: {dataset: {eid: "Y — reason"}}
    sug = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    idx = json.loads((WORK / "eval_index.json").read_text(encoding="utf-8"))
    reports = {d.name: json.loads((d / "report.json").read_text(encoding="utf-8"))
               for d in sorted((WORK / "results").iterdir()) if (d / "report.json").exists() and not d.name.startswith("_")}
    PIC.mkdir(parents=True, exist_ok=True)
    rec = idx["recall_image"]
    risky = {n: r for n, r in reports.items() if r.get("verdict") == "Risky"}
    pending = {n: r for n, r in reports.items() if r.get("pending") or r.get("img_pending")}

    done = not pending
    removed = {n: (WORK / "results" / n / "removed_ids.txt").read_text(encoding="utf-8").split()
               for n in reports if (WORK / "results" / n / "removed_ids.txt").exists()}
    removed = {n: v for n, v in removed.items() if v}
    if done:
        L = ["# Contamination 간이 검사 — 결과", ""]
        n_rm = sum(len(v) for v in removed.values())
        L += [f"> **검수까지 끝났습니다. 학습에서 뺄 레코드는 {len(removed)}개 데이터셋의 {n_rm}개이고, ViRL39K는 계산상 Risky입니다.** "
              "뺄 레코드 목록은 아래 「학습에서 뺄 레코드」에 있고, `reports/dataset_search.md` 4열도 이 결과로 채웠습니다. "
              "간이 검사라 바꿔 쓴 문제와 잘라 낸 이미지는 놓칠 수 있습니다.", ""]
    else:
        L = ["# Contamination 간이 검사 — 검수 요청", ""]
        L += ["> **아래 후보가 MMMU·MMMU-Pro 문항과 정말 같은지 Y/N만 적어 주시면 됩니다.** 그림 후보는 왼쪽이 학습 데이터, "
              "오른쪽이 평가 문항이고, 텍스트 후보는 두 질문을 나란히 놓았습니다. 같은 문제(숫자·대상·묻는 것이 같음)면 Y, "
              "문장 틀만 비슷하면 N입니다. 다 채우면 `python decontam/review_md.py --apply` 후 "
              "`python decontam/quick_check.py grade`로 `reports/dataset_search.md` 4열이 다시 만들어집니다.", ""]

    L += ["## 판정 요약", "",
          "데이터셋마다 간이 검사 결과입니다. 판정 기준은 `reports/dataset_search.md` 2장 2.3절을 그대로 따랐습니다.", "",
          "| 데이터셋 | 판정 | 적중 MMMU / Pro | 검수 대기 레코드 (그림 / 텍스트) |", "|---|---|---|---|"]
    for n, r in reports.items():
        L.append(f"| {n} | {cell(r.get('verdict', ''), 80)} | {r['k']['mmmu']} / {r['k']['pro']} | "
                 f"{r.get('img_pending', 0)} / {r.get('pending', 0)} |")
    for n, e in s.get("failed", {}).items():
        L.append(f"| {n} | 검사 못 함 | - | {cell(e, 80)} |")
    L.append("")

    L += ["## Risky가 나오는 이유", ""]
    L += [f"**간이 검사는 잘라 낸 이미지를 거의 못 잡기 때문에, 그림이 한 건이라도 겹치면 계산상 Risky가 됩니다.** "
          f"평가 이미지를 일부러 편집해 다시 찾게 한 결과, 크기 축소 {rec.get('resize')}·JPEG {rec.get('jpeg')}는 거의 다 "
          f"잡았지만 5% 자르기는 {rec.get('crop')}, 자르기+축소+JPEG는 {rec.get('all')}만 잡았습니다(표본 {idx['n_recall']}장). "
          "2.3절은 이 중 가장 낮은 값을 recall r로 쓰므로, 남은 오염 추정 k × (1 − r) / r이 크게 부풀려집니다.", ""]
    if risky:
        L += ["| 데이터셋 | 적중 MMMU / Pro | r | 잔여 inflation (%p) |", "|---|---|---|---|"]
        for n, r in risky.items():
            inf = r.get("residual_inflation_pp", {})
            L.append(f"| {n} | {r['k']['mmmu']} / {r['k']['pro']} | {r.get('recall_r')} | "
                     f"MMMU {inf.get('mmmu')} · Pro {inf.get('pro')} |")
        L += ["", "실제로 겹친 건 아래 「학습에서 뺄 레코드」에 있는 레코드뿐이라, Risky인 데이터셋은 팀에서 셋 중 하나를 고르면 됩니다. "
              "**(1) 그 레코드만 빼고 사용**(간이 검사의 낮은 r을 감수), (2) RunPod 정식 검사"
              "(`decontam/run_all.sh`, SSCD로 자르기도 잡음)로 r을 다시 잰 뒤 판정, (3) 데이터셋째 학습에서 제외.", ""]
    else:
        L += ["지금은 검수 전이라 Risky로 확정된 데이터셋이 없습니다.", ""]
    # what the verdicts become if the first-pass opinions are confirmed
    sim = []
    for n, r in reports.items():
        ys = {e for e, v in sug.get(n, {}).items() if str(v).upper().startswith("Y")}
        if not ys:
            continue
        k = {b: len(set(r["hit_eids"][b]) | {e for e in ys if e.startswith(("pro:" if b == "pro" else "mmmu:"))})
             for b in ("mmmu", "pro")}
        if r.get("images"):
            rr = min(rec.values())
            inf = {b: round(100 * k[b] * (1 - rr) / rr / {"mmmu": 900, "pro": 1730}[b], 2) for b in k}
            v = "Risky" if max(inf.values()) >= 0.5 else "Use after removal"
            sim.append(f"| {n} | {k['mmmu']} / {k['pro']} | {rr} | MMMU {inf['mmmu']} · Pro {inf['pro']} | **{v}** |")
        else:
            sim.append(f"| {n} | {k['mmmu']} / {k['pro']} | 미측정 (텍스트만 검사) | - | 판정 보류 → 겹친 레코드 제거 후 사용 권장 |")
    if sim and not done:
        L += ["1차 의견대로 Y가 확정되면 판정은 아래처럼 바뀝니다. **ViRL39K처럼 이미지를 검사한 데이터셋은 텍스트 1건만 겹쳐도 "
              "위의 낮은 r 때문에 Risky가 됩니다.** 실제로 겹친 건 그 레코드뿐이므로, 그 레코드만 빼고 쓸지 "
              "정식 검사로 r을 다시 잴지를 팀에서 정하면 됩니다.", "",
              "| 데이터셋 | 적중 MMMU / Pro | r | 잔여 inflation (%p) | 판정 |", "|---|---|---|---|---|"] + sim + [""]

    if removed:
        L += ["## 학습에서 뺄 레코드", "",
              "검수에서 같은 문제(Y)로 확정됐거나 이미지가 그대로 같은 레코드입니다. 학습 데이터를 만들 때 이 id를 빼 주세요.", "",
              "| 데이터셋 | 레코드 id | 겹친 시험 문항 |", "|---|---|---|"]
        for n, ids in removed.items():
            hits = {h["tid"]: h for h in json.loads((WORK / "results" / n / "hits.json").read_text(encoding="utf-8"))}
            yes = {}
            for r in read_csv(WORK / "results" / n / "text_candidates.csv"):
                if r["same(Y/N)"].strip().upper().startswith("Y"):
                    yes.setdefault(r["tid"], []).append(r["eid"])
            for t in ids:
                h = hits.get(t, {})
                eids = sorted(set(yes.get(t, [])) | set(h.get("img_exact", [])) | set(h.get("img_near", {})))
                L.append(f"| {n} | `{t}` | {', '.join(f'`{e}`' for e in eids)} |")
        L.append("")
    L += ["## 검수할 후보", ""]
    if not pending:
        L += ["검수할 후보가 없습니다. (텍스트 후보는 모두 검수했고, 답은 `qc_work/results/*/text_candidates.csv`에 남아 있습니다.)", ""]
    for n in pending:
        d = WORK / "results" / n
        imgs = [r for r in read_csv(d / "image_candidates.csv") if not r["same(Y/N)"].strip()][:MAX_ROWS]
        txts = sorted((r for r in read_csv(d / "text_candidates.csv") if not r["same(Y/N)"].strip()),
                      key=lambda r: (r["eid"].split(":", 1)[1], r["eid"], r["tid"]))[:MAX_ROWS]
        if imgs:
            L += [f"### {n} — 그림 후보 {len(imgs)}건", "",
                  "| 같은 그림? | 평가 문항 | 학습 레코드 수 | 그림 (왼쪽 학습 · 오른쪽 평가) | 1차 의견 |", "|---|---|---|---|---|"]
            for i, r in enumerate(imgs, 1):
                src = d / "image_review" / r["picture (image_review/)"]
                dst = f"{n}_img{i}.jpg"
                if src.exists():
                    shutil.copy(src, PIC / dst)
                L.append(f"|  | `{r['eid']}` | {r['n_records']} | ![{n} {i}]({PIC.name}/{dst}) | "
                         f"{cell(sug.get(n, {}).get(r['eid'], ''), 80)} |")
            L.append("")
        if txts:
            L += [f"### {n} — 텍스트 후보 {len(txts)}쌍 (학습 레코드 {len({r['tid'] for r in txts})}개)", "",
                  "같은 평가 문항끼리 붙여 두었습니다. 1차 의견은 Claude가 먼저 본 것이라 틀릴 수 있으니 확인해 주세요.", "",
                  "| 같은 문제? | 학습 데이터 질문 | 평가 질문 | 1차 의견 | key |", "|---|---|---|---|---|"]
            for r in txts:
                L.append(f"|  | {cell(r['train_question'])} | {cell(r['eval_question'])} | "
                         f"{cell(sug.get(n, {}).get(r['eid'], ''), 80)} | `{r['tid']} {r['eid']}` |")
            L.append("")
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"-> {OUT_MD}  (그림 {len(list(PIC.glob('*.jpg')))}장: {PIC})")


def apply(answers=None):
    """Read Y/N from the review page (or answers.json saved by decontam_review.html) back into the candidate CSVs."""
    ans_img, ans_txt, cur = {}, {}, None
    if answers:
        for a in json.loads(Path(answers).read_text(encoding="utf-8")):
            ans_txt[(a["dataset"], a["tid"], a["eid"])] = a["same"]
    for l in ([] if answers else OUT_MD.read_text(encoding="utf-8").splitlines()):
        m = re.match(r"### (\S+) — (그림|텍스트) 후보", l)
        if m:
            cur = (m.group(1), m.group(2))
            continue
        if not cur or not l.startswith("|") or l.startswith("|---") or "같은" in l:
            continue
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        yn = cells[0].upper()[:1]
        if yn not in ("Y", "N"):
            continue
        if cur[1] == "그림":
            ans_img[(cur[0], cells[1].strip("`"))] = yn
        else:
            tid, eid = cells[-1].strip("`").rsplit(" ", 1)
            ans_txt[(cur[0], tid, eid)] = yn
    n = 0
    for d in (WORK / "results").iterdir():
        for name, key in (("image_candidates.csv", lambda r: (d.name, r["eid"])),
                          ("text_candidates.csv", lambda r: (d.name, r["tid"], r["eid"]))):
            p = d / name
            rows = read_csv(p)
            if not rows:
                continue
            ans = ans_img if name.startswith("image") else ans_txt
            for r in rows:
                if key(r) in ans:
                    r["same(Y/N)"] = ans[key(r)]
                    n += 1
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    print(f"{n}개 답을 반영했습니다. 이제 `python decontam/quick_check.py grade`")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="read Y/N from reports/decontam_review.md")
    ap.add_argument("--apply-json", help="read Y/N from answers.json saved by reports/decontam_review.html")
    a = ap.parse_args()
    apply(a.apply_json) if (a.apply or a.apply_json) else build()
