#!/usr/bin/env python
"""Post-processing over N seeds of the frozen pipeline (run_eval.py). Stdlib only, except `export`.

python analyze.py aggregate results/seed*                   # -> results/table.md + results/scores.json (mean ± sd)
python analyze.py failures  results/seed* [--tags T.jsonl]  # stability classes, truncation/loop breakdown, axes table
python analyze.py compare   results/seed* vs tuned/seed0 tuned/seed1 --target "Subj1,Subj2"   # paired Δ + forgetting
python analyze.py export    results/seed* --out DIR --sample 48            # first 48 of a seeded shuffle -> DIR/untagged/<id>/
python analyze.py export    results/seed* --out DIR --tags T.jsonl --per-type 5   # first 5 per tag, same order -> DIR/<type>/<id>/
(`export` needs `datasets`; tags follow reports/failure_tagging_protocol.md, one JSON object per line)
"""
import ast, json, math, random, re, statistics as st, sys
from collections import Counter, defaultdict
from pathlib import Path

TAGS = {"P": ("P_perception", "지각 (Perception)"), "K": ("K_knowledge", "지식 (Knowledge)"),
        "R": ("R_reasoning", "추론 (Reasoning)"), "T": ("T_textual", "텍스트 이해 (Textual understanding)"),
        "PK": ("PK_perception_or_knowledge", "지각/지식 구분 불가"), "G": ("G_generation", "생성 실패 (Generation)"),
        "S": ("S_scoring", "채점 오류 (Scoring) — 모델 실패 아님"), "D": ("D_item_defect", "문항 결함 (Item defect)"),
        "X": ("X_rejection", "거부/포기 (Rejection)")}


def load(d):
    return {p["id"]: p for p in map(json.loads, open(Path(d) / "predictions.jsonl"))}


def looped(p):
    """Tail repeats a 100-char chunk >=3 times -> degenerate loop; more budget won't help."""
    t = p["response"][-3000:]
    c = t[-200:-100]
    return bool(c) and t.count(c) >= 3


def sd(xs):
    return st.stdev(xs) if len(xs) > 1 else 0.0


def check_comparable(dirs):
    """Seeds are only averaged if every other config key is identical — otherwise the mean is meaningless."""
    cfgs = [json.load(open(Path(d) / "scores.json"))["config"] for d in dirs]
    diff = {k for c in cfgs for k in set(c) | set(cfgs[0]) if k not in ("seed", "out") and c.get(k) != cfgs[0].get(k)}
    if diff:
        sys.exit(f"refusing to aggregate: runs differ in {sorted(diff)}")
    return cfgs[0]


def aggregate(dirs):
    cfg = check_comparable(dirs)
    runs = [load(d) for d in dirs]
    subjects = list(dict.fromkeys(p["subject"] for p in runs[0].values()))
    acc = {s: [100 * st.mean(p["correct"] for p in R.values() if p["subject"] == s) for R in runs] for s in subjects}
    overall = [st.mean(acc[s][i] for s in subjects) for i in range(len(runs))]
    k = Counter(sum(R[i]["correct"] for R in runs) for i in runs[0])
    per_seed = [json.load(open(Path(d) / "scores.json")) for d in dirs]
    scores = {
        "n_seeds": len(runs), "seeds": [s["config"]["seed"] for s in per_seed],
        "overall_mean": st.mean(overall), "overall_sd": sd(overall), "overall_per_seed": overall,
        "per_subject": {s: {"mean": st.mean(v), "sd": sd(v), "per_seed": v} for s, v in acc.items()},
        "questions_by_times_correct": {str(n): k[n] for n in range(len(runs) + 1)},
        "truncated_per_seed": [s["truncated"] for s in per_seed],
        "fallback_guess_per_seed": [s["fallback_guess"] for s in per_seed],
        "config": {**cfg, "seed": "see seeds", "out": str(Path(dirs[0]).parent)},
    }
    out = Path(dirs[0]).parent
    (out / "scores.json").write_text(json.dumps(scores, indent=2))
    n = len(runs)
    lines = [f"| No. | Subject | Data Num | Acc (mean of {n} seeds) | sd |", "|---|---|---|---|---|"]
    for i, s in enumerate(subjects, 1):
        lines.append(f"| {i} | {s} | 30 | {st.mean(acc[s]):.1f} | {sd(acc[s]):.1f} |")
    lines.append(f"| | **Overall (macro avg)** | **{len(runs[0])}** | **{st.mean(overall):.2f}** | {sd(overall):.2f} |")
    (out / "table.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nper-seed overall: {', '.join(f'{x:.2f}' for x in overall)}")
    print(f"questions by times correct (0..{n}): {[k[i] for i in range(n + 1)]}")


def failures(dirs, tags=None):
    runs = [load(d) for d in dirs]
    n, ids = len(runs), list(runs[0])
    c = {i: st.mean(R[i]["correct"] for R in runs) for i in ids}
    stable_wrong = [i for i in ids if c[i] == 0]
    print(f"== {n} runs: stable-wrong {len(stable_wrong)}, unstable {sum(0 < c[i] < 1 for i in ids)}, "
          f"stable-correct {sum(c[i] == 1 for i in ids)}")

    wrong = [R[i] for R in runs for i in ids if not R[i]["correct"]]
    tw = [p for p in wrong if p["truncated"]]
    print(f"== wrong responses over all runs: {len(wrong)} (per run {len(wrong) / n:.0f})")
    print(f"   truncated {len(tw)}: loop {sum(map(looped, tw))}, parser random-guess {sum(p['fallback_guess'] for p in tw)}")
    print(f"   completed {len(wrong) - len(tw)}")

    overall = 100 * st.mean(c.values())
    axes = {"subject": lambda p: [p["subject"]], "img_type": lambda p: p.get("img_type", []),
            "difficulty": lambda p: [p.get("topic_difficulty")]}
    for name, key in axes.items():
        groups = defaultdict(list)
        for i in ids:
            for g in key(runs[0][i]):
                groups[g].append(i)
        print(f"\n== by {name}  (overall {overall:.1f}; * = 95% CI excludes overall; question-level CI)")
        rows = []
        for g, qs in groups.items():
            if len(qs) < 15:
                continue
            v = [c[i] for i in qs]
            m, half = 100 * st.mean(v), 196 * sd(v) / math.sqrt(len(v))
            t = Counter(tags[i]["tag"] for i in qs if tags and i in tags)
            rows.append((m, g, len(qs), half, sum(c[i] == 0 for i in qs), t))
        for m, g, k, half, sw, t in sorted(rows):
            flag = "*" if abs(m - overall) > half else " "
            tagstr = " ".join(f"{a}{b}" for a, b in t.most_common()) if t else ""
            print(f" {flag} {str(g):38s} n={k:3d} acc {m:5.1f} ± {half:4.1f}  stable-wrong {sw:3d}  {tagstr}")
    if tags:
        t = Counter(tags[i]["tag"] for i in stable_wrong if i in tags)
        print(f"\n== tags over stable-wrong ({sum(t.values())}/{len(stable_wrong)} tagged): {dict(t.most_common())}")


def compare(base_dirs, tuned_dirs, target_subjects=(), reps=2000):
    """Base vs fine-tuned, paired by seed and question. Primary: Δacc on all non-target questions (no selection).
    Descriptive: of what the base model reliably solved, what the tuned model no longer solves, split into
    format vs content losses. "Reliably solved" is picked ONLY from base runs whose seed is not in the paired
    comparison — selecting and measuring on the same runs makes an unchanged model look ~10 pts worse
    (regression to the mean; measured with a base-vs-base null test)."""
    cfg = lambda d: json.load(open(Path(d) / "scores.json"))["config"]
    skip = {"seed", "out", "model", "model_revision", "ids_file"}
    b0 = cfg(base_dirs[0])
    for d in tuned_dirs:
        diff = {k for k in set(cfg(d)) | set(b0) if k not in skip and cfg(d).get(k) != b0.get(k)}
        if diff:
            sys.exit(f"refusing to compare: eval settings differ in {sorted(diff)}")
    base = {cfg(d)["seed"]: load(d) for d in base_dirs}
    tuned = {cfg(d)["seed"]: load(d) for d in tuned_dirs}
    seeds = sorted(set(base) & set(tuned))
    if not seeds:
        sys.exit("no seed in common between base and tuned runs")
    ids = sorted(set.intersection(*(set(R) for R in [*base.values(), *tuned.values()])))
    mean = lambda runs, i: st.mean(runs[s][i]["correct"] for s in seeds)
    delta = {i: mean(tuned, i) - mean(base, i) for i in ids}
    rng = random.Random(0)

    def ci(qs):
        if not qs:
            return float("nan"), float("nan"), float("nan")
        boots = sorted(st.mean(delta[rng.choice(qs)] for _ in qs) for _ in range(reps))
        return 100 * st.mean(delta[i] for i in qs), 100 * boots[int(0.025 * reps)], 100 * boots[int(0.975 * reps)]

    held = [s for s in base if s not in seeds]  # selection runs, disjoint from the measured ones
    print(f"== paired on seeds {seeds}, {len(ids)} questions; 'base stable-correct' selected on held-out base seeds {held}")
    groups = {"all": ids, "target subjects": [i for i in ids if base[seeds[0]][i]["subject"] in target_subjects],
              "non-target subjects": [i for i in ids if base[seeds[0]][i]["subject"] not in target_subjects]}
    strong = [i for i in groups["non-target subjects"] if held and all(base[s][i]["correct"] for s in held)]
    groups["non-target, base stable-correct"] = strong
    for name, qs in groups.items():
        m, lo, hi = ci(qs)
        print(f"   Δacc {name:32s} n={len(qs):3d}  {m:+6.2f} pts  95% CI [{lo:+.2f}, {hi:+.2f}]")
    lost = lambda runs: [i for i in strong if not any(runs[s][i]["correct"] for s in seeds)]
    fmt = [i for i in lost(tuned) if all(tuned[s][i]["truncated"] or not tuned[s][i]["answer_tag_found"] for s in seeds)]
    print(f"== non-target stable-correct ({len(strong)}): wrong in every paired seed — base {len(lost(base))} (noise floor), "
          f"tuned {len(lost(tuned))} (format: truncated/no Answer tag {len(fmt)}, content: completed but wrong "
          f"{len(lost(tuned)) - len(fmt)})")
    for name, runs in (("base", base), ("tuned", tuned)):
        P = [runs[s][i] for s in seeds for i in ids]
        print(f"   {name:5s} truncated {100 * st.mean(p['truncated'] for p in P):5.1f}%  "
              f"Answer tag {100 * st.mean(p['answer_tag_found'] for p in P):5.1f}%  "
              f"mean response {st.mean(len(p['response']) for p in P):7.0f} chars")


def load_tags(path):
    return {t["id"]: t for t in (json.loads(l) for l in open(path) if l.strip())}


def case_md(r, preds, seeds, imgs, t):
    """One failure case as markdown: metadata, diagnosis (if tagged), images, exact prompt, full responses."""
    p = preds[0]
    gold = r["answer"]
    m = re.search(rf"^\({re.escape(gold)}\) (.*)$", p["prompt"], re.M) if len(gold) == 1 else None
    answers = ", ".join(f"seed {s}: {q['parsed']} {'✓' if q['correct'] else '✗'}{' (잘림)' if q['truncated'] else ''}"
                        for s, q in zip(seeds, preds))
    md = [f"# {r['id']}" + (f" — {t['tag']} {TAGS[t['tag']][1]}" if t else ""), "",
          "| 항목 | 값 |", "|---|---|",
          f"| 과목 / 세부 분야 | {p['subject']} / {r['subfield']} |",
          f"| 이미지 유형 / 난이도 | {', '.join(ast.literal_eval(r['img_type']))} / {r['topic_difficulty']} |",
          f"| 정답 | **{gold}**{' — ' + m.group(1) if m else ''} |",
          f"| 모델 답 | {answers} |"]
    if t:
        md += ["", "## 진단 (Claude 판정 — 팀 검수 전)", "",
               f"- **유형**: {t['tag']} {TAGS[t['tag']][1]}" + (f" / {t['subtype']}" if t.get("subtype") else ""),
               f"- **첫 오류 (모델 응답 인용)**: “{t['evidence']}”",
               f"- **실제**: {t['truth']}",
               f"- **확신도**: {t['confidence']}"] + ([f"- **비고**: {t['notes']}"] if t.get("notes") else []) \
              + ([f"- **검수**: {t['review']}"] if t.get("review") else [])
    md += ["", "## 이미지", "", *imgs, "", "## 문제 (모델에 들어간 텍스트 그대로)", "", "````text", p["prompt"], "````",
           "", "## 모델의 풀이", ""]
    for s, q in zip(seeds, preds):
        md += [f"<details><summary>seed {s} — 파싱 {q['parsed']}, {'정답' if q['correct'] else '오답'}, "
               f"잘림 {'예' if q['truncated'] else '아니오'}, 루프 {'예' if looped(q) else '아니오'}</summary>", "",
               "````text", q["response"], "````", "", "</details>", ""]
    return "\n".join(md)


def export(dirs, out, tags=None, per_type=0, sample=0, seed=0):
    """Case folders for questions wrong in every given run: <out>/<type>/<id>/{case.md, image_k.png}.
    Candidates are shuffled with a fixed seed. `sample=N` writes the first N untagged (to be tagged);
    `tags` + `per_type=K` writes the first K of each tag in the same order -> a random pick within each type."""
    from datasets import load_dataset
    runs = [load(d) for d in dirs]
    cfg = check_comparable(dirs)
    seeds = [json.load(open(Path(d) / "scores.json"))["config"]["seed"] for d in dirs]
    order = sorted(i for i in runs[0] if not any(R[i]["correct"] for R in runs))
    random.Random(seed).shuffle(order)
    if tags:
        pick, k = [], Counter()
        for i in order:
            if i in tags and k[tags[i]["tag"]] < per_type:
                pick.append(i)
                k[tags[i]["tag"]] += 1
    else:
        pick = order[:sample] if sample else order
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "order.txt").write_text("\n".join(order) + "\n")  # audit trail of the random order
    want = defaultdict(set)
    for i in pick:
        want[runs[0][i]["subject"]].add(i)
    for s, ids in want.items():
        for r in load_dataset(cfg["data"], s, split="validation", revision=cfg["data_revision"]):
            if r["id"] not in ids:
                continue
            t = tags[r["id"]] if tags else None
            d = Path(out) / (TAGS[t["tag"]][0] if t else "untagged") / r["id"]
            d.mkdir(parents=True, exist_ok=True)
            imgs = []
            for n in range(1, 8):
                if r.get(f"image_{n}"):
                    r[f"image_{n}"].convert("RGB").save(d / f"image_{n}.png")
                    imgs.append(f"![image {n}](image_{n}.png)")
            (d / "case.md").write_text(case_md(r, [R[r["id"]] for R in runs], seeds, imgs, t))
    print(f"{len(order)} candidates (wrong in all {len(runs)} runs), wrote {len(pick)} case folders to {out}")


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    opts = {rest[i]: rest[i + 1] for i, a in enumerate(rest) if a.startswith("--")}
    dirs = [a for i, a in enumerate(rest) if not a.startswith("--") and (i == 0 or not rest[i - 1].startswith("--"))]
    tags = load_tags(opts["--tags"]) if "--tags" in opts else None
    if cmd == "aggregate":
        aggregate(dirs)
    elif cmd == "failures":
        failures(dirs, tags)
    elif cmd == "compare":  # analyze.py compare BASE_DIR... vs TUNED_DIR... [--target "Subj1,Subj2"]
        k = dirs.index("vs")
        compare(dirs[:k], dirs[k + 1:], tuple(opts.get("--target", "").split(",")) if "--target" in opts else ())
    elif cmd == "export":
        export(dirs, opts["--out"], tags, int(opts.get("--per-type", 0)), int(opts.get("--sample", 0)),
               int(opts.get("--seed", 0)))
    else:
        sys.exit(__doc__)
