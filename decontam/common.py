"""Shared pieces of the contamination check (reports/dataset_search.md, section 2).

E (evaluation set) = MMMU dev + validation, MMMU-Pro standard (10 options) + vision. One E *item* = one question;
its images are compared one by one and hits are counted per item (section 2.1).
T (training set)   = one candidate dataset, one record per question (an image shared by several QA = several records).
"""
import hashlib
import io
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NGRAM = 13                 # section 2.1: 13-gram of normalized question + options
SSCD_MATCH = 0.95          # section 2.1: near-duplicate threshold
TEMPLATE_MIN = 10          # section 2.1: same question string >= 10 times in T = template question
E_SIZE = {"mmmu": 900, "pro": 1730}   # section 2.3: inflation is per MMMU val item / per MMMU-Pro item

_IMG_TAG = re.compile(r"<image\s*\d*>", re.I)
_OPT_MARK = re.compile(r"(?:(?<=\s)|^)\(?[A-Ja-j][\).:](?=\s)")   # "(A)", "A.", "b)" option markers


def norm_text(s):
    """Section 2.1 normalization: lowercase, <image n> and option markers removed, punctuation/whitespace unified."""
    s = _IMG_TAG.sub(" ", str(s))
    s = _OPT_MARK.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).split()


def ngrams(tokens, n=NGRAM):
    return {" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def item_text(question, options=()):
    """The text that is compared: question + options (options may be a list, a dict or an MMMU-style repr string)."""
    if isinstance(options, str):
        try:
            import ast
            options = ast.literal_eval(options)
        except Exception:
            options = [options]
    if isinstance(options, dict):
        options = list(options.values())
    return " ".join([str(question)] + [str(o) for o in (options or [])])


def to_rgb(im):
    if isinstance(im, (bytes, bytearray)):
        im = Image.open(io.BytesIO(im))
    elif isinstance(im, (str, Path)):
        im = Image.open(im)
    elif isinstance(im, dict) and ("bytes" in im or "path" in im):      # datasets Image(decode=False)
        im = Image.open(io.BytesIO(im["bytes"])) if im.get("bytes") else Image.open(im["path"])
    return im.convert("RGB")


def pixel_sha256(im):
    """Section 2.1 exact match: decode -> RGB -> SHA-256 of the pixels (+ size), so PNG/JPEG container bytes don't matter."""
    im = to_rgb(im)
    h = hashlib.sha256(f"{im.width}x{im.height}".encode())
    h.update(im.tobytes())
    return h.hexdigest()


# --- image embedders -------------------------------------------------------------------------------------------
class SSCD:
    """SSCD copy-detection descriptor (Pizzi et al. 2022), the model FineVision used with cosine 0.95.
    TorchScript weights: https://dl.fbaipublicfiles.com/sscd-copy-detection/sscd_disc_mixup.torchscript.pt"""
    URL = "https://dl.fbaipublicfiles.com/sscd-copy-detection/sscd_disc_mixup.torchscript.pt"

    def __init__(self, weights=None, device=None, batch=64):
        import torch
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        path = Path(weights or Path.home() / ".cache/sscd/sscd_disc_mixup.torchscript.pt")
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            torch.hub.download_url_to_file(self.URL, str(path))
        self.model = torch.jit.load(str(path), map_location=self.device).eval()
        self.batch = batch
        self.dim = 512
        self.mean = np.array([0.485, 0.456, 0.406], np.float32)
        self.std = np.array([0.229, 0.224, 0.225], np.float32)

    def _prep(self, im):
        """SSCD's eval transform without torchvision: shorter side 288, centre crop 288, ImageNet normalization."""
        im = to_rgb(im)
        w, h = im.size
        s = 288 / min(w, h)
        im = im.resize((max(288, round(w * s)), max(288, round(h * s))), Image.Resampling.BILINEAR)
        w, h = im.size
        l, t = (w - 288) // 2, (h - 288) // 2
        x = (np.asarray(im.crop((l, t, l + 288, t + 288)), np.float32) / 255 - self.mean) / self.std
        return x.transpose(2, 0, 1)

    def __call__(self, images):
        out = []
        with self.torch.no_grad():
            for i in range(0, len(images), self.batch):
                x = self.torch.from_numpy(np.stack([self._prep(im) for im in images[i:i + self.batch]])).to(self.device)
                e = self.model(x)
                out.append(self.torch.nn.functional.normalize(e, dim=1).float().cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, self.dim), np.float32)


class TinyEmbed:
    """Test-only stand-in (no download): 16x16 grayscale, mean-centred, L2-normalized. Survives resize/JPEG, not crops."""
    dim = 256

    def __call__(self, images):
        if not images:
            return np.zeros((0, self.dim), np.float32)
        a = np.stack([np.asarray(to_rgb(im).convert("L").resize((16, 16), Image.Resampling.BILINEAR), np.float32).ravel()
                      for im in images])
        a -= a.mean(1, keepdims=True)
        return (a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-6)).astype(np.float32)


def image_embedder(name, **kw):
    return SSCD(**kw) if name == "sscd" else TinyEmbed()


# --- text embedders (paraphrase candidates for the LLM judge) -----------------------------------------------------
class STEmbed:
    """Multilingual sentence embedding (mean pooling, as the model card prescribes), so translated copies are found.
    Uses transformers directly: no extra package that could move the pinned torch/transformers."""

    def __init__(self, model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", batch=256):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tok = AutoTokenizer.from_pretrained(model)
        self.m = AutoModel.from_pretrained(model).to(self.device).eval()
        self.batch = batch

    def __call__(self, texts):
        out = []
        with self.torch.no_grad():
            for i in range(0, len(texts), self.batch):
                x = self.tok(list(texts[i:i + self.batch]), padding=True, truncation=True, max_length=256,
                             return_tensors="pt").to(self.device)
                h = self.m(**x).last_hidden_state
                m = x["attention_mask"].unsqueeze(-1).float()
                e = (h * m).sum(1) / m.sum(1).clamp(min=1e-9)
                out.append(self.torch.nn.functional.normalize(e, dim=1).float().cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 384), np.float32)


class HashEmbed:
    """Test-only stand-in: hashed word 1-2-grams. Catches light rewording, not translation."""
    dim = 2048

    def __call__(self, texts):
        out = np.zeros((len(texts), self.dim), np.float32)
        for i, t in enumerate(texts):
            w = norm_text(t)
            for g in w + [a + " " + b for a, b in zip(w, w[1:])]:
                out[i, int(hashlib.md5(g.encode()).hexdigest()[:8], 16) % self.dim] += 1
        return out / (np.linalg.norm(out, axis=1, keepdims=True) + 1e-6)


def text_embedder(name, **kw):
    return STEmbed(**kw) if name == "st" else HashEmbed()
