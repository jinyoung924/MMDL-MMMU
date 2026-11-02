#!/usr/bin/env python
"""Forgetting pilot (pre-registered in pilot_forgetting/README.md): LoRA-SFT of Qwen3-VL-4B on PathVQA yes/no.

Trains toward EXTERNAL targets (the dataset's answer), logs target-task accuracy on a fixed PathVQA test sample,
and saves the LoRA adapter at fixed steps. Forgetting is measured separately: merge an adapter and run the
frozen MMMU pipeline on it (run_eval.py --model <merged dir>), then `analyze.py compare` against the base seeds.

python pilot_forgetting/train_sft.py --out pilot_forgetting/runs/sft_lr1e-4
python pilot_forgetting/train_sft.py --merge pilot_forgetting/runs/sft_lr1e-4/step2000   # -> ..._merged/
Runs in the `vllm-train` env (= the eval env + peft/accelerate), so the eval env stays untouched.
"""
import argparse, json, random, time
from pathlib import Path

import torch

MODEL, MODEL_REV = "Qwen/Qwen3-VL-4B-Instruct", "ebb281ec70b05090aa6165b016eac8ec08e71b17"
DATA, DATA_REV = "flaviagiammarino/path-vqa", "1685832883334b5bb5beaf4e4b333fdeecaa4ad9"
# The fine-tuning task's own instruction, deliberately NOT the MMMU CoT instruction: if MMMU reasoning
# behaviour changes after training, that is forgetting, not the eval prompt leaking into training.
INSTR = "Answer with yes or no."
LORA_TARGETS = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"
PIXELS = dict(min_pixels=4 * 32 * 32, max_pixels=1280 * 32 * 32)  # same image budget as run_eval.py


def closed_questions(split, n=0, seed=0):
    from datasets import load_dataset
    ds = load_dataset(DATA, split=split, revision=DATA_REV).filter(lambda a: a in ("yes", "no"), input_columns="answer")
    idx = list(range(len(ds)))
    random.Random(seed).shuffle(idx)
    return ds.select(idx[:n] if n else idx)


def encode(proc, rows, train):
    prompts = [proc.apply_chat_template([{"role": "user", "content": [
        {"type": "image"}, {"type": "text", "text": f"{r['question']}\n{INSTR}"}]}],
        add_generation_prompt=True, tokenize=False) for r in rows]
    imgs = [r["image"].convert("RGB") for r in rows]
    proc.tokenizer.padding_side = "right" if train else "left"
    if not train:
        return proc(text=prompts, images=imgs, return_tensors="pt", padding=True)
    enc = proc(text=[p + r["answer"] + "<|im_end|>" for p, r in zip(prompts, rows)], images=imgs,
               return_tensors="pt", padding=True)
    labels = enc["input_ids"].clone()
    for i, (p, img) in enumerate(zip(prompts, imgs)):  # loss only on the answer tokens
        labels[i, :proc(text=[p], images=[img], return_tensors="pt")["input_ids"].shape[1]] = -100
    labels[enc["attention_mask"] == 0] = -100
    enc["labels"] = labels
    return enc


@torch.no_grad()
def target_acc(model, proc, rows, bs=16):
    model.eval()
    hit = 0
    for i in range(0, len(rows), bs):
        chunk = rows[i:i + bs]
        enc = encode(proc, chunk, train=False).to(model.device)
        out = model.generate(**enc, max_new_tokens=4, do_sample=False)
        texts = proc.batch_decode(out[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)
        hit += sum(t.strip().lower().startswith(r["answer"]) for t, r in zip(texts, chunk))
    model.train()
    return hit / len(rows)


def train(a):
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForImageTextToText, AutoProcessor
    torch.manual_seed(a.seed)
    proc = AutoProcessor.from_pretrained(MODEL, revision=MODEL_REV, **PIXELS)
    model = AutoModelForImageTextToText.from_pretrained(MODEL, revision=MODEL_REV, dtype=torch.bfloat16).to(a.device)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05,
                                             target_modules=LORA_TARGETS))
    tr = closed_questions("train", seed=a.seed)
    te = closed_questions("test", a.n_eval, seed=0)
    test = [te[i] for i in range(len(te))]
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / a.warmup))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log = [{"step": 0, "pathvqa_acc": target_acc(model, proc, test)}]
    print(log[-1], flush=True)
    order, rng, pos, t0 = list(range(len(tr))), random.Random(a.seed), len(tr), time.time()
    for step in range(1, a.steps + 1):
        for _ in range(a.accum):
            if pos + a.bs > len(order):
                rng.shuffle(order)
                pos = 0
            loss = model(**encode(proc, [tr[i] for i in order[pos:pos + a.bs]], train=True).to(a.device)).loss
            (loss / a.accum).backward()
            pos += a.bs
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        if step % 50 == 0:
            print(f"step {step} loss {loss.item():.4f} {time.time() - t0:.0f}s", flush=True)
        if step in a.save_at:
            model.save_pretrained(out / f"step{step}")
            log.append({"step": step, "loss": loss.item(), "pathvqa_acc": target_acc(model, proc, test)})
            print(log[-1], flush=True)
            (out / "log.json").write_text(json.dumps({"config": vars(a), "n_train": len(tr), "log": log}, indent=2))


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="pilot_forgetting/runs/sft_lr1e-4")
    ap.add_argument("--merge", default="", help="adapter dir to merge instead of training")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--bs", type=int, default=4)
    ap.add_argument("--accum", type=int, default=2)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--save-at", type=int, nargs="+", default=[250, 1000, 2000])
    ap.add_argument("--n-eval", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    merge(a.merge) if a.merge else train(a)
