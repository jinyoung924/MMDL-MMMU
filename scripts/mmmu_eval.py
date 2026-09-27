#!/usr/bin/env python3
"""MMMU-val 평가 파이프라인 — Qwen3-VL-4B-Instruct

colab/mmmu_eval_v5.ipynb 로 실행해 58.44점을 얻은 파이프라인을 명령행 스크립트로 옮긴 것이다.
프롬프트 구성, 이미지 처리, 생성 설정, 채점 로직은 노트북 셀 원문을 그대로 가져왔다.
(이미지 면적 상한을 명령행 인자로 받기 위해 cap_image_pixels 기본 인자 처리 2줄만 다르며, 기본값에서 동작은 같다.)

모드
  기본          추론 → 채점 → 집계 (GPU 필요)
  --grade_only  기존 raw_generations.jsonl 을 다시 채점 (GPU 불필요, 원본 파일은 덮어쓰지 않음)
  --verify_prompts_against PATH
                데이터셋만 읽어 900문항 프롬프트를 만들고 PATH(예: v5 raw_generations.jsonl)에
                기록된 프롬프트와 문항 단위로 대조 (GPU 불필요)

예
  bash scripts/run_mmmu_eval.sh --model_path Qwen/Qwen3-VL-4B-Instruct --data_root ./data/hf_datasets
  bash scripts/run_mmmu_eval.sh --model_path /path/to/finetuned_ckpt --data_root ./data/hf_datasets --run_tag ft_v1
"""
import argparse
import ast
import base64
import csv
import io
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from PIL import Image

# =============================================================================
# 1. 고정 스펙 (과제 가이드 1.1, 1.2)
# =============================================================================
DEFAULT_MODEL_PATH = "Qwen/Qwen3-VL-4B-Instruct"
DEFAULT_MODEL_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
DATASET_REPO = "MMMU/MMMU"
DEFAULT_DATASET_REVISION = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"
DATASET_SPLIT = "validation"

MMMU_SUBJECTS = [
    "Accounting", "Agriculture", "Architecture_and_Engineering", "Art", "Art_Theory",
    "Basic_Medical_Science", "Biology", "Chemistry", "Clinical_Medicine", "Computer_Science",
    "Design", "Diagnostics_and_Laboratory_Medicine", "Economics", "Electronics",
    "Energy_and_Power", "Finance", "Geography", "History", "Literature", "Manage",
    "Marketing", "Materials", "Math", "Mechanical_Engineering", "Music", "Pharmacy",
    "Physics", "Psychology", "Public_Health", "Sociology",
]
assert len(MMMU_SUBJECTS) == 30

# Qwen3-VL 공식 "Evaluation Reproduction" recipe (Instruct 모델) — 임의 변경 금지
# 출처: https://github.com/QwenLM/Qwen3-VL README.md "Evaluation Reproduction"
#       https://github.com/QwenLM/Qwen3-VL/blob/main/evaluation/mmmu/README.md
OFFICIAL_SAMPLING = dict(
    temperature=0.7,
    top_p=0.8,
    top_k=20,
    repetition_penalty=1.0,
    presence_penalty=1.5,
    seed=3407,
)
OFFICIAL_MAX_TOKENS = 32768  # 공식 out_seq_length (기록용)

MAX_IMAGES_PER_QUESTION = 7  # MMMU 스키마: image_1 ~ image_7

# 아래 두 값은 명령행 인자로 덮어쓴다. 이름을 노트북과 같게 두어 함수 본문을 원문 그대로 유지한다.
IMAGE_MAX_PIXELS = 1_048_576
IMAGE_CONTENT_MODE = "image_pil"

SOURCES = {
    "sampling_recipe": "https://github.com/QwenLM/Qwen3-VL (README.md, 'Evaluation Reproduction', Instruct models)",
    "prompt_and_scoring": "https://github.com/MMMU-Benchmark/MMMU (mmmu/configs/llava1.5.yaml, "
                          "mmmu/utils/data_utils.py, mmmu/utils/eval_utils.py)",
}

# =============================================================================
# 2. 프롬프트 구성 + 채점 — 노트북 '8. MMMU 공식 프롬프트 템플릿 / 파싱 / 채점 로직' 셀 원문
#    (random.seed(42) 는 채점 직전에 호출한다: grade() 참고)
# =============================================================================
TASK_INSTRUCTIONS = ""
MULTI_CHOICE_EXAMPLE_FORMAT = "{}\n\n{}\n\nAnswer with the option's letter from the given choices directly."
SHORT_ANS_EXAMPLE_FORMAT = "{}\n\nAnswer the question using a single word or phrase."


def parse_gold_answer(sample):
    """open 문항의 gold answer가 리스트 형태 문자열인 경우 복원 (이 노트북 추가분)."""
    ans = sample["answer"]
    if sample["question_type"] == "multiple-choice":
        return ans
    try:
        parsed = ast.literal_eval(ans)
        return parsed if isinstance(parsed, list) else ans
    except (ValueError, SyntaxError):
        return ans


def construct_prompt(sample):
    """MMMU 공식 data_utils.py::construct_prompt 이식."""
    question = sample["question"]
    options = ast.literal_eval(sample["options"]) if isinstance(sample["options"], str) else sample["options"]
    res = {}
    if sample["question_type"] == "multiple-choice":
        start_chr = "A"
        example = ""
        prediction_range = []
        index2ans = {}
        for option in options:
            prediction_range.append(start_chr)
            example += f"({start_chr}) {option}\n"
            index2ans[start_chr] = option
            start_chr = chr(ord(start_chr) + 1)
        empty_prompt = MULTI_CHOICE_EXAMPLE_FORMAT.format(question, example)
        res["index2ans"] = index2ans
        res["all_choices"] = prediction_range
        res["correct_choice"] = sample["answer"]
        res["gt_content"] = options[ord(sample["answer"].upper()) - ord("A")]
    else:
        empty_prompt = SHORT_ANS_EXAMPLE_FORMAT.format(question)
        res["gt_content"] = parse_gold_answer(sample)

    res["final_input_prompt"] = (
        TASK_INSTRUCTIONS.strip() + "\n\n" + empty_prompt if TASK_INSTRUCTIONS else empty_prompt
    )
    return res


# ----------------------- 아래부터 eval_utils.py 원본 이식 -----------------------

def parse_multi_choice_response(response, all_choices, index2ans):
    for char in [",", ".", "!", "?", ";", ":", "'"]:
        response = response.strip(char)
    response = " " + response + " "

    index_ans = True
    ans_with_brack = False
    candidates = []
    for choice in all_choices:
        if f"({choice})" in response:
            candidates.append(choice)
            ans_with_brack = True

    if len(candidates) == 0:
        for choice in all_choices:
            if f" {choice} " in response:
                candidates.append(choice)

    if len(candidates) == 0 and len(response.split()) > 5:
        for index, ans in index2ans.items():
            if ans.lower() in response.lower():
                candidates.append(index)
                index_ans = False

    if len(candidates) == 0:
        pred_index = random.choice(all_choices)
    elif len(candidates) > 1:
        start_indexes = []
        if index_ans:
            if ans_with_brack:
                for can in candidates:
                    start_indexes.append(response.rfind(f"({can})"))
            else:
                for can in candidates:
                    start_indexes.append(response.rfind(f" {can} "))
        else:
            for can in candidates:
                start_indexes.append(response.lower().rfind(index2ans[can].lower()))
        pred_index = candidates[int(np.argmax(start_indexes))]
    else:
        pred_index = candidates[0]

    return pred_index


def check_is_number(string):
    try:
        float(string.replace(",", ""))
        return True
    except ValueError:
        return False


def normalize_str(string):
    string = string.strip()
    if check_is_number(string):
        string = string.replace(",", "")
        string = float(string)
        string = round(string, 2)
        return [string]
    else:
        string = string.lower()
        if len(string) == 1:
            return [" " + string, string + " "]
        return [string]


def extract_numbers(string):
    pattern_commas = r"-?\b\d{1,3}(?:,\d{3})+\b"
    pattern_scientific = r"-?\d+(?:\.\d+)?[eE][+-]?\d+"
    pattern_simple = r"-?(?:\d+\.\d+|\.\d+|\d+\b)(?![eE][+-]?\d+)(?![,\d])"
    return (re.findall(pattern_commas, string)
            + re.findall(pattern_scientific, string)
            + re.findall(pattern_simple, string))


def parse_open_response(response):
    def get_key_subresponses(response):
        key_responses = []
        response = response.strip().strip(".").lower()
        sub_responses = re.split(r"\.\s(?=[A-Z])|\n", response)
        indicators_of_keys = ["could be ", "so ", "is ",
                              "thus ", "therefore ", "final ", "answer ", "result "]
        for index, resp in enumerate(sub_responses):
            local_indicators = indicators_of_keys + ["="] if index == len(sub_responses) - 1 else indicators_of_keys
            shortest_key_response = None
            for indicator in local_indicators:
                if indicator in resp:
                    cand = resp.split(indicator)[-1].strip()
                    if not shortest_key_response or len(cand) < len(shortest_key_response):
                        shortest_key_response = cand
            if shortest_key_response and shortest_key_response.strip() not in [":", ",", ".", "!", "?", ";", ":", "'"]:
                key_responses.append(shortest_key_response)
        if len(key_responses) == 0:
            return [response]
        return key_responses

    key_responses = get_key_subresponses(response)
    pred_list = key_responses.copy()
    for resp in key_responses:
        pred_list.extend(extract_numbers(resp))

    tmp_pred_list = []
    for p in pred_list:
        tmp_pred_list.extend(normalize_str(p))
    return list(set(tmp_pred_list))


def eval_multi_choice(gold_i, pred_i):
    if isinstance(gold_i, list):
        return any(answer == pred_i for answer in gold_i)
    return gold_i == pred_i


def eval_open(gold_i, pred_i):
    if isinstance(gold_i, list):
        norm_answers = []
        for answer in gold_i:
            norm_answers.extend(normalize_str(str(answer)))
    else:
        norm_answers = normalize_str(str(gold_i))
    correct = False
    for pred in pred_i:
        if isinstance(pred, str):
            for norm_ans in norm_answers:
                if isinstance(norm_ans, str) and norm_ans in pred:
                    correct = True
                    break
        else:
            if pred in norm_answers:
                correct = True
        if correct:
            break
    return correct

# =============================================================================
# 3. 이미지 처리 + chat content — 노트북 '9. 이미지 처리 및 vLLM chat content 구성' 셀 원문
#    차이 2줄: cap_image_pixels 의 기본 인자를 호출 시점에 IMAGE_MAX_PIXELS 로 해석
# =============================================================================
resize_counter = {"resized": 0, "total": 0}


def cap_image_pixels(img, max_pixels=None):
    """면적이 상한을 넘는 이미지만 종횡비 유지 축소."""
    if max_pixels is None:  # [스크립트 차이] 호출 시점의 IMAGE_MAX_PIXELS 사용 (명령행 인자 반영)
        max_pixels = IMAGE_MAX_PIXELS
    resize_counter["total"] += 1
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    area = w * h
    if area <= max_pixels:
        return img
    scale = math.sqrt(max_pixels / area)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resize_counter["resized"] += 1
    return img.resize((new_w, new_h), Image.LANCZOS)


def _image_content(img):
    if IMAGE_CONTENT_MODE == "image_pil":
        return {"type": "image_pil", "image_pil": img}
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


IMAGE_TAG_RE = re.compile(r"<image\s*(\d+)>")


def build_chat_content(sample, prompt_info):
    text = prompt_info["final_input_prompt"]
    content = []
    last_end = 0
    used_any_image = False

    for m in IMAGE_TAG_RE.finditer(text):
        if m.start() > last_end:
            seg = text[last_end:m.start()]
            if seg.strip():
                content.append({"type": "text", "text": seg})
        img = sample.get(f"image_{int(m.group(1))}")
        if img is not None:
            content.append(_image_content(cap_image_pixels(img)))
            used_any_image = True
        last_end = m.end()

    tail = text[last_end:]
    if tail.strip():
        content.append({"type": "text", "text": tail})

    # <image N> 태그가 없는데 이미지 필드가 존재하는 예외 케이스 방어
    if not used_any_image:
        for i in range(1, MAX_IMAGES_PER_QUESTION + 1):
            img = sample.get(f"image_{i}")
            if img is not None:
                content.append(_image_content(cap_image_pixels(img)))

    return content


def build_conversation(subject_datasets, subject, row_idx):
    """노트북 build_conversation 과 동일. 데이터셋 딕셔너리를 인자로 받는 점만 다르다."""
    sample = subject_datasets[subject][row_idx]
    prompt_info = construct_prompt(sample)
    content = build_chat_content(sample, prompt_info)
    conv = [{"role": "user", "content": content}]
    meta = {
        "id": sample["id"],
        "subject": subject,
        "question_type": sample["question_type"],
        "prompt_info": prompt_info,
    }
    return conv, meta


# =============================================================================
# 4. GPU 메모리 측정
#    vLLM 엔진은 별도 프로세스에서 돌기 때문에 torch.cuda.max_memory_allocated 로는 잡히지 않는다.
#    드라이버 수준(NVML, 없으면 nvidia-smi)에서 GPU 전체 사용량을 주기적으로 읽어 최댓값을 기록한다.
# =============================================================================
class GpuMemMonitor:
    def __init__(self, interval_sec=1.0):
        self.interval = interval_sec
        self.peak_mib = None
        self.total_mib = None
        self.samples = 0
        self.method = None
        self._stop = threading.Event()
        self._thread = None
        vis = os.environ.get("CUDA_VISIBLE_DEVICES", "0").split(",")[0].strip()
        self.index = int(vis) if vis.isdigit() else 0
        self._nvml = None
        try:
            import pynvml  # nvidia-ml-py (선택)
            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(self.index)
            self.method = "nvml"
        except Exception:
            self.method = "nvidia-smi"

    def _read(self):
        if self._nvml is not None:
            info = self._nvml.nvmlDeviceGetMemoryInfo(self._handle)
            return info.used / 2**20, info.total / 2**20
        out = subprocess.run(
            ["nvidia-smi", f"--id={self.index}", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip().splitlines()[0]
        used, total = (float(x) for x in out.split(","))
        return used, total

    def _loop(self):
        while not self._stop.is_set():
            try:
                used, total = self._read()
                self.total_mib = total
                self.peak_mib = used if self.peak_mib is None else max(self.peak_mib, used)
                self.samples += 1
            except Exception:
                pass
            self._stop.wait(self.interval)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=15)
        return self.report()

    def report(self):
        return {
            "peak_used_mib": None if self.peak_mib is None else round(self.peak_mib, 1),
            "peak_used_gib": None if self.peak_mib is None else round(self.peak_mib / 1024, 2),
            "total_mib": self.total_mib,
            "method": self.method,
            "samples": self.samples,
            "gpu_index": self.index,
            "note": "GPU 전체 사용량(드라이버 기준)의 최댓값. vLLM은 gpu_memory_utilization 비율만큼 미리 확보한다.",
        }


# =============================================================================
# 5. 단계별 함수
# =============================================================================
def load_mmmu(data_root, dataset_revision, limit_per_subject=None):
    """30개 config를 각각 로드한다 (노트북 '7. 데이터셋 로드' 셀과 동일, cache_dir 인자만 추가)."""
    from datasets import load_dataset

    subject_datasets = {}
    flat_index = []  # (subject, row_idx, example_id)
    for subject in MMMU_SUBJECTS:
        ds = load_dataset(
            DATASET_REPO,
            subject,
            split=DATASET_SPLIT,
            revision=dataset_revision,
            cache_dir=data_root,
        )
        subject_datasets[subject] = ds
        ids = ds["id"]  # id 컬럼만 읽으므로 이미지 디코딩 없음
        if limit_per_subject:
            ids = ids[:limit_per_subject]
        for row_idx, ex_id in enumerate(ids):
            flat_index.append((subject, row_idx, ex_id))
        print(f"{subject:40s} n={len(ds)}")

    print(f"\ntotal: {len(flat_index)}")
    if not limit_per_subject:
        assert len(flat_index) == 900, (
            f"기대한 900문항이 아니라 {len(flat_index)}문항이 로드되었습니다. "
            f"필터링/서브샘플링 없이 원본 그대로인지 확인하세요."
        )
    assert len(set(i[2] for i in flat_index)) == len(flat_index), "문항 id에 중복이 있습니다."
    return subject_datasets, flat_index


def check_or_write_run_config(config_path, run_config):
    """설정이 다른 결과가 한 디렉터리에 섞이지 않도록 막는다 (노트북과 같은 키)."""
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            prev = json.load(f)
        if prev != run_config:
            msg = [
                "[중단] 이 디렉터리에 다른 설정으로 만든 결과가 있습니다.",
                f"  경로: {os.path.dirname(config_path)}",
                f"  기존: {prev}",
                f"  현재: {run_config}",
                "-> --run_tag 를 바꾸거나 해당 디렉터리를 비우고 다시 실행하세요.",
            ]
            raise SystemExit("\n".join(msg))
        print("기존 실행과 설정 일치 -> 이어서 실행")
    else:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(run_config, f, ensure_ascii=False, indent=2)
        print("새 실행 디렉터리 생성")


def build_llm(args, sampling_recipe):
    from vllm import LLM, SamplingParams

    is_local = os.path.isdir(args.model_path)
    revision = None if is_local else args.model_revision
    llm_kwargs = dict(
        model=args.model_path,
        revision=revision,
        tokenizer_revision=revision,
        dtype="bfloat16",
        trust_remote_code=True,
        limit_mm_per_prompt={"image": MAX_IMAGES_PER_QUESTION},
        max_model_len=args.max_model_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_num_seqs=args.max_num_seqs,
        enforce_eager=args.enforce_eager,
    )
    if args.model_cache_dir:
        llm_kwargs["download_dir"] = args.model_cache_dir
    llm = LLM(**llm_kwargs)
    sampling_params = SamplingParams(
        temperature=sampling_recipe["temperature"],
        top_p=sampling_recipe["top_p"],
        top_k=sampling_recipe["top_k"],
        repetition_penalty=sampling_recipe["repetition_penalty"],
        presence_penalty=sampling_recipe["presence_penalty"],
        seed=sampling_recipe["seed"],
        max_tokens=sampling_recipe["max_tokens"],
    )
    print(sampling_params)
    return llm, sampling_params


def run_inference(llm, sampling_params, subject_datasets, flat_index, raw_log_path, args):
    """노트북 '11. 본 추론 실행' 셀과 동일: 배치 단위 생성, 즉시 기록, 문항 id 기반 재개."""
    done_ids = set()
    if os.path.exists(raw_log_path):
        with open(raw_log_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done_ids.add(json.loads(line)["id"])
                except json.JSONDecodeError:
                    continue
        print(f"기존 로그에서 완료된 문항 {len(done_ids)}건 확인 -> 건너뜁니다.")

    todo = [(s, r, eid) for (s, r, eid) in flat_index if eid not in done_ids]
    print(f"이번 실행 대상: {len(todo)}문항")

    batch_size = args.batch_size
    n_batches = (len(todo) + batch_size - 1) // batch_size
    t_start = time.time()
    prompt_budget = args.max_model_len - args.max_new_tokens

    with open(raw_log_path, "a", encoding="utf-8") as fout:
        for b in range(n_batches):
            lo, hi = b * batch_size, min((b + 1) * batch_size, len(todo))
            batch = todo[lo:hi]

            convs, metas = [], []
            for subject, row_idx, _ in batch:
                c, m = build_conversation(subject_datasets, subject, row_idx)
                convs.append(c)
                metas.append(m)

            t0 = time.time()
            outputs = llm.chat(convs, sampling_params=sampling_params, use_tqdm=True)
            dt = time.time() - t0

            for m, out in zip(metas, outputs):
                n_prompt_tok = len(out.prompt_token_ids)
                if n_prompt_tok > prompt_budget:
                    print(f"  [경고] {m['id']} 프롬프트 토큰 {n_prompt_tok:,}이 예산을 초과했습니다.")
                rec = {
                    **m,
                    "response": out.outputs[0].text,
                    "n_prompt_tokens": n_prompt_tok,
                    "n_gen_tokens": len(out.outputs[0].token_ids),
                    "finish_reason": out.outputs[0].finish_reason,
                }
                fout.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            fout.flush()

            elapsed = time.time() - t_start
            eta = elapsed / (b + 1) * (n_batches - b - 1)
            print(f"batch {b + 1}/{n_batches} [{lo}:{hi}] {dt:.1f}s | 누적 {elapsed/60:.1f}분 | ETA {eta/60:.1f}분",
                  flush=True)

    print(f"\n전체 추론 완료 -> {raw_log_path}")
    print(f"이미지 리사이즈 누적: {resize_counter['resized']}/{resize_counter['total']}장")


def grade(raw_log_path, expected_n):
    """노트북 '12. 파싱 & 채점' 셀과 동일.

    MMMU 공식 파서는 보기 문자를 못 찾으면 random.choice 로 고른다. 노트북은 채점 함수 셀에서
    random.seed(42) 를 한 번 호출한 뒤 raw_generations.jsonl 순서대로 채점했으므로, 여기서도
    채점 직전에 같은 시드를 설정하고 같은 순서로 채점한다.
    """
    random.seed(42)
    graded = []
    with open(raw_log_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            response = rec["response"]
            prompt_info = rec["prompt_info"]
            qtype = rec["question_type"]

            if qtype == "multiple-choice":
                pred = parse_multi_choice_response(response, prompt_info["all_choices"], prompt_info["index2ans"])
                gold = prompt_info["correct_choice"]
                correct = eval_multi_choice(gold, pred)
            else:
                pred = parse_open_response(response)
                gold = prompt_info["gt_content"]
                correct = eval_open(gold, pred)

            graded.append({
                "id": rec["id"],
                "subject": rec["subject"],
                "question_type": qtype,
                "pred": str(pred),
                "gold": str(gold),
                "correct": bool(correct),
                "n_prompt_tokens": rec.get("n_prompt_tokens"),
                "n_gen_tokens": rec.get("n_gen_tokens"),
                "finish_reason": rec.get("finish_reason"),
            })

    if expected_n is not None:
        assert len(graded) == expected_n, (
            f"채점 대상이 {expected_n}문항이 아닙니다: {len(graded)}. 추론이 끝까지 완료됐는지 확인하세요.")
    return graded


def write_graded_csv(graded, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(graded[0].keys()))
        writer.writeheader()
        writer.writerows(graded)


def summarize(graded, run_config, sampling_recipe, args, extra):
    """노트북 '13. 집계' 셀과 같은 필드 + 소요 시간 / peak VRAM."""
    by_subject = defaultdict(list)
    by_type = defaultdict(list)
    for g in graded:
        by_subject[g["subject"]].append(g["correct"])
        by_type[g["question_type"]].append(g["correct"])

    subject_acc = {s: sum(by_subject[s]) / len(by_subject[s]) for s in MMMU_SUBJECTS if s in by_subject}
    macro = sum(subject_acc.values()) / len(subject_acc)
    micro = sum(g["correct"] for g in graded) / len(graded)
    n_len = sum(1 for g in graded if g.get("finish_reason") == "length")

    summary = {
        "model": run_config["model_repo"],
        "model_revision": run_config["model_revision"],
        "dtype": "bfloat16",
        "dataset": DATASET_REPO,
        "dataset_revision": run_config["dataset_revision"],
        "split": DATASET_SPLIT,
        "n_total": len(graded),
        "overall_accuracy": macro,
        "overall_definition": "mean of per-subject accuracy (macro). 과목당 30문항으로 균등하여 micro 와 같다.",
        "micro_accuracy": micro,
        "per_subject_accuracy": subject_acc,
        "per_subject_correct": {s: int(sum(by_subject[s])) for s in subject_acc},
        "per_question_type_accuracy": {k: sum(v) / len(v) for k, v in by_type.items()},
        "sampling_recipe": sampling_recipe,
        "sampling_recipe_source": SOURCES["sampling_recipe"],
        "sampling_recipe_deviation": {
            "field": "max_tokens",
            "official_value": OFFICIAL_MAX_TOKENS,
            "used_value": sampling_recipe["max_tokens"],
            "reason": "생성 예산은 과제 가이드상 자유 설정 항목. L4 24GB에서 900문항 완주를 위해 축소.",
            "n_finish_reason_length": n_len,
            "ratio_finish_reason_length": n_len / len(graded),
        },
        "eval_protocol_source": SOURCES["prompt_and_scoring"],
        "inference_engine": "vLLM",
        "max_model_len": args.max_model_len,
        "image_max_pixels": IMAGE_MAX_PIXELS,
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    summary.update(extra)
    return summary


def write_results_table(summary, path):
    """제출 템플릿 '5. 결과' 표를 그대로 붙여넣을 수 있는 형태로 만든다."""
    lines = ["| No. | Subject | Data Num | Acc |", "|---|---|---|---|"]
    total_n = 0
    for i, s in enumerate(MMMU_SUBJECTS, 1):
        if s not in summary["per_subject_accuracy"]:
            continue
        acc = summary["per_subject_accuracy"][s]
        k = summary["per_subject_correct"][s]
        n = round(k / acc) if acc else None
        n = n if n else 30
        total_n += n
        lines.append(f"| {i} | {s} | {n} | {acc * 100:.2f} ({k}/{n}) |")
    lines.append(f"| | **Overall (macro avg)** | **{total_n}** | **{summary['overall_accuracy'] * 100:.2f}** |")
    lines.append("")
    lines.append("계산식: `Overall = mean(30개 과목 accuracy)` — 과목당 30문항으로 균등하므로 "
                 f"전체 정답 비율({sum(summary['per_subject_correct'].values())}/{total_n})과 같다.")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def collect_environment(gpu_report=None):
    env = {"python": sys.version}
    for mod in ("torch", "vllm", "transformers", "datasets", "PIL"):
        try:
            m = __import__(mod)
            env["pillow" if mod == "PIL" else mod] = m.__version__
        except Exception:
            env["pillow" if mod == "PIL" else mod] = None
    try:
        import torch
        env["cuda"] = torch.version.cuda
        if torch.cuda.is_available():
            env["gpu_name"] = torch.cuda.get_device_name(0)
            env["gpu_total_mem_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)
    except Exception:
        pass
    try:
        env["nvidia_driver"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
    except Exception:
        env["nvidia_driver"] = None
    if gpu_report:
        env["peak_vram"] = gpu_report
    return env


def verify_prompts(subject_datasets, flat_index, reference_path):
    """데이터셋에서 다시 만든 프롬프트가 기준 raw_generations.jsonl 의 프롬프트와 같은지 문항 단위로 대조."""
    ref = {}
    with open(reference_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            ref[r["id"]] = r["prompt_info"]
    keys = ["final_input_prompt", "all_choices", "index2ans", "correct_choice", "gt_content"]
    mismatches, missing = [], []
    for subject, row_idx, ex_id in flat_index:
        sample = subject_datasets[subject][row_idx]
        pi = construct_prompt(sample)
        build_chat_content(sample, pi)  # 이미지 처리까지 수행해 리사이즈 건수도 대조
        pi = json.loads(json.dumps(pi, ensure_ascii=False, default=str))
        if ex_id not in ref:
            missing.append(ex_id)
            continue
        diff = [k for k in keys if pi.get(k) != ref[ex_id].get(k)]
        if diff:
            mismatches.append((ex_id, diff))
    print(f"대조 문항 {len(flat_index)}건 | 기준에 없음 {len(missing)}건 | 불일치 {len(mismatches)}건")
    for ex_id, diff in mismatches[:10]:
        print(f"  불일치: {ex_id} -> {diff}")
    print(f"이미지 리사이즈: {resize_counter['resized']}/{resize_counter['total']}장")
    return len(mismatches) == 0 and len(missing) == 0


# =============================================================================
# 6. main
# =============================================================================
def parse_args():
    p = argparse.ArgumentParser(description="MMMU-val 평가 (Qwen3-VL-4B-Instruct 베이스라인 파이프라인)")
    p.add_argument("--model_path", default=DEFAULT_MODEL_PATH,
                   help="HF repo id 또는 로컬 체크포인트 디렉터리 (파인튜닝 결과 재평가 시 교체)")
    p.add_argument("--model_revision", default=DEFAULT_MODEL_REVISION,
                   help="HF repo id일 때 고정할 commit sha. 로컬 디렉터리면 무시")
    p.add_argument("--model_cache_dir", default=None, help="모델 가중치 다운로드 위치 (기본: HF 캐시)")
    p.add_argument("--data_root", default=None,
                   help="MMMU 데이터셋 캐시 디렉터리. 없으면 여기로 내려받고, 있으면 재사용 (--grade_only 외 필수)")
    p.add_argument("--dataset_revision", default=DEFAULT_DATASET_REVISION)
    p.add_argument("--output_root", default="results", help="결과 상위 디렉터리")
    p.add_argument("--run_tag", default="v5_maxtok8192", help="결과 하위 디렉터리 이름")
    p.add_argument("--max_new_tokens", type=int, default=8192)
    p.add_argument("--max_model_len", type=int, default=12288)
    p.add_argument("--image_max_pixels", type=int, default=1_048_576)
    p.add_argument("--image_content_mode", choices=["image_pil", "base64"], default="image_pil")
    p.add_argument("--gpu_memory_utilization", type=float, default=0.90)
    p.add_argument("--max_num_seqs", type=int, default=8)
    p.add_argument("--enforce_eager", action="store_true", help="CUDA 그래프 끄기 (메모리 부족 시)")
    p.add_argument("--batch_size", type=int, default=25, help="체크포인트 저장 단위")
    p.add_argument("--grade_only", action="store_true",
                   help="추론 없이 기존 raw_generations.jsonl 재채점 (*_regrade 파일로 저장)")
    p.add_argument("--verify_prompts_against", default=None,
                   help="기준 raw_generations.jsonl 경로. 프롬프트 재현만 검증하고 종료 (GPU 불필요)")
    p.add_argument("--limit_per_subject", type=int, default=None,
                   help="스모크 테스트용. 과목당 N문항만 실행하며 결과는 *_smoke 디렉터리에 저장 (보고용 아님)")
    return p.parse_args()


def main():
    global IMAGE_MAX_PIXELS, IMAGE_CONTENT_MODE
    args = parse_args()
    if not args.grade_only and not args.data_root:
        raise SystemExit("--data_root 가 필요합니다 (MMMU 데이터셋 캐시 디렉터리).")
    IMAGE_MAX_PIXELS = args.image_max_pixels
    IMAGE_CONTENT_MODE = args.image_content_mode

    run_tag = args.run_tag + ("_smoke" if args.limit_per_subject else "")
    output_dir = os.path.join(args.output_root, run_tag)
    os.makedirs(output_dir, exist_ok=True)
    raw_log_path = os.path.join(output_dir, "raw_generations.jsonl")
    config_path = os.path.join(output_dir, "run_config.json")

    sampling_recipe = dict(OFFICIAL_SAMPLING, max_tokens=args.max_new_tokens)
    is_local = os.path.isdir(args.model_path)
    run_config = {
        "model_repo": args.model_path,
        "model_revision": None if is_local else args.model_revision,
        "dataset_repo": DATASET_REPO,
        "dataset_revision": args.dataset_revision,
        "split": DATASET_SPLIT,
        "sampling_recipe": sampling_recipe,
        "max_model_len": args.max_model_len,
        "image_max_pixels": IMAGE_MAX_PIXELS,
    }
    expected_n = None if args.limit_per_subject else 900

    # --- 프롬프트 재현 검증 모드 (GPU 불필요) ---
    if args.verify_prompts_against:
        subject_datasets, flat_index = load_mmmu(args.data_root, args.dataset_revision, args.limit_per_subject)
        ok = verify_prompts(subject_datasets, flat_index, args.verify_prompts_against)
        print("프롬프트 재현: " + ("일치" if ok else "불일치 있음"))
        sys.exit(0 if ok else 1)

    # --- 재채점 모드 (GPU 불필요) ---
    if args.grade_only:
        assert os.path.exists(raw_log_path), f"{raw_log_path} 가 없습니다."
        prev_path = os.path.join(output_dir, "summary.json")
        prev = json.load(open(prev_path, encoding="utf-8")) if os.path.exists(prev_path) else {}
        if os.path.exists(config_path):
            run_config = json.load(open(config_path, encoding="utf-8"))
            sampling_recipe = run_config["sampling_recipe"]
        graded = grade(raw_log_path, expected_n)
        write_graded_csv(graded, os.path.join(output_dir, "graded_results_regrade.csv"))
        keep = {k: prev[k] for k in ("images_resized", "images_total_seen", "timing_sec", "peak_vram") if k in prev}
        summary = summarize(graded, run_config, sampling_recipe, args, keep)
        with open(os.path.join(output_dir, "summary_regrade.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        write_results_table(summary, os.path.join(output_dir, "results_table_regrade.md"))
        print(f"재채점 완료: {sum(g['correct'] for g in graded)}/{len(graded)} = {summary['overall_accuracy'] * 100:.2f}")
        return

    # --- 전체 실행 ---
    t_script = time.time()
    check_or_write_run_config(config_path, run_config)
    monitor = GpuMemMonitor().start()

    t0 = time.time()
    subject_datasets, flat_index = load_mmmu(args.data_root, args.dataset_revision, args.limit_per_subject)
    t_data = time.time() - t0

    t0 = time.time()
    llm, sampling_params = build_llm(args, sampling_recipe)
    t_model = time.time() - t0

    t0 = time.time()
    run_inference(llm, sampling_params, subject_datasets, flat_index, raw_log_path, args)
    t_infer = time.time() - t0
    gpu_report = monitor.stop()

    t0 = time.time()
    graded = grade(raw_log_path, expected_n)
    write_graded_csv(graded, os.path.join(output_dir, "graded_results.csv"))
    t_grade = time.time() - t0

    timing = {
        "data_load": round(t_data, 1),
        "model_load": round(t_model, 1),
        "inference": round(t_infer, 1),
        "grading": round(t_grade, 1),
        "total": round(time.time() - t_script, 1),
        "note": "이번 실행 기준. 중단 후 재개했다면 inference 는 마지막 실행분만 포함한다.",
    }
    extra = {
        "images_resized": resize_counter["resized"],
        "images_total_seen": resize_counter["total"],
        "timing_sec": timing,
        "peak_vram": gpu_report,
        "valid_for_report": not bool(args.limit_per_subject),
    }
    summary = summarize(graded, run_config, sampling_recipe, args, extra)
    with open(os.path.join(output_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    write_results_table(summary, os.path.join(output_dir, "results_table.md"))
    with open(os.path.join(output_dir, "environment.json"), "w", encoding="utf-8") as f:
        json.dump(collect_environment(gpu_report), f, ensure_ascii=False, indent=2)

    print("\n=== 과목별 정확도 ===")
    for s, a in summary["per_subject_accuracy"].items():
        print(f"{s:40s} {a * 100:6.2f}%")
    print(f"\nOverall (macro): {summary['overall_accuracy'] * 100:.2f}  | n={summary['n_total']}")
    print(f"생성 상한 도달: {summary['sampling_recipe_deviation']['n_finish_reason_length']}건")
    print(f"peak VRAM: {gpu_report['peak_used_gib']} GiB ({gpu_report['method']}) | 총 소요: {timing['total'] / 60:.1f}분")
    print(f"결과 디렉터리: {output_dir}")


if __name__ == "__main__":
    main()
