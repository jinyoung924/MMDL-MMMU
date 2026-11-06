"""Shared, fail-closed pilot loader and the existing evaluation instruction."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_eval import COT_MC_SUFFIX, MODEL_REV

MODEL = 'Qwen/Qwen3-VL-4B-Instruct'
PIXELS = dict(min_pixels=4*32*32, max_pixels=1280*32*32)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_pilot(directory, split):
    directory = Path(directory).resolve()
    require(split in ('train', 'diagnostic'), 'Unsupported split')
    lock = json.loads((directory/'dataset_lock.json').read_text())
    require(sha(directory/'annotations.json') == lock['annotation_sha256'], 'Annotations changed after dataset preparation')
    loaded = {}
    for kind in ('train', 'diagnostic'):
        path = directory/f'{kind}.jsonl'
        require(sha(path) == lock['files'][path.name], f'Manifest changed: {kind}')
        loaded[kind] = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        require(len(loaded[kind]) == lock['counts'][kind], 'Count mismatch')
        for row in loaded[kind]:
            require(row['source_split'] == 'train' and row['source_path'] == 'trainset/bmmr-train-80k.jsonl', 'Original evaluation data forbidden')
            require(row['source_sha256'] == lock['source_sha256'] and row['source_revision'] == lock['source_revision'], 'Source identity mismatch')
            require(row['split'] == kind and row['ready_for_training'] == (kind=='train'), 'Split/approval mismatch')
            image = (directory/row['image']).resolve()
            require(image.is_relative_to(directory/'images'), 'Image outside pilot image directory')
            require(sha(image) == row['image_sha256'], 'Image checksum mismatch')
            for key in ('teacher_response', 'answer_only_response'):
                require(row[key].endswith('Answer: '+row['answer']), 'Label/target mismatch')
    for key in ('id','image_pixels_sha256','group'):
        require(not ({r[key] for r in loaded['train']} & {r[key] for r in loaded['diagnostic']}), f'Train/diagnostic overlap: {key}')
    return loaded[split], lock


def prompt(proc, row):
    return proc.apply_chat_template([{'role':'user','content':[
        {'type':'image'}, {'type':'text','text':row['question']+'\n'+COT_MC_SUFFIX}]}],
        add_generation_prompt=True, tokenize=False)
