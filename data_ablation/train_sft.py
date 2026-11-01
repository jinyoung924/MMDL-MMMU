#!/usr/bin/env python
"""LoRA SFT of Qwen3-VL-4B-Instruct on one or more record files (data_ablation/common.py format).

python data_ablation/train_sft.py --data runs/abl_cosyn/data/sft.jsonl --out runs/abl_cosyn/train
python data_ablation/train_sft.py --merge runs/abl_cosyn/train/step1500        # -> step1500_merged/ for run_eval.py

Generalised from pilot_forgetting/train_sft.py (same LoRA targets, optimiser, masking) with three changes:
  * data comes from jsonl records (prompt / response / images) instead of a hard-coded dataset
  * the prompt is the evaluation's own CoT wording (built in prepare_data.py) and the loss covers the whole
    response = explanation + "Answer: X" line, so what is learned is the same behaviour the evaluation measures
  * the budget is FIXED across conditions: --steps x --bs x --accum examples (default 1500 x 8 x 1 = 12,000),
    so every dataset gets the same number of gradient updates and the same number of examples
Runs in the training env (eval env + peft/accelerate; cloud/runpod.sh TRAIN=1).
"""
import argparse, json, math, random, sys, time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import git_commit, read_jsonl  # noqa: E402

MODEL, MODEL_REV = "Qwen/Qwen3-VL-4B-Instruct", "ebb281ec70b05090aa6165b016eac8ec08e71b17"
LORA_TARGETS = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"
PIXELS = dict(min_pixels=4 * 32 * 32, max_pixels=1280 * 32 * 32)  # same image budget as run_eval.py


def load_records(paths, max_images):
    rows = []
    for p in paths:
        base = Path(p).parent
        for r in read_jsonl(p):
            if not r.get("response") or not r.get("prompt"):
                continue
            if len(r["images"]) > max_images:
                continue
            r["_images"] = [base / q for q in r["images"]]
            rows.append(r)
    return rows


def encode(proc, rows, max_len):
    """Batch -> input_ids/pixel values/labels. Loss only on the assistant tokens (prompt tokens are -100)."""
    from PIL import Image
    prompts, imgs, full = [], [], []
    for r in rows:
        content = [{"type": "image"} for _ in r["_images"]] + [{"type": "text", "text": r["prompt"]}]
        p = proc.apply_chat_template([{"role": "user", "content": content}], add_generation_prompt=True, tokenize=False)
        prompts.append(p)
        imgs.append([Image.open(q).convert("RGB") for q in r["_images"]])
        full.append(p + r["response"].strip() + "<|im_end|>")
    proc.tokenizer.padding_side = "right"
    enc = proc(text=full, images=[im for group in imgs for im in group] or None, return_tensors="pt",
               padding=True, truncation=True, max_length=max_len)
    labels = enc["input_ids"].clone()
    for i, (p, group) in enumerate(zip(prompts, imgs)):
        n_prompt = proc(text=[p], images=group or None, return_tensors="pt")["input_ids"].shape[1]
        labels[i, :n_prompt] = -100
    labels[enc["attention_mask"] == 0] = -100
    enc["labels"] = labels
    return enc


def train(a):
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForImageTextToText, AutoProcessor
    torch.manual_seed(a.seed)
    rows = load_records(a.data, a.max_images)
    assert rows, "no trainable records (empty response?)"
    need = a.steps * a.bs * a.accum
    print(f"[train] {len(rows)} records, budget {a.steps} steps x {a.bs} x {a.accum} = {need} examples "
          f"({need / len(rows):.2f} epochs)", flush=True)
    proc = AutoProcessor.from_pretrained(MODEL, revision=MODEL_REV, **PIXELS)
    model = AutoModelForImageTextToText.from_pretrained(MODEL, revision=MODEL_REV, dtype=torch.bfloat16).to(a.device)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05,
                                             target_modules=LORA_TARGETS))
    model.print_trainable_parameters()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    def lr_mult(s):
        warm = min(1.0, (s + 1) / a.warmup)
        if not a.cosine:
            return warm
        frac = min(1.0, max(0, s - a.warmup) / max(1, a.steps - a.warmup))
        return warm * 0.5 * (1 + math.cos(math.pi * frac))

    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_mult)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    order, pos, t0, log = list(range(len(rows))), len(rows), time.time(), []
    skipped_oom = 0
    model.train()
    for step in range(1, a.steps + 1):
        losses = []
        for _ in range(a.accum):
            if pos + a.bs > len(order):
                rng.shuffle(order)
                pos = 0
            batch = [rows[i] for i in order[pos:pos + a.bs]]
            pos += a.bs
            try:
                loss = model(**encode(proc, batch, a.max_len).to(a.device)).loss
                (loss / a.accum).backward()
                losses.append(loss.item())
            except torch.cuda.OutOfMemoryError:
                skipped_oom += 1
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                print(f"[train] OOM at step {step}, batch skipped (total {skipped_oom})", flush=True)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        if losses and (step % a.log_every == 0 or step == 1):
            log.append({"step": step, "loss": sum(losses) / len(losses), "lr": sched.get_last_lr()[0],
                        "elapsed_s": round(time.time() - t0)})
            print(f"step {step}/{a.steps} loss {log[-1]['loss']:.4f} lr {log[-1]['lr']:.2e} {log[-1]['elapsed_s']}s", flush=True)
        if step in a.save_at or step == a.steps:
            model.save_pretrained(out / f"step{step}")
            (out / "log.json").write_text(json.dumps({"config": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items()},
                                                      "n_records": len(rows), "skipped_oom": skipped_oom,
                                                      "code_commit": git_commit(), "log": log}, indent=2))
    print(f"[train] done in {(time.time() - t0) / 60:.1f} min, adapters in {out}", flush=True)


def merge(adapter):
    """Adapter -> full bf16 model dir that run_eval.py / vLLM can load like the original checkpoint."""
    from peft import PeftModel
    from transformers import AutoModelForImageTextToText, AutoProcessor
    base = AutoModelForImageTextToText.from_pretrained(MODEL, revision=MODEL_REV, dtype=torch.bfloat16)
    dst = Path(str(adapter).rstrip("/") + "_merged")
    PeftModel.from_pretrained(base, adapter).merge_and_unload().save_pretrained(dst)
    AutoProcessor.from_pretrained(MODEL, revision=MODEL_REV).save_pretrained(dst)
    print(f"merged -> {dst}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", nargs="*", default=[], help="one or more sft.jsonl files")
    ap.add_argument("--out", default="runs/sft/train")
    ap.add_argument("--merge", default="", help="adapter dir to merge instead of training")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--bs", type=int, default=8, help="A100 80GB default; use 2-4 with --accum on 24GB")
    ap.add_argument("--accum", type=int, default=1)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--cosine", type=int, default=1, help="1 = cosine decay after warmup, 0 = constant")
    ap.add_argument("--max-len", type=int, default=4096, help="tokens per example incl. image tokens")
    ap.add_argument("--max-images", type=int, default=4)
    ap.add_argument("--save-at", type=int, nargs="*", default=[])
    ap.add_argument("--log-every", type=int, default=25)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.merge:
        merge(a.merge)
    else:
        assert a.data, "--data is required"
        train(a)
