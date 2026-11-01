#!/usr/bin/env python
"""One table over all ablation conditions: paired Δ vs the official main baseline (results/seed*).

python data_ablation/summarize.py --runs runs/abl_cosyn runs/abl_vwi runs/abl_pmcvqa     # -> stdout (markdown)
python data_ablation/summarize.py --runs runs/abl_* --out data_ablation/results.md

For each run: seeds in common with results/seed*, paired per question and seed (same statistic as
`analyze.py compare`), bootstrap 95% CI over questions, plus the per-subject deltas with the largest movement.
Stdlib only.
"""
import argparse, json, random, statistics as st, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyze import load  # noqa: E402

BASE = [Path("results") / f"seed{s}" for s in range(5)]
TARGET = {  # subjects whose always-wrong items the dataset was chosen for (reports/failure_tagging_1차)
    "cosyn": ["Chemistry", "Electronics", "Music", "Math", "Computer_Science", "Materials", "Mechanical_Engineering", "Energy_and_Power"],
    "vwi": ["Math", "Physics", "Chemistry", "Finance", "Economics", "Accounting", "Electronics", "Mechanical_Engineering", "Energy_and_Power", "Materials"],
    "pmcvqa": ["Basic_Medical_Science", "Clinical_Medicine", "Diagnostics_and_Laboratory_Medicine", "Pharmacy", "Public_Health"],
}


def cfg(d):
    return json.load(open(Path(d) / "scores.json"))["config"]


def paired(base, tuned, seeds, ids, reps=2000, seed=0):
    mean = lambda runs, i: st.mean(runs[s][i]["correct"] for s in seeds)
    delta = {i: mean(tuned, i) - mean(base, i) for i in ids}
    rng = random.Random(seed)

    def ci(qs):
        if not qs:
            return float("nan"), float("nan"), float("nan")
        boots = sorted(st.mean(delta[rng.choice(qs)] for _ in qs) for _ in range(reps))
        return 100 * st.mean(delta[i] for i in qs), 100 * boots[int(0.025 * reps)], 100 * boots[int(0.975 * reps)]
    return delta, ci


def summarize_run(run):
    run = Path(run)
    evald = run / "eval"
    tuned_dirs = sorted(p for p in evald.glob("seed*") if (p / "scores.json").exists())
    if not tuned_dirs:
        return None
    base_cfg = cfg(BASE[0])
    skip = {"seed", "out", "model", "model_revision", "ids_file"}
    for d in tuned_dirs:
        diff = {k for k in set(cfg(d)) | set(base_cfg) if k not in skip and cfg(d).get(k) != base_cfg.get(k)}
        if diff:
            sys.exit(f"{run}: eval settings differ from baseline in {sorted(diff)} -> not comparable")
    base = {cfg(d)["seed"]: load(d) for d in BASE if (d / "scores.json").exists()}
    tuned = {cfg(d)["seed"]: load(d) for d in tuned_dirs}
    seeds = sorted(set(base) & set(tuned))
    ids = sorted(set.intersection(*(set(R) for R in [*base.values(), *tuned.values()])))
    delta, ci = paired(base, tuned, seeds, ids)
    cond = run.name.replace("abl_", "").split("_")[0]
    targets = TARGET.get(cond, [])
    subj = {i: base[seeds[0]][i]["subject"] for i in ids}
    by_subj = defaultdict(list)
    for i in ids:
        by_subj[subj[i]].append(i)
    rows = {s: 100 * st.mean(delta[i] for i in qs) for s, qs in by_subj.items()}
    acc = lambda runs: 100 * st.mean(runs[s][i]["correct"] for s in seeds for i in ids)
    trunc = lambda runs: 100 * st.mean(runs[s][i]["truncated"] for s in seeds for i in ids)
    tag = lambda runs: 100 * st.mean(runs[s][i]["answer_tag_found"] for s in seeds for i in ids)
    n_train = None
    for p in (run / "data" / "sft.jsonl",):
        if p.exists():
            n_train = sum(1 for l in open(p) if l.strip())
    rep = {}
    for name in ("decontam_report.json", "self_cot_report.json"):
        p = run / "data" / name
        if p.exists():
            rep[name] = json.load(open(p))
    tr = run / "train" / "log.json"
    train_log = json.load(open(tr)) if tr.exists() else {}
    return {"run": run.name, "condition": cond, "seeds": seeds, "n_questions": len(ids), "n_train": n_train,
            "base_acc": acc(base), "tuned_acc": acc(tuned),
            "delta_all": ci(ids), "delta_target": ci([i for i in ids if subj[i] in targets]),
            "delta_nontarget": ci([i for i in ids if subj[i] not in targets]),
            "subject_delta": dict(sorted(rows.items(), key=lambda kv: -abs(kv[1]))),
            "base_trunc": trunc(base), "tuned_trunc": trunc(tuned), "base_tag": tag(base), "tuned_tag": tag(tuned),
            "decontam_removed": rep.get("decontam_report.json", {}).get("removed"),
            "self_cot_kept": rep.get("self_cot_report.json", {}).get("kept"),
            "final_loss": (train_log.get("log") or [{}])[-1].get("loss"),
            "code_commit": train_log.get("code_commit", "")[:8]}


def fmt(c):
    m, lo, hi = c
    return f"{m:+.2f} [{lo:+.2f}, {hi:+.2f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--top-subjects", type=int, default=6)
    a = ap.parse_args()
    res = [r for r in (summarize_run(p) for p in a.runs) if r]
    lines = ["# 데이터셋별 LoRA SFT 효과 (main 베이스라인 results/seed* 대비, 문항·seed 짝 비교)", "",
             "| 조건 | 학습 레코드 | seeds | base | tuned | Δ 전체 [95% CI] | Δ 표적 과목 | Δ 비표적 과목 | 잘림 % (base→tuned) | Answer 태그 % |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in res:
        lines.append(f"| {r['run']} | {r['n_train']} | {','.join(map(str, r['seeds']))} | {r['base_acc']:.2f} | {r['tuned_acc']:.2f} "
                     f"| **{fmt(r['delta_all'])}** | {fmt(r['delta_target'])} | {fmt(r['delta_nontarget'])} "
                     f"| {r['base_trunc']:.1f}→{r['tuned_trunc']:.1f} | {r['base_tag']:.1f}→{r['tuned_tag']:.1f} |")
    lines += ["", "Δ는 (tuned 정답률 − base 정답률)을 같은 seed·같은 문항끼리 묶어 평균한 값(점). CI는 문항 부트스트랩 2000회.",
              "표적 과목 = 그 데이터셋이 겨냥한 실패 유형이 몰린 과목(summarize.py TARGET). 표적에서 오르고 비표적에서 안 떨어지는지 본다.", ""]
    for r in res:
        top = list(r["subject_delta"].items())[:a.top_subjects]
        lines.append(f"**{r['run']}** 과목별 변화 상위: " + ", ".join(f"{s} {d:+.1f}" for s, d in top)
                     + f" · 오염 제거 {r['decontam_removed']}건 · self-CoT 채택 {r['self_cot_kept']}"
                     + (f" · 마지막 loss {r['final_loss']:.3f}" if r['final_loss'] is not None else "") + f" · code {r['code_commit']}")
    text = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    (Path(a.out).with_suffix(".json") if a.out else Path("/dev/null")).write_text(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
