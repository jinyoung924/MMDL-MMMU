#!/usr/bin/env python
"""GRPO for Qwen3-VL-4B-Instruct on one 24 GB GPU.

One round = `rollout` (vLLM: 4 samples per question, 4 more for questions whose first 4 are
all wrong) then `train` (HF + LoRA: clipped GRPO surrogate + k3 KL to the frozen base,
token-mean over each optimizer step). Separate processes, so the GPU is freed in between.
Reward = 1 iff the response ends with EOS and its last "Answer:" matches the gold (letter, or
number within 1 %); truncated = 0 since the eval budget is the same 8192 tokens. v3 adds an
optional `judge` step (v3_protocol.md): a frozen judge compares each finished response with the
item's reference solution, and reward = correct + 0.5 image_ok + 0.5 reasoning_ok. Groups whose
rewards are all equal carry no signal and are skipped. Rollouts sample the raw policy (T=1, no
top-k/p, no penalties), so vLLM's sampled-token logprobs are the behavior policy mu of the ratio.
"""
import argparse, json, math, os, re, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_eval import ANSWER_TAG_MC

MODEL = 'Qwen/Qwen3-VL-4B-Instruct'
REV = 'ebb281ec70b05090aa6165b016eac8ec08e71b17'
PIXELS = {'min_pixels': 4096, 'max_pixels': 1310720}  # = run_eval defaults
JUDGE_REVS = {'Qwen/Qwen3-VL-8B-Instruct-FP8': '9cdc6310a8cb770ce18efaf4e9935334512aee45'}  # pinned like MODEL
TEACHER = 'Qwen/Qwen3-VL-8B-Instruct-FP8'  # v6 on-policy distillation teacher (v6_prep_protocol.md B1)
LORA_TARGETS = r'.*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)'


SCI = re.compile(r'(-?\d+(?:\.\d+)?)\s*(?:\\times|×|\\cdot|x|\*)\s*10\^\{?\s*([-+]?\d+)\s*\}?')
NUM = re.compile(r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?')


def numbers(s):
    """Every number in s; scientific notation (2.5 \\times 10^{3}) first, thousands commas allowed."""
    return [float(f"{m}e{e}") for m, e in SCI.findall(s)] + [
        float(x.replace(',', '')) for x in NUM.findall(SCI.sub(' ', s))]


def gold_number(short_answer):
    """The answer's value when it holds exactly one number (units/labels around it are fine), else None."""
    v = numbers(short_answer)
    return v[0] if len(v) == 1 else None


WORDS = {w: float(i) for i, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve '
                                          'thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split())}


SYMBOLIC = re.compile(r"√|sqrt|π|\\pi|\\[dt]?frac|°\s*\d+(?:\.\d+)?\s*['′]|\d\s*/\s*\d")


def expr_value(s):
    """Value of a short written expression: √, π, \\frac, a/b, implicit products (50√3, 45π), 71°46'; else None."""
    t = s.replace('$', '').replace('\\left', '').replace('\\right', '').replace('\\,', ' ').strip()
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*°\s*(\d+(?:\.\d+)?)\s*['′]", t)
    if m:
        return float(m[1]) + float(m[2]) / 60
    for _ in range(3):  # nested fractions
        t = re.sub(r'\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}', r'((\1)/(\2))', t)
    t = re.sub(r'\\sqrt\{([^{}]*)\}', r'sqrt(\1)', t)
    t = re.sub(r'√\s*\{([^{}]*)\}', r'sqrt(\1)', t)
    t = re.sub(r'√\s*\(', 'sqrt(', t)
    t = re.sub(r'√\s*(\d+(?:\.\d+)?)', r'sqrt(\1)', t)
    for a, b in (('\\pi', 'pi'), ('π', 'pi'), ('\\cdot', '*'), ('\\times', '*'), ('×', '*')):
        t = t.replace(a, b)
    m = re.match(r'(?:[\s\d.+\-*/()]|sqrt|pi)+', t)
    if not m or '**' in m.group(0):
        return None
    e = re.sub(r'(\d|\)|pi)\s*(?=sqrt|pi|\()', r'\1*', m.group(0).strip())
    e = re.sub(r'(pi|\))\s*(?=\d)', r'\1*', e)
    try:
        return float(eval(e, {'__builtins__': {}}, {'sqrt': math.sqrt, 'pi': math.pi}))
    except Exception:  # malformed or division by zero: not evaluable
        return None


def decimals(s):
    m = NUM.search(s or '')
    return len(m.group(0).split('.')[1]) if m and '.' in m.group(0) else 0


def close(v, g, dg=0, dp=None):
    """Within 1 % (x 10^±3 unit prefixes allowed); decimal answers also within half a unit of the coarser
    printed decimal place (v4)."""
    tol = 0.01 * abs(g) + 1e-9
    d = dg if dp is None else min(dg, dp)
    if d >= 1:
        tol = max(tol, 0.5 * 10 ** -d)
    return any(abs(v - g * k) <= tol * k for k in (1, 1e3, 1e-3))


def answer_value(t):
    """(value, printed decimals or None) of an answer string."""
    if SYMBOLIC.search(t):
        v = expr_value(t)
        if v is not None:
            return v, None
    n = numbers(t)
    if n:
        return n[0], decimals(t)
    w = [WORDS[x] for x in re.findall(r'[a-z]+', t.lower()) if x in WORDS]
    return (w[0], None) if w else (None, None)


def correct(q, text, finish):
    """1.0 iff the response ended with EOS and its last 'Answer:' is the gold letter, or the gold value under
    close() (number words: v3 Amendment 6; expressions and decimal places: v4)."""
    if finish != 'stop':
        return 0.0
    if q.get('kind') == 'num' or isinstance(q['gold'], (int, float)):
        tags = re.findall(r'Answer:\s*(.+)', text)
        v, dp = answer_value(tags[-1]) if tags else (None, None)
        return float(v is not None and close(v, q['gold'], decimals(q.get('gold_str')), dp))
    hits = ANSWER_TAG_MC.findall(text)
    return float(bool(hits) and hits[-1].upper() == q['gold'])


def fix_gold(q):
    """v4: symbolic gold strings (45π, \\frac) get their evaluated value; None when not evaluable."""
    if q.get('kind') == 'num' and SYMBOLIC.search(q.get('gold_str') or ''):
        return {**q, 'gold': expr_value(q['gold_str'])}
    return q


JUDGE = """You are grading a student's solution to the problem about the image.

PROBLEM:
{question}

REFERENCE SOLUTION (correct):
{reference}

STUDENT SOLUTION:
{student}

Grade the student solution against the image and the reference solution.
IMAGE: are all visual facts the student states or relies on (values, labels, which point, side, angle or component a value belongs to, markings, relations shown) consistent with the image and the reference? One uncorrected wrong visual claim makes it INCORRECT.
REASONING: is the student's final line of reasoning valid (right principles, correctly applied, correct arithmetic) so that it actually supports its final answer? Mistakes the student explicitly corrects do not count. A correct final answer reached through invalid reasoning is INVALID.
Write at most five short sentences of analysis, then end with exactly these two lines:
IMAGE: CORRECT or INCORRECT
REASONING: VALID or INVALID"""
IMAGE_V = re.compile(r'IMAGE:\s*\**\s*(CORRECT|INCORRECT)', re.I)
REASON_V = re.compile(r'REASONING:\s*\**\s*(VALID|INVALID)', re.I)


def parse_judge(text):
    """(image_ok, reasoning_ok) as 0/1; None where the verdict line is missing."""
    i, r = IMAGE_V.findall(text), REASON_V.findall(text)
    return (float(i[-1].upper() == 'CORRECT') if i else None, float(r[-1].upper() == 'VALID') if r else None)


def judge_generate(model, items, gpu_mem=0.85):
    """items = [(question, reference, student, image_path)] -> judge output texts (greedy)."""
    from PIL import Image
    from transformers import AutoProcessor
    from vllm import LLM, SamplingParams
    rev = REV if model == MODEL else JUDGE_REVS[model]
    proc = AutoProcessor.from_pretrained(model, revision=rev, **PIXELS)
    prompts = [{'prompt': chat(proc, '<image>\n' + JUDGE.format(question=q, reference=ref, student=s)),
                'multi_modal_data': {'image': [Image.open(p).convert('RGB')]}} for q, ref, s, p in items]
    llm = LLM(model=model, revision=rev, max_model_len=16384, gpu_memory_utilization=gpu_mem,
              limit_mm_per_prompt={'image': 1}, mm_processor_kwargs=PIXELS, seed=0)
    return [o.outputs[0].text for o in llm.generate(prompts, SamplingParams(temperature=0.0, max_tokens=512))]


def advantages(rewards):
    """(r - mean) / std within the group; None when all rewards are equal (no signal)."""
    n, mean = len(rewards), sum(rewards) / len(rewards)
    std = math.sqrt(sum((r - mean) ** 2 for r in rewards) / (n - 1))
    return None if std == 0 else [(r - mean) / (std + 1e-4) for r in rewards]


def group_adv(rewards, teacher=False):
    """Group advantages; None = skip the group. v6 (teacher): zeros instead, so every finished sample still gets the
    teacher's per-token signal."""
    adv = advantages(rewards) if len(rewards) > 1 else None
    return adv or ([0.0] * len(rewards) if teacher and rewards else None)


def chat(proc, text):
    content = []
    for i, part in enumerate(text.split('<image>')):
        if i:
            content.append({'type': 'image'})
        if part:
            content.append({'type': 'text', 'text': part})
    return proc.apply_chat_template([{'role': 'user', 'content': content}],
                                    add_generation_prompt=True, tokenize=False)


def log(run, rec):
    with open(run / 'log.jsonl', 'a') as f:
        f.write(json.dumps(rec) + '\n')
    print(json.dumps(rec), flush=True)


def engine(a, seed, model=MODEL):
    from vllm import LLM
    # max_num_seqs caps per-step sampler/logprob buffers (a 256-sequence step OOMed next to other GPU jobs);
    # KV space already limits concurrency to ~25 long responses, so throughput is unchanged.
    # The teacher (no LoRA) caps prefill chunks: prompt logprobs hold chunk x 152k-vocab fp32 logits.
    kw = (dict(revision=REV, enable_lora=True, max_lora_rank=16, max_loras=1) if model == MODEL
          else dict(revision=JUDGE_REVS[model], max_num_batched_tokens=2048))
    return LLM(model=model, max_model_len=16384, gpu_memory_utilization=a.gpu_mem, max_num_seqs=64,
               limit_mm_per_prompt={'image': 1}, seed=seed, mm_processor_kwargs=PIXELS, **kw)


def sample_rows(llm, proc, items, n, max_tokens, lora=None, stage=1, logprobs=True):
    """items = [(question, prompt text, hint or None)] -> one row per sample (behaviour logprobs, correctness)."""
    from PIL import Image
    from vllm import SamplingParams
    if not items:
        return []
    chats = [chat(proc, t) for _, t, _ in items]
    prompts = [{'prompt': c, 'multi_modal_data': {'image': [Image.open(q['image']).convert('RGB')]}}
               for c, (q, _, _) in zip(chats, items)]
    sp = SamplingParams(n=n, temperature=1.0, top_p=1.0, top_k=0, max_tokens=max_tokens,
                        logprobs=0 if logprobs else None)
    rows = []
    for (q, _, hint), c, o in zip(items, chats, llm.generate(prompts, sp, lora_request=lora)):
        for out in o.outputs:
            ids = list(out.token_ids)
            ok = correct(q, out.text, out.finish_reason)
            rows.append({'qid': q['qid'], 'group': q['qid'] + ('#hint' if hint else ''), 'stage': stage, 'hint': hint,
                         'chat': c, 'image': q['image'], 'gold': q['gold'], 'gold_str': q.get('gold_str'),
                         'kind': q.get('kind'), 'prompt_len': len(o.prompt_token_ids), 'ids': ids,
                         'logps': [lp[t].logprob for t, lp in zip(ids, out.logprobs)] if logprobs else [],
                         'finish': out.finish_reason, 'text': out.text, 'correct': ok, 'reward': ok,
                         'question': q.get('question'), 'reference': q.get('reference')})
    return rows


HINT_SYSTEM = ('You write short hints for students in a research experiment. Use only the Read tool. '
               'Do not create or modify any file. Reply with only the hint text.')
HINT_PROMPT = """A student failed the problem below. Look at the image file {image} with the Read tool, then read the problem and its reference solution.
Write ONE hint of at most two sentences that points the student to the key visual fact or the key principle for the first step.
Never state the final answer, the quantity that is asked for, or a value that directly gives it away. Reply with only the hint.

PROBLEM:
{question}

REFERENCE SOLUTION:
{reference}"""


def get_hints(qs, workers=8):
    """v4: one Sonnet hint per failed question (headless, effort low); hints whose numbers hit the gold are dropped."""
    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    def one(q):
        cmd = ['claude', '-p', '--model', 'sonnet', '--effort', 'low', '--tools', 'Read', '--allowedTools', 'Read',
               '--strict-mcp-config', '--system-prompt', HINT_SYSTEM, '--add-dir', str(Path(q['image']).parent),
               '--no-session-persistence', '--output-format', 'json',
               HINT_PROMPT.format(image=q['image'], question=q['question'], reference=q['reference'])]
        try:
            h = json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=900).stdout).get('result', '')
        except (subprocess.TimeoutExpired, ValueError):
            return q['qid'], None, 'failed'
        h = ' '.join(h.split())
        if not h:
            return q['qid'], None, 'failed'
        if any(close(v, q['gold'], decimals(q.get('gold_str'))) for v in numbers(h)):
            return q['qid'], None, 'leak'
        return q['qid'], h, 'ok'

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, qs))
    return {qid: h for qid, h, _ in res if h}, dict(__import__('collections').Counter(st for _, _, st in res))


def rollout(a):
    os.environ['VLLM_BATCH_INVARIANT'] = '0'
    from transformers import AutoProcessor
    from vllm.lora.request import LoRARequest
    from run_eval import COT_OPEN_SUFFIX
    run = Path(a.run)
    (run / 'rounds').mkdir(parents=True, exist_ok=True)
    pool = [json.loads(l) for l in open(a.pool)]
    qs = pool[a.pool_offset + a.round * a.questions:a.pool_offset + (a.round + 1) * a.questions]
    assert qs, 'pool exhausted'
    proc, llm, adapter, t0 = AutoProcessor.from_pretrained(MODEL, revision=REV, **PIXELS), engine(a, a.round), run / 'adapter', time.time()
    lora = (LoRARequest(f'round{a.round}', a.round + 1, str(adapter))
            if (adapter / 'adapter_config.json').exists() else None)
    rows = sample_rows(llm, proc, [(q, q['text'], None) for q in qs], a.samples, a.max_tokens, lora, 1)
    first, solved = list(rows), {r['qid'] for r in rows if r['correct']}
    failed = [q for q in qs if q['qid'] not in solved]
    if a.topup:  # v1-v3: 4 more plain samples when the first 4 are all wrong
        rows += sample_rows(llm, proc, [(q, q['text'], None) for q in failed], a.samples, a.max_tokens, lora, 2)
    hints, hint_status = get_hints(failed) if a.hints else ({}, {})
    rows += sample_rows(llm, proc, [(q, q['text'].replace(COT_OPEN_SUFFIX, f"Hint: {hints[q['qid']]}\n" + COT_OPEN_SUFFIX),
                                     hints[q['qid']]) for q in failed if q['qid'] in hints],
                        a.samples, a.max_tokens, lora, 3)
    with open(run / f'rounds/r{a.round:03d}.jsonl', 'w') as f:
        f.writelines(json.dumps(r) + '\n' for r in rows)
    hinted = [r for r in rows if r['stage'] == 3]
    log(run, {'round': a.round, 'phase': 'rollout', 'questions': len(qs), 'failed': len(failed), 'retried': len(failed) if a.topup else 0,
              'hints': hint_status, 'hinted_acc': sum(r['correct'] for r in hinted) / max(1, len(hinted)),
              'samples': len(rows), 'stage1_acc': sum(r['correct'] for r in first) / len(first),
              'stage1_trunc': sum(r['finish'] == 'length' for r in first) / len(first),
              'stage1_mean_tokens': sum(len(r['ids']) for r in first) / len(first),
              'eos_last_token': sum(r['ids'][-1] in (151643, 151645) for r in rows if r['finish'] == 'stop'),
              'stopped': sum(r['finish'] == 'stop' for r in rows), 'sec': round(time.time() - t0)})


def screen(a):
    """v4 pool screening: base model, a.samples per item for the qids listed in a.ids; per-item counts to a.out."""
    os.environ['VLLM_BATCH_INVARIANT'] = '0'
    from transformers import AutoProcessor
    pool = {q['qid']: q for q in map(json.loads, open(a.pool))}
    qs = [fix_gold(pool[i]) for i in Path(a.ids).read_text().splitlines() if i]  # one id per line (ViRL ids can hold spaces)
    qs = [q for q in qs if q['gold'] is not None]
    m = a.screen_model  # v6: the teacher screens the pool
    proc, t0 = AutoProcessor.from_pretrained(m, revision=REV if m == MODEL else JUDGE_REVS[m], **PIXELS), time.time()
    llm = engine(a, 0, m)
    if a.adapter:  # held-out test (heldout_protocol.md): a trained adapter on the base engine, as in training rollouts
        from vllm.lora.request import LoRARequest
        lora = LoRARequest('heldout', 1, a.adapter)
    rows = sample_rows(llm, proc, [(q, q['text'], None) for q in qs], a.samples, a.max_tokens,
                       lora if a.adapter else None, logprobs=False)
    Path(a.out).with_suffix('.rows.jsonl').write_text(''.join(
        json.dumps({k: r[k] for k in ('qid', 'finish', 'correct', 'text')}) + '\n' for r in rows))
    by = {}
    for r in rows:
        by.setdefault(r['qid'], []).append(r)
    with open(a.out, 'w') as f:
        for q in qs:
            g = by.get(q['qid'], [])
            f.write(json.dumps({'qid': q['qid'], 'n': len(g), 'correct': sum(r['correct'] for r in g),
                                'trunc': sum(r['finish'] == 'length' for r in g),
                                'tokens': sum(len(r['ids']) for r in g) / max(1, len(g))}) + '\n')
    print(json.dumps({'items': len(qs), 'samples': len(rows), 'sec': round(time.time() - t0)}))


def build_pool_v4(a):
    """v4 pool: screened items with <= 1 of 2 correct + v3-seen items with <= 3 of 4 correct (regraded), shuffled."""
    pool = {q['qid']: q for q in map(json.loads, open(a.pool))}
    from_screen = [s['qid'] for s in map(json.loads, open(a.out)) if s['n'] == 2 and s['correct'] <= 1]
    from_v3 = []
    for f in sorted(Path('runs/v3/rounds').glob('r*.jsonl')):
        st = {}
        for r in map(json.loads, open(f)):
            if r['stage'] == 1 and not r.get('suspect_gold'):
                st.setdefault(r['qid'], []).append(correct(fix_gold(pool[r['qid']]), r['text'], r['finish']))
        from_v3 += [q for q, c in st.items() if len(c) == 4 and sum(c) <= 3]
    out = [q for q in (fix_gold(pool[k]) for k in dict.fromkeys(from_screen + from_v3)) if q['gold'] is not None]
    __import__('random').Random(0).shuffle(out)
    Path('data/pool_v4.jsonl').write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in out))
    print(json.dumps({'pool_v4': len(out), 'from_screen': len(from_screen), 'from_v3': len(from_v3)}))


def teacher_score(a):
    """v6: the teacher's logprob of every token of each finished student response (sampled-token reverse KL)."""
    os.environ['VLLM_BATCH_INVARIANT'] = '0'
    from PIL import Image
    from transformers import AutoProcessor
    from vllm import SamplingParams
    run, t0 = Path(a.run), time.time()
    path = run / f'rounds/r{a.round:03d}.jsonl'
    rows = [json.loads(l) for l in open(path)]
    done = [r for r in rows if r['finish'] == 'stop']
    # Engine first: vLLM forks its engine process, and a fork after the processor's torch thread pool has run
    # deadlocks the child (smoke test 11/05: hung for 7 h in a CPU torch.zeros).
    llm = engine(a, 0, TEACHER)
    proc, prompts = AutoProcessor.from_pretrained(MODEL, revision=REV, **PIXELS), []
    for r in done:  # the student's exact prompt + response tokens (same tokenizer and image processor in the family)
        with Image.open(r['image']) as im:
            img = im.convert('RGB')
        ids = proc.tokenizer(r['chat'], add_special_tokens=False)['input_ids']  # one image pad: vLLM expands it
        prompts.append({'prompt_token_ids': ids + r['ids'], 'multi_modal_data': {'image': [img]}})
    outs = llm.generate(prompts, SamplingParams(max_tokens=1, prompt_logprobs=0))
    for r, o in zip(done, outs):
        n0 = r['prompt_len']
        assert len(o.prompt_token_ids) == n0 + len(r['ids']) and list(o.prompt_token_ids[n0:]) == r['ids'], \
            'teacher saw different tokens'
        r['tlogps'] = [o.prompt_logprobs[n0 + i][t].logprob for i, t in enumerate(r['ids'])]
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    ntok = sum(len(r['ids']) for r in done)
    log(run, {'round': a.round, 'phase': 'teacher', 'scored': len(done),
              'rkl': sum(m - t for r in done for m, t in zip(r['logps'], r['tlogps'])) / max(1, ntok),
              'sec': round(time.time() - t0)})


def train(a):
    import torch
    from PIL import Image
    from peft import LoraConfig, PeftModel, get_peft_model
    from torch.utils.checkpoint import checkpoint
    from transformers import AutoModelForImageTextToText, AutoProcessor
    run, t0 = Path(a.run), time.time()
    rows = [json.loads(l) for l in open(run / f'rounds/r{a.round:03d}.jsonl')]
    by_q = {}
    for r in rows:
        by_q.setdefault(r.get('group', r['qid']), []).append(r)
    if a.drop_truncated:  # v5: overlong filtering, truncated responses neither trained on nor in the baseline
        by_q = {k: [r for r in g if r['finish'] == 'stop'] for k, g in by_q.items()}
    groups = [list(zip(g, adv)) for g in by_q.values() if (adv := group_adv([r['reward'] for r in g], a.teacher_coef))]
    steps = [groups[i:i + a.groups_per_step] for i in range(0, len(groups), a.groups_per_step)]

    torch.manual_seed(0)
    proc = AutoProcessor.from_pretrained(MODEL, revision=REV, **PIXELS)
    model = AutoModelForImageTextToText.from_pretrained(MODEL, revision=REV, dtype=torch.bfloat16).cuda()
    adapter = run / 'adapter'
    if (adapter / 'adapter_config.json').exists():
        model = PeftModel.from_pretrained(model, str(adapter), is_trainable=True)
    else:
        model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.0,
                               target_modules=LORA_TARGETS, bias='none'))
    params = [p for p in model.parameters() if p.requires_grad]
    for p in params:
        p.data = p.data.float()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    model.config.use_cache = False
    model.train()
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
    if (run / 'optim.pt').exists():
        opt.load_state_dict(torch.load(run / 'optim.pt'))
    inner = model.get_base_model()

    def chunk_logp(h, t):
        return torch.log_softmax(inner.lm_head(h).float(), -1).gather(-1, t[:, None])[:, 0]

    def logps(enc, n):
        # Hidden states, then the 152k-vocab head in 1024-token chunks: full 8k-token fp32 logits
        # (~5 GB, plus their gradient) would not fit next to the model.
        h = inner.model(**enc, use_cache=False).last_hidden_state[0, -n - 1:-1]
        t = enc['input_ids'][0, -n:]
        return torch.cat([checkpoint(chunk_logp, h[i:i + 1024], t[i:i + 1024], use_reentrant=False)
                          for i in range(0, n, 1024)])

    def encode(r):
        with Image.open(r['image']) as img:
            enc = proc(text=[r['chat']], images=[img.convert('RGB')], return_tensors='pt')
        assert enc['input_ids'].shape[1] == r['prompt_len'], 'HF and vLLM prompt tokens differ'
        tail = torch.tensor([r['ids']], dtype=enc['input_ids'].dtype)
        enc['input_ids'] = torch.cat([enc['input_ids'], tail], 1)
        enc['attention_mask'] = torch.ones_like(enc['input_ids'])
        enc['mm_token_type_ids'] = torch.cat(
            [enc['mm_token_type_ids'], torch.zeros_like(tail, dtype=enc['mm_token_type_ids'].dtype)], 1)
        return {k: v.cuda() for k, v in enc.items()}

    stats = []
    for s, step in enumerate(steps):
        items = [x for g in step for x in g]
        ntok = sum(len(r['ids']) for r, _ in items)
        acc = dict(mismatch=0.0, clipped=0.0, kl=0.0, loss=0.0, rkl=0.0)
        for r, adv in items:
            enc, n = encode(r), len(r['ids'])
            with torch.autocast('cuda', dtype=torch.bfloat16):
                lp = logps(enc, n)
                ref = None
                if a.beta:
                    with torch.no_grad(), model.disable_adapter():
                        ref = logps(enc, n)
            mu = torch.tensor(r['logps'], device='cuda')
            if a.teacher_coef and 'tlogps' in r:  # v6 per-token advantage: outcome + coef * (log teacher - log student)
                gap = torch.tensor(r['tlogps'], device='cuda') - mu
                adv = adv + a.teacher_coef * gap
                acc['rkl'] += float(-gap.sum()) / ntok
            ratio = (lp - mu).exp()
            loss = -torch.minimum(ratio * adv, ratio.clamp(1 - a.clip, 1 + a.clip) * adv).sum()
            if ref is not None:
                d = ref - lp
                kl = (d.exp() - d - 1).sum()
                loss = loss + a.beta * kl
                acc["kl"] += float(kl.detach()) / ntok
            (loss / ntok).backward()
            with torch.no_grad():
                acc['mismatch'] += float((lp - mu).abs().sum()) / ntok
                acc['clipped'] += float(((ratio - 1).abs() > a.clip).sum()) / ntok
                acc['loss'] += float(loss) / ntok
            del enc, lp, ref, ratio, loss
        gn = float(torch.nn.utils.clip_grad_norm_(params, 1.0))
        opt.step()
        opt.zero_grad(set_to_none=True)
        stats.append({**{k: round(v, 5) for k, v in acc.items()}, 'grad_norm': round(gn, 4),
                      'groups': len(step), 'samples': len(items), 'tokens': ntok})
        print('step', s, stats[-1], flush=True)

    model.save_pretrained(str(adapter))
    torch.save(opt.state_dict(), run / 'optim.pt')
    if (a.round + 1) % a.ckpt_every == 0:
        shutil.copytree(adapter, run / f'ckpt/r{a.round:03d}', dirs_exist_ok=True)
    log(run, {'round': a.round, 'phase': 'train', 'groups': len(groups), 'steps': len(steps),
              'peak_gb': round(torch.cuda.max_memory_allocated() / 2**30, 1),
              'sec': round(time.time() - t0), 'per_step': stats})


def judge(a):
    """v3 reward (v3_protocol.md): finished responses get correct + 0.5 image_ok + 0.5 reasoning_ok."""
    os.environ['VLLM_BATCH_INVARIANT'] = '0'
    run, t0 = Path(a.run), time.time()
    path = run / f'rounds/r{a.round:03d}.jsonl'
    rows = [json.loads(l) for l in open(path)]
    done = [r for r in rows if r['finish'] == 'stop']
    texts = judge_generate(a.judge_model, [(r['question'], r['reference'], r['text'], r['image']) for r in done], a.gpu_mem)
    for r, t in zip(done, texts):
        r['image_ok'], r['reasoning_ok'] = parse_judge(t)
        r['judge_text'] = t
    for r in rows:  # an unparsed verdict counts 0; a truncated response gets 0 outright
        r['reward'] = (r['correct'] + 0.5 * (r.get('image_ok') or 0.0) + 0.5 * (r.get('reasoning_ok') or 0.0)
                       if r['finish'] == 'stop' else 0.0)
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    s1 = [r for r in rows if r['stage'] == 1]
    log(run, {'round': a.round, 'phase': 'judge', 'judged': len(done),
              'unparsed': sum(r['image_ok'] is None or r['reasoning_ok'] is None for r in done),
              'stage1_judge': sum((r.get('image_ok') or 0.0) + (r.get('reasoning_ok') or 0.0) for r in s1) / len(s1),
              'image_ok': sum(r['image_ok'] or 0.0 for r in done) / max(1, len(done)),
              'reasoning_ok': sum(r['reasoning_ok'] or 0.0 for r in done) / max(1, len(done)),
              'sec': round(time.time() - t0)})


def length_ratio(run, rnd, ref):
    """Median over questions of mean finished stage-1 tokens / the teacher's screen tokens (v6 Amendment 1)."""
    by = {}
    for r in map(json.loads, open(Path(run) / f'rounds/r{rnd:03d}.jsonl')):
        if r['stage'] == 1 and r['finish'] == 'stop':
            by.setdefault(r['qid'], []).append(len(r['ids']))
    xs = sorted(sum(v) / len(v) / ref[q] for q, v in by.items())
    return (xs[(len(xs) - 1) // 2] + xs[len(xs) // 2]) / 2


def guard(a):
    """Exit 1 (stops loop.sh) on the v3_protocol.md stop rules; round 0 is the reference."""
    recs = [json.loads(l) for l in open(Path(a.run) / 'log.jsonl')]
    mean = lambda xs: sum(xs) / len(xs)
    ro, ju = [r for r in recs if r['phase'] == 'rollout'], [r for r in recs if r['phase'] == 'judge']
    tr = [r for r in recs if r['phase'] == 'train'][-1]
    acc0, acc = ro[0]['stage1_acc'], mean([r['stage1_acc'] for r in ro[-a.acc_window:]])
    kl = max((s['kl'] for s in tr['per_step']), default=0.0)
    hacking = bool(ju) and mean([r['stage1_judge'] for r in ju[-2:]]) >= ju[0]['stage1_judge'] + 0.3 and acc <= acc0
    tok0, tok = ro[0]['stage1_mean_tokens'], mean([r['stage1_mean_tokens'] for r in ro[-2:]])
    if a.length_ref:  # v6 Amendment 1: finished responses only, relative to the teacher's length on the same question
        ref = {s['qid']: s['tokens'] for s in map(json.loads, open(a.length_ref))}
        tok0, tok = length_ratio(a.run, 0, ref), mean([length_ratio(a.run, r['round'], ref) for r in ro[-2:]])
    why = [w for w, bad in [('accuracy', acc < 0.7 * acc0), ('truncation', ro[-1]['stage1_trunc'] > 0.35),
                            ('length_collapse', a.length_guard and tok < 0.6 * tok0),
                            ('kl', kl > 0.1), ('reward_hacking', hacking)] if bad]
    print('guard', {f'acc_{a.acc_window}round': round(acc, 3), 'acc_round0': acc0, 'trunc': ro[-1]['stage1_trunc'],
                    'kl_max': kl, 'len': round(tok, 3), 'len_round0': round(tok0, 3), 'stop': why})
    sys.exit(1 if why else 0)


def validation_items():
    """The 120 teacher-judged Geometry3K DEV responses (judge gate only; never trained on)."""
    V = ROOT / 'pilot_diagram/stability_v1/error_feedback_v12_20261101'
    pool = {x['id']: x for x in map(json.loads, open(ROOT / 'data/geometry_stability/review_pool.jsonl'))}
    qid = {q['q']: q['id'] for q in json.load(open(V / 'private_question_mapping.json'))}
    sol = {s['question_alias']: s for b in (1, 2, 3)
           for s in json.load(open(V / f'native_solutions_batch{b}.json'))['items']}
    lab = {r['response_alias']: r for r in json.load(open(V / 'descriptive_error_stage_results.json'))['reviewed_responses']}
    resp = sorted((json.load(open(f)) for f in V.glob('response_inputs/batch*/R*.json')),
                  key=lambda r: (r['question_alias'], r['response_alias']))
    assert len(resp) == 120 and all(r['response_alias'] in lab for r in resp)
    ref = lambda s: ('Key visual facts:\n' + '\n'.join('- ' + f for f in s['image_facts'])
                     + f"\nWorked solution: {s['worked_solution']}\nFinal answer: {s['answer_letter']} ({s['answer_value']})")
    return [{'alias': r['response_alias'], 'qa': r['question_alias'], 'question': pool[qid[r['question_alias']]]['question'],
             'reference': ref(sol[r['question_alias']]), 'response': r['response'],
             'image': pool[qid[r['question_alias']]]['image_path'],
             'image_teacher': lab[r['response_alias']]['stage_status'].get('image_facts'),
             'valid_teacher': lab[r['response_alias']]['final_proof_valid']} for r in resp]


def gate_metrics(rows):
    """v3_protocol.md gate on rows with image_judge/reasoning_judge (0/1/None) and the teacher labels."""
    im = [x for x in rows if x['image_teacher'] in ('pass', 'fail')]
    rv = [x for x in rows if x['valid_teacher'] is not None]
    bad = [x for x in rv if x['valid_teacher'] is False]
    m = {'image_agreement': sum(x['image_judge'] is not None and (x['image_judge'] == 1) == (x['image_teacher'] == 'pass')
                                for x in im) / len(im),
         'reasoning_agreement': sum(x['reasoning_judge'] is not None and (x['reasoning_judge'] == 1) == x['valid_teacher']
                                    for x in rv) / len(rv),
         'false_pass': sum(x['reasoning_judge'] == 1 for x in bad) / len(bad),
         'unparsed': sum(x['image_judge'] is None or x['reasoning_judge'] is None for x in rows),
         'n_image': len(im), 'n_reasoning': len(rv), 'n_teacher_invalid': len(bad)}
    m['passed'] = m['image_agreement'] >= 0.8 and m['reasoning_agreement'] >= 0.8 and m['false_pass'] <= 0.1
    # Amendment 3 (post hoc, user-approved): no teacher-invalid response may get full process credit
    m['full_credit_false_pass'] = sum(x['image_judge'] == 1 and x['reasoning_judge'] == 1 for x in bad)
    m['passed_amendment3'] = (m['image_agreement'] >= 0.8 and m['reasoning_agreement'] >= 0.8
                              and m['full_credit_false_pass'] == 0)
    return m


def validate_judge(a):
    """Gate for a local vLLM judge (v3_protocol.md)."""
    os.environ['VLLM_BATCH_INVARIANT'] = '0'
    items = validation_items()
    rows = []
    for x, t in zip(items, judge_generate(a.judge_model, [(x['question'], x['reference'], x['response'], x['image'])
                                                          for x in items], a.gpu_mem)):
        img, rea = parse_judge(t)
        rows.append({**{k: x[k] for k in ('alias', 'image_teacher', 'valid_teacher')},
                     'image_judge': img, 'reasoning_judge': rea, 'judge_text': t})
    m = gate_metrics(rows)
    out = Path(__file__).resolve().parent / f"judge_validation_{a.judge_model.split('/')[-1]}.json"
    out.write_text(json.dumps({'judge_model': a.judge_model, 'metrics': m, 'rows': rows}, indent=1))
    print(json.dumps(m))


def write_packets(groups, out, per_agent=4):
    """groups = [(question, reference, image, [(id, response text)])] -> packet_NN.md (4 questions each) + manifest."""
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for k in range(0, len(groups), per_agent):
        chunk, lines, ids = groups[k:k + per_agent], [], []
        for j, (q, ref, img, resps) in enumerate(chunk, 1):
            lines += [f'# Question {j} of {len(chunk)}', f'Image: {img}', '', '## Problem', q, '',
                      '## Reference solution (correct)', ref, '']
            for rid, text in resps:
                lines += [f'### Response {rid}', text, '']
                ids.append(rid)
        name = f'packet_{k // per_agent:02d}.md'
        (out / name).write_text('\n'.join(lines))
        manifest.append({'packet': str(out / name), 'verdict': str(out / name.replace('packet', 'verdict').replace('.md', '.json')),
                         'ids': ids})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    print(len(manifest), 'packets in', out)


def read_verdicts(out):
    """id -> (image_ok, reasoning_ok) from the orchestrator-written verdict_NN.json files; missing ids absent."""
    v = {}
    for p in json.load(open(out / 'manifest.json')):
        txt = Path(p['verdict']).read_text() if Path(p['verdict']).exists() else '[]'
        arr = json.loads(txt[txt.find('['):txt.rfind(']') + 1] or '[]')
        for x in arr:
            img, rea = str(x.get('image', '')).upper(), str(x.get('reasoning', '')).upper()
            v[str(x.get('id'))] = ({'CORRECT': 1.0, 'INCORRECT': 0.0}.get(img), {'VALID': 1.0, 'INVALID': 0.0}.get(rea))
    return v


def judge_packets(a):
    """Subagent judge (Amendment 1): packets for the finished responses of a round, or for the gate set."""
    if a.validation:
        by = {}
        for x in validation_items():
            by.setdefault(x['qa'], []).append(x)
        groups = [(g[0]['question'], g[0]['reference'], g[0]['image'], [(x['alias'], x['response']) for x in g])
                  for g in by.values()]
        return write_packets(groups, Path(__file__).resolve().parent / f'judge_validation_{a.judge_name}')
    rows = [json.loads(l) for l in open(Path(a.run) / f'rounds/r{a.round:03d}.jsonl')]
    by = {}
    for i, r in enumerate(rows):
        if r['finish'] == 'stop':
            by.setdefault(r.get('group', r['qid']), []).append((f'r{i}', r))
    show = lambda r: r['question'] + (f"\n(Hint given to the student: {r['hint']})" if r.get('hint') else '')
    groups = [(show(g[0][1]), g[0][1]['reference'], g[0][1]['image'], [(rid, r['text']) for rid, r in g])
              for g in by.values()]
    write_packets(groups, Path(a.run) / f'judge/r{a.round:03d}')


def judge_apply(a):
    """Subagent verdicts -> reward = correct + 0.5 image_ok + 0.5 reasoning_ok (unparsed = 0, truncated = 0)."""
    run = Path(a.run)
    path, v = run / f'rounds/r{a.round:03d}.jsonl', read_verdicts(run / f'judge/r{a.round:03d}')
    rows = [json.loads(l) for l in open(path)]
    for i, r in enumerate(rows):
        r['correct'] = correct(r, r['text'], r['finish'])  # regrade with the current rules
        img, rea = v.get(f'r{i}', (None, None)) if r['finish'] == 'stop' else (None, None)
        r['image_ok'], r['reasoning_ok'] = img, rea
        r['judge_text'] = 'cli' if (run / f'judge/r{a.round:03d}/run_log.json').exists() else 'subagent'
        if r['finish'] != 'stop':
            r['reward'] = 0.0
        elif a.reward == 'v5':  # no image credit: a wrong finished answer earns nothing
            r['reward'] = r['correct'] * (1 + 0.5 * (rea or 0.0))
        elif a.reward == 'v4':  # reasoning credit only for correct answers; image credit fades out over 30 rounds
            r['reward'] = r['correct'] * (1 + 0.5 * (rea or 0.0)) + 0.25 * max(0.0, 1 - a.round / 30) * (img or 0.0)
        else:
            r['reward'] = r['correct'] + 0.5 * (img or 0.0) + 0.5 * (rea or 0.0)
    by = {}
    for r in rows:
        by.setdefault(r.get('group', r['qid']), []).append(r)
    suspect = [q for q, g in by.items() if (f := [r for r in g if r['finish'] == 'stop'])
               and sum(not r['correct'] and r['image_ok'] == 1 and r['reasoning_ok'] == 1 for r in f) >= 0.5 * len(f)]
    for q in suspect:  # suspect gold (Amendment 6): equal rewards -> no gradient for this group
        for r in by[q]:
            r['reward'], r['suspect_gold'] = 0.0, True
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    done, s1 = [r for r in rows if r['finish'] == 'stop'], [r for r in rows if r['stage'] == 1]
    log(run, {'round': a.round, 'phase': 'judge', 'judge': rows[0]['judge_text'], 'judged': len(done), 'suspect_gold': suspect,
              'unparsed': sum(r['image_ok'] is None or r['reasoning_ok'] is None for r in done),
              'stage1_judge': sum((r['image_ok'] or 0.0) + (r['reasoning_ok'] or 0.0) for r in s1) / len(s1),
              'image_ok': sum(r['image_ok'] or 0.0 for r in done) / max(1, len(done)),
              'reasoning_ok': sum(r['reasoning_ok'] or 0.0 for r in done) / max(1, len(done))})


CLI_SYSTEM = ('You grade student solutions for a research experiment. Follow the task instructions in the prompt exactly. '
              'Use only the Read tool. Do not create or modify any file. Your final message must be only what the prompt asks for.')


def judge_run(a):
    """Amendment 4b: one headless Claude Code session per packet (Sonnet 5.5, effort low, Read only, no MCP)."""
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    here = Path(__file__).resolve().parent
    out = here / f'judge_validation_{a.judge_name}' if a.validation else Path(a.run).resolve() / f'judge/r{a.round:03d}'
    instr, man, t0 = (here / 'judge_instructions.md').read_text(), json.load(open(out / 'manifest.json')), time.time()

    def call(p):
        if Path(p['verdict']).exists():
            return {'packet': p['packet'], 'skipped': True}
        cmd = ['claude', '-p', '--model', 'sonnet', '--effort', 'low', '--tools', 'Read', '--allowedTools', 'Read',
               '--strict-mcp-config', '--system-prompt', CLI_SYSTEM,
               '--add-dir', '/tmp/geometry3k_audit', '/home/leesg17/data', str(out),
               '--no-session-persistence', '--output-format', 'json', instr.replace('PACKET_PATH', p['packet'])]
        for attempt in (1, 2):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, cwd=out)
            try:
                d = json.loads(r.stdout)
                txt = d.get('result', '')
                arr = json.loads(txt[txt.find('['):txt.rfind(']') + 1])
                if [str(x.get('id')) for x in arr] == p['ids']:
                    Path(p['verdict']).write_text(json.dumps(arr, indent=1))
                    return {'packet': p['packet'], 'attempt': attempt, 'cost_usd': d.get('total_cost_usd'),
                            'sec': round(d.get('duration_ms', 0) / 1000)}
            except (ValueError, AttributeError):
                pass
        return {'packet': p['packet'], 'failed': True, 'stderr': r.stderr[-300:]}

    with ThreadPoolExecutor(a.judge_workers) as ex:
        res = list(ex.map(call, man))
    (out / 'run_log.json').write_text(json.dumps({'sec': round(time.time() - t0), 'calls': res}, indent=1))
    print(json.dumps({'packets': len(man), 'failed': sum('failed' in r for r in res), 'sec': round(time.time() - t0),
                      'cost_usd': round(sum(r.get('cost_usd') or 0 for r in res), 2)}))


def judge_score(a):
    """Gate metrics for the subagent judge on the 120 (verdicts written by the orchestrator)."""
    out = Path(__file__).resolve().parent / f'judge_validation_{a.judge_name}'
    v = read_verdicts(out)
    rows = [{**{k: x[k] for k in ('alias', 'image_teacher', 'valid_teacher')},
             'image_judge': v.get(x['alias'], (None, None))[0], 'reasoning_judge': v.get(x['alias'], (None, None))[1]}
            for x in validation_items()]
    m = gate_metrics(rows)
    (out / 'result.json').write_text(json.dumps({'judge': f'{a.judge_name} subagent, 4 questions/agent', 'metrics': m,
                                                 'rows': rows}, indent=1))
    print(json.dumps(m))


def merge(a):
    """LoRA folded into the base weights -> plain checkpoint: the submission form, and what the frozen
    run_eval.py / analyze.py compare accept without LoRA flags."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForImageTextToText, AutoProcessor
    base = AutoModelForImageTextToText.from_pretrained(MODEL, revision=REV, dtype=torch.bfloat16)
    PeftModel.from_pretrained(base, a.adapter).merge_and_unload().save_pretrained(a.out)
    AutoProcessor.from_pretrained(MODEL, revision=REV).save_pretrained(a.out)


def selfcheck():
    assert advantages([1, 1, 1, 1]) is None and advantages([0.0] * 8) is None
    adv = advantages([1, 0, 0, 0])
    assert group_adv([1, 1]) is None and group_adv([1]) is None and group_adv([], True) is None
    assert group_adv([1, 1], True) == [0.0, 0.0] and group_adv([0], True) == [0.0] and group_adv([1, 0], True)[0] > 0
    assert adv[0] > 0 > adv[1] and abs(sum(adv)) < 1e-9
    mc, num = {'gold': 'B'}, {'kind': 'num', 'gold': 2500.0}
    assert correct(mc, 'x\nAnswer: B', 'stop') == 1 and correct(mc, 'x\nAnswer: B', 'length') == 0
    assert correct(mc, 'Answer: B ... Answer: (C)', 'stop') == 0 and correct(mc, 'no tag', 'stop') == 0
    assert correct(num, 'Answer: 2.5 \\times 10^{3} N', 'stop') == 1 and correct(num, 'Answer: 2,510 N', 'stop') == 1
    assert correct(num, 'Answer: 2600', 'stop') == 0 and correct(num, 'Answer: 2500', 'length') == 0
    assert correct({'kind': 'num', 'gold': 0.0}, 'Answer: zero', 'stop') == 1
    assert correct({'kind': 'num', 'gold': 31.4}, 'Answer: 31384 VAR', 'stop') == 1
    assert correct({'kind': 'num', 'gold': 110.0}, 'Answer: 70', 'stop') == 0
    for txt, g, gs in [('50√3', 86.6, '86.6 meters'), ('45π', 141.37, '141.37 cubic inches'), ('250/3', 83.33, '83.33 s'),
                       ('\\frac{3\\pi}{5}', 1.885, ''), ("71°46'", 71.77, '71.77°'), ('2.24', 2.2, '2.2%'),
                       ('0.32', 0.316, '0.316 m'), ('68.25\\pi', 214.5, '214.5 cm²'), ('√10 / 10', 0.316, '0.316')]:
        assert correct({'kind': 'num', 'gold': g, 'gold_str': gs}, 'Answer: ' + txt, 'stop') == 1, txt
    for txt, g, gs in [('12.6', 12.0, '12'), ('10√2', 12.0, '12 m/s'), ('2.3', 2.2, '2.2'), ('2**99999', 1.0, '')]:
        assert correct({'kind': 'num', 'gold': g, 'gold_str': gs}, 'Answer: ' + txt, 'stop') == 0, txt
    assert fix_gold({'kind': 'num', 'gold': 45.0, 'gold_str': '45π'})['gold'] == 45 * math.pi
    assert gold_number('540 m²') == 540 and gold_number('-29.47 m/s') == -29.47
    assert gold_number('5,250,000 VND') == 5250000 and gold_number('1.6 \\times 10^{-19} C') == 1.6e-19
    assert gold_number('b = 5/2') is None and gold_number('Hindi') is None
    assert parse_judge('ok\nIMAGE: CORRECT\nREASONING: INVALID') == (1.0, 0.0)
    assert parse_judge('IMAGE: INCORRECT\nREASONING: VALID') == (0.0, 1.0) and parse_judge('none') == (None, None)
    print('selfcheck ok')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['rollout', 'screen', 'teacher-score', 'build-pool-v4', 'judge', 'judge-packets', 'judge-run', 'judge-apply', 'judge-score', 'train', 'guard', 'validate-judge', 'merge', 'selfcheck'])
    ap.add_argument('--run', default='runs/v1')
    ap.add_argument('--round', type=int, default=0)
    ap.add_argument('--pool', default=str(Path(__file__).resolve().parent / 'data/pool.jsonl'))
    ap.add_argument('--questions', type=int, default=64)
    ap.add_argument('--pool-offset', type=int, default=0)  # v4: round 0 used 32 questions, later rounds 16
    ap.add_argument('--max-tokens', type=int, default=8192)
    ap.add_argument('--groups-per-step', type=int, default=8)
    ap.add_argument('--lr', type=float, default=1e-5)
    ap.add_argument('--beta', type=float, default=0.04)
    ap.add_argument('--clip', type=float, default=0.2)
    ap.add_argument('--ckpt-every', type=int, default=5)
    ap.add_argument('--judge-model', default=MODEL)
    ap.add_argument('--gpu-mem', type=float, default=0.85)  # 0.90 OOMed (display ~1 GB); lower if other GPU jobs run
    ap.add_argument('--adapter', default='')
    ap.add_argument('--out', default='')
    ap.add_argument('--validation', action='store_true')
    ap.add_argument('--judge-name', default='haiku')  # subagent judge label for the gate directories
    ap.add_argument('--judge-workers', type=int, default=8)
    ap.add_argument('--samples', type=int, default=4)  # per question (v4: 8)
    ap.add_argument('--no-topup', dest='topup', action='store_false')  # v4: no plain top-up
    ap.add_argument('--hints', action='store_true')  # v4: Sonnet hints for 0-correct questions
    ap.add_argument('--reward', default='v3', choices=['v3', 'v4', 'v5'])
    ap.add_argument('--drop-truncated', action='store_true')  # v5 overlong filtering
    ap.add_argument('--length-guard', action='store_true')  # v5 stop rule: 2-round mean length < 0.6 x round 0
    ap.add_argument('--ids', default='')
    ap.add_argument('--screen-model', default=MODEL)
    ap.add_argument('--teacher-coef', type=float, default=0.0)  # v6: 1.0
    ap.add_argument('--length-ref', default='')  # v6 Amendment 1: teacher screen file for the length guard
    ap.add_argument('--acc-window', type=int, default=2)  # v6: 4 (v5 stopped on a 2-round mean by < 1 response)
    a = ap.parse_args()
    {'rollout': rollout, 'screen': screen, 'teacher-score': teacher_score, 'build-pool-v4': build_pool_v4, 'judge': judge, 'judge-packets': judge_packets, 'judge-run': judge_run, 'judge-apply': judge_apply,
     'judge-score': judge_score, 'train': train, 'guard': guard, 'validate-judge': validate_judge,
     'merge': merge, 'selfcheck': lambda _: selfcheck()}[a.cmd](a)
